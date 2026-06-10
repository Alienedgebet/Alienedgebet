import os
import sys
import time
import requests
import pandas as pd
import json
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# --- 1. HOSTING & ENVIRONMENT SETUP ---
load_dotenv()

# ==============================================================================
# CONFIGURATION & VS CODE STRICT PATHS
# ==============================================================================
API_TOKEN = os.getenv("SPORTMONKS_API_KEY") or "7ST9IhxYqJG7zaGlC47MICTW5bFKe8HyJGIZfIK7t52TkAOKHe8EsmXGrogM"
BASE_URL  = "https://api.sportmonks.com/v3/football"

# --- STRICT VS CODE ARCHITECTURE (Sub-folder compatible) ---
BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR   = os.path.join(BASE_DIR, "data")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(DATA_DIR,   exist_ok=True)

# GLOBAL CACHES TO PREVENT DUPLICATE API CALLS
TEAM_STATS_CACHE = {}
LEAGUE_CACHE = {}

# ==============================================================================
# TITANIUM HTTP HELPER (ANTI-CRASH & ANTI-RATE LIMIT)
# ==============================================================================
def GET(endpoint, params=None):
    if params is None: params = {}
    params.setdefault('api_token', API_TOKEN)
    url = f"{BASE_URL}{endpoint}"

    max_retries = 5
    backoff = 2.0
    
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, timeout=15)
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 429:
                # Rate limit hit! Pause and wait before trying again.
                time.sleep(backoff * (attempt + 1))
                continue
            else:
                # Other API errors
                time.sleep(1.0)
                continue
        except Exception:
            # Network failure or timeout
            time.sleep(backoff)
            continue
            
    return {"data": []}

# ==============================================================================
# UTILS & EXTRACTION LOGIC
# ==============================================================================
def get_scores_ht_ft(scores_list):
    h_ht, a_ht = 0, 0
    h_ft, a_ft = 0, 0

    for s in (scores_list or []):
        desc = s.get("description", "")
        if "score" in s:
            p = s["score"].get("participant")
            g = int(s["score"].get("goals", 0))
        else:
            p = s.get("participant")
            g = int(s.get("goals", 0))

        if desc == "1ST_HALF":
            if p == "home": h_ht = g
            elif p == "away": a_ht = g

        if desc in ["CURRENT", "2ND_HALF", "FULL_TIME"]:
            if p == "home": h_ft = g
            elif p == "away": a_ft = g

    return (h_ht, a_ht), (h_ft, a_ft)

# ==============================================================================
# SINGLE MEGA-FUNCTION (FIRST HALF CACHE)
# ==============================================================================
def get_team_stats_cached_fh(team_id, check_date_str):
    """
    Fetches the team's last 5 matches ONCE and calculates BOTH the
    Phase 1 (1H Activity) AND Phase 2 (FHVI Detailed) stats simultaneously.
    """
    if team_id in TEAM_STATS_CACHE:
        return TEAM_STATS_CACHE[team_id]

    target_date_obj = datetime.strptime(check_date_str, "%Y-%m-%d")
    end = (target_date_obj - timedelta(days=1)).strftime("%Y-%m-%d")
    start = (target_date_obj - timedelta(days=120)).strftime("%Y-%m-%d")

    params = {
        "include": "scores;participants;events",
        "per_page": 10,
        "filters": "fixtureStates:5",
        "order": "desc"
    }
    resp = GET(f"/fixtures/between/{start}/{end}/{team_id}", params=params)

    # Filter for valid dates and get strictly the last 5
    valid_matches = [m for m in resp.get("data", []) if m.get("starting_at", "").split(" ")[0] < check_date_str][:5]
    total = len(valid_matches)

    stats = {
        "total_matches": total,
        "1h_activity_rate": 0,
        "fh_r": 0, "fh_c_r": 0, "sh_r": 0, "sh_c_r": 0,
        "avg_sh_g": 0, "early_goals": 0
    }

    if total == 0:
        TEAM_STATS_CACHE[team_id] = stats
        return stats

    games_with_1h_activity = 0
    fh_scored, fh_conceded = 0, 0
    sh_scored, sh_conceded = 0, 0
    total_sh_goals = 0
    early_goals = 0

    for m in valid_matches:
        (h_ht, a_ht), (h_ft, a_ft) = get_scores_ht_ft(m.get("scores", []))

        # Phase 1: 1H Activity Check
        if (h_ht + a_ht) > 0:
            games_with_1h_activity += 1

        # Phase 2 Logic Setup
        is_home = True
        for p in m.get("participants", []):
            if str(p.get("id")) == str(team_id):
                if p.get("meta", {}).get("location") == "away": is_home = False

        if is_home:
            t_fh_s, t_fh_c = h_ht, a_ht
            t_sh_s, t_sh_c = (h_ft - h_ht), (a_ft - a_ht)
        else:
            t_fh_s, t_fh_c = a_ht, h_ht
            t_sh_s, t_sh_c = (a_ft - a_ht), (h_ft - h_ht)

        if t_fh_s > 0: fh_scored += 1
        if t_fh_c > 0: fh_conceded += 1
        if t_sh_s > 0: sh_scored += 1
        if t_sh_c > 0: sh_conceded += 1

        total_sh_goals += (t_sh_s + t_sh_c)

        # Check Early Goals (1-30 min)
        for ev in m.get("events", []):
            if ev.get("minute", 99) <= 30 and str(ev.get("participant_id", "")) == str(team_id) and ev.get("type_id") in [14, 52]:
                early_goals += 1
                break

    stats["1h_activity_rate"] = (games_with_1h_activity / total) * 100
    stats["fh_r"] = fh_scored / total
    stats["fh_c_r"] = fh_conceded / total
    stats["sh_r"] = sh_scored / total
    stats["sh_c_r"] = sh_conceded / total
    stats["avg_sh_g"] = total_sh_goals / total
    stats["early_goals"] = early_goals

    TEAM_STATS_CACHE[team_id] = stats
    return stats

# ==============================================================================
# FH VOLATILITY INDEX (FHVI) ENGINE
# ==============================================================================
def apply_fhvi_upgrade(base_results, check_date_str, verbose=False):
    if verbose:
        print("\n==============================================================================")
        print("🚀 APPLYING FH VOLATILITY INDEX (STRICT FILTER MODE)")
        print("==============================================================================")

    upgraded_matches = []

    for fid, data in base_results.items():
        h_id, a_id = data["h_id"], data["a_id"]
        league_id = data["league_id"]

        if league_id not in LEAGUE_CACHE:
            resp = GET(f"/leagues/{league_id}", params={"include": "country"})
            country_name = resp.get("data", {}).get("country", {}).get("name", "Unknown")
            LEAGUE_CACHE[league_id] = country_name
        country_name = LEAGUE_CACHE[league_id]

        h_s = TEAM_STATS_CACHE[h_id]
        a_s = TEAM_STATS_CACHE[a_id]

        if h_s["total_matches"] == 0 or a_s["total_matches"] == 0:
            continue

        # ==========================================
        # HARD FILTERS: ANY FAILURE = INSTANT DELETE
        # ==========================================
        if h_s["fh_r"] < 0.50 or a_s["fh_r"] < 0.50: continue

        comb_fh_r = h_s["fh_r"] + a_s["fh_r"]
        if comb_fh_r < 1.10: continue

        if h_s["fh_c_r"] < 0.35 or a_s["fh_c_r"] < 0.35: continue

        total_m = h_s["total_matches"] + a_s["total_matches"]
        avg_sh_goals = ((h_s["avg_sh_g"] * h_s["total_matches"]) + (a_s["avg_sh_g"] * a_s["total_matches"])) / total_m
        if avg_sh_goals < 0.5: continue

        fh_pressure = (h_s["fh_r"] + a_s["fh_r"] + h_s["fh_c_r"] + a_s["fh_c_r"]) * 100
        if fh_pressure < 200: continue

        # ==========================================
        # MATCH SURVIVED: CALCULATE FHVI
        # ==========================================
        fhvi = 0
        if h_s["fh_r"] > h_s["sh_r"]: fhvi += 2
        if a_s["fh_r"] > a_s["sh_r"]: fhvi += 2
        if h_s["fh_c_r"] > h_s["sh_c_r"]: fhvi += 2
        if a_s["fh_c_r"] > a_s["sh_c_r"]: fhvi += 2
        if comb_fh_r >= 1.30: fhvi += 2
        if 0.8 <= avg_sh_goals <= 1.6: fhvi += 1
        if h_s["early_goals"] > 0 and a_s["early_goals"] > 0: fhvi += 2

        if fhvi >= 10: label = "🔥 Very explosive FH"
        elif fhvi >= 7: label = "⚡ Good FH match"
        elif fhvi >= 4: label = "⚖️ Neutral"
        else: label = "🛑 Avoid"

        data["fhvi_score"] = fhvi
        data["fhvi_label"] = label
        data["fh_pressure"] = int(fh_pressure)
        data["country"] = country_name
        data["comb_fh_r"] = int(comb_fh_r * 100)
        data["avg_sh_goals"] = round(avg_sh_goals, 2)
        data["h_fh_r_disp"], data["a_fh_r_disp"] = int(h_s["fh_r"] * 100), int(a_s["fh_r"] * 100)
        data["h_fh_c_r_disp"], data["a_fh_c_r_disp"] = int(h_s["fh_c_r"] * 100), int(a_s["fh_c_r"] * 100)
        
        # Categorize for validation sorting
        if fhvi >= 10: data["Category"] = "🔥 TIER 1 - EXPLOSIVE FH"
        elif fhvi >= 7: data["Category"] = "⚡ TIER 2 - GOOD FH"
        else: data["Category"] = "⚖️ TIER 3 - NEUTRAL"

        upgraded_matches.append(data)

    upgraded_matches.sort(key=lambda x: x["fhvi_score"], reverse=True)

    if verbose:
        for m in upgraded_matches:
            ht = m.get("ht_score", "0-0")
            ft = m.get("ft_score", "0-0")
            print(f"[{m['country'].upper()}] {m['fixture']} [HT: {ht} | FT: {ft}]")
            print(f"   => FHVI: {m['fhvi_score']}/13 ({m['fhvi_label']}) | Pressure: {m['fh_pressure']}")
            print(f"   => FH Rates: Home {m['h_fh_r_disp']}% / Away {m['a_fh_r_disp']}% (Combined {m['comb_fh_r']}%)")
            print(f"   => FH Conceded: Home {m['h_fh_c_r_disp']}% / Away {m['a_fh_c_r_disp']}%")
            print(f"   => Avg Match SH Goals: {m['avg_sh_goals']:.1f}")
            print("-" * 75)

    return upgraded_matches

# ==============================================================================
# MAIN RUNNER WRAPPER
# ==============================================================================
def run_fhvi_engine(target_date=None, verbose=False):
    """
    Executes the FHVI Streak Miner Engine.
    Fully wrapped for the VS Code Pipeline.
    verbose=False keeps it silent for API/Aggregator calls, BUT ALWAYS SAVES CSV/JSON.
    """
    if not API_TOKEN or API_TOKEN == "YOUR_API_KEY_HERE":
        raise ValueError("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")

    if target_date is None:
        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if verbose:
        print(f"\n--- ⛏️ STREAK MINER (STRICT FHVI MODE - HYPER OPTIMIZED) ---")
        print(f"Target: {target_date}")

    # 1. FETCH TODAY'S FIXTURES (With Titanium Anti-Loop Memory)
    all_fx = []
    seen = set()
    page = 1
    while True:
        params = {"include": "participants;scores", "per_page": 50, "page": page}
        resp = GET(f"/fixtures/date/{target_date}", params=params)
        data = resp.get("data", [])
        if not data: break
        
        added_new = False
        for f in data:
            fid = f.get("id")
            if fid not in seen:
                seen.add(fid)
                all_fx.append(f)
                added_new = True
                
        if not added_new: break
        page += 1

    if verbose:
        print(f"Total Matches to Analyze: {len(all_fx)}\n")
        print("⏳ Processing matches (this will be much faster now)...\n")
        
    results = {}

    for i, fx in enumerate(all_fx):
        parts = fx.get("participants", [])
        if len(parts) < 2: continue

        fid = str(fx["id"])
        league_id = str(fx.get("league_id", ""))
        h_id, h_name = str(parts[0]["id"]), parts[0]["name"]
        a_id, a_name = str(parts[1]["id"]), parts[1]["name"]

        (h_ht, a_ht), (h_ft, a_ft) = get_scores_ht_ft(fx.get("scores", []))

        # SHORT-CIRCUIT LOGIC: Only fetch Away team if Home team passes 100% test!
        h_stats = get_team_stats_cached_fh(h_id, target_date)
        if h_stats["1h_activity_rate"] != 100:
            continue # Instantly skip this match, saving 1 API call

        a_stats = get_team_stats_cached_fh(a_id, target_date)
        if a_stats["1h_activity_rate"] != 100:
            continue # Instantly skip

        # If it reaches here, BOTH teams have 100% 1H Activity!
        results[fid] = {
            "fixture": f"{h_name} vs {a_name}",
            "ht_score": f"{h_ht}-{a_ht}",
            "ft_score": f"{h_ft}-{a_ft}",
            "h_id": h_id,
            "a_id": a_id,
            "league_id": league_id,
        }

    upgraded_data = []
    
    if results:
        upgraded_data = apply_fhvi_upgrade(results, target_date, verbose=verbose)
        
        # ==============================================================
        # GUARANTEED SAVE: The Auditor reads these files!
        # ==============================================================
        json_file = os.path.join(OUTPUT_DIR, f"fhvi_strict_filtered_{target_date}.json")
        with open(json_file, "w", encoding='utf-8') as f:
            json.dump(upgraded_data, f, indent=4, ensure_ascii=False)
            
        csv_file = os.path.join(OUTPUT_DIR, f"fhvi_strict_filtered_{target_date}.csv")
        df = pd.DataFrame(upgraded_data)
        df.to_csv(csv_file, index=False)
            
        if verbose:
            print(f"\n✅ Filtered FHVI results saved to {json_file} and {csv_file}")
            if not upgraded_data:
                print("⚠️ Zero matches survived the strict filters today. No bets recommended.")
    else:
        if verbose:
            print("\nNo matches passed the initial engine. Upgrade bypassed.")

    return upgraded_data

# ==============================================================================
# INDEPENDENT CALL WRAPPERS (FOR VS CODE AGGREGATORS)
# ==============================================================================
def get_fhvi_predictions(target_date=None, verbose=False):
    """Call this from your aggregator to instantly receive the FHVI picks list."""
    return run_fhvi_engine(target_date, verbose)

# --- LOCAL RUN EXECUTION ---
if __name__ == "__main__":
    target = input("\nEnter target date (YYYY-MM-DD) or leave empty for today: ").strip()
    run_fhvi_engine(target if target else None, verbose=True)