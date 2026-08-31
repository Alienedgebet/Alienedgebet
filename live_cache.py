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
CACHE_FILE = os.path.join(DATA_DIR, "live_inplay_cache.json")
API_KEY = os.getenv("SPORTMONKS_API_KEY")

CACHE_TTL = 120  # 120 seconds (2 minutes) shared cross-engine TTL

# Import standardizer safely
try:
    from backend.settlement_service import extract_match_data
except ImportError:
    try:
        from settlement_service import extract_match_data
    except ImportError:
        def extract_match_data(fx): return fx


def get_live_scores_cached(force_refresh: bool = False) -> list:
    """
    Universal Single Source of Truth for Live In-Play Scores.
    - Reads from shared file cache `data/live_inplay_cache.json`.
    - If cache is under 2 minutes old -> returns saved data instantly (0 API calls).
    - If cache is expired AND user refreshed -> queries SportMonks ONCE, updates file.
    - Used by Settlement, Code 1, Code 2, and Code 6 simultaneously.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    now = time.time()

    # 1. Check if valid disk cache exists
    if not force_refresh and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                payload = json.load(f)
            cached_ts = payload.get("timestamp", 0)
            if (now - cached_ts) < CACHE_TTL and payload.get("data"):
                return payload["data"]
        except Exception:
            pass  # Fall through to fetch if file read fails

    # 2. If no API key configured, return whatever stale data exists
    if not API_KEY:
        print("[CACHE WARNING] SPORTMONKS_API_KEY is missing in .env")
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f).get("data", [])
            except Exception: pass
        return []

    # 3. Cache expired or user manually refreshed -> Fetch SportMonks ONCE
    url = "https://api.sportmonks.com/v3/football/livescores/inplay"
    params = {
        "api_token": API_KEY,
        "include": "participants;scores;statistics;statistics.type;state;periods;events.type"
    }

    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200:
            raw_data = r.json().get("data", [])
            parsed = [extract_match_data(fx) for fx in raw_data]

            # Save to shared file so all other engines read it
            cache_payload = {
                "timestamp": now,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "count": len(parsed),
                "data": parsed
            }
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache_payload, f, indent=2)

            return parsed
        else:
            print(f"[CACHE ERROR] SportMonks returned {r.status_code}")
    except Exception as e:
        print(f"[CACHE EXCEPTION] Failed querying SportMonks: {e}")

    # Fallback to existing disk cache if network fails
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get("data", [])
        except Exception: pass

    return []
