"""
FastAPI router for user-defined live alert rules.

Wire into your existing api/main.py with:

    from api.user_rules_router import router as user_rules_router
    app.include_router(user_rules_router)

Self-contained — does not touch or require changes to your existing
/api/live/* endpoints. If you're on Pydantic v1 instead of v2, replace
every `.model_dump()` below with `.dict()`, and every `exclude_none=True`
usage still works the same way under v1.
"""

import os
import sys
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, Union

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root
from api.auth_store import check_rate_limit
from LIVE_SCANNER.user_rules_store import (
    list_rules,
    create_rule,
    update_rule,
    delete_rule,
    find_candidates,
    RuleValidationError,
)

router = APIRouter(prefix="/api/live", tags=["live-user-rules"])

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
READY_TO_PUSH_FILE = os.path.join(OUTPUT_DIR, "ready_to_push.json")
ORCHESTRATOR_BOARD_FILE = os.path.join(OUTPUT_DIR, "orchestrator_board.json")


# ==============================================================================
# ALERT STATUS — "where is this alert right now?"
# ==============================================================================
#
# An alert that has never fired is indistinguishable from one that can never
# fire. The alert log alone cannot tell them apart, because a log only records
# things that happened. So status is assembled from three sources:
#
#   rule_live      (the board)  which rules match a LIVE fixture at this instant
#   ready_to_push  (the log)    what this rule has actually fired, and when
#   subscriptions               whether this user could even receive it
#
# All three are read-only. Nothing here creates, mutates or deletes an alert.
ALERT_HISTORY_MAX_AGE_HOURS = 48


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _parse_iso(value):
    """
    Parse a timestamp to an aware datetime, or None.

    The alert log writes NAIVE local timestamps (`datetime.now().isoformat()`),
    while the staleness cutoffs are timezone-aware UTC. Comparing the two
    raises TypeError, which took the whole status endpoint down on every real
    call. A naive timestamp is therefore interpreted in the server's own local
    zone — which is how it was written — and only then compared.
    """
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed


def _rule_fire_history(user_id: str) -> dict:
    """rule_id -> {count, last: {...}} from the alert log, newest last."""
    if not os.path.exists(READY_TO_PUSH_FILE):
        return {}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ALERT_HISTORY_MAX_AGE_HOURS)
    out: dict = {}
    try:
        with open(READY_TO_PUSH_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("user_id") != user_id or not rec.get("rule_id"):
                    continue
                stamp = _parse_iso(rec.get("time"))
                if stamp is not None and stamp < cutoff:
                    continue
                entry = {
                    "fixture_id": rec.get("f_id"),
                    "fixture": rec.get("fixture"),
                    "minute": rec.get("minute"),
                    "score": rec.get("score_at_trigger"),
                    "time": rec.get("time"),
                    "outcome": rec.get("outcome"),
                }
                slot = out.setdefault(rec["rule_id"], {"count": 0, "last": None})
                slot["count"] += 1
                # The file is append-ordered, so the last one seen is newest.
                slot["last"] = entry
    except OSError:
        return {}
    return out


@router.get("/user-rules/status")
def get_user_rule_status(request: Request):
    """
    Per-rule status: is this alert waiting, matching right now, or already
    fired?

    Only possible by combining the live board with the fire history — a log
    records what happened, never what is about to. That is the difference
    between "waiting for a match" and "no match can ever satisfy this".
    """
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")

    rules = list_rules(user_id=user["user_id"])
    history = _rule_fire_history(user["user_id"])
    board = _read_json(ORCHESTRATOR_BOARD_FILE, {}) or {}
    rule_live = board.get("rule_live") or {}
    board_age = _parse_iso(board.get("generated_at"))

    # Whether this user could receive a push at all, on their own devices.
    try:
        from notifications import get_prefs as _push_prefs
        prefs = _push_prefs(user["user_id"])
        push_ready = bool(prefs.get("subscribed"))
    except Exception:
        # Never let a notification-store problem hide the alert status.
        push_ready = None

    out = []
    for rule in rules:
        rid = rule["rule_id"]
        live = rule_live.get(rid) or []
        hist = history.get(rid) or {}
        last = hist.get("last")
        active = bool(rule.get("active", True))

        if not active:
            status, label = "paused", "Paused"
        elif live:
            status, label = "live", "Qualifying now"
        elif last:
            status, label = "fired", "Alerted"
        else:
            status, label = "waiting", "Waiting"

        # "It matches right now but this device cannot receive it" is the one
        # combination that otherwise looks like silence. Say it explicitly
        # rather than leaving the user to wonder why nothing arrived.
        needs_push = bool(live) and push_ready is False

        out.append({
            "rule_id": rid,
            "label": rule.get("label", "Untitled Rule"),
            "active": active,
            "status": status,
            "status_label": label,
            "live_count": len(live),
            "live_matches": live,
            "fired_count": hist.get("count", 0),
            "last_fired": last,
            "needs_push": needs_push,
            "push_ready": push_ready,
            # None when the board has never been written, so the UI can say so
            # rather than rendering a confident "nothing right now".
            "board_age": board.get("generated_at") if board else None,
            "board_stale": bool(
                board_age is not None
                and (datetime.now(timezone.utc) - board_age) > timedelta(minutes=10)
            ),
        })
    return out


# ==============================================================================
# SCHEMAS
# Every field here mirrors exactly what user_rules_store.py's
# _validate_prematch() / _validate_live() / _validate_minute_window()
# actually accept. Fields not needed for a given `type` are simply left
# unset by the frontend — the store's validators enforce correctness
# server-side regardless of what the client sends.
# ==============================================================================
class PrematchCondition(BaseModel):
    type: str = Field(
        ...,
        description=(
            "'none' | 'flag' | 'rate' | 'gk_liability' | 'key_missing' | "
            "'aggregator_chemistry' | 'aggregator_breach'"
        ),
    )
    # flag
    flag: Optional[str] = None
    # rate
    metric: Optional[str] = None
    min_value: Optional[float] = None
    # gk_liability / key_missing / aggregator_breach
    side: Optional[str] = None
    # key_missing
    min_count: Optional[int] = None
    # aggregator_chemistry
    market: Optional[str] = None
    level: Optional[str] = None


class LiveCondition(BaseModel):
    """One live condition, e.g. {"type": "goals", "direction": "under",
    "line": 2.5}. Several of these can be combined — see LiveConditionGroup."""
    type: str = Field(
        ...,
        description=(
            "'snapshot' | 'pressure_share' | 'chaos_index' | 'xg' | 'sot' | "
            "'corners' | 'da' | 'key_player_lost' | 'goals'"
        ),
    )
    side: Optional[str] = None
    min_value: Optional[float] = None
    min_count: Optional[int] = None
    # Scoreline gate ('goals'): direction is "under" | "over" | "exact" and
    # `line` is the goal total. There is no `side` — a goal limitation is
    # always about the match total, never one side's tally.
    direction: Optional[str] = None
    line: Optional[float] = None


class LiveConditionGroup(BaseModel):
    """
    The live half of a rule: any number of conditions plus how many must hold.

    mode="all"      every condition must hold
    mode="at_least" `threshold` of them must hold — any N of the K chosen

    A bare single LiveCondition is still accepted and normalised to a
    one-condition group, so alerts saved before multi-select keep working.
    """
    conditions: list[LiveCondition]
    mode: str = "all"
    threshold: Optional[int] = None


class MinuteWindow(BaseModel):
    start: int = 0
    end: int = 120


class UserRuleIn(BaseModel):
    # Accepted for wire compatibility, but the server replaces it with the
    # authenticated user ID before persistence.
    user_id: Optional[str] = None
    label: str = "Untitled Rule"
    prematch: PrematchCondition
    # Either a group of conditions, or a single condition (legacy shape).
    live: Union[LiveConditionGroup, LiveCondition]
    minute_window: Optional[MinuteWindow] = None
    # Fixture ids the user accepted in the setup board. SOFT: it ranks and
    # marks alerts, it never filters them.
    watchlist: Optional[list[str]] = None
    active: bool = True


class UserRulePatch(BaseModel):
    label: Optional[str] = None
    prematch: Optional[PrematchCondition] = None
    live: Optional[Union[LiveConditionGroup, LiveCondition]] = None
    minute_window: Optional[MinuteWindow] = None
    watchlist: Optional[list[str]] = None
    active: Optional[bool] = None


class CandidateRequest(BaseModel):
    """Just the prematch condition to score the whole fixture board against."""

    prematch: PrematchCondition


# ==============================================================================
# CRUD
# ==============================================================================
def _rate(request: Request, bucket: str, limit: int) -> None:
    if not check_rate_limit(f"{bucket}:{request.client.host if request.client else 'unknown'}", limit, 60):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")


# ── CANDIDATE BOARD SUPPORT ───────────────────────────────────────────────
# The setup board needs the running scoreline of whatever is live right now, so
# a user setting "under 2.5" can see, before saving, which matches are already
# past their own limit. Read from the board stage 6 already publishes — no new
# provider call, and no score is invented for a fixture that is not live.
LIVE_DASHBOARD_FILE = os.path.join(OUTPUT_DIR, "live_dashboard.json")


def _live_score_index() -> dict:
    """fixture_id -> (h, a) for fixtures that are actually live right now."""
    index: dict = {}
    try:
        with open(LIVE_DASHBOARD_FILE, "r", encoding="utf-8") as f:
            board = json.load(f)
    except (OSError, json.JSONDecodeError):
        return index

    for row in (board or {}).get("matches", []) or []:
        if not isinstance(row, dict):
            continue
        fid = row.get("id")
        if fid is None:
            continue
        stats = row.get("statistics") or {}
        try:
            h = int(float((stats.get("home") or {}).get("goals")))
            a = int(float((stats.get("away") or {}).get("goals")))
        except (TypeError, ValueError):
            # A live fixture whose goals block is missing is UNKNOWN, not 0-0.
            # Leaving it out keeps the board honest instead of showing a
            # goalless draw nobody ever saw.
            continue
        index[str(fid)] = (h, a)
    return index


@router.post("/user-rules/candidates")
def post_user_rule_candidates(payload: CandidateRequest, request: Request):
    """
    Every known fixture, scored against the user's chosen prematch condition.

    Read-only: it touches no rule store and no engine state, it only reads the
    four prematch sources the live cycle already reads. The condition is
    validated with the same validator a save would use, so the board can never
    offer a combination that the save endpoint would reject with a 422.
    """
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    _rate(request, f"candidates:{user['user_id']}", 60)

    # Imported here, not at module scope: stage6 pulls in requests/dotenv and
    # a rate gate that has no business being initialised by the rules router.
    from LIVE_SCANNER.live_stage6_alerts import build_prematch_db

    # `payload.model_dump()` yields {"prematch": {...}} — the WRAPPER. Passing
    # that straight to find_candidates() gave it a dict with no "type" key, so
    # every condition was rejected as invalid. Unwrap the condition itself.
    condition = payload.model_dump(exclude_none=True).get("prematch") or {"type": "none"}
    try:
        return find_candidates(condition, build_prematch_db(), _live_score_index())
    except RuleValidationError:
        raise HTTPException(status_code=422, detail="The prematch condition is invalid.")


@router.get("/user-rules")
def get_user_rules(request: Request, user_id: Optional[str] = Query(None)):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return list_rules(user_id=user["user_id"])


@router.post("/user-rules", status_code=201)
def post_user_rule(payload: UserRuleIn, request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    _rate(request, f"rule:{user['user_id']}", 30)
    clean = payload.model_dump(exclude_none=True)
    clean["user_id"] = user["user_id"]
    try:
        return create_rule(clean)
    except RuleValidationError:
        raise HTTPException(status_code=422, detail="The alert rule is invalid.")


@router.patch("/user-rules/{rule_id}")
def patch_user_rule(rule_id: str, patch: UserRulePatch, request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    _rate(request, f"rule:{user['user_id']}", 30)
    clean_patch = {
        k: (v.model_dump(exclude_none=True) if hasattr(v, "model_dump") else v)
        for k, v in patch.model_dump(exclude_none=True).items()
    }
    try:
        updated = update_rule(rule_id, clean_patch, user_id=user["user_id"])
    except RuleValidationError:
        raise HTTPException(status_code=422, detail="The alert rule is invalid.")
    if updated is None:
        raise HTTPException(status_code=404, detail="Rule not found.")
    return updated


@router.delete("/user-rules/{rule_id}", status_code=204)
def delete_user_rule(rule_id: str, request: Request, user_id: Optional[str] = Query(None)):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    ok = delete_rule(rule_id, user["user_id"])
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found or not owned by this user.")
    return None


# ==============================================================================
# "MY ALERTS" — filters ready_to_push.json (already written by live_stage6_alerts.py)
# down to only this user's fired alerts.
# ==============================================================================
@router.get("/alerts/mine")
def get_my_alerts(request: Request, user_id: Optional[str] = Query(None), limit: int = Query(50, ge=1, le=200)):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if not os.path.exists(READY_TO_PUSH_FILE):
        return []

    rows = []
    try:
        with open(READY_TO_PUSH_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("user_id") == user["user_id"]:
                    rows.append(row)
    except OSError:
        return []

    rows.sort(key=lambda r: r.get("time", ""), reverse=True)
    return rows[:limit]