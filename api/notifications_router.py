"""
FastAPI router for Code 2 push notifications (Web Push).

Wire into api/main.py with:

    from api.notifications_router import router as notifications_router
    app.include_router(notifications_router)

Self-contained: it only reads the caller's existing session user_id, so
notifications are always scoped to the signed-in user. It never exposes
another user's subscriptions.
"""

import os
import sys
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api.auth_store import get_user_for_session, SESSION_COOKIE
import notifications as notify

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class SubscribePayload(BaseModel):
    endpoint: str = Field(..., min_length=8)
    keys: dict = Field(...)
    prefs: Optional[dict] = None


class PrefsPayload(BaseModel):
    triggered: Optional[bool] = None
    settled: Optional[bool] = None
    # The user's own "Setup my alert" notifications, including the scoreline
    # gate. Off by default would be wrong — it is the product — so it defaults
    # on, and the toggle exists to switch it off.
    user_alert: Optional[bool] = None


def _require_user(request: Request):
    user = get_user_for_session(request.cookies.get(SESSION_COOKIE))
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


@router.get("/prefs")
def get_prefs(request: Request):
    """
    The VAPID public key (safe to expose) plus this user's current state.
    The frontend calls this on load to decide whether to show the opt-in.
    """
    user = _require_user(request)
    prefs = notify.get_prefs(user["user_id"])
    return {
        "vapid_public_key": notify.public_key(),
        "supported": bool(notify.public_key()),
        "triggered": prefs["triggered"],
        "settled": prefs["settled"],
        "user_alert": prefs["user_alert"],
        "subscribed": prefs["subscribed"],
        # How many of this user's devices are registered. More than one is
        # normal — a phone and a laptop both receive every alert.
        "devices": prefs.get("devices", 0),
    }


@router.post("/subscribe")
def subscribe(payload: SubscribePayload, request: Request):
    user = _require_user(request)
    if not payload.keys.get("p256dh") or not payload.keys.get("auth"):
        raise HTTPException(status_code=400, detail="keys.p256dh and keys.auth are required")
    record = notify.save_subscription(
        user["user_id"],
        payload.endpoint,
        payload.keys,
        prefs=payload.prefs,
        user_agent=request.headers.get("user-agent", ""),
    )
    return {"ok": True, "subscribed": True, "updated_at": record["updated_at"]}


@router.post("/unsubscribe")
def unsubscribe(request: Request, endpoint: Optional[str] = Query(None)):
    """Unsubscribe this device, or every device when no endpoint is given."""
    user = _require_user(request)
    notify.delete_subscription(user["user_id"], endpoint=endpoint)
    return {"ok": True, "subscribed": False}


@router.patch("/prefs")
def patch_prefs(payload: PrefsPayload, request: Request):
    user = _require_user(request)
    patch = {k: v for k, v in payload.model_dump().items() if v is not None}
    try:
        prefs = notify.update_prefs(user["user_id"], patch)
    except KeyError:
        raise HTTPException(status_code=404, detail="No push subscription for this user")
    return {"ok": True, "triggered": prefs["triggered"], "settled": prefs["settled"],
            "user_alert": prefs["user_alert"]}


@router.get("/recent")
def recent(request: Request, limit: int = 20):
    """
    Most recent notification events, newest last. Used by the in-app list so
    the history stays visible even without OS notifications.
    """
    _require_user(request)
    events = notify.read_events(limit=max(1, min(limit, 100)))
    return {"events": events}
