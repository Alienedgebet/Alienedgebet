import os
import sys
import json
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from settlement_service import extract_match_data
import output_store as store

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# daily_archiver.py lives in the repo ROOT (not a subpackage), so a single
# dirname() resolves to the backend root. The old double-dirname() resolved to
# the PARENT directory (/var/www) and would have written archive_{date}.json to
# /var/www/output/ while settlement (and every other component) uses
# /var/www/backend/output/. Same class of bug that 242b8f6 fixed in
# live_cache.py — one canonical output hierarchy for the whole application.
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
API_KEY = os.getenv("SPORTMONKS_API_KEY")

def fetch_day_results(date_str):
    """Fetches all played fixtures for a specific date from SportMonks."""
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
    while True:
        params["page"] = page
        try:
            r = requests.get(url, params=params, timeout=20)
            if r.status_code != 200:
                break
            data = r.json().get("data", [])
            if not data:
                break
            for fx in data:
                all_fixtures.append(extract_match_data(fx))
            page += 1
        except Exception as e:
            print(f"[ARCHIVER ERROR] Fetch failed on page {page}: {e}")
            break

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


def archive_date(target_date):
    """
    Builds and saves a static JSON snapshot of target_date's settled match results.
    Future requests for this date read directly from disk with 0 API calls.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    archive_file = os.path.join(OUTPUT_DIR, f"archive_{target_date}.json")

    print(f"📦 Archiving matchday {target_date}...")
    actual_results = fetch_day_results(target_date)

    # ── SNAPSHOT GUARD (Batch A) ─────────────────────────────────────────────
    # settlement_service treats archive_<date>.json as that date's PERMANENT
    # result universe, so overwriting a 63-fixture archive with the handful of
    # fixtures the date endpoint still returned at 22:30 rewrites history for
    # that date forever — exactly what happened to 2026-09-15 (3 fixtures kept,
    # 60 lost). `fetch_day_results()` also returns [] on any non-200 page, so a
    # rate-limited capture would otherwise blank a whole date.
    #
    # The rule is the SAME single definition the cache writer uses —
    # output_store.collapse_decision — so there is one meaning of "suspiciously
    # collapsed", not two competing mechanisms. On REJECT the existing archive
    # is left byte-for-byte unchanged and nothing is deleted.
    decision = store.collapse_decision(_existing_archive_universe(archive_file),
                                       store.fixture_universe(actual_results))
    if decision["decision"] == "REJECT":
        print(f"[SNAPSHOT GUARD] date={target_date} key=archive "
              f"existing_fixtures={decision['existing_fixtures']} "
              f"new_fixtures={decision['new_fixtures']} "
              f"decision=REJECT reason={decision['reason']} "
              f"existing_snapshot_preserved=true file={archive_file}")
        return decision

    archive_payload = {
        "date": target_date,
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "total_fixtures": len(actual_results),
        "fixtures": actual_results
    }

    with open(archive_file, "w", encoding="utf-8") as f:
        json.dump(archive_payload, f, indent=2)

    print(f"✅ SUCCESS: {len(actual_results)} fixtures archived to {archive_file}")
    print(f"⚡ Future requests for {target_date} will now execute at 0 API cost.")

    # SNAPSHOT GUARD (Batch A): hand the decision back to __main__ so a REJECT
    # can set a non-zero exit code (a rejected capture must not look green).
    return decision


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
