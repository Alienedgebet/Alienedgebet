import time
import requests
import os
from dotenv import load_dotenv
from settlement_service import extract_match_data

load_dotenv()

API_KEY = os.getenv("SPORTMONKS_API_KEY")
CACHE_TTL = 120  # 120 seconds (2 minutes) shared server cache

_LIVE_CACHE = {
    "timestamp": 0,
    "data": []
}

def get_live_scores_cached(force_refresh=False):
    """
    Fetches live in-play and scheduled match data from SportMonks.
    Guarantees maximum 30 API calls per hour regardless of user traffic.
    """
    global _LIVE_CACHE
    now = time.time()

    # If cache is valid (under 2 minutes old), return immediately (0 API calls)
    if not force_refresh and (now - _LIVE_CACHE["timestamp"] < CACHE_TTL) and _LIVE_CACHE["data"]:
        return _LIVE_CACHE["data"]

    if not API_KEY:
        print("[CACHE WARNING] SPORTMONKS_API_KEY is missing in .env")
        return _LIVE_CACHE["data"] or []

    url = "https://api.sportmonks.com/v3/football/livescores/inplay"
    params = {
        "api_token": API_KEY,
        "include": "participants;scores;statistics;statistics.type;state"
    }

    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200:
            raw_data = r.json().get("data", [])
            parsed = [extract_match_data(fx) for fx in raw_data]
            _LIVE_CACHE["data"] = parsed
            _LIVE_CACHE["timestamp"] = now
            return parsed
        else:
            print(f"[CACHE ERROR] SportMonks returned status {r.status_code}")
    except Exception as e:
        print(f"[CACHE EXCEPTION] Failed to query SportMonks: {e}")

    return _LIVE_CACHE["data"]
