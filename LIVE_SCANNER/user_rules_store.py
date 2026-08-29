"""
Shared storage + generalized evaluation logic for user-defined live alert
rules (Code 6 "flexibility filter").

Imported by:
  - api/user_rules_router.py        (FastAPI CRUD endpoints)
  - LIVE_SCANNER/live_stage6_alerts.py (evaluates rules against live
    matches every cycle, calling evaluate_rule_for_match(rule, intel, pre,
    minute, key_loss))

Storage: a single JSON file, data/user_rules.json.

Every condition type below is backed by a field CONFIRMED to exist in one
of Code 6's three real prematch sources or its live intel/key_loss data —
nothing here is invented:
  - SH-GG Winner feed  -> pre['flags'], pre['metrics']
  - Aggregator report  -> pre['match_chemistry_list'], pre['danger_report']
  - Stage 1 team audit -> pre['team_audit']['home'/'away']
  - Live intel         -> intel['match'], intel['home'/'away']
  - Live key_loss       -> key_loss['h_lost'] / ['a_lost']
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
# VALID OPTIONS — single source of truth. Frontend dropdowns must mirror
# these exactly, or a save gets rejected with a 422.
# ==============================================================================

# SH-GG Winner flags (LIVE_SCANNER/live_stage6_alerts.py load via sh_gg_winner_feed.json)
VALID_PREMATCH_FLAGS = {
    "both_2h_goal_100_percent",
    "home_h2h_win_100",
    "away_h2h_win_100",
    "h2h_gg_100",
    "h2h_o25_100",
}

# SH-GG Winner raw rate metrics
VALID_PREMATCH_RATE_METRICS = {
    "home_2h_rate",
    "away_2h_rate",
}

# Aggregator report — match_chemistry_list markets (confirmed in
# LiveDangerReport / LiveAggregatorReport shapes)
VALID_CHEMISTRY_MARKETS = {
    "Gg",
    "Corner",
    "Home Win",
    "Away Win",
    "Over2.5",
    "Under3.5",
    "Over1.5",
}

# Aggregator report — chemistry level strings actually produced (confirmed
# in mock/real shape). Matched case-insensitively, exact string only — no
# invented tier ranking.
VALID_CHEMISTRY_LEVELS = {
    "excellent",
    "elite",
    "very strong",
    "strong",
    "weak",
    "very weak",
}

# Stage 1 team audit — fields confirmed in prematch_team_audit.json
VALID_TEAM_AUDIT_SIDES = {"home", "away", "any"}

VALID_PREMATCH_TYPES = {
    "none", "flag", "rate",
    "gk_liability", "key_missing",
    "aggregator_chemistry", "aggregator_breach",
}

VALID_LIVE_TYPES = {
    "snapshot", "pressure_share", "chaos_index",
    "xg", "sot", "corners", "da", "key_player_lost",
}
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


# ==============================================================================
# VALIDATION
# ==============================================================================
def _validate_minute_window(raw) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise RuleValidationError("minute_window must be an object with start/end.")
    try:
        start = int(raw.get("start", 0))
        end = int(raw.get("end", 120))
    except (TypeError, ValueError):
        raise RuleValidationError("minute_window.start/end must be integers.")
    if not (0 <= start <= 120) or not (0 <= end <= 120):
        raise RuleValidationError("minute_window values must be between 0 and 120.")
    if start > end:
        raise RuleValidationError("minute_window.start cannot be after minute_window.end.")
    return {"start": start, "end": end}


def _validate_prematch(prematch: dict) -> dict:
    ptype = prematch.get("type")
    if ptype not in VALID_PREMATCH_TYPES:
        raise RuleValidationError(f"Unknown prematch.type: {ptype}")

    if ptype == "none":
        return {"type": "none"}

    if ptype == "flag":
        flag = prematch.get("flag")
        if flag not in VALID_PREMATCH_FLAGS:
            raise RuleValidationError(f"Unknown prematch flag: {flag}")
        return {"type": "flag", "flag": flag}

    if ptype == "rate":
        metric = prematch.get("metric")
        if metric not in VALID_PREMATCH_RATE_METRICS:
            raise RuleValidationError(f"Unknown prematch rate metric: {metric}")
        try:
            min_value = float(prematch.get("min_value"))
        except (TypeError, ValueError):
            raise RuleValidationError("prematch.min_value must be a number.")
        if not (0 <= min_value <= 100):
            raise RuleValidationError("prematch.min_value must be between 0 and 100.")
        return {"type": "rate", "metric": metric, "min_value": min_value}

    if ptype == "gk_liability":
        side = prematch.get("side", "any")
        if side not in VALID_TEAM_AUDIT_SIDES:
            raise RuleValidationError(f"Unknown prematch.side: {side}")
        return {"type": "gk_liability", "side": side}

    if ptype == "key_missing":
        side = prematch.get("side", "any")
        if side not in VALID_TEAM_AUDIT_SIDES:
            raise RuleValidationError(f"Unknown prematch.side: {side}")
        try:
            min_count = int(prematch.get("min_count"))
        except (TypeError, ValueError):
            raise RuleValidationError("prematch.min_count must be an integer.")
        if min_count < 1:
            raise RuleValidationError("prematch.min_count must be at least 1.")
        return {"type": "key_missing", "side": side, "min_count": min_count}

    if ptype == "aggregator_chemistry":
        market = prematch.get("market")
        if market not in VALID_CHEMISTRY_MARKETS:
            raise RuleValidationError(f"Unknown chemistry market: {market}")
        level = str(prematch.get("level", "")).strip().lower()
        if level not in VALID_CHEMISTRY_LEVELS:
            raise RuleValidationError(f"Unknown chemistry level: {level}")
        return {"type": "aggregator_chemistry", "market": market, "level": level}

    if ptype == "aggregator_breach":
        side = prematch.get("side", "any")
        if side not in VALID_TEAM_AUDIT_SIDES:
            raise RuleValidationError(f"Unknown prematch.side: {side}")
        return {"type": "aggregator_breach", "side": side}

    raise RuleValidationError(f"Unhandled prematch.type: {ptype}")


def _validate_live(live: dict) -> dict:
    ltype = live.get("type")
    if ltype not in VALID_LIVE_TYPES:
        raise RuleValidationError(f"Unknown live.type: {ltype}")

    if ltype == "snapshot":
        return {"type": "snapshot"}

    if ltype in ("pressure_share", "xg", "sot", "corners", "da"):
        side = live.get("side", "any")
        if side not in VALID_SIDES:
            raise RuleValidationError(f"Unknown live.side: {side}")
        try:
            min_value = float(live.get("min_value"))
        except (TypeError, ValueError):
            raise RuleValidationError("live.min_value must be a number.")
        if min_value < 0:
            raise RuleValidationError("live.min_value must be >= 0.")
        if ltype == "pressure_share" and min_value > 100:
            raise RuleValidationError("live.min_value for pressure_share must be <= 100.")
        return {"type": ltype, "side": side, "min_value": min_value}

    if ltype == "chaos_index":
        try:
            min_value = float(live.get("min_value"))
        except (TypeError, ValueError):
            raise RuleValidationError("live.min_value must be a number.")
        if min_value < 0:
            raise RuleValidationError("live.min_value must be >= 0.")
        return {"type": "chaos_index", "min_value": min_value}

    if ltype == "key_player_lost":
        side = live.get("side", "any")
        if side not in VALID_SIDES:
            raise RuleValidationError(f"Unknown live.side: {side}")
        try:
            min_count = int(live.get("min_count", 1))
        except (TypeError, ValueError):
            raise RuleValidationError("live.min_count must be an integer.")
        if min_count < 1:
            raise RuleValidationError("live.min_count must be at least 1.")
        return {"type": "key_player_lost", "side": side, "min_count": min_count}

    raise RuleValidationError(f"Unhandled live.type: {ltype}")


def validate_rule_payload(payload: dict) -> dict:
    """Validates + normalizes an incoming rule. Raises RuleValidationError on failure."""
    if not isinstance(payload, dict):
        raise RuleValidationError("Rule payload must be an object.")

    user_id = str(payload.get("user_id", "")).strip()
    if not user_id:
        raise RuleValidationError("user_id is required.")

    label = str(payload.get("label", "")).strip() or "Untitled Rule"

    prematch = _validate_prematch(payload.get("prematch") or {"type": "none"})
    live = _validate_live(payload.get("live") or {})
    minute_window = _validate_minute_window(payload.get("minute_window"))

    if prematch.get("type") == "none" and live.get("type") == "snapshot":
        raise RuleValidationError(
            "A rule needs at least one real condition — "
            "snapshot-only with no prematch filter is not allowed."
        )

    result = {
        "user_id": user_id,
        "label": label,
        "prematch": prematch,
        "live": live,
        "active": bool(payload.get("active", True)),
    }
    if minute_window is not None:
        result["minute_window"] = minute_window
    return result


# ==============================================================================
# CRUD
# ==============================================================================
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
        if any(k in patch for k in ("prematch", "live", "label", "user_id", "minute_window")):
            validated = validate_rule_payload(merged)
            merged = {
                **validated,
                "rule_id": rule_id,
                "created_at": target.get("created_at", _now_iso()),
            }
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
# ==============================================================================

def _minute_window_ok(rule: dict, minute: int) -> tuple[bool, str]:
    window = rule.get("minute_window")
    if not window:
        return True, ""
    start, end = window["start"], window["end"]
    ok = start <= minute <= end
    return ok, f"[{start}'-{end}' window]"


def _prematch_condition_met(rule_prematch: dict, pre: dict) -> tuple[bool, str]:
    ptype = rule_prematch.get("type")
    pre = pre or {}

    if ptype == "none":
        return True, "No prematch filter"

    if ptype == "flag":
        flag_name = rule_prematch["flag"]
        flags = pre.get("flags") or {}
        met = bool(flags.get(flag_name))
        return met, f"Prematch flag '{flag_name}': {'✅' if met else '❌'}"

    if ptype == "rate":
        metric_name = rule_prematch["metric"]
        min_value = rule_prematch["min_value"]
        metrics = pre.get("metrics") or {}
        raw = metrics.get(metric_name)
        if raw is None:
            return False, f"Prematch metric '{metric_name}' unavailable"
        pct = float(raw) * 100 if raw <= 1 else float(raw)
        met = pct >= min_value
        return met, f"Prematch '{metric_name}' {pct:.1f}% >= {min_value}%: {'✅' if met else '❌'}"

    if ptype == "gk_liability":
        side = rule_prematch.get("side", "any")
        audit = pre.get("team_audit") or {}
        h_out = bool(safe_dig(audit, "home", "gk_out"))
        a_out = bool(safe_dig(audit, "away", "gk_out"))
        if side == "home":
            met = h_out
        elif side == "away":
            met = a_out
        else:
            met = h_out or a_out
        return met, f"GK liability ({side}): H={h_out} A={a_out} → {'✅' if met else '❌'}"

    if ptype == "key_missing":
        side = rule_prematch.get("side", "any")
        min_count = rule_prematch["min_count"]
        audit = pre.get("team_audit") or {}
        h_miss = safe_dig(audit, "home", "missing_count") or 0
        a_miss = safe_dig(audit, "away", "missing_count") or 0
        if side == "home":
            met = h_miss >= min_count
        elif side == "away":
            met = a_miss >= min_count
        else:
            met = max(h_miss, a_miss) >= min_count
        return met, f"Key missing ({side}) H={h_miss} A={a_miss} >= {min_count}: {'✅' if met else '❌'}"

    if ptype == "aggregator_chemistry":
        market = rule_prematch["market"]
        level = rule_prematch["level"]
        chem = pre.get("match_chemistry_list") or {}
        actual = str(chem.get(market, "")).strip().lower()
        met = actual == level
        return met, f"Chemistry '{market}' = '{actual}' (need '{level}'): {'✅' if met else '❌'}"

    if ptype == "aggregator_breach":
        side = rule_prematch.get("side", "any")
        danger = pre.get("danger_report") or {}
        h_breach = bool(safe_dig(danger, "home", "breach"))
        a_breach = bool(safe_dig(danger, "away", "breach"))
        if side == "home":
            met = h_breach
        elif side == "away":
            met = a_breach
        else:
            met = h_breach or a_breach
        return met, f"Danger breach ({side}): H={h_breach} A={a_breach} → {'✅' if met else '❌'}"

    return False, "Unknown prematch condition"


def _live_condition_met(rule_live: dict, intel: dict, key_loss: dict) -> tuple[bool, str]:
    ltype = rule_live.get("type")
    intel = intel or {}
    match_intel = intel.get("match") or {}
    home_intel = intel.get("home") or {}
    away_intel = intel.get("away") or {}
    key_loss = key_loss or {}

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

    if ltype == "xg":
        side = rule_live.get("side", "any")
        min_value = rule_live["min_value"]
        h = home_intel.get("live_xg", 0)
        a = away_intel.get("live_xg", 0)
        if side == "home":
            met = h >= min_value
        elif side == "away":
            met = a >= min_value
        else:
            met = max(h, a) >= min_value
        return met, f"xG ({side}) H={h} A={a} >= {min_value}: {'✅' if met else '❌'}"

    if ltype == "sot":
        side = rule_live.get("side", "any")
        min_value = rule_live["min_value"]
        h = home_intel.get("sot", 0)
        a = away_intel.get("sot", 0)
        if side == "home":
            met = h >= min_value
        elif side == "away":
            met = a >= min_value
        else:
            met = max(h, a) >= min_value
        return met, f"SOT ({side}) H={h} A={a} >= {min_value}: {'✅' if met else '❌'}"

    if ltype == "corners":
        side = rule_live.get("side", "any")
        min_value = rule_live["min_value"]
        h = home_intel.get("corn", 0)
        a = away_intel.get("corn", 0)
        if side == "home":
            met = h >= min_value
        elif side == "away":
            met = a >= min_value
        else:
            met = max(h, a) >= min_value
        return met, f"Corners ({side}) H={h} A={a} >= {min_value}: {'✅' if met else '❌'}"

    if ltype == "da":
        side = rule_live.get("side", "any")
        min_value = rule_live["min_value"]
        h = home_intel.get("da", 0)
        a = away_intel.get("da", 0)
        if side == "home":
            met = h >= min_value
        elif side == "away":
            met = a >= min_value
        else:
            met = max(h, a) >= min_value
        return met, f"Dangerous Attacks ({side}) H={h} A={a} >= {min_value}: {'✅' if met else '❌'}"

    if ltype == "key_player_lost":
        side = rule_live.get("side", "any")
        min_count = rule_live["min_count"]
        h_lost = key_loss.get("h_lost", 0)
        a_lost = key_loss.get("a_lost", 0)
        if side == "home":
            met = h_lost >= min_count
        elif side == "away":
            met = a_lost >= min_count
        else:
            met = max(h_lost, a_lost) >= min_count
        return met, f"Key player lost ({side}) H={h_lost} A={a_lost} >= {min_count}: {'✅' if met else '❌'}"

    return False, "Unknown live condition"


def safe_dig(d, *keys, default=None):
    """Small local safe-nested-get, kept here so this module has no runtime
    dependency on live_stage6_alerts.py's safe_get (avoids circular import)."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def evaluate_rule_for_match(rule: dict, intel: dict, pre: dict, minute: int, key_loss: dict) -> dict | None:
    """Returns a triggered-alert dict if this rule fires this cycle, else None."""
    if not rule.get("active", True):
        return None

    window_met, window_note = _minute_window_ok(rule, minute)
    if not window_met:
        return None

    pre_met, pre_note = _prematch_condition_met(rule.get("prematch", {"type": "none"}), pre)
    if not pre_met:
        return None

    live_met, live_note = _live_condition_met(rule.get("live", {}), intel, key_loss)
    if not live_met:
        return None

    conf = ((intel or {}).get("match") or {}).get("confidence_score", 0)
    full_note = f"{pre_note} | {live_note}"
    if window_note:
        full_note = f"{window_note} {full_note}"

    return {
        "rule_id": rule["rule_id"],
        "user_id": rule["user_id"],
        "label": rule.get("label", "Untitled Rule"),
        "note": full_note,
        "conf": conf,
    }