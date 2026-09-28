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
    "unavailable",
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
    # The scoreline gate. See _scoreline_condition_met() for why this exists
    # and why it is the one condition that fails CLOSED.
    "goals",
}
VALID_SIDES = {"home", "away", "any"}

# Scoreline gate directions. `under`/`over` take a fractional line (2.5),
# `exact` takes a whole number of goals (3).
VALID_GOAL_DIRECTIONS = {"under", "over", "exact"}
MAX_GOAL_LINE = 10


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


VALID_CONDITION_MODES = {"all", "at_least"}
MAX_LIVE_CONDITIONS = 8  # every real type in VALID_LIVE_TYPES, plus headroom


def _validate_live(live) -> dict:
    """
    Normalise and validate the live half of a rule into a CONDITION GROUP.

    ACCEPTED INPUTS
      * a single condition, e.g. {"type": "goals", "direction": "under",
        "line": 2.5} — the original shape. Normalised to a one-condition
        group in "all" mode, which is exactly the old behaviour. This is what
        keeps every alert saved before multi-select working untouched.
      * a group, e.g. {"conditions": [...], "mode": "at_least", "threshold": 2}

    RETURNED SHAPE is always the group, so the evaluator has one code path.
    """
    # Legacy single condition.
    if not isinstance(live, dict) or "conditions" not in live:
        return {
            "conditions": [_validate_one_live_condition(live or {"type": "snapshot"})],
            "mode": "all",
            "threshold": 1,
        }

    conditions = live.get("conditions")
    if not isinstance(conditions, list) or not conditions:
        raise RuleValidationError("live.conditions must be a non-empty list.")
    if len(conditions) > MAX_LIVE_CONDITIONS:
        raise RuleValidationError(
            f"live.conditions accepts at most {MAX_LIVE_CONDITIONS} conditions."
        )

    normalized = [_validate_one_live_condition(c) for c in conditions]

    mode = str(live.get("mode", "all")).strip().lower()
    if mode not in VALID_CONDITION_MODES:
        raise RuleValidationError(
            f"live.mode must be one of {sorted(VALID_CONDITION_MODES)}."
        )

    try:
        threshold = int(live.get("threshold", len(normalized)))
    except (TypeError, ValueError):
        raise RuleValidationError("live.threshold must be a whole number.")
    if threshold < 1 or threshold > len(normalized):
        raise RuleValidationError(
            f"live.threshold must be between 1 and {len(normalized)} "
            f"(you selected {len(normalized)} condition(s))."
        )

    # "all" ignores the threshold, but a nonsensical one is still a typo worth
    # rejecting rather than silently accepting.
    return {"conditions": normalized, "mode": mode, "threshold": threshold}


def _validate_one_live_condition(live: dict) -> dict:
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

    if ltype == "goals":
        # The scoreline gate. There is deliberately NO `side`: a goal
        # limitation is a statement about the MATCH total, because a market
        # like OVER 2.5 is won or lost on the combined count, never on one
        # side's tally.
        direction = str(live.get("direction", "")).strip().lower()
        if direction not in VALID_GOAL_DIRECTIONS:
            raise RuleValidationError(
                f"live.direction must be one of {sorted(VALID_GOAL_DIRECTIONS)}."
            )
        try:
            line = float(live.get("line"))
        except (TypeError, ValueError):
            raise RuleValidationError("live.line must be a number of goals.")
        if line < 0 or line > MAX_GOAL_LINE:
            raise RuleValidationError(
                f"live.line must be between 0 and {MAX_GOAL_LINE}."
            )
        if direction == "exact" and line != int(line):
            raise RuleValidationError(
                "live.line for an exact goal count must be a whole number."
            )
        return {"type": "goals", "direction": direction, "line": line}

    raise RuleValidationError(f"Unhandled live.type: {ltype}")


def _validate_watchlist(raw) -> list[str]:
    """
    The user's accepted matches. DELIBERATELY SOFT.

    A watchlist is a statement of intent — "these are the fixtures I am
    watching" — NOT a filter. The evaluator never tests membership, so a rule
    still fires on any fixture that meets its conditions, including one the
    user did not click. Accepting a match only raises it to the top of the
    feed and marks it, so the user can see at a glance that a match they
    personally care about went live.

    A rule with no watchlist is entirely normal (all three pre-existing rules
    in data/user_rules.json have none), so the default is an empty list.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise RuleValidationError("watchlist must be an array of fixture ids.")
    out: list[str] = []
    for item in raw:
        fid = str(item).strip()
        # Fixture ids are numeric strings from the provider. Accept anything
        # non-empty, but de-duplicate so a double-click cannot bloat the rule.
        if fid and fid not in out:
            out.append(fid)
    return out


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
        "watchlist": _validate_watchlist(payload.get("watchlist")),
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


def update_rule(rule_id: str, patch: dict, user_id: str | None = None) -> dict | None:
    with _lock:
        rules = _read_all()
        target = next((r for r in rules if r.get("rule_id") == rule_id), None)
        if target is None or (user_id is not None and target.get("user_id") != user_id):
            return None
        merged = {**target, **patch}
        if any(k in patch for k in ("prematch", "live", "label", "user_id", "minute_window", "watchlist")):
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


# ==============================================================================
# CANDIDATE DISCOVERY — "show me every match that falls under this condition"
# ==============================================================================
def _candidate_evidence(pre: dict) -> dict:
    """
    The handful of real, already-on-disk facts shown on a candidate card, so a
    user can judge a match without opening it. Every value is read from a
    field the four real prematch sources actually publish — nothing is derived
    or invented here.
    """
    audit = pre.get("team_audit") or {}
    danger = pre.get("danger_report") or {}
    chem = pre.get("match_chemistry_list") or {}
    h_audit = audit.get("home") or {}
    a_audit = audit.get("away") or {}
    h_danger = danger.get("home") or {}
    a_danger = danger.get("away") or {}

    return {
        "has_lineup": bool(audit.get("has_lineup")),
        "has_formation": bool(audit.get("has_formation")),
        "formations": audit.get("formations") or {},
        "home_missing": h_audit.get("missing_count"),
        "away_missing": a_audit.get("missing_count"),
        "home_gk_out": bool(h_audit.get("gk_out")),
        "away_gk_out": bool(a_audit.get("gk_out")),
        "home_breach": bool(h_danger.get("breach")),
        "away_breach": bool(a_danger.get("breach")),
        "home_danger_status": h_danger.get("status"),
        "away_danger_status": a_danger.get("status"),
        "home_formation": h_danger.get("formation"),
        "away_formation": a_danger.get("formation"),
        "chemistry": chem or None,
        "flags": (pre.get("flags") or {}) or None,
        "metrics": (pre.get("metrics") or {}) or None,
        "picks": pre.get("picks") or pre.get("incoming_probabilities") or [],
        "kickoff_utc": audit.get("kickoff_utc"),
        "status_text": audit.get("status_text"),
        "state": audit.get("state"),
    }


def find_candidates(prematch: dict, prematch_db: dict, live_scores: dict | None = None) -> list[dict]:
    """
    Every known fixture, scored against the user's chosen prematch condition.

    The match set is `prematch_db` — the SAME fixture_id-keyed merge of all
    four sources that the live cycle itself uses (stage6.load_all_prematch_data).
    Reusing it here is the point: the card a user accepts is scored by the
    identical predicate the cycle will later use, so "3 matches matched" cannot
    quietly disagree with what actually fires.

    `live_scores` maps fixture_id -> (h, a) and is best-effort: it only adds a
    read-only "current score" to the card so the user can see, at setup time,
    which of the matches they are watching are already past their own goal
    limit. A fixture absent from it simply has no score shown — it is never
    rendered as 0-0.

    Returns rows sorted with matches FIRST (most actionable at the top), then
    by kickoff. Every row carries `met` plus the `reason` string the predicate
    itself produced, so nothing on the card is a UI guess.
    """
    # Validate the incoming condition with the SAME validator the save path
    # uses, so the board can never offer a condition that a save would reject.
    normalized = _validate_prematch(prematch or {"type": "none"})

    live_scores = live_scores or {}
    rows: list[dict] = []

    for fid, pre in (prematch_db or {}).items():
        if not isinstance(pre, dict):
            continue
        met, reason = _prematch_condition_met(normalized, pre)

        teams = pre.get("teams") if isinstance(pre.get("teams"), dict) else {}
        audit_sides = pre.get("team_audit") or {}
        home_name = ((teams.get("home") or {}).get("name")) or (audit_sides.get("home") or {}).get("team_name")
        away_name = ((teams.get("away") or {}).get("name")) or (audit_sides.get("away") or {}).get("team_name")

        # Source of truth for the display name, most-specific first: the
        # aggregator's own "Home vs Away" string, then an explicit name, then
        # the two team names, then the bare id. Never an empty label.
        name = (
            pre.get("fixture")
            or pre.get("name")
            or (" vs ".join([str(x) for x in (home_name, away_name) if x]))
            or f"Fixture {fid}"
        )

        score = live_scores.get(str(fid))
        evidence = _candidate_evidence(pre)

        rows.append({
            "fixture_id": str(fid),
            "name": name,
            "home_name": home_name,
            "away_name": away_name,
            "met": bool(met),
            "reason": reason,
            "evidence": evidence,
            # None means "not known", which the UI must show as unknown, never
            # as a goalless draw.
            "live_score": list(score) if isinstance(score, (tuple, list)) else None,
            "kickoff_utc": evidence.get("kickoff_utc"),
            "state": evidence.get("state"),
        })

    rows.sort(key=lambda r: (not r["met"], str(r.get("kickoff_utc") or ""), r["name"]))
    return rows


def _live_condition_met(rule_live: dict, intel: dict, key_loss: dict, score=None) -> tuple[bool, str]:
    """
    Evaluate ONE live condition.

    `goals` is evaluated here like any other condition. It used to be a
    special case decided before this function was called, which meant it could
    not be combined with anything — "under 2.5 AND home pressure > 60%" was
    inexpressible. It is now a peer, so the scoreline limitation composes with
    the rest of the user's selection.
    """
    ltype = rule_live.get("type")
    intel = intel or {}
    match_intel = intel.get("match") or {}
    home_intel = intel.get("home") or {}
    away_intel = intel.get("away") or {}
    key_loss = key_loss or {}

    if ltype == "snapshot":
        return True, "Live snapshot (always fires)"

    if ltype == "goals":
        # Delegates rather than re-implementing, so the gate keeps its one
        # definition — including failing closed on an unreadable scoreline.
        return _scoreline_condition_met(rule_live, score)

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
        # `live_xg` is CUMULATIVE, not a rate. It is a weighted sum of the whole
        # match so far (SOT, box entries, dangerous attacks, corners, possession)
        # and only ever grows, so a fixed min_value means something DIFFERENT at
        # 45' than at 75'. Measured on a live feed, every match past 45' sat
        # above 3.0, so a 3.0 bar fired on 10 of 10 candidates and meant nothing.
        # A seeded default rule on this condition was REMOVED for exactly that
        # reason. If you build one: pair it with a NARROW minute_window so the
        # bar is only read in one band of match time, and take the bar from the
        # observed distribution for that band — never from an unrelated scale
        # such as the confidence thresholds.
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
        return met, (
            f"xG ({side}) H={h} A={a} >= {min_value}: "
            f"{'✅' if met else '❌'} (cumulative, not a rate)"
        )

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


def _scoreline_condition_met(rule_live: dict, score) -> tuple[bool, str]:
    """
    THE SCORELINE GATE — the limitation the user sets on the goal count.

    THE PROBLEM IT SOLVES
    A prematch condition is a statement about the FIXTURE ("this side has 100%
    second-half H2H over 2.5"). It says nothing about whether the price is
    still available. A 2-0 at 38' makes OVER 2.5 a dead market, yet the old
    rule set had no way to say so, so an alert could arrive for a trade that
    could not be taken any more. This gate is the user's answer: set the goal
    limit, and the alert is only allowed through while the scoreline is still
    inside it.

        direction=over,  line=2.5  ->  total >= 3   the line is already beaten
        direction=under, line=2.5  ->  total <= 2   the line is still alive
        direction=exact, line=3    ->  total == 3   only the named total

    Note the asymmetry, which is the whole point. For OVER, the alert is
    useful once the line HAS been crossed — that is the confirmation. For
    UNDER, usefulness is the opposite: the alert is useful while the line has
    NOT been crossed, because that is the last moment the price still exists.
    Treating both as `total >= line` would fire the UNDER gate only once the
    market was already dead.

    FAILS CLOSED. `score` of None means the provider published no readable
    scoreline this cycle. That is UNKNOWN, not 0-0 (see
    stage6.score_from_fixture, which returns None rather than fabricating a
    goalless draw for exactly this reason). A gate whose entire job is to know
    the scoreline must never pass on a scoreline it does not have.
    """
    direction = rule_live.get("direction", "under")
    line = rule_live.get("line")
    if line is None:
        return False, "Scoreline gate has no goal line set"

    if score is None:
        return False, (
            f"Scoreline gate: scoreline unavailable this cycle, "
            f"cannot confirm {direction} {line} — not alerting"
        )
    if not isinstance(score, (tuple, list)) or len(score) < 2:
        return False, (
            f"Scoreline gate: scoreline unreadable ({score!r}), "
            f"cannot confirm {direction} {line} — not alerting"
        )
    try:
        h, a = int(score[0]), int(score[1])
    except (TypeError, ValueError):
        return False, (
            f"Scoreline gate: scoreline not numeric ({score!r}), "
            f"cannot confirm {direction} {line} — not alerting"
        )

    total = h + a
    base = int(float(line))  # floor() for a positive line

    if direction == "under":
        # "Still available" semantics — see the docstring. A fractional line
        # (2.5) keeps the market alive up to 2 goals; a whole line (3.0) is a
        # push at 3, so the market is still there at 3 too.
        met = total <= base
        return met, (
            f"Scoreline {h}-{a} ({total} goals) — "
            f"under {line} {'still available ✅' if met else 'already gone ❌'}"
        )

    if direction == "over":
        # The line must actually be crossed. A push at a whole line is not a
        # win, so over 3.0 needs 4 — consistent with `under 3.0` still being
        # alive at 3, which is the same fact seen from the other side.
        needed = base + 1
        met = total >= needed
        return met, (
            f"Scoreline {h}-{a} ({total} goals) — "
            f"over {line} {'beaten ✅' if met else 'not yet ❌'}"
        )

    # exact
    met = total == int(line)
    return met, (
        f"Scoreline {h}-{a} ({total} goals) — "
        f"exactly {int(line)}: {'✅' if met else '❌'}"
    )


def safe_dig(d, *keys, default=None):
    """Small local safe-nested-get, kept here so this module has no runtime
    dependency on live_stage6_alerts.py's safe_get (avoids circular import)."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _live_conditions_met(group, intel, key_loss, score=None) -> tuple[bool, str]:
    """
    Evaluate a whole live condition group and decide it by the chosen mode.

        mode="all"       every selected condition must hold
        mode="at_least"  `threshold` of them must hold — any N of the K chosen

    The note is the audit trail. A rule that never fires is far more useful
    when it says WHICH condition held it back, so every condition is named,
    the passing ones ticked, and the blocking ones called out. A silent rule
    looks identical to a broken one.
    """
    # Tolerate a bare single condition so a legacy stored rule evaluates
    # through this one path too.
    if not isinstance(group, dict) or "conditions" not in group:
        group = {"conditions": [group or {"type": "snapshot"}],
                 "mode": "all", "threshold": 1}

    conditions = group.get("conditions") or []
    mode = group.get("mode", "all")
    try:
        threshold = int(group.get("threshold", len(conditions)))
    except (TypeError, ValueError):
        threshold = len(conditions)

    if not conditions:
        return True, "No live condition set (fires every update)"

    results = []
    for cond in conditions:
        try:
            met, note = _live_condition_met(cond, intel, key_loss, score)
        except Exception as exc:
            # One malformed condition must not take the whole evaluation down;
            # it is reported as unmet so the note stays truthful.
            met, note = False, f"{cond.get('type', '?')}: could not be read ({exc})"
        results.append((bool(met), str(note)))

    passed = sum(1 for met, _ in results if met)
    total = len(results)
    met_overall = passed >= threshold if mode == "at_least" else passed == total

    summary = (
        f"{passed}/{total} live conditions met "
        f"({'all required' if mode == 'all' else f'need {threshold}'})"
    )
    detail = " | ".join(note for _, note in results)
    return met_overall, f"{summary} — {detail}"


def describe_goal_gate(group) -> str | None:
    """The scoreline limitation in plain words, e.g. "under 2.5".

    Reads a group and returns the FIRST goal gate it contains, or None. Shown on
    the lockscreen notification, so it must survive being read at a glance with
    no context.
    """
    if not isinstance(group, dict):
        group = {"conditions": [group]} if group else {}
    elif "conditions" not in group:
        # A stored legacy single condition, e.g. {"type": "goals", ...}. It IS
        # a dict, so the isinstance check alone does not catch it.
        group = {"conditions": [group]}
    for cond in group.get("conditions") or []:
        if isinstance(cond, dict) and cond.get("type") == "goals":
            direction = cond.get("direction")
            line = cond.get("line")
            if direction not in VALID_GOAL_DIRECTIONS or line is None:
                continue
            text = int(line) if float(line) == int(line) else line
            if direction == "under":
                return f"under {text}"
            if direction == "over":
                return f"over {text}"
            return f"exactly {text} goals"
    return None



def evaluate_rule_for_match(
    rule: dict,
    intel: dict,
    pre: dict,
    minute: int,
    key_loss: dict,
    score=None,
    fixture_id: str | None = None,
) -> dict | None:
    """
    Returns a triggered-alert dict if this rule fires this cycle, else None.

    `score` and `fixture_id` are keyword-only-ish additions (both defaulted) so
    the 166 existing contract tests and any other caller keep working
    unchanged. `score` is the running (h, a) tuple from
    stage6.score_from_fixture, or None when it could not be read.

    ORDER MATTERS for honesty of the audit trail, not for correctness — every
    gate must pass. The scoreline gate is checked immediately after the
    prematch filter and BEFORE the live-stat threshold, because it is the
    cheapest question to answer and the one most likely to be the reason a
    rule stayed silent.
    """
    if not rule.get("active", True):
        return None

    window_met, window_note = _minute_window_ok(rule, minute)
    if not window_met:
        return None

    pre_met, pre_note = _prematch_condition_met(rule.get("prematch", {"type": "none"}), pre)
    if not pre_met:
        return None

    rule_live = rule.get("live", {})

    # The live half is a CONDITION GROUP, decided by its own mode: all of them,
    # or at least `threshold` of them. The scoreline gate is one member of that
    # group, not a separate step, which is what makes "under 2.5 AND home
    # pressure > 60%" expressible at last.
    live_met, live_note = _live_conditions_met(rule_live, intel, key_loss, score)
    if not live_met:
        return None

    conf = ((intel or {}).get("match") or {}).get("confidence_score", 0)
    full_note = f"{pre_note} | {live_note}"
    if window_note:
        full_note = f"{window_note} {full_note}"

    watchlist = [str(f) for f in (rule.get("watchlist") or [])]
    watchlisted = bool(fixture_id) and str(fixture_id) in watchlist

    return {
        "rule_id": rule["rule_id"],
        "user_id": rule["user_id"],
        "label": rule.get("label", "Untitled Rule"),
        "note": full_note,
        "conf": conf,
        # Soft preference: recorded, never enforced. The alert is emitted
        # either way; this flag only lets the UI rank and mark it.
        "watchlisted": watchlisted,
        "score": list(score) if isinstance(score, (tuple, list)) else None,
        # The scoreline limitation in words, or None when the group has no goal
        # gate. Carried onto the push notification because "under 2.5" is not
        # actionable from a lockscreen without knowing the match is still
        # inside it.
        "gate": describe_goal_gate(rule_live),
    }


