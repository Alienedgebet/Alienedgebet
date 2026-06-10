import os
import sys
import time
import math
import json
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from dotenv import load_dotenv

# --- 1. HOSTING & ENVIRONMENT SETUP ---
load_dotenv()

# ==============================================================================
# CONFIGURATION & VS CODE STRICT PATHS
# ==============================================================================
API_TOKEN = os.getenv("SPORTMONKS_API_KEY") or "7ST9IhxYqJG7zaGlC47MICTW5bFKe8HyJGIZfIK7t52TkAOKHe8EsmXGrogM"
BASE_URL  = "https://api.sportmonks.com/v3/football"

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR   = os.path.join(BASE_DIR, "data")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(DATA_DIR,   exist_ok=True)

# Precision Settings
LOOKBACK_GAMES = 10         
FORM_GAMES = 3              
RECENCY_DECAY = 0.90        
MIN_PROJECTED_SOT = 8.5

# GLOBAL CACHES
TEAM_STATS_CACHE = {}

# ==============================================================================
# TITANIUM HTTP HELPER
# ==============================================================================
def GET(endpoint, params=None):
    if params is None: params = {}
    params.setdefault('api_token', API_TOKEN)
    url = f"{BASE_URL}{endpoint}"

    backoff = 2.0
    for attempt in range(5):
        try:
            r = requests.get(url, params=params, timeout=15)
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 429:
                time.sleep(backoff * (attempt + 1))
                continue
            else:
                time.sleep(1.0)
                continue
        except Exception:
            time.sleep(backoff)
            continue
    return {"data": []}

# ==============================================================================
# PROBABILITY MATH (POISSON)
# ==============================================================================
def poisson_probability(lmbda, x):
    if lmbda <= 0: return 0
    return (math.exp(-lmbda) * math.pow(lmbda, x)) / math.factorial(x)

def calculate_over_prob(proj_mean, threshold):
    if proj_mean <= 0: return 0.0
    prob_less_than_equal = 0
    for i in range(math.floor(threshold) + 1):
        prob_less_than_equal += poisson_probability(proj_mean, i)
    return round((1 - prob_less_than_equal) * 100, 1)

# ==============================================================================
# DATA EXTRACTION & NORMALIZATION
# ==============================================================================
def normalize_stat_name(n):
    if not n: return None
    n = n.lower().strip()
    if "shots on target" in n or n == "sot": return "Shots On Target"
    if "dangerous attacks" in n: return "Dangerous Attacks"
    return None

def extract_goals(scores):
    home, away = 0, 0
    for entry in (scores or []):
        if not isinstance(entry, dict): continue
        s_obj = entry.get("score") or entry
        p = s_obj.get("participant") or entry.get("participant")
        g = s_obj.get("goals") if isinstance(s_obj, dict) else entry.get("goals")
        if g is not None:
            val = int(g)
            if p == "home": home = max(home, val)
            elif p == "away": away = max(away, val)
    return home, away

def extract_odds(fx):
    home_val, over_val = None, None
    markets = fx.get("odds", [])
    if isinstance(markets, dict): markets = list(markets.values())
    for market in (markets or []):
        m_name = (market.get("name") or market.get("market_description") or "").lower()
        selections = market.get("odds") or market.get("values") or market.get("selections") or []
        for sel in selections:
            label = str(sel.get("label")).lower()
            try: val = float(sel.get("value"))
            except: continue
            if "winner" in m_name or "1x2" in m_name:
                if label in ["1", "home"] and home_val is None: home_val = val
            if "over/under" in m_name and "2.5" in str(sel.get("total", "")):
                if "over" in label and over_val is None: over_val = val
    return home_val, over_val

# ==============================================================================
# CERBERUS CORE ENGINE
# ==============================================================================
def compute_cerberus_stats(team_id, location, check_date_str):
    # ✅ EXACT FIX: Now strictly tied to the date being predicted to prevent cache collision!
    cache_key = f"{team_id}_{location}_{check_date_str}"
    
    if cache_key in TEAM_STATS_CACHE:
        return TEAM_STATS_CACHE[cache_key]

    target_date = datetime.strptime(check_date_str, "%Y-%m-%d")
    end = (target_date - timedelta(days=1)).strftime("%Y-%m-%d")
    start = (target_date - timedelta(days=365)).strftime("%Y-%m-%d")
    
    params = {
        "include": "participants;statistics.type;scores",
        "filters": f"fixtureStates:5;teamLocation:{location}",
        "sortBy": "starting_at", "order": "desc", "per_page": LOOKBACK_GAMES
    }
    
    resp = GET(f"/fixtures/between/{start}/{end}/{team_id}", params)
    data = [m for m in resp.get("data", []) if m.get("starting_at", "").split(" ")[0] < check_date_str]
    
    if len(data) < 3: 
        TEAM_STATS_CACHE[cache_key] = None
        return None
    
    long_term_sums = defaultdict(float)
    short_term_sums = defaultdict(float) 
    sot_history, conceded_history = [], []
    total_w, curr_w = 0.0, 1.0
    points_total, games_played = 0, 0
    
    for i, fx in enumerate(data[:LOOKBACK_GAMES]):
        hg, ag = extract_goals(fx.get("scores", []))
        my_goals = hg if location == "home" else ag
        opp_goals = ag if location == "home" else hg
        if my_goals > opp_goals: points_total += 3
        elif my_goals == opp_goals: points_total += 1
        games_played += 1

        stats_list = fx.get("statistics", [])
        if isinstance(stats_list, dict): stats_list = list(stats_list.values())
        
        m_sot, m_da, m_conceded_sot = 0.0, 0.0, 0.0
        
        for s in stats_list:
            t_obj = s.get("type", {})
            name = normalize_stat_name(t_obj.get("name") if isinstance(t_obj, dict) else t_obj)
            is_our_team = str(s.get("participant_id")) == str(team_id)
            val = float(s.get("data", {}).get("value", 0) if isinstance(s.get("data"), dict) else s.get("value", 0))
            
            if name == "Shots On Target":
                if is_our_team: m_sot = val
                else: m_conceded_sot = val
            elif name == "Dangerous Attacks" and is_our_team:
                m_da = val

        # Weighted Calcs
        long_term_sums["SOT"] += m_sot * curr_w
        long_term_sums["DA"] += m_da * curr_w
        long_term_sums["SOT_Conceded"] += m_conceded_sot * curr_w
        sot_history.append(m_sot)
        
        if i < FORM_GAMES:
            short_term_sums["SOT"] += m_sot
            
        total_w += curr_w
        curr_w *= RECENCY_DECAY
        
    avg = {
        "SOT": round(long_term_sums["SOT"]/total_w, 2),
        "DA": round(long_term_sums["DA"]/total_w, 2),
        "SOT_Conceded": round(long_term_sums["SOT_Conceded"]/total_w, 2),
        "PPG": round(points_total / games_played, 2) if games_played > 0 else 0.0
    }
    
    form_div = min(len(data), FORM_GAMES)
    form_sot = round(short_term_sums["SOT"]/form_div, 2)
    
    # Consistency Logic
    std_dev = np.std(sot_history)
    mean_val = np.mean(sot_history)
    consistency = 100
    if mean_val > 0:
        cv = std_dev / mean_val
        consistency = max(0, min(100, round(100 * (1 - cv))))
        
    res = {"Long": avg, "Form_SOT": form_sot, "Consistency": consistency}
    TEAM_STATS_CACHE[cache_key] = res
    return res

def calculate_cerberus_prediction(h_data, a_data):
    h_avg, h_form_sot = h_data["Long"], h_data["Form_SOT"]
    a_avg, a_form_sot = a_data["Long"], a_data["Form_SOT"]
    
    h_base = (h_avg["SOT"] + a_avg["SOT_Conceded"]) / 2
    a_base = (a_avg["SOT"] + h_avg["SOT_Conceded"]) / 2
    
    # Efficiency Penalty
    if h_avg["DA"] > 0 and (h_avg["SOT"] / h_avg["DA"]) < 0.06: h_base *= 0.95
    if a_avg["DA"] > 0 and (a_avg["SOT"] / a_avg["DA"]) < 0.06: a_base *= 0.95
        
    # Game Script Adjustments
    tag = "STANDARD"
    if h_avg["PPG"] > 2.0 and a_avg["PPG"] > 2.0:
        h_base *= 0.90; a_base *= 0.90
        tag = "TACTICAL CHESS (Low Event)"
    elif h_avg["SOT_Conceded"] > 5.0 and a_avg["SOT_Conceded"] > 5.0:
        h_base *= 1.10; a_base *= 1.10
        tag = "GLASS CANNONS (Shootout)"
    elif h_avg["PPG"] > 1.8 and a_avg["PPG"] < 0.8:
        h_base *= 1.15; a_base *= 0.80
        tag = "SLAUGHTER (One-Sided)"

    # Momentum
    h_trend = h_form_sot - h_avg["SOT"]
    a_trend = a_form_sot - a_avg["SOT"]
    
    mom = "STABLE"
    if h_trend > 1.5: h_base += 0.5; mom = "HOME HEATING UP 🔥"
    elif h_trend < -1.5: h_base -= 0.8; mom = "HOME COLD ❄️"
    if a_trend > 1.5: a_base += 0.5; mom = "AWAY HEATING UP 🔥"
    elif a_trend < -1.5: a_base -= 0.8; mom = "AWAY COLD ❄️"
        
    total = round(h_base + a_base, 2)
    avg_cons = int((h_data["Consistency"] + a_data["Consistency"]) / 2)
    
    return total, tag, mom, avg_cons

# ==============================================================================
# MAIN RUNNER WRAPPER
# ==============================================================================
def run_sot_engine(target_date=None, verbose=False):
    """
    Executes the Cerberus Shots On Target Engine.
    Fully wrapped for the VS Code Pipeline.
    """
    if not API_TOKEN or API_TOKEN == "YOUR_API_KEY_HERE":
        raise ValueError("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")

    if target_date is None:
        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if verbose:
        print(f"\n--- 🎯 CERBERUS S.O.T. ENGINE ---")
        print(f"Target: {target_date}")

    # Paginator setup
    all_fx, seen, page = [], set(), 1
    
    while True:
        resp = GET(f"/fixtures/date/{target_date}", params={"include": "participants;odds", "per_page": 50, "page": page})
        data = resp.get("data", [])
        if not data: break
        
        added_new = False
        for f in data:
            if f.get("id") not in seen:
                seen.add(f.get("id"))
                all_fx.append(f)
                added_new = True
                
        if not added_new: break
        page += 1

    if verbose: print(f"⏳ Scanning {len(all_fx)} matches utilizing Poisson Distribution...\n")
        
    results = []
    
    for idx, fx in enumerate(all_fx, 1):
        if verbose and (idx % 25 == 0 or idx == len(all_fx)):
            print(f"   > Processing match {idx}/{len(all_fx)}...")

        parts = fx.get("participants", [])
        if len(parts) < 2: continue
        
        home = next((p for p in parts if (p.get("meta") or {}).get("location")=="home"), parts[0])
        away = next((p for p in parts if (p.get("meta") or {}).get("location")=="away"), parts[1])
        
        h_data = compute_cerberus_stats(home["id"], "home", target_date)
        if not h_data: continue
        
        a_data = compute_cerberus_stats(away["id"], "away", target_date)
        if not a_data: continue
        
        total_proj, tag, mom, cons = calculate_cerberus_prediction(h_data, a_data)
        
        if total_proj < MIN_PROJECTED_SOT: continue
            
        h_odd, o25_odd = extract_odds(fx)
        prob_over_8_5 = calculate_over_prob(total_proj, 8.5)

        # Strict Verdicts
        if total_proj >= 10.0 and cons > 70: verdict = "💎 DIAMOND (Stable & High)"
        elif total_proj >= 10.0: verdict = "⚠️ HIGH VOLATILITY (Risky)"
        elif total_proj >= 9.0 and "HEATING UP" in mom: verdict = "🔥 MOMENTUM PLAY"
        else: verdict = "🥈 VALUE PLAY"
        
        results.append({
            "Fixture": f"{home['name']} vs {away['name']}",
            "Verdict": verdict,
            "Proj_SOT": total_proj,
            "Poisson_Over_8.5": f"{prob_over_8_5}%",
            "Consistency": f"{cons}%",
            "Game_Script": tag,
            "Momentum": mom,
            "1x2_Home_Odd": h_odd if h_odd else "N/A"
        })

    if results:
        df = pd.DataFrame(results).sort_values(by=["Proj_SOT", "Consistency"], ascending=[False, False])
        
        # GUARANTEED SAVE
        json_file = os.path.join(OUTPUT_DIR, f"sot_cerberus_predictions_{target_date}.json")
        with open(json_file, "w", encoding='utf-8') as f:
            json.dump(df.to_dict(orient="records"), f, indent=4, ensure_ascii=False)
            
        csv_file = os.path.join(OUTPUT_DIR, f"sot_cerberus_predictions_{target_date}.csv")
        df.to_csv(csv_file, index=False)
            
        if verbose:
            print("\n" + "="*110)
            print(f" 🎯 CERBERUS S.O.T. FINAL REPORT - {target_date}")
            print("="*110)
            print(df.to_string(index=False))
            print("="*110)
            print(f"✅ Saved strictly to {csv_file}")
            
    else:
        if verbose: print("\n❌ No matches found mathematically projecting Over 8.5 SOT today.")

    return results

# ==============================================================================
# INDEPENDENT CALL WRAPPERS (FOR VS CODE AGGREGATORS)
# ==============================================================================
def get_sot_predictions(target_date=None, verbose=False):
    return run_sot_engine(target_date, verbose)

if __name__ == "__main__":
    target = input("\nEnter target date (YYYY-MM-DD) or leave empty for today: ").strip()
    run_sot_engine(target if target else None, verbose=True)