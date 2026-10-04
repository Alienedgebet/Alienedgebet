import os
import sys
import time
import json
import math
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS ---
# This ensures the engine saves to the 'output' folder regardless of environment
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

# ==============================================================================
# 📦 THE BLACK BOX WRAPPER (CALLABLE BY THE MASTER PIPELINE)
# ==============================================================================
def run_sh_master_vortex(target_date):
    """
    Executes the SH Volatility Index (SHVI) Engine.
    Math: 13-Point Segmental Audit.
    Logic: Time Machine protected.
    """
    # Ensure directories exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    # -------------------------
    # CONFIGURATION
    # -------------------------
    API_KEY = os.getenv("SPORTMONKS_API_KEY")
    BASE_URL = "https://api.sportmonks.com/v3/football"
    
    # Forensic Constants
    SAMPLE_SIZE = 5
    LOOKBACK_DAYS = 150
    REQUEST_DELAY = 0.2
    
    if not API_KEY:
        print("CRITICAL: SPORTMONKS_API_KEY is missing!")
        return[]

    # -------------------------
    # UTILITIES (V3 COMPLIANT)
    # -------------------------
    def GET(path, params=None):
        # Note: If running through Main.py, this 'requests.get' is hijacked by the Warden
        if params is None: params = {}
        params.setdefault("api_token", API_KEY)
        try:
            r = requests.get(f"{BASE_URL}{path}", params=params, timeout=30)
            if r.status_code == 200: return r.json()
        except Exception as e:
            print(f"API Error: {e}")
        return {"data":[]}

    def get_scores_ht_ft(scores_list):
        """
        Forensically separates First Half (FH) and Second Half (SH) goals.
        """
        h_ht, a_ht = 0, 0
        h_ft, a_ft = 0, 0
        for s in scores_list:
            desc = s.get("description", "")
            # Handle nested V3 structure
            score_obj = s.get("score") if "score" in s else s
            p = score_obj.get("participant")
            g = int(score_obj.get("goals", 0))

            if desc == "1ST_HALF":
                if p == "home": h_ht = g
                elif p == "away": a_ht = g
            if desc in["CURRENT", "2ND_HALF", "FULL_TIME"]:
                if p == "home": h_ft = g
                elif p == "away": a_ft = g
        return (h_ht, a_ht), (h_ft, a_ft)

    # -------------------------
    # FORENSIC SEGMENTAL ANALYSIS
    # -------------------------
    def analyze_team_volatility(team_id, check_date_str):
        """
        TIME MACHINE logic: Only looks at games BEFORE the target_date.
        Analyzes scoring/conceding frequency per half.
        """
        target_dt = datetime.strptime(check_date_str, "%Y-%m-%d")
        end_date = (target_dt - timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = (target_dt - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

        params = {
            "include": "scores;participants;events",
            "per_page": 20,
            "filters": "fixtureStates:5",
            "order": "desc"
        }
        resp = GET(f"/fixtures/between/{start_date}/{end_date}/{team_id}", params=params)
        data = resp.get("data",[])
        
        # Enforce strict chronological order
        valid_matches = [m for m in data if m.get("starting_at", "").split(" ")[0] < check_date_str][:SAMPLE_SIZE]

        if not valid_matches: return {"total": 0}

        fh_s, fh_c = 0, 0
        sh_s, sh_c = 0, 0
        total_fh_goals = 0
        late_goals = 0

        for m in valid_matches:
            (h_ht, a_ht), (h_ft, a_ft) = get_scores_ht_ft(m.get("scores",[]))
            
            # Find team location in history
            is_home = any(str(p['id']) == str(team_id) and p.get('meta',{}).get('location') == 'home' for p in m.get('participants',[]))

            if is_home:
                t_fh_s, t_fh_c = h_ht, a_ht
                t_sh_s, t_sh_c = (h_ft - h_ht), (a_ft - a_ht)
            else:
                t_fh_s, t_fh_c = a_ht, h_ht
                t_sh_s, t_sh_c = (a_ft - a_ht), (h_ft - h_ht)

            # Record frequency (Did they score/concede > 0?)
            if t_fh_s > 0: fh_s += 1
            if t_fh_c > 0: fh_c += 1
            if t_sh_s > 0: sh_s += 1
            if t_sh_c > 0: sh_c += 1
            
            total_fh_goals += (t_fh_s + t_fh_c)

            # 70 min+ Goal Audit (The Final Strike)
            for ev in m.get("events",[]):
                if ev.get("minute", 0) >= 70 and str(ev.get("participant_id")) == str(team_id):
                    if ev.get("type_id") in[14, 52]: # Goal or Penalty
                        late_goals += 1
                        break 

        count = len(valid_matches)
        return {
            "ht_r": fh_s/count, "ht_c_r": fh_c/count, # First Half Rates
            "sh_r": sh_s/count, "sh_c_r": sh_c/count, # Second Half Rates
            "avg_fh_g": total_fh_goals/count,
            "late_goals": late_goals,
            "total": count
        }

    # -------------------------
    # MAIN ENGINE PIPELINE
    # -------------------------
    print(f"\n[ENGINE] 🌪️ SHVI VORTEX ACTIVATED FOR {target_date}")
    
    # 1. Fetch Full Daily Slate
    all_fixtures =[]
    page = 1
    while True:
        resp = GET(f"/fixtures/date/{target_date}", params={"include": "participants;scores;league", "per_page": 50, "page": page})
        data = resp.get("data",[])
        if not data: break
        all_fixtures.extend(data)
        if len(data) < 50: break
        page += 1

    print(f" > Auditing {len(all_fixtures)} fixtures for 13-point volatility...")

    results =[]
    league_names = {}

    for idx, fx in enumerate(all_fixtures, 1):
        try:
            parts = fx.get("participants",[])
            if len(parts) < 2: continue

            h_id, h_name = str(parts[0]["id"]), parts[0]["name"]
            a_id, a_name = str(parts[1]["id"]), parts[1]["name"]

            # H2H SKIP RULE: Minimum 4 matches to ensure data integrity
            h2h_data = GET(f"/fixtures/head-to-head/{h_id}/{a_id}")
            if len(h2h_data.get("data",[])) < 4:
                continue

            # Step 1: Individual Forensic Analysis
            h_v = analyze_team_volatility(h_id, target_date)
            a_v = analyze_team_volatility(a_id, target_date)

            if h_v.get("total", 0) < 4 or a_v.get("total", 0) < 4:
                continue

            # Step 2: Apply Hard Filters (The Survival Gate)
            if h_v["sh_r"] < 0.50 or a_v["sh_r"] < 0.50: continue # Both must score 2H in 50%+
            comb_sh_r = h_v["sh_r"] + a_v["sh_r"]
            if comb_sh_r < 1.10: continue # Must show collective 2H dominance
            if h_v["sh_c_r"] < 0.35 or a_v["sh_c_r"] < 0.35: continue # Must have leaky 2H defenses

            # Step 3: The 13-Point VORTEX SCORING
            shvi = 0
            # Trends (+8 pts max)
            if h_v["sh_r"] > h_v["ht_r"]: shvi += 2
            if a_v["sh_r"] > a_v["ht_r"]: shvi += 2
            if h_v["sh_c_r"] > h_v["ht_c_r"]: shvi += 2
            if a_v["sh_c_r"] > a_v["ht_c_r"]: shvi += 2
            
            # Volume Indicators (+3 pts max)
            if comb_sh_r >= 1.30: shvi += 2
            avg_fh = (h_v["avg_fh_g"] + a_v["avg_fh_g"]) / 2
            if 0.8 <= avg_fh <= 1.6: shvi += 1 # Sweet spot for 2nd half escalation
            
            # Late Game Threat (+2 pts max)
            if h_v["late_goals"] > 0 and a_v["late_goals"] > 0: shvi += 2

            # Step 4: Finalize Match Object
            l_id = str(fx.get("league_id", ""))
            if l_id not in league_names:
                l_resp = GET(f"/leagues/{l_id}")
                league_names[l_id] = l_resp.get("data", {}).get("name", "Unknown")

            (h_ht, a_ht), (h_ft, a_ft) = get_scores_ht_ft(fx.get("scores",[]))

            results.append({
                "fixture": f"{h_name} vs {a_name}",
                "league": league_names[l_id],
                "shvi_score": shvi,
                "sh_pressure": int((comb_sh_r + h_v['sh_c_r'] + a_v['sh_c_r']) * 100),
                "ht": f"{h_ht}-{a_ht}",
                "ft": f"{h_ft}-{a_ft}",
                "sh_scoring_rate": f"{int(h_v['sh_r']*100)}% / {int(a_v['sh_r']*100)}%",
                "avg_fh_goals": round(avg_fh, 2),
                "late_threat": "🔥 HIGH" if h_v['late_goals'] > 0 and a_v['late_goals'] > 0 else "NORMAL"
            })

        except Exception: continue

    # Step 5: Sorting & Saving
    if results:
        df = pd.DataFrame(results).sort_values(by="shvi_score", ascending=False)
        
        # Save both formats to Output folder
        csv_path = os.path.join(OUTPUT_DIR, f"shvi_vortex_report_{target_date}.csv")
        json_path = os.path.join(OUTPUT_DIR, f"shvi_vortex_report_{target_date}.json")
        
        df.to_csv(csv_path, index=False)
        df.to_json(json_path, orient="records", indent=4)
        
        print("\n" + "="*80)
        print(f"🏆 SHVI VORTEX COMPLETE: {len(df)} VOLATILE MATCHES FOUND")
        print("="*80)
        # Display Top 10
        print(df[["fixture", "shvi_score", "sh_pressure", "ht", "ft"]].head(10).to_string(index=False))
        
        return results
    else:
        print(" > No matches survived the SHVI Vortex filters today.")
        return