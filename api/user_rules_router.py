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

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root
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
    user_id: str
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
@router.get("/user-rules")
def get_user_rules(user_id: str = Query(..., description="Anonymous or account user id")):
    return list_rules(user_id=user_id)


@router.post("/user-rules", status_code=201)
def post_user_rule(payload: UserRuleIn):
    # exclude_none so optional fields the client didn't set (e.g. `flag`
    # on a `type: rate` prematch condition) aren't sent through as
    # explicit None and don't confuse the store's dict-based validators.
    try:
        return create_rule(payload.model_dump(exclude_none=True))
    except RuleValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.patch("/user-rules/{rule_id}")
def patch_user_rule(rule_id: str, patch: UserRulePatch):
    clean_patch = {
        k: (v.model_dump(exclude_none=True) if hasattr(v, "model_dump") else v)
        for k, v in patch.model_dump(exclude_none=True).items()
    }
    try:
        updated = update_rule(rule_id, clean_patch)
    except RuleValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if updated is None:
        raise HTTPException(status_code=404, detail="Rule not found.")
    return updated


@router.delete("/user-rules/{rule_id}", status_code=204)
def delete_user_rule(rule_id: str, user_id: str = Query(...)):
    ok = delete_rule(rule_id, user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found or not owned by this user.")
    return None


# ==============================================================================
# "MY ALERTS" — filters ready_to_push.json (already written by live_stage6_alerts.py)
# down to only this user's fired alerts.
# ==============================================================================
@router.get("/alerts/mine")
def get_my_alerts(user_id: str = Query(...), limit: int = Query(50, le=200)):
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
                if row.get("user_id") == user_id:
                    rows.append(row)
    except OSError:
        return []

    rows.sort(key=lambda r: r.get("time", ""), reverse=True)
    return rows[:limit]