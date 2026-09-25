import os
import sys
import time
import json
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

# live_cache.py lives in the repo ROOT (not a subpackage), so a single
# dirname() resolves to the backend root. The old double-dirname() resolved
# to the PARENT directory (/var/www) and wrote live_inplay_cache.json to
# /var/www/data/ while the API and every LIVE_SCANNER stage read/write
# /var/www/backend/data/. One canonical path for all components.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LIVE_CACHE_FILE = os.path.join(DATA_DIR, "live_inplay_cache.json")
PREMATCH_CACHE_FILE = os.path.join(DATA_DIR, "live_prematch_cache.json")

API_KEY = os.getenv("SPORTMONKS_API_KEY")

LIVE_TTL = 45       # 45s: scanner-cycle freshness for prompt FT detection
PREMATCH_TTL = 900  # 900 seconds (15 minutes) for lineups & formations



def _persist_finished_from_live(raw_data):
    """Persist every finished fixture visible in a live-feed payload.

    The live feed is cached on disk, so a finished fixture can be observed in
    one response and disappear before the next network fetch. Run this same
    extractor for fresh responses, fresh disk-cache hits, and stale-cache
    fallbacks; the snapshot writer is additive and will not downgrade a
    previously captured score.
    """
    try:
        from settlement_service import extract_match_data, write_ft_snapshot

        finished_by_date = {}
        for fx in raw_data or []:
            if not isinstance(fx, dict):
                continue
            std = extract_match_data(fx)
            if not std.get("is_finished"):
                continue
            fx_date = std.get("match_date") or datetime.now().strftime("%Y-%m-%d")
            finished_by_date.setdefault(fx_date, []).append(std)

        if not finished_by_date:
            return 0
        write_ft_snapshot(finished_by_date)
        return sum(len(rows) for rows in finished_by_date.values())
    except Exception as exc:
        # Snapshot emission must never break the live cache read/write path.
        print(f"[FT SNAPSHOT] update failed (non-fatal): {exc}")
        return 0

# ── GATE 1: LIVE IN-PLAY SHARED CACHE (Used by Settlement, Code 2, and Code 6) ──
def get_live_scores_cached(force_refresh: bool = False) -> list:
    os.makedirs(DATA_DIR, exist_ok=True)
    now = time.time()

    # 1. Read from shared 2-minute disk cache if valid
    if not force_refresh and os.path.exists(LIVE_CACHE_FILE):
        try:
            with open(LIVE_CACHE_FILE, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if (now - payload.get("timestamp", 0)) < LIVE_TTL and payload.get("data"):
                _persist_finished_from_live(payload["data"])
                return payload["data"]
        except Exception:
            pass

    if not API_KEY:
        print("[CACHE WARNING] SPORTMONKS_API_KEY is missing!")
        return []

    # Pacing is a BACKGROUND-only concern now. This function runs inside
    # USER-FACING API requests (the in-play fetch feeds /api/win/apex,
    # /api/corners, settlement, ...). The old behaviour — time.sleep() up to
    # 10s when a shared 429 cooldown gate was active — stalled every request
    # behind the gate (measured live: 10.1s per endpoint → browser
    # "timeout of 10000ms exceeded" on SHVI/FHVI/Underdog) and made date
    # switching lag badly. New policy, in order:
    #   1. fresh cache            → returned above, no API call at all
    #   2. cooldown gate active   → serve the STALE cache immediately
    #                               (any age), or [] if none exists —
    #                               never sleep, never hammer the provider
    #   3. no gate                → normal single fetch
    # Long gate-aware pacing still happens where it belongs: scanner stages,
    # the daily archiver and the pipeline are background jobs.
    _gate_file = os.path.join(DATA_DIR, "api_429_cooldown.lock")
    try:
        with open(_gate_file, "r") as _f:
            _gate = json.load(_f)
        if float(_gate.get("until", 0)) > time.time():
            if os.path.exists(LIVE_CACHE_FILE):
                try:
                    with open(LIVE_CACHE_FILE, "r", encoding="utf-8") as _f2:
                        _stale = json.load(_f2)
                    if _stale.get("data"):
                        print("[API GATE] live_cache: shared cooldown active — "
                              "serving stale cache without refetch")
                        _persist_finished_from_live(_stale["data"])
                        return _stale["data"]
                except Exception:
                    pass
            print("[API GATE] live_cache: shared cooldown active — no cache "
                  "available, returning [] without refetch")
            return []
    except Exception:
        pass

    # 2. Fetch SportMonks ONCE
    url = "https://api.sportmonks.com/v3/football/livescores/inplay"
    params = {
        "api_token": API_KEY,
        "include": "participants;scores;statistics;statistics.type;state;periods;events.type"
    }

    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200:
            raw_data = r.json().get("data", [])
            
            # Save to shared file
            cache_payload = {
                "timestamp": now,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "count": len(raw_data),
                "data": raw_data
            }
            with open(LIVE_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache_payload, f, indent=2)
            print(f"[LIVE CACHE] refreshed: {len(raw_data)} in-play fixture(s)")

            # GATE 2b (FT-SNAPSHOT RECOVERY): a 200 + EMPTY payload is still a
            # successful acquisition — of "nothing is in-play right now" — and
            # an empty list means every fixture that WAS live has left it
            # (finished). If the scanner missed the whistle in a 429 storm,
            # this is the LAST chance to keep the result: merge any finished
            # fixtures still missing from the snapshot in from today's archive
            # (and yesterday's, for past-midnight runs). The snapshot merge is
            # additive and id-preserving; we only pull rows the snapshot lacks
            # and only rows with a usable score, so a good live-captured
            # result can never be downgraded by an archive row.
            if not raw_data:
                try:
                    from settlement_service import (
                        load_finished_archive,
                        load_ft_snapshot,
                        write_ft_snapshot,
                    )
                    _today = datetime.now().strftime("%Y-%m-%d")
                    _dates = {_today, (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")}
                    _have = set()
                    for _d in _dates:
                        _have |= set(load_ft_snapshot(_d).keys())
                    _pull = {}
                    for _d in _dates:
                        _missing = []
                        for _fid, _fx in load_finished_archive(_d).items():
                            if _fid in _have:
                                continue
                            if not _fx.get("score_available", True):
                                continue  # a score-less row adds nothing
                            _missing.append(_fx)
                        if _missing:
                            _pull[_d] = _missing
                    if _pull:
                        write_ft_snapshot(_pull)
                        _n = sum(len(v) for v in _pull.values())
                        print(f"[FT SNAPSHOT] empty in-play feed — recovered "
                              f"{_n} finished result(s) from archive")
                    else:
                        print(f"[FT SNAPSHOT] empty in-play feed — snapshot already "
                              f"holds {len(_have)} result(s)")
                except Exception as _rec_err:
                    print(f"[FT SNAPSHOT] empty-feed recovery failed (non-fatal): {_rec_err}")
                return []

            # FT RESULT SNAPSHOT: persist finished fixtures so settlement can
            # use them after the fixture leaves the inplay feed (before the
            # nightly archive runs). The helper is deliberately shared with
            # disk-cache hits so a short-lived FT response cannot disappear
            # between two network fetches.
            n = _persist_finished_from_live(raw_data)
            if n:
                print(f"[FT SNAPSHOT] {n} finished fixture(s) persisted from in-play feed")

            return raw_data
    except Exception as e:
        print(f"[CACHE EXCEPTION] Live in-play fetch failed: {e}")

    # Fallback to stale file if available
    if os.path.exists(LIVE_CACHE_FILE):
        try:
            with open(LIVE_CACHE_FILE, "r", encoding="utf-8") as f:
                stale_data = json.load(f).get("data", [])
            _persist_finished_from_live(stale_data)
            return stale_data
        except Exception: pass

    return []


# ── GATE 2: PREMATCH LINEUPS SHARED CACHE (Used by Code 1, Code 3, and Code 4) ──
def get_prematch_fixtures_cached(target_date: str, force_refresh: bool = False) -> list:
    os.makedirs(DATA_DIR, exist_ok=True)
    now = time.time()
    cache_path = os.path.join(DATA_DIR, f"prematch_{target_date}.json")

    # 1. Read from shared 15-minute disk cache if valid
    if not force_refresh and os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if (now - payload.get("timestamp", 0)) < PREMATCH_TTL and payload.get("data"):
                return payload["data"]
        except Exception:
            pass

    if not API_KEY:
        return []

    # 2. Fetch SportMonks lineups for target_date
    url = f"https://api.sportmonks.com/v3/football/fixtures/date/{target_date}"
    all_fixtures = []
    page = 1

    while True:
        params = {
            "api_token": API_KEY,
            "include": "participants;lineups.details.type;lineups.player.position;lineups.player.detailedPosition",
            "page": page
        }
        try:
            r = requests.get(url, params=params, timeout=20)
            if r.status_code != 200: break
            data = r.json().get("data", [])
            if not data: break
            all_fixtures.extend(data)
            page += 1
        except Exception:
            break

    # Save to 15-minute shared file
    if all_fixtures:
        try:
            cache_payload = {
                "timestamp": now,
                "date": target_date,
                "count": len(all_fixtures),
                "data": all_fixtures
            }
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache_payload, f, indent=2)
        except Exception: pass

    return all_fixtures


# ── GATE 3: FEED WRITE GUARD (an empty acquisition must never destroy a good feed) ──
# On 2026-09-17 a subscription/quota failure made every Live stage read {"data": []}
# from SportMonks (which answers HTTP 200 with an empty array and a "you don't have
# access ... via your current subscription" message) and the stages then overwrote
# the last good feeds with {} / [] — live_predictions.json, incoming_predictions.json
# and danger_audit.json were all emptied while the provider was answering. A FAILED
# acquisition and a genuinely quiet day are different facts and must produce
# different writes.
#
# The acquiring stage tags its provider response via note_acquisition() (the local
# GET() wrappers do this). An UNTAGGED {"data": []} stays a legitimate zero — no
# matches today — and is still written exactly as before.

def _log(msg):
    """Emit a guard/acquisition message where the OPERATOR will actually see it.

    Under systemd, stdout is a pipe, so plain print() is block-buffered (8KB) and
    these messages would sit invisible for minutes — the same buffering that hid
    earlier Live diagnostics. When the process has a logging configuration (the
    24/7 service does) log through it, because logging flushes per record; when it
    does not (ad-hoc scripts) fall back to print()."""
    import logging
    if logging.getLogger().handlers:
        logging.getLogger("alienedge.live_cache").warning(msg)
    else:
        print(msg)


def note_acquisition(result, status_code=None, reason=None):
    """Tag a provider response dict IN PLACE with why it is empty, then return it.
    The extra keys are ignored by every existing `resp.get("data", [])` caller."""
    if isinstance(result, dict):
        if status_code is not None:
            result["_http_status"] = status_code
        if reason:
            result["_failure"] = str(reason)[:200]
    return result


def acquisition_failed(resp) -> bool:
    """True only when an acquiring GET() wrapper recorded a FAILURE. A plain
    {"data": []} is a legitimate empty result, never a failure."""
    return isinstance(resp, dict) and bool(resp.get("_failure"))


def _read_feed(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def write_feed(path, payload, acquisition_ok=True, label=None):
    """Write one Live feed without ever replacing a good feed with the result of a
    FAILED acquisition.

    * acquisition_ok=False AND the new payload is EMPTY AND the file already holds a
      non-empty feed  ->  the existing feed is preserved untouched and "preserved" is
      returned (the failure is logged, with the feed's age).
    * anything else (successful acquisition, or a legitimate empty day) -> the payload
      is written atomically, exactly as every writer did before.

    Returns "written" or "preserved".
    """
    label = label or os.path.basename(path)
    if not payload and not acquisition_ok:
        existing = _read_feed(path)
        if existing:
            try:
                age = int(time.time() - os.path.getmtime(path))
                age_txt = f"{age // 60}m{age % 60}s" if age >= 60 else f"{age}s"
            except OSError:
                age_txt = "unknown"
            _log(f"[FEED GUARD] {label}: acquisition FAILED — existing feed "
                 f"({len(existing)} entries, age {age_txt}) PRESERVED; the empty "
                 f"result was NOT written.")
            return "preserved"

    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, path)  # atomic — readers never see a half-written feed
    if not payload:
        if acquisition_ok:
            _log(f"[FEED GUARD] {label}: acquisition OK and genuinely empty — written "
                 f"as empty (intended behaviour, unchanged).")
        else:
            _log(f"[FEED GUARD] {label}: acquisition FAILED but there was no existing "
                 f"feed to protect — wrote empty (nothing to preserve).")
    return "written"
