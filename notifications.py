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
#
# USER_ALERT is the user-defined alert (Code 6 "Setup my alert"), including the
# scoreline gate. It is a PERSONAL announcement, not a system one, so it is
# audience-scoped in dispatch(): it goes only to the user who owns the rule.
# TRIGGERED/SETTLED remain the system prediction events and stay broadcast.
ALLOWED_EVENTS = {"TRIGGERED", "SETTLED", "USER_ALERT"}

# Preference keys are the lowercased event names. Derived from ALLOWED_EVENTS so
# adding an event type cannot silently ship without a toggle to switch it off.
DEFAULT_PREFS = {e.lower(): True for e in ALLOWED_EVENTS}

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
                         "final_score", "settlement", "signal", "rule_id",
                         "rule_label", "gate", "watchlisted"):
                if name in details and details[name] is not None:
                    record[name] = details[name]
            # AUDIENCE. A user-defined alert belongs to exactly one account.
            # Without this, dispatch() — which is a broadcast for the system
            # TRIGGERED/SETTLED events — would push one user's private alert to
            # every subscriber on the system. Recorded only when the caller
            # supplies it, so a legacy event simply stays a broadcast.
            if details.get("audience_user_id"):
                record["audience_user_id"] = str(details["audience_user_id"])
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
#
# SHAPE: { user_id: { endpoint_url: {endpoint, keys, prefs, ...} } }
#
# This is a nested map, not one endpoint per user. The original store held a
# single endpoint per user_id, so subscribing on a phone and then on a laptop
# SILENTLY REPLACED the phone — the user would receive alerts on one device,
# believe both were covered, and miss every alert on the other. Every read path
# below tolerates the old flat shape and migrates it, so an existing
# single-device subscriber keeps working untouched on first load.


def _migrate(data):
    """Fold any legacy single-endpoint records into the nested shape, in place."""
    if not isinstance(data, dict):
        return {}
    for user_id, value in list(data.items()):
        # Legacy: {endpoint, keys, prefs, ...} describing ONE device.
        if isinstance(value, dict) and value.get("endpoint"):
            data[user_id] = {value["endpoint"]: value}
    return data


def list_subscriptions():
    data = _read_json(SUBS_FILE, {})
    return _migrate(data) if isinstance(data, dict) else {}


def _user_devices(data, user_id):
    """This user's device records, as a list. Tolerates the legacy flat shape."""
    value = (data or {}).get(user_id)
    if not isinstance(value, dict) or not value:
        return []
    if value.get("endpoint"):
        return [value]  # legacy single-device record
    return [v for v in value.values() if isinstance(v, dict) and v.get("endpoint")]


def save_subscription(user_id, endpoint, keys, prefs=None, user_agent=""):
    """Register (or refresh) a browser push endpoint for a user.

    Multiple devices per user are now kept side by side. Re-subscribing the SAME
    endpoint refreshes that device rather than creating a duplicate.
    """
    if not user_id or not endpoint or not isinstance(keys, dict):
        raise ValueError("user_id, endpoint and keys are required")
    with _write_lock:
        data = list_subscriptions()
        devices = {d["endpoint"]: d for d in _user_devices(data, user_id)}

        # Prefs are a per-USER setting. Carry them across from an existing
        # device so adding a second device does not silently reset the user's
        # choices back to their defaults.
        merged_prefs = dict(DEFAULT_PREFS)
        for dev in devices.values():
            if isinstance(dev.get("prefs"), dict):
                merged_prefs.update(
                    {k: v for k, v in dev["prefs"].items() if k in DEFAULT_PREFS}
                )
        if isinstance(prefs, dict):
            merged_prefs.update(
                {k: bool(v) for k, v in prefs.items() if k in DEFAULT_PREFS}
            )

        existing = devices.get(endpoint, {})
        devices[endpoint] = {
            "endpoint": endpoint,
            "keys": {"p256dh": keys.get("p256dh"), "auth": keys.get("auth")},
            "prefs": merged_prefs,
            "user_agent": user_agent[:200],
            "created_at": existing.get("created_at") or _now(),
            "updated_at": _now(),
        }
        data[user_id] = devices

        # Cap by DEVICE count, not user count, so one user with many devices
        # cannot quietly evict everyone else's single phone.
        total = sum(len(v) for v in data.values() if isinstance(v, dict))
        if total > MAX_SUBSCRIPTIONS:
            ordered = sorted(
                ((d.get("created_at", ""), u, e)
                 for u, devs in data.items() if isinstance(devs, dict)
                 for e, d in devs.items()),
                key=lambda t: t[0],
            )
            for _, u, e in ordered[: max(0, total - MAX_SUBSCRIPTIONS)]:
                if isinstance(data.get(u), dict):
                    data[u].pop(e, None)
        _write_json_atomic(SUBS_FILE, data)
    return devices[endpoint]


def delete_subscription(user_id, endpoint=None):
    """Remove one device, or with no endpoint, all of the user's devices."""
    with _write_lock:
        data = list_subscriptions()
        devices = {d["endpoint"]: d for d in _user_devices(data, user_id)}
        if not devices:
            return False
        if endpoint:
            if endpoint not in devices:
                return False
            devices.pop(endpoint, None)
        else:
            devices = {}
        if devices:
            data[user_id] = devices
        else:
            data.pop(user_id, None)
        _write_json_atomic(SUBS_FILE, data)
    return True


def get_prefs(user_id):
    """This user's preferences, and whether ANY of their devices is subscribed."""
    devices = _user_devices(list_subscriptions(), user_id)
    if not devices:
        return {**DEFAULT_PREFS, "subscribed": False, "devices": 0}
    # Newest device wins. Prefs are written to every device together, so this is
    # only a defensive tie-break for a half-migrated file.
    newest = max(devices, key=lambda d: d.get("updated_at", ""))
    prefs = newest.get("prefs") if isinstance(newest.get("prefs"), dict) else {}
    out = {name: bool(prefs.get(name, True)) for name in DEFAULT_PREFS}
    out["subscribed"] = True
    out["devices"] = len(devices)
    return out


def update_prefs(user_id, patch):
    """Update preferences on EVERY device the user owns, so they cannot diverge."""
    with _write_lock:
        data = list_subscriptions()
        devices = {d["endpoint"]: d for d in _user_devices(data, user_id)}
        if not devices:
            raise KeyError("no push subscription for this user")
        for dev in devices.values():
            prefs = dict(DEFAULT_PREFS)
            if isinstance(dev.get("prefs"), dict):
                prefs.update(
                    {k: v for k, v in dev["prefs"].items() if k in DEFAULT_PREFS}
                )
            for name in DEFAULT_PREFS:
                if name in patch:
                    prefs[name] = bool(patch[name])
            dev["prefs"] = prefs
            dev["updated_at"] = _now()
        data[user_id] = devices
        _write_json_atomic(SUBS_FILE, data)
    return get_prefs(user_id)


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
    if event.get("event") == "USER_ALERT":
        # The user's OWN alert, fired by their rule. The scoreline is the whole
        # point of the scoreline gate, so it leads the body — "under 2.5" is
        # useless to act on without knowing the match is still inside it.
        label = event.get("rule_label") or event.get("market") or "your alert"
        title = f"🔥 {label}"
        body = f"{fixture}"
        minute = event.get("minute")
        if minute is not None:
            body += f" · {minute}'"
        score = event.get("score_at_trigger")
        if score:
            body += f" · {score}"
        gate = event.get("gate")
        if gate:
            body += f" · {gate}"
        data = {
            "fixture_id": event.get("fixture_id"),
            "rule_id": event.get("rule_id"),
            "url": f"/live/edges?fixture={event.get('fixture_id')}",
        }
    elif event.get("event") == "TRIGGERED":
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

    AUDIENCE. An event carrying `audience_user_id` is a private, user-owned
    announcement and is sent ONLY to that account's devices. An event without
    one is a system announcement and stays a broadcast, which is what the
    original Code 2 TRIGGERED/SETTLED behaviour was.

    The distinction is the whole reason this function was rewritten: the old
    version looped over every subscriber for every event, so a personal alert
    would have been pushed to every account on the system. `attempted` tracks
    whether the intended audience was actually reached, and only then is the
    event retired — an alert addressed to someone with no subscribed device
    stays pending instead of being silently consumed.
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

    prune = []  # (user_id, endpoint) — a dead DEVICE, not a dead user
    delivered_now = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        name = event.get("event")
        # Preference keys are stored lowercase ("user_alert"/"triggered") while
        # event names are uppercase. Comparing directly silently ignored every
        # user toggle, so normalise before looking up the preference.
        pref_name = str(name or "").lower()
        audience = event.get("audience_user_id")
        payload = build_payload(event)
        attempted = False

        for user_id, raw in list(subscriptions.items()):
            # Private event: only ever the named account.
            if audience and str(user_id) != str(audience):
                continue
            for sub in _user_devices({user_id: raw}, user_id):
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
                    prune.append((user_id, sub.get("endpoint")))
                else:
                    summary["failed"] += 1

        if attempted:
            delivered_now.append(event.get("key"))
    if prune:
        try:
            with _write_lock:
                data = list_subscriptions()
                for user_id, endpoint in prune:
                    devices = data.get(user_id)
                    # Remove only the dead DEVICE. Dropping the whole account
                    # here would silently unsubscribe the user's phone because
                    # their laptop was thrown away.
                    if isinstance(devices, dict):
                        devices.pop(endpoint, None)
                        if not devices:
                            data.pop(user_id, None)
                _write_json_atomic(SUBS_FILE, data)
        except Exception:
            pass
    mark_delivered(delivered_now)
    return summary


def dispatch_pending(limit=50):
    """Hand every undelivered event to the push service.

    The single entry point the live cycle should call. Wrapped in its own
    try/except by the caller: a broken push must never delay or break a live
    analysis cycle, which is this module's standing contract.
    """
    try:
        pending = pending_events(limit=limit)
        if not pending:
            return {"sent": 0, "failed": 0, "pruned": 0, "skipped": 0, "pending": 0}
        summary = dispatch(pending)
        summary["pending"] = len(pending)
        return summary
    except Exception:
        # Never let a push failure escape into the scanner.
        return {"sent": 0, "failed": 0, "pruned": 0, "skipped": 0, "pending": 0, "error": True}



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
