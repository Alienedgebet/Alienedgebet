import os
import sys
import time
import json
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
LIVE_CACHE_FILE = os.path.join(DATA_DIR, "live_inplay_cache.json")
PREMATCH_CACHE_FILE = os.path.join(DATA_DIR, "live_prematch_cache.json")

API_KEY = os.getenv("SPORTMONKS_API_KEY")

LIVE_TTL = 120      # 120 seconds (2 minutes) for in-play scores & stats
PREMATCH_TTL = 900  # 900 seconds (15 minutes) for lineups & formations

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
                return payload["data"]
        except Exception:
            pass

    if not API_KEY:
        print("[CACHE WARNING] SPORTMONKS_API_KEY is missing!")
        return []

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

            return raw_data
    except Exception as e:
        print(f"[CACHE EXCEPTION] Live in-play fetch failed: {e}")

    # Fallback to stale file if available
    if os.path.exists(LIVE_CACHE_FILE):
        try:
            with open(LIVE_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get("data", [])
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
