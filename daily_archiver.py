import os
import sys
import json
import time
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from settlement_service import extract_match_data
import output_store as store

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
API_KEY = os.getenv("SPORTMONKS_API_KEY")

# ── SAFE INCREMENTAL ARCHIVE CONFIG ──────────────────────────────────────────
ARCHIVE_COLLAPSE_WARNING_RATIO = 0.25   # ≤25% → warning
ARCHIVE_COLLAPSE_STRONG_RATIO = 0.10    # ≤10% → strong warning
ARCHIVE_MIN_EXPECTED_FIELDS = 6         # minimum meaningful keys per fixture

def _is_suspiciously_small_fetch(existing_ids, new_fixtures):
    """Return (warning_level, reason) when a new fetch looks suspiciously small."""
    if not existing_ids:
        return None, ""
    existing_n = len(existing_ids)
    new_n = len(new_fixtures) if new_fixtures else 0
    if new_n == 0:
        return "strong_warning", f"new fetch returned 0 fixtures but existing archive has {existing_n}"
    ratio = new_n / existing_n
    if ratio <= ARCHIVE_COLLAPSE_STRONG_RATIO:
        return "strong_warning", (f"new fetch returned {new_n} fixtures vs existing {existing_n} "
                                  f"(ratio {ratio:.2f} ≤ {ARCHIVE_COLLAPSE_STRONG_RATIO})")
    if ratio <= ARCHIVE_COLLAPSE_WARNING_RATIO:
        return "warning", (f"new fetch returned {new_n} fixtures vs existing {existing_n} "
                           f"(ratio {ratio:.2f} ≤ {ARCHIVE_COLLAPSE_WARNING_RATIO})")
    return None, ""


def _has_minimum_fields(fixture, min_fields=ARCHIVE_MIN_EXPECTED_FIELDS):
    """Return True when a fixture dict has at least `min_fields` meaningful keys."""
    if not isinstance(fixture, dict):
        return False
    keys = set(k for k, v in fixture.items()
               if v is not None and v != '' and v != 0 and v != [])
    return len(keys) >= min_fields


# ── SHARED 429 COOLDOWN GATE (archiver side) ─────────────────────────────────
# Root cause of the empty nightly archives: page 1 hit HTTP 429 (a burst limit,
# NOT quota exhaustion — probes show X-RateLimit-Remaining ≈ 2998/3000) and the
# old loop had NO retry for the archiver, so "Fetched 0 fixtures" was merged and
# the archive was written as an empty shell. Root causes fixed here:
#   1. page 1 is retried with backoff instead of silently breaking;
#   2. Retry-After / X-RateLimit-Reset are honoured;
#   3. a small cross-process cooldown file lets the archiver, the pipeline and
#      the live stages stop piling onto the API during a storm.
_MAX_429_RETRIES = 4
_API_GATE_LOCK_FILE = os.path.join(BASE_DIR, "data", "api_429_cooldown.lock")


def _429_gate_wait(retry_after=None, limit_reset=None, attempt=1, who="", broadcast=False):
    """Wait out a SportMonks 429 using the best available signal.

    Priority: server Retry-After > X-RateLimit-Reset > shared cooldown file >
    jittered exponential floor (2s, 4s, 8s, 16s… capped at 30s). With
    broadcast=True the caller records the cooldown so OTHER processes wait
    instead of instantly re-triggering the burst limit. A pacing call
    (attempt<=0, no hints) only sleeps when a shared cooldown is actually
    active — otherwise it returns immediately.
    """
    import random as _random

    now = time.time()
    wait = 0.0
    shared_active = False
    if retry_after:
        try:
            wait = max(wait, float(retry_after))
        except (TypeError, ValueError):
            pass
    try:
        os.makedirs(os.path.dirname(_API_GATE_LOCK_FILE), exist_ok=True)
        with open(_API_GATE_LOCK_FILE, "r") as f:
            shared = json.load(f)
        if isinstance(shared, dict) and shared.get("until", 0) > now:
            shared_active = True
            wait = max(wait, shared["until"] - now)
    except Exception:
        shared = None
    if isinstance(limit_reset, str) and limit_reset.isdigit():
        wait = max(wait, min(max(float(limit_reset) - now, 0.0), 60.0))
    if attempt > 0:
        wait = max(wait, min(2.0 * (2 ** (attempt - 1)), 30.0))
        wait += _random.random() * 1.5
    # CLAMP: SportMonks sometimes sends Retry-After values of ~20 minutes.
    # Sleeping that long (or broadcasting it) would freeze the nightly run and
    # every sibling process; bursts clear in seconds, so never wait longer
    # than 45s per attempt regardless of what the server suggests.
    wait = min(wait, 45.0)
    if attempt <= 0 and retry_after is None and not shared_active:
        return
    if broadcast:
        try:
            with open(_API_GATE_LOCK_FILE + ".tmp", "w") as f:
                json.dump({"until": now + wait, "by": who or "unknown"}, f)
            os.replace(_API_GATE_LOCK_FILE + ".tmp", _API_GATE_LOCK_FILE)
        except Exception:
            pass
    print(f"[API GATE] {who or 'caller'}: cooling down {wait:.1f}s (attempt {attempt})")
    time.sleep(wait)


def fetch_day_results(date_str):
    """Fetches all played fixtures for a specific date from SportMonks.

    Implements pagination with safety limits to prevent infinite loops or
    incomplete fetches from destroying existing archives. 429-aware: every
    rate-limited page is retried with server-honouring backoff; a page-1
    failure aborts the run so the merge's existing-empty guard keeps the
    previous archive intact (a truncated fetch must never overwrite it).
    """
    if not API_KEY:
        print("[ERROR] SPORTMONKS_API_KEY is missing.")
        return []

    url = f"https://api.sportmonks.com/v3/football/fixtures/date/{date_str}"
    params = {
        "api_token": API_KEY,
        "include": "participants;scores;statistics;statistics.type;state",
        "per_page": 50
    }
    all_fixtures = []
    page = 1
    max_pages = 20  # Safety limit to prevent infinite loops
    consecutive_empty = 0

    while page <= max_pages:
        params["page"] = page
        if page == 1:
            # Pacing: wait out an ACTIVE shared cooldown before the first hit.
            _429_gate_wait(who="archiver", attempt=0)
        data = None
        attempt = 0
        while True:
            try:
                r = requests.get(url, params=params, timeout=20)
            except Exception as e:
                print(f"[ARCHIVER ERROR] Fetch failed on page {page}: {e}")
                break
            if r.status_code == 200:
                data = r.json().get("data", [])
                break
            if r.status_code == 429:
                attempt += 1
                _429_gate_wait(retry_after=r.headers.get("Retry-After"),
                               limit_reset=r.headers.get("X-RateLimit-Reset"),
                               attempt=attempt, who="archiver", broadcast=True)
                if attempt >= _MAX_429_RETRIES:
                    print(f"[ARCHIVER ERROR] HTTP 429 persisted after "
                          f"{attempt} retries on page {page}")
                    break
                continue
            print(f"[ARCHIVER WARNING] Non-200 response on page {page}: {r.status_code}")
            break
        if data is None:
            if page == 1:
                # A truncated first page must never silently produce an empty
                # archive; abort — the merge only ever ADDS to what exists.
                print("[ARCHIVER ERROR] First-page fetch failed — aborting run "
                      "(existing archive preserved by merge).")
            else:
                print(f"[ARCHIVER WARNING] Page {page} fetch failed — results "
                      f"may be incomplete (partial data kept).")
            break
        if not data:
            consecutive_empty += 1
            if consecutive_empty >= 2:
                # Two consecutive empty pages = end of results
                break
            page += 1
            continue
        consecutive_empty = 0
        for fx in data:
            standardized = extract_match_data(fx)
            if _has_minimum_fields(standardized):
                all_fixtures.append(standardized)
            else:
                print(f"[ARCHIVER WARNING] Skipping suspiciously incomplete fixture on page {page}")
        page += 1

    return all_fixtures


def _existing_archive_universe(archive_file):
    """Unique fixture ids already stored in this date's archive.

    Returns an empty set when the archive does not exist or cannot be read, so
    the guard's ALLOW path (nothing to protect) is taken instead of an
    exception. Fixture identity is the archive's own `fixture_id` field — never
    team names.
    """
    if not os.path.exists(archive_file):
        return set()
    try:
        with open(archive_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return store.fixture_universe(payload.get("fixtures") or [])
    except Exception:
        return set()


def _read_existing_archive(archive_file):
    """Read existing archive and return (fixtures_list, fixture_id_set).

    Returns ([], set()) when file doesn't exist or is unreadable.
    """
    if not os.path.exists(archive_file):
        return [], set()
    try:
        with open(archive_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
        fixtures = payload.get("fixtures") or []
        if not isinstance(fixtures, list):
            return [], set()
        fixture_ids = store.fixture_universe(fixtures)
        return fixtures, fixture_ids
    except Exception:
        return [], set()


def _merge_fixtures(existing_fixtures, new_fixtures):
    """Merge new fixtures into existing fixtures with safety rules.

    RULES:
    1. Existing fixture IDs are ALWAYS preserved (never removed).
    2. New fixtures with unknown IDs are added.
    3. For existing IDs:
       a. If existing is finished → never overwrite with incomplete
       b. If new is finished and existing is NOT finished → update
       c. If both finished and contradictory → preserve existing, log conflict
       d. If both finished and identical → safe idempotent update
    4. New fixtures must have minimum fields to be trusted.
    """
    # Build lookup by fixture_id
    existing_by_id = {}
    for fx in existing_fixtures:
        fid = str(fx.get("fixture_id") or "")
        if fid:
            existing_by_id[fid] = fx

    # Track conflicts for logging
    conflicts = []

    # Start with existing fixtures (preserve all)
    merged_by_id = dict(existing_by_id)

    # Process new fixtures
    for new_fx in new_fixtures:
        if not isinstance(new_fx, dict):
            continue

        fid = str(new_fx.get("fixture_id") or "")
        if not fid:
            continue

        # Skip suspiciously incomplete fixtures
        if not _has_minimum_fields(new_fx):
            print(f"[ARCHIVER WARNING] Skipping incomplete fixture {fid} during merge")
            continue

        existing = merged_by_id.get(fid)

        if existing is None:
            # New fixture — add it
            merged_by_id[fid] = dict(new_fx)
            continue

        # Existing fixture — apply merge rules
        existing_finished = bool(existing.get("is_finished"))
        new_finished = bool(new_fx.get("is_finished"))
        existing_score_avail = existing.get("score_available", True)
        new_score_avail = new_fx.get("score_available", True)

        if existing_finished and existing_score_avail:
            # Rule 3a: Existing is finished with valid score — preserve it
            if not new_finished or not new_score_avail:
                # New is incomplete — keep existing finished result
                pass  # No change
            elif (existing.get("h_ft") == new_fx.get("h_ft") and
                  existing.get("a_ft") == new_fx.get("a_ft")):
                # Rule 3d: Both finished, same score — safe idempotent update
                merged_by_id[fid] = dict(new_fx)
                merged_by_id[fid]["is_finished"] = True
                merged_by_id[fid]["h_ft"] = existing.get("h_ft")
                merged_by_id[fid]["a_ft"] = existing.get("a_ft")
                merged_by_id[fid]["ft_score"] = existing.get("ft_score")
                merged_by_id[fid]["score_available"] = True
            else:
                # Rule 3c: Both finished, different scores — conflict
                conflicts.append({
                    "fixture_id": fid,
                    "existing": f"{existing.get('h_ft')}-{existing.get('a_ft')}",
                    "new": f"{new_fx.get('h_ft')}-{new_fx.get('a_ft')}",
                    "preserved": f"{existing.get('h_ft')}-{existing.get('a_ft')}"
                })
        elif new_finished and new_score_avail:
            # Rule 3b: New is finished, existing is not — update
            merged_by_id[fid] = dict(new_fx)
            merged_by_id[fid]["is_finished"] = True
            merged_by_id[fid]["score_available"] = True

    # Convert back to list, sorted by fixture_id
    merged = list(merged_by_id.values())
    merged.sort(key=lambda fx: str(fx.get("fixture_id") or ""))

    return merged, conflicts


def merge_archives(existing_fixtures, new_fixtures):
    """Public merge function for testing and external use."""
    merged, conflicts = _merge_fixtures(existing_fixtures, new_fixtures)
    return merged


def _write_archive_atomic(archive_file, payload):
    """Write archive atomically using .tmp + os.replace."""
    tmp_file = archive_file + ".tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_file, archive_file)
        return True
    except Exception as e:
        if os.path.exists(tmp_file):
            try:
                os.unlink(tmp_file)
            except Exception:
                pass
        print(f"[ARCHIVER ERROR] Atomic write failed: {e}")
        return False


def archive_date(target_date):
    """
    Builds and saves a SAFE INCREMENTAL snapshot of target_date's settled match results.

    This is the SAFE version that:
    1. Merges new results with existing archive (never destructive replace)
    2. Preserves existing finished results over incomplete new data
    3. Handles contradictory finished results safely
    4. Uses atomic writes to prevent partial reads
    5. Logs warnings for suspiciously small fetches

    Future requests for this date read directly from disk with 0 API calls.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    archive_file = os.path.join(OUTPUT_DIR, f"archive_{target_date}.json")

    print(f"📦 Archiving matchday {target_date}...")

    # Fetch new results from SportMonks
    new_results = fetch_day_results(target_date)
    print(f"  Fetched {len(new_results)} fixtures from SportMonks")

    # Read existing archive (if any)
    existing_fixtures, existing_ids = _read_existing_archive(archive_file)
    print(f"  Existing archive: {len(existing_ids)} fixture IDs")

    # Check for suspiciously small fetch
    warning_level, warning_reason = _is_suspiciously_small_fetch(existing_ids, new_results)
    if warning_level:
        print(f"  [ARCHIVER {warning_level.upper()}] {warning_reason}")
        if warning_level == "strong_warning":
            print(f"  [ARCHIVER INFO] Preserving existing archive — merge will add new fixtures only")

    # Perform safe merge
    merged_fixtures, conflicts = _merge_fixtures(existing_fixtures, new_results)

    # Log conflicts if any
    if conflicts:
        print(f"  [ARCHIVER CONFLICT] {len(conflicts)} contradictory finished results detected:")
        for conflict in conflicts[:5]:  # Show first 5
            print(f"    Fixture {conflict['fixture_id']}: existing={conflict['existing']} vs new={conflict['new']} → preserved={conflict['preserved']}")
        if len(conflicts) > 5:
            print(f"    ... and {len(conflicts) - 5} more conflicts")

    # Build archive payload preserving all fields
    archive_payload = {
        "date": target_date,
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "total_fixtures": len(merged_fixtures),
        "fixtures": merged_fixtures
    }

    # Atomic write
    if _write_archive_atomic(archive_file, archive_payload):
        print(f"✅ SUCCESS: {len(merged_fixtures)} fixtures archived to {archive_file}")
        print(f"   Existing preserved: {len(existing_ids)} | New added: {len(merged_fixtures) - len(existing_ids) if existing_ids else len(merged_fixtures)}")
        print(f"   Conflicts resolved by preserving existing: {len(conflicts)}")
        print(f"⚡ Future requests for {target_date} will now execute at 0 API cost.")

        # ── FT RESULT SNAPSHOT EMISSION ──────────────────────────────────────
        # Settlement's `load_ft_snapshot()` reads data/ft_result_snapshot.json,
        # but until now NO writer existed: the file was always absent and the
        # primary FT layer sat empty (verdicts frozen at PENDING whenever the
        # in-play feed missed the fixture). Every finished fixture of this
        # archive — fresh or preserved — is merged into the snapshot here, so
        # the snapshot self-heals on every archive run.
        try:
            from settlement_service import write_ft_snapshot
            finished = [fx for fx in merged_fixtures
                        if isinstance(fx, dict) and fx.get("is_finished")]
            if finished:
                write_ft_snapshot({target_date: finished})
                print(f"📸 FT snapshot updated: {len(finished)} finished fixtures "
                      f"for {target_date}")
        except Exception as _snap_err:
            # Snapshot emission must never fail the archive itself.
            print(f"[ARCHIVER WARNING] FT snapshot update failed: {_snap_err}")
    else:
        print(f"❌ FAILED: Could not write archive to {archive_file}")
        return {"decision": "ERROR", "reason": "atomic write failed"}

    # Return summary
    return {
        "decision": "MERGED",
        "existing_fixtures": len(existing_ids),
        "new_fixtures_fetched": len(new_results),
        "merged_total": len(merged_fixtures),
        "conflicts": len(conflicts),
    }


if __name__ == "__main__":
    # If date passed as argument (e.g. python daily_archiver.py 2026-08-29)
    if len(sys.argv) > 1:
        target = sys.argv[1].strip()
    else:
        target = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    _decision = archive_date(target)

    # SNAPSHOT GUARD (Batch A): a capture rejected as suspiciously collapsed must
    # not look green in systemd, or the date's archive silently stays stale
    # forever with nobody noticing.
    if _decision and _decision.get("decision") == "REJECT":
        sys.exit(2)
