"""
Code 2 push notifications (Web Push).

Emits two irreversible, high-value events from the live validator:
    TRIGGERED - a prediction armed (with the score at that moment)
    SETTLED   - the final result (WON / LOST)

SUPPORTED is deliberately NOT emitted. It is a transient, reversible state: a
prediction can read SUPPORTED on one cycle and CONTRADICTED the next. Notifying
on it would announce signals that un-happen, which is exactly the misleading
behaviour the validator was rebuilt to eliminate.

Design constraints:
  * Best-effort by design. Every failure path is swallowed so a broken push can
    never delay, raise through, or fail a live match cycle.
  * De-duplicated on fixture+market+target+event and persisted, so a prediction
    notifies exactly once even across restarts and the ~40-110s cycle rate.
  * Subscriptions are per-user, keyed by the existing session user_id.

Web Push requires pywebpush. It is imported lazily and its absence disables
sending without affecting event capture, so the scanner never hard-depends on it.
"""

import json
import os
import threading
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # root-level module
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

EVENTS_FILE = os.path.join(OUTPUT_DIR, "push_events.jsonl")
SUBS_FILE = os.path.join(DATA_DIR, "push_subscriptions.json")
SENT_FILE = os.path.join(DATA_DIR, "push_sent.json")
# Events already handed to the push service. Separate from SENT_FILE (which
# stops an event being recorded twice) so the append-only history can still
# feed the in-app list without being re-sent every cycle.
DELIVERED_FILE = os.path.join(DATA_DIR, "push_delivered.json")

# Only these are ever announced. Keep this list in sync with emit_event callers.
ALLOWED_EVENTS = {"TRIGGERED", "SETTLED"}

_write_lock = threading.Lock()

# Hard cap so a misbehaving provider or a long outage cannot grow these files
# without bound.
MAX_EVENTS = 2000
MAX_SUBSCRIPTIONS = 5000
MAX_SENT = 5000


def _now():
    return datetime.now(timezone.utc).isoformat()


def _ensure_dirs():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = json.load(f)
        return value if value is not None else default
    except (OSError, ValueError, TypeError):
        return default


def _write_json_atomic(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, path)



# ── Event capture ───────────────────────────────────────────────────────────

def event_key(fixture_id, market, target, event):
    """Stable identity for one announcement about one prediction."""
    return f"{fixture_id}:{market}:{target}:{event}"


def _sent_keys():
    return set(_read_json(SENT_FILE, []) or [])


def _remember_sent(key):
    keys = _sent_keys()
    if key in keys:
        return False
    keys.add(key)
    if len(keys) > MAX_SENT:
        keys = set(list(keys)[-MAX_SENT:])
    try:
        _write_json_atomic(SENT_FILE, sorted(keys))
    except OSError:
        return False
    return True


def emit_event(event, fixture_id, fixture, market, target, **details):
    """
    Record a notifiable event. Returns the event key when newly recorded,
    otherwise None (already seen). Never raises.
    """
    if event not in ALLOWED_EVENTS:
        return None
    # A prediction with no identity cannot be de-duplicated or linked back to
    # a fixture, so refuse it rather than recording an unusable "None:None"
    # event that would occupy a delivered slot forever.
    if not fixture_id or not market:
        return None
    try:
        _ensure_dirs()
        key = event_key(fixture_id, market, target, event)
        with _write_lock:
            if not _remember_sent(key):
                return None
            record = {
                "event": event,
                "key": key,
                "fixture_id": str(fixture_id),
                "fixture": fixture,
                "market": market,
                "target": target,
                "at": _now(),
            }
            for name in ("minute", "trigger_minute", "score_at_trigger",
                         "final_score", "settlement", "signal"):
                if name in details and details[name] is not None:
                    record[name] = details[name]
            lines = []
            if os.path.exists(EVENTS_FILE):
                try:
                    with open(EVENTS_FILE, "r", encoding="utf-8") as f:
                        lines = f.readlines()[-MAX_EVENTS:]
                except OSError:
                    lines = []
            lines.append(json.dumps(record) + "\n")
            tmp = EVENTS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(lines)
            os.replace(tmp, EVENTS_FILE)
        return key
    except Exception:
        # Notifications are never allowed to disturb the live pipeline.
        return None


# ── Subscription store ──────────────────────────────────────────────────────

def list_subscriptions():
    data = _read_json(SUBS_FILE, {})
    return data if isinstance(data, dict) else {}


def save_subscription(user_id, endpoint, keys, prefs=None, user_agent=""):
    """Register (or refresh) a browser push endpoint for a user."""
    if not user_id or not endpoint or not isinstance(keys, dict):
        raise ValueError("user_id, endpoint and keys are required")
    with _write_lock:
        data = list_subscriptions()
        existing = data.get(user_id, {})
        merged_prefs = {"triggered": True, "settled": True}
        if isinstance(existing.get("prefs"), dict):
            merged_prefs.update(existing["prefs"])
        if isinstance(prefs, dict):
            merged_prefs.update({k: v for k, v in prefs.items()
                                 if k in merged_prefs})
        data[user_id] = {
            "endpoint": endpoint,
            "keys": {"p256dh": keys.get("p256dh"), "auth": keys.get("auth")},
            "prefs": merged_prefs,
            "user_agent": user_agent[:200],
            "created_at": existing.get("created_at") or _now(),
            "updated_at": _now(),
        }
        if len(data) > MAX_SUBSCRIPTIONS:
            for stale in sorted(data, key=lambda u: data[u].get("created_at", ""))[
                    :len(data) - MAX_SUBSCRIPTIONS]:
                data.pop(stale, None)
        _write_json_atomic(SUBS_FILE, data)
    return data[user_id]


def delete_subscription(user_id, endpoint=None):
    """Remove a user's endpoint. With no endpoint, removes all of theirs."""
    with _write_lock:
        data = list_subscriptions()
        record = data.get(user_id)
        if not record:
            return False
        if endpoint and record.get("endpoint") != endpoint:
            return False
        data.pop(user_id, None)
        _write_json_atomic(SUBS_FILE, data)
    return True


def get_prefs(user_id):
    record = list_subscriptions().get(user_id) or {}
    prefs = record.get("prefs") if isinstance(record.get("prefs"), dict) else {}
    return {
        "triggered": bool(prefs.get("triggered", True)),
        "settled": bool(prefs.get("settled", True)),
        "subscribed": bool(record.get("endpoint")),
    }


def update_prefs(user_id, patch):
    with _write_lock:
        data = list_subscriptions()
        record = data.get(user_id)
        if not record:
            raise KeyError("no push subscription for this user")
        prefs = record.get("prefs") or {}
        for name in ("triggered", "settled"):
            if name in patch:
                prefs[name] = bool(patch[name])
        record["prefs"] = prefs
        record["updated_at"] = _now()
        data[user_id] = record
        _write_json_atomic(SUBS_FILE, data)
    return prefs


# ── Dispatch ────────────────────────────────────────────────────────────────

def _vapid_keys():
    """
    Read VAPID keys from the environment.

    The scanner already calls load_dotenv(), but this module is also imported
    by the API router, so load it defensively rather than silently seeing no
    keys and disabling delivery.
    """
    priv = os.getenv("VAPID_PRIVATE_KEY")
    pub = os.getenv("VAPID_PUBLIC_KEY")
    if not (priv and pub):
        try:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(BASE_DIR, ".env"))
        except Exception:
            pass
        priv = os.getenv("VAPID_PRIVATE_KEY")
        pub = os.getenv("VAPID_PUBLIC_KEY")
    return (priv or None), (pub or None)


def public_key():
    return _vapid_keys()[1]


def build_payload(event):
    """Human-readable notification text. Kept short — lockscreen space is tiny."""
    fixture = event.get("fixture") or "Match"
    market = event.get("market") or ""
    target = event.get("target") or ""
    label = market if target in (None, "", "match") else f"{market} ({target})"
    if event.get("event") == "TRIGGERED":
        minute = event.get("trigger_minute", event.get("minute"))
        score = event.get("score_at_trigger")
        title = f"🔥 {label} armed"
        body = f"{fixture}" + (f" · {minute}'" if minute is not None else "")
        if score:
            body += f" · score {score}"
        data = {
            "fixture_id": event.get("fixture_id"),
            "url": f"/live/edges?fixture={event.get('fixture_id')}",
        }
    else:
        settlement = str(event.get("settlement") or "")
        # check_if_done() phrases outcomes as e.g. "Away scored ✅",
        # "GG settled ✅" or "... ❌", so detect the mark, not a prefix.
        won = "✅" in settlement
        lost = "❌" in settlement
        title = ("✅ " if won else "❌ " if lost else "🏁 ") + f"{label} settled"
        body = f"{fixture}"
        if event.get("final_score"):
            body += f" · final {event['final_score']}"
        if settlement:
            body += f" · {settlement}"
        data = {
            "fixture_id": event.get("fixture_id"),
            "url": f"/live/edges?fixture={event.get('fixture_id')}",
        }
    return {"title": title, "body": body, "data": data}


def _send_one(subscription, payload, vapid_private, vapid_public):
    """
    Send to a single endpoint.

    Returns "sent", "gone" (404/410 - prune) or "error". Never raises, so one
    dead subscription cannot block the rest.
    """
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        return "error"
    try:
        webpush(
            subscription_info={
                "endpoint": subscription["endpoint"],
                "keys": subscription.get("keys") or {},
            },
            data=json.dumps(payload),
            vapid_private_key=vapid_private,
            vapid_claims={"sub": "mailto:alerts@alienedge.tech"},
            ttl=3600,
            timeout=10,
        )
        return "sent"
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            return "gone"
        return "error"
    except Exception:
        return "error"


def dispatch(events, subscriptions=None):
    """
    Send the given events to subscribed users.

    Returns a summary dict. Safe to call from anywhere: any internal error is
    contained and reported as counts rather than propagated.
    """
    summary = {"sent": 0, "failed": 0, "pruned": 0, "skipped": 0}
    vapid_private, vapid_public = _vapid_keys()
    if not vapid_private or not vapid_public:
        summary["skipped"] = len(events or [])
        return summary
    if subscriptions is None:
        subscriptions = list_subscriptions()
    if not subscriptions:
        summary["skipped"] = len(events or [])
        return summary

    prune = []
    delivered_now = []
    for event in events or []:
        name = event.get("event")
        # Preference keys are stored lowercase ("triggered"/"settled") while
        # event names are uppercase. Comparing directly silently ignored every
        # user toggle, so normalise before looking up the preference.
        pref_name = str(name or "").lower()
        payload = build_payload(event)
        attempted = False
        for user_id, sub in list(subscriptions.items()):
            prefs = sub.get("prefs") or {}
            if not prefs.get(pref_name, True):
                summary["skipped"] += 1
                continue
            attempted = True
            result = _send_one(sub, payload, vapid_private, vapid_public)
            if result == "sent":
                summary["sent"] += 1
            elif result == "gone":
                summary["pruned"] += 1
                prune.append(user_id)
            else:
                summary["failed"] += 1
        # Only retire the event once every subscriber was actually attempted,
        # so a transient failure is retried on the next cycle instead of
        # silently dropping an alert the user never received.
        if attempted:
            delivered_now.append(event.get("key"))
    if prune:
        try:
            with _write_lock:
                data = list_subscriptions()
                for user_id in set(prune):
                    data.pop(user_id, None)
                _write_json_atomic(SUBS_FILE, data)
        except Exception:
            pass
    mark_delivered(delivered_now)
    return summary


def read_events(limit=200):
    try:
        if not os.path.exists(EVENTS_FILE):
            return []
        with open(EVENTS_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
    except OSError:
        return []
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _delivered_keys():
    return set(_read_json(DELIVERED_FILE, []) or [])


def pending_events(limit=200):
    """
    Events that have been recorded but not yet handed to the dispatcher.

    The event log is append-only history (it also feeds the in-app list), so
    delivery needs its own persisted marker. Without this the dispatcher would
    re-send the last N events on every cycle.
    """
    delivered = _delivered_keys()
    return [e for e in read_events(limit=limit) if e.get("key") not in delivered]


def mark_delivered(keys):
    """Record events as handed off so they are never sent twice."""
    if not keys:
        return
    with _write_lock:
        delivered = _delivered_keys()
        delivered.update(keys)
        if len(delivered) > MAX_SENT:
            delivered = set(sorted(delivered)[-MAX_SENT:])
        try:
            _write_json_atomic(DELIVERED_FILE, sorted(delivered))
        except OSError:
            pass
