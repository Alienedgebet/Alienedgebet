"""
Shared storage + generalized evaluation logic for user-defined live alert
rules (Code 6 "flexibility filter").

Imported by:
  - api/user_rules_router.py        (FastAPI CRUD endpoints)
  - LIVE_SCANNER/live_stage6_alerts.py (evaluates rules against live
    matches every cycle)

Storage: a single JSON file, data/user_rules.json, shaped as:
[
  {
    "rule_id": "r_...",
    "user_id": "u_...",
    "label": "My BTTS 2H Rule",
    "prematch": {"type": "flag", "flag": "both_2h_goal_100_percent"},
    "live": {"type": "pressure_share", "side": "home", "min_value": 55},
    "active": true,
    "created_at": "2026-08-26T12:00:00Z"
  }
]
"""

import os
import json
import uuid
import threading
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
USER_RULES_FILE = os.path.join(DATA_DIR, "user_rules.json")

_lock = threading.Lock()

# ==============================================================================
# VALID OPTIONS — single source of truth. The frontend dropdowns
# (lib/api.ts PREMATCH_FLAG_OPTIONS / PREMATCH_RATE_OPTIONS) must match
# these exactly, or a save will get rejected with a 422.
# ==============================================================================
VALID_PREMATCH_FLAGS = {
    "both_2h_goal_100_percent",
    "home_h2h_win_100",
    "away_h2h_win_100",
    "h2h_gg_100",
    "h2h_o25_100",
}

VALID_PREMATCH_RATE_METRICS = {
    "home_2h_rate",
    "away_2h_rate",
}

VALID_LIVE_TYPES = {"snapshot", "pressure_share", "chaos_index"}
VALID_SIDES = {"home", "away", "any"}


class RuleValidationError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_files():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(USER_RULES_FILE):
        with open(USER_RULES_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)


def _read_all() -> list:
    _ensure_files()
    try:
        with open(USER_RULES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def _write_all(rules: list) -> None:
    _ensure_files()
    tmp_path = USER_RULES_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(rules, f, indent=2)
    os.replace(tmp_path, USER_RULES_FILE)  # atomic swap — no half-written files


def validate_rule_payload(payload: dict) -> dict:
    """Validates + normalizes an incoming rule. Raises RuleValidationError on failure."""
    if not isinstance(payload, dict):
        raise RuleValidationError("Rule payload must be an object.")

    user_id = str(payload.get("user_id", "")).strip()
    if not user_id:
        raise RuleValidationError("user_id is required.")

    label = str(payload.get("label", "")).strip() or "Untitled Rule"

    prematch = payload.get("prematch") or {"type": "none"}
    ptype = prematch.get("type")
    if ptype == "flag":
        flag = prematch.get("flag")
        if flag not in VALID_PREMATCH_FLAGS:
            raise RuleValidationError(f"Unknown prematch flag: {flag}")
        prematch = {"type": "flag", "flag": flag}
    elif ptype == "rate":
        metric = prematch.get("metric")
        if metric not in VALID_PREMATCH_RATE_METRICS:
            raise RuleValidationError(f"Unknown prematch rate metric: {metric}")
        try:
            min_value = float(prematch.get("min_value"))
        except (TypeError, ValueError):
            raise RuleValidationError("prematch.min_value must be a number.")
        if not (0 <= min_value <= 100):
            raise RuleValidationError("prematch.min_value must be between 0 and 100.")
        prematch = {"type": "rate", "metric": metric, "min_value": min_value}
    elif ptype == "none":
        prematch = {"type": "none"}
    else:
        raise RuleValidationError(f"Unknown prematch.type: {ptype}")

    live = payload.get("live") or {}
    ltype = live.get("type")
    if ltype not in VALID_LIVE_TYPES:
        raise RuleValidationError(f"Unknown live.type: {ltype}")

    if ltype == "snapshot":
        live = {"type": "snapshot"}
    elif ltype == "pressure_share":
        side = live.get("side", "any")
        if side not in VALID_SIDES:
            raise RuleValidationError(f"Unknown live.side: {side}")
        try:
            min_value = float(live.get("min_value"))
        except (TypeError, ValueError):
            raise RuleValidationError("live.min_value must be a number.")
        if not (0 <= min_value <= 100):
            raise RuleValidationError("live.min_value must be between 0 and 100.")
        live = {"type": "pressure_share", "side": side, "min_value": min_value}
    elif ltype == "chaos_index":
        try:
            min_value = float(live.get("min_value"))
        except (TypeError, ValueError):
            raise RuleValidationError("live.min_value must be a number.")
        if min_value < 0:
            raise RuleValidationError("live.min_value must be >= 0.")
        live = {"type": "chaos_index", "min_value": min_value}

    if prematch.get("type") == "none" and live.get("type") == "snapshot":
        raise RuleValidationError(
            "A rule needs at least one real condition — "
            "snapshot-only with no prematch filter is not allowed."
        )

    return {
        "user_id": user_id,
        "label": label,
        "prematch": prematch,
        "live": live,
        "active": bool(payload.get("active", True)),
    }


def list_rules(user_id: str | None = None, active_only: bool = False) -> list:
    with _lock:
        rules = _read_all()
    if user_id is not None:
        rules = [r for r in rules if r.get("user_id") == user_id]
    if active_only:
        rules = [r for r in rules if r.get("active")]
    return rules


def create_rule(payload: dict) -> dict:
    normalized = validate_rule_payload(payload)
    normalized["rule_id"] = f"r_{uuid.uuid4().hex[:12]}"
    normalized["created_at"] = _now_iso()
    with _lock:
        rules = _read_all()
        rules.append(normalized)
        _write_all(rules)
    return normalized


def update_rule(rule_id: str, patch: dict) -> dict | None:
    with _lock:
        rules = _read_all()
        target = next((r for r in rules if r.get("rule_id") == rule_id), None)
        if target is None:
            return None
        merged = {**target, **patch}
        if any(k in patch for k in ("prematch", "live", "label", "user_id")):
            validated = validate_rule_payload(merged)
            merged = {**validated, "rule_id": rule_id, "created_at": target.get("created_at", _now_iso())}
        else:
            merged["rule_id"] = rule_id
        merged["active"] = bool(patch.get("active", target.get("active", True)))
        rules = [merged if r.get("rule_id") == rule_id else r for r in rules]
        _write_all(rules)
    return merged


def delete_rule(rule_id: str, user_id: str) -> bool:
    with _lock:
        rules = _read_all()
        before = len(rules)
        rules = [
            r for r in rules
            if not (r.get("rule_id") == rule_id and r.get("user_id") == user_id)
        ]
        if len(rules) == before:
            return False
        _write_all(rules)
    return True


# ==============================================================================
# EVALUATION — called by LIVE_SCANNER/live_stage6_alerts.py every cycle.
# Lives here (not in stage6) so the API and the scanner never drift apart
# on what a rule actually means.
# ==============================================================================

def _prematch_condition_met(rule_prematch: dict, pre: dict) -> tuple[bool, str]:
    ptype = rule_prematch.get("type")
    if ptype == "none":
        return True, "No prematch filter"

    if ptype == "flag":
        flag_name = rule_prematch["flag"]
        flags = (pre or {}).get("flags") or {}
        met = bool(flags.get(flag_name))
        return met, f"Prematch flag '{flag_name}': {'✅' if met else '❌'}"

    if ptype == "rate":
        metric_name = rule_prematch["metric"]
        min_value = rule_prematch["min_value"]
        metrics = (pre or {}).get("metrics") or {}
        raw = metrics.get(metric_name)
        if raw is None:
            return False, f"Prematch metric '{metric_name}' unavailable"
        pct = float(raw) * 100 if raw <= 1 else float(raw)
        met = pct >= min_value
        return met, f"Prematch '{metric_name}' {pct:.1f}% >= {min_value}%: {'✅' if met else '❌'}"

    return False, "Unknown prematch condition"


def _live_condition_met(rule_live: dict, intel: dict) -> tuple[bool, str]:
    ltype = rule_live.get("type")
    match_intel = (intel or {}).get("match") or {}

    if ltype == "snapshot":
        return True, "Live snapshot (always fires)"

    if ltype == "pressure_share":
        side = rule_live.get("side", "any")
        min_value = rule_live["min_value"]
        h = match_intel.get("h_pressure_share", 0)
        a = match_intel.get("a_pressure_share", 0)
        if side == "home":
            met = h >= min_value
            return met, f"Home pressure {h}% >= {min_value}%: {'✅' if met else '❌'}"
        if side == "away":
            met = a >= min_value
            return met, f"Away pressure {a}% >= {min_value}%: {'✅' if met else '❌'}"
        met = max(h, a) >= min_value
        return met, f"Max pressure {max(h, a)}% >= {min_value}%: {'✅' if met else '❌'}"

    if ltype == "chaos_index":
        min_value = rule_live["min_value"]
        chaos = match_intel.get("chaos_index", 0)
        met = chaos >= min_value
        return met, f"Chaos {chaos:.1f} >= {min_value}: {'✅' if met else '❌'}"

    return False, "Unknown live condition"


def evaluate_rule_for_match(rule: dict, intel: dict, pre: dict) -> dict | None:
    """Returns a triggered-alert dict if this rule fires this cycle, else None."""
    if not rule.get("active", True):
        return None

    pre_met, pre_note = _prematch_condition_met(rule.get("prematch", {"type": "none"}), pre)
    if not pre_met:
        return None

    live_met, live_note = _live_condition_met(rule.get("live", {}), intel)
    if not live_met:
        return None

    conf = ((intel or {}).get("match") or {}).get("confidence_score", 0)
    return {
        "rule_id": rule["rule_id"],
        "user_id": rule["user_id"],
        "label": rule.get("label", "Untitled Rule"),
        "note": f"{pre_note} | {live_note}",
        "conf": conf,
    }