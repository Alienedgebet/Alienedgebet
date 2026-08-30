import os
import sys
import json
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from settlement_service import extract_match_data

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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

def archive_date(target_date):
    """
    Builds and saves a static JSON snapshot of target_date's settled match results.
    Future requests for this date read directly from disk with 0 API calls.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    archive_file = os.path.join(OUTPUT_DIR, f"archive_{target_date}.json")

    print(f"📦 Archiving matchday {target_date}...")
    actual_results = fetch_day_results(target_date)

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

if __name__ == "__main__":
    # If date passed as argument (e.g. python daily_archiver.py 2026-08-29)
    if len(sys.argv) > 1:
        target = sys.argv[1].strip()
    else:
        target = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    archive_date(target)
