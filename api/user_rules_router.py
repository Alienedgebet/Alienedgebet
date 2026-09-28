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