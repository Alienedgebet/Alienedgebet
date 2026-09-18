"""
shared_fixture_window.py — SHARED FUTURE FIXTURE ACQUISITION + 7-DAY SLIDING WINDOW.

WHAT THIS IS
------------
The reusable future-data layer that BOTH consumers share:
    PREMATCH (its target date is the first day of the window)
    WEEKLY   (GG / WIN / O2.5 over the same seven dates)
It is NOT a Weekly cache, NOT a DNA cache and NOT an API cache. The global API
cache (api_cache.smart_get) remains ABOVE this layer: every fetch here goes
through `requests.get`, which main.py has hijacked with smart_get, so this
module can never bypass the umbrella protection:

    SportMonks
        ↑
    GLOBAL API CACHE / smart_get / guards        (api_cache.py)
        ↑
    SHARED FUTURE FIXTURE ACQUISITION            (this file)
        ↑
    7-DAY SLIDING WINDOW (one canonical store)
        ↑
    PREMATCH  +  WEEKLY

WHY A NEW STORE (and not data/fixture_date_cache.json / output_store)
--------------------------------------------------------------------
Investigated before writing anything; this file is the ONE authoritative
future-fixture source of truth, and it does not duplicate any existing store:
  * data/fixture_date_cache.json is OWNED BY THE LIVE SCANNER
    (LIVE_SCANNER/live_stage1_prematch.py): single-date, written every ~cycle by
    a different process, 15-minute TTL, `_acquisition_ok` tagging, no horizon and
    no eviction. Sharing it would (a) couple the pre-match process to a Live
    module, and (b) let a pipeline-written entry be served to the live scanner as
    "fresh" — i.e. exactly the Live contamination the architecture forbids.
    Skipped deliberately.
  * output/cache/* (output_store) is the API-FACING ENGINE-OUTPUT contract
    (`{engine_key,date,generated_at,status,error,row_count,data}`) with a
    fixture-collapse snapshot guard whose semantics belong to engine results.
    A multi-day acquisition window is operational cache, not an engine output.
    Skipped deliberately.
  * data/*.json is the established operational-cache location with the project's
    atomic tmp+os.replace write and stale-fallback-on-failure convention, so the
    window lives there as `data/future_fixture_window.json`.

Window semantics
----------------
  * Dates   : anchor..anchor+horizon-1 (7 days) where anchor is the pipeline's
              TARGET date, so the premise "PREMATCH and WEEKLY share the same
              future dates" holds by construction.
  * Fetch   : ONE canonical include per date (canonical superset) instead of the
              12 different includes the engines each use. Narrower engine
              requests are then served from it by api_cache's alias gate with
              ZERO extra API calls.
  * Rolling : a later fill keeps every still-relevant day and acquires ONLY the
              newly required one; expired days are evicted (never a full refetch).
  * Freshness: a day is refetched only when older than DAY_FRESH_SECONDS; it is
              still SERVED (stale-fallback) up to DAY_STALE_MAX_SECONDS, so a
              429 storm can never empty the window.
  * Atomic  : tmp + os.replace; a FAILED/partial acquisition NEVER overwrites a
              good stored day.
  * Memory  : at most ONE day is held in RAM (`_MEM`), released by
              api_cache.flush_memory(), so the pipeline's OOM protection is kept.
"""

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests

import api_request_identity as rid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
WINDOW_FILE = os.path.join(DATA_DIR, "future_fixture_window.json")

SCHEMA = 1
HORIZON_DAYS = 7
DAY_FRESH_SECONDS = 6 * 3600        # refetch a day at most once per 6 h
DAY_STALE_MAX_SECONDS = 24 * 3600   # ...but keep SERVING it for up to 24 h
MAX_PAGES = 20
CANONICAL_PER_PAGE = 50

# The canonical superset the window acquires. Deliberately EXCLUDES `odds`:
# odds are volatile and each engine's odds freshness requirement is unchanged by
# this work, so an odds request must never be answered from a stored fixture day.
CANONICAL_INCLUDE = ("participants;league;season;state;scores;lineups;"
                     "formations;statistics")

BASE_URL = "https://api.sportmonks.com/v3/football"
FETCH_TIMEOUT = 20

_DATE_RE = re.compile(r"^/fixtures/date/(\d{4}-\d{2}-\d{2})$")

_MEM = {"date": None, "entry": None}     # single-day in-memory copy
_FETCHING = False


def is_fetching():
    """True while this module is itself fetching — stops smart_get recursion."""
    return _FETCHING


def release_memory():
    """Drop the in-memory day copy (called by api_cache.flush_memory)."""
    _MEM["date"] = None
    _MEM["entry"] = None


# ── store I/O (project conventions: atomic write, never clobber with a failure) ──

def _empty_store():
    return {"schema": SCHEMA, "updated_at": None,
            "canonical_include": CANONICAL_INCLUDE, "days": {}}


def _load_store():
    if not os.path.exists(WINDOW_FILE):
        return _empty_store()
    try:
        with open(WINDOW_FILE, "r", encoding="utf-8") as f:
            store = json.load(f)
        if not isinstance(store, dict) or not isinstance(store.get("days"), dict):
            return _empty_store()
        return store
    except Exception:
        return _empty_store()


def _save_store(store):
    """Atomic write; on failure the previous file is left untouched."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = WINDOW_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(store, f)
        os.replace(tmp, WINDOW_FILE)
        return True
    except Exception as e:
        print(f"[WINDOW ERROR] could not persist window: {e}")
        return False


# ── window dates ────────────────────────────────────────────────────────────

def window_dates(anchor_date, horizon=HORIZON_DAYS):
    """['anchor', 'anchor+1', ...] as YYYY-MM-DD (inclusive, `horizon` days)."""
    try:
        anchor = datetime.strptime(str(anchor_date)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        anchor = datetime.now(timezone.utc).date()
    return [(anchor + timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(int(horizon))]


# ── acquisition (always through the hijacked requests.get) ──────────────────

def _api_token():
    return os.getenv("SPORTMONKS_API_KEY")


def _get(path, params):
    """One page through the global API cache. Returns a body dict or None."""
    url = f"{BASE_URL}{path}"
    try:
        resp = requests.get(url, params=params, timeout=FETCH_TIMEOUT)
    except Exception as e:
        print(f"[WINDOW WARN] {path} raised {type(e).__name__}: {e}")
        return None
    if getattr(resp, "status_code", None) != 200:
        print(f"[WINDOW WARN] {path} HTTP {getattr(resp, 'status_code', '?')}")
        return None
    try:
        body = resp.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None


def fetch_day(date, token=None):
    """Acquire ONE future date with the canonical include (all pages).

    Returns an entry dict on complete success, else None. A partial acquisition
    is reported as a failure on purpose: a half-page day must never be stored,
    because consumers would then see a collapsed fixture universe.
    """
    global _FETCHING
    token = token or _api_token()
    if not token:
        print("[WINDOW ERROR] SPORTMONKS_API_KEY missing — cannot fill window.")
        return None

    path = f"/fixtures/date/{date}"
    pages = {}
    total = 0
    _FETCHING = True
    try:
        for page in range(1, MAX_PAGES + 1):
            params = {"api_token": token, "include": CANONICAL_INCLUDE,
                      "per_page": CANONICAL_PER_PAGE, "page": page}
            body = _get(path, params)
            if body is None:
                print(f"[WINDOW WARN] {date} page {page} failed — "
                      f"day NOT stored (existing data preserved).")
                return None
            items = body.get("data") or []
            pages[str(page)] = {"params": params, "body": body}
            total += len(items)
            pagination = body.get("pagination") or {}
            if not items or not pagination.get("has_more"):
                break
    finally:
        _FETCHING = False

    return {
        "fetched_at": time.time(),
        "fetched_on": datetime.now(timezone.utc).isoformat(),
        "canonical_include": CANONICAL_INCLUDE,
        "count": total,
        "pages": pages,
        "page_count": len(pages),
        "acquisition_ok": True,
    }


# ── the 7-day sliding window: fill, roll, evict ─────────────────────────────

def fill_window(anchor_date=None, horizon=HORIZON_DAYS, force=False,
                store_path=None):
    """Keep the window holding exactly anchor..anchor+horizon-1.

    Rolling behaviour (the FIFO the architecture asks for): dates that left the
    horizon are EVICTED, dates already held stay as they are, and ONLY the
    missing/stale date(s) are acquired. A stale-but-good day is preserved when
    its refetch fails. Returns a summary dict for logging/tests.
    """
    global WINDOW_FILE
    if store_path:
        WINDOW_FILE = store_path

    desired = window_dates(anchor_date, horizon)
    store = _load_store()
    days = store.get("days") or {}
    now = time.time()

    evicted = [d for d in list(days) if d not in desired]
    for d in evicted:
        days.pop(d, None)

    fetched, reused, failed, stale_kept = [], [], [], []
    for d in desired:
        entry = days.get(d)
        fresh = (entry and entry.get("acquisition_ok")
                 and (now - float(entry.get("fetched_at") or 0)) < DAY_FRESH_SECONDS)
        if fresh and not force:
            reused.append(d)
            continue
        new_entry = fetch_day(d)
        if new_entry:
            days[d] = new_entry
            fetched.append(d)
        elif entry:
            failed.append(d)
            stale_kept.append(d)          # last-known-good day kept and served
        else:
            failed.append(d)

    store["schema"] = SCHEMA
    store["canonical_include"] = CANONICAL_INCLUDE
    store["updated_at"] = datetime.now(timezone.utc).isoformat()
    store["days"] = days
    _save_store(store)

    summary = {"anchor": desired[0] if desired else None, "dates": desired,
               "fetched": fetched, "reused": reused, "failed": failed,
               "stale_kept": stale_kept, "evicted": evicted,
               "days_in_window": sorted(days.keys())}
    print(f"[WINDOW] anchor={summary['anchor']} dates={len(desired)} "
          f"fetched={len(fetched)} reused={len(reused)} "
          f"stale_kept={len(stale_kept)} evicted={len(evicted)}")
    if fetched:
        print(f"[WINDOW] newly acquired: {', '.join(fetched)}")
    if evicted:
        print(f"[WINDOW] evicted (out of horizon): {', '.join(evicted)}")
    return summary


# ── the shared read path: serve a fixtures/date request with 0 API calls ────

def is_future_date(date_str):
    """True when `date_str` is strictly AFTER the current LOCAL date.

    The window is ONLY for future/upcoming data (it must never become a Live or
    same-day source). This gate is what makes that structural: a request for
    "today" — e.g. the 06:00 second-chance re-run of today's engines — is never
    answered from last night's stored copy, so same-day lineups/scores can never
    be served stale. Local date is used deliberately, because the pipeline's own
    "tomorrow" (systemd `date -d tomorrow`) is local too; no timezone semantics
    are changed anywhere.
    """
    try:
        d = datetime.strptime(str(date_str), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return False
    return d > datetime.now().date()


def _day_entry(date):
    """One day's entry — memory first, then a single-day disk read."""
    if _MEM["date"] == date and _MEM["entry"] is not None:
        return _MEM["entry"]
    store = _load_store()
    entry = (store.get("days") or {}).get(date)
    if entry is None:
        return None
    _MEM["date"] = date                  # keep at most ONE day in RAM
    _MEM["entry"] = entry
    return entry


def lookup_for_request(path, params):
    """Answer a /fixtures/date/{date} request from the window, or None.

    Served only when the date is IN the window, its acquisition succeeded, it is
    not older than DAY_STALE_MAX_SECONDS, a complete page for the requested page
    number exists, and the strict safety gate confirms the stored canonical
    superset really contains everything the caller asked for. Any doubt →
    None → the global cache falls through to a normal (cached) API call.
    """
    m = _DATE_RE.match(str(path))
    if not m:
        return None
    date = m.group(1)
    if not is_future_date(date):
        return None                      # window serves FUTURE dates only
    entry = _day_entry(date)
    if not entry or not entry.get("acquisition_ok"):
        return None
    age = time.time() - float(entry.get("fetched_at") or 0)
    if age > DAY_STALE_MAX_SECONDS:
        return None
    slot = (entry.get("pages") or {}).get(rid.requested_page(params))
    if not slot:
        return None
    ok, _reason = rid.request_can_be_served(
        slot.get("body"), slot.get("params"), path, params, cached_path=path)
    return slot.get("body") if ok else None


def window_status():
    """Operator/test view of the window: per-date count, age and freshness."""
    store = _load_store()
    now = time.time()
    out = {}
    for date, entry in sorted((store.get("days") or {}).items()):
        age = now - float(entry.get("fetched_at") or 0)
        out[date] = {"count": entry.get("count"),
                     "pages": entry.get("page_count"),
                     "age_seconds": int(age),
                     "fresh": age < DAY_FRESH_SECONDS,
                     "servable": age <= DAY_STALE_MAX_SECONDS,
                     "acquisition_ok": bool(entry.get("acquisition_ok"))}
    return {"file": WINDOW_FILE, "schema": store.get("schema"),
            "updated_at": store.get("updated_at"),
            "canonical_include": store.get("canonical_include"),
            "days": out}


if __name__ == "__main__":               # manual inspection only, never a pipeline run
    import sys
    anchor = sys.argv[1] if len(sys.argv) > 1 else None
    print(json.dumps(window_status(), indent=2))
    if anchor:
        fill_window(anchor)