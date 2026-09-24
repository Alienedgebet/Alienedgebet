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
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root
from api.auth_store import check_rate_limit
from LIVE_SCANNER.user_rules_store import (
    list_rules,
    create_rule,
    update_rule,
    delete_rule,
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
    type: str = Field(
        ...,
        description=(
            "'snapshot' | 'pressure_share' | 'chaos_index' | 'xg' | 'sot' | "
            "'corners' | 'da' | 'key_player_lost'"
        ),
    )
    side: Optional[str] = None
    min_value: Optional[float] = None
    min_count: Optional[int] = None


class MinuteWindow(BaseModel):
    start: int = 0
    end: int = 120


class UserRuleIn(BaseModel):
    # Accepted for wire compatibility, but the server replaces it with the
    # authenticated user ID before persistence.
    user_id: Optional[str] = None
    label: str = "Untitled Rule"
    prematch: PrematchCondition
    live: LiveCondition
    minute_window: Optional[MinuteWindow] = None
    active: bool = True


class UserRulePatch(BaseModel):
    label: Optional[str] = None
    prematch: Optional[PrematchCondition] = None
    live: Optional[LiveCondition] = None
    minute_window: Optional[MinuteWindow] = None
    active: Optional[bool] = None


# ==============================================================================
# CRUD
# ==============================================================================
def _rate(request: Request, bucket: str, limit: int) -> None:
    if not check_rate_limit(f"{bucket}:{request.client.host if request.client else 'unknown'}", limit, 60):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")


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