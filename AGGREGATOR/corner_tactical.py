import os
import sys
import time
import json
import math
import logging
import requests
from datetime import datetime, timedelta, timezone
from collections import defaultdict, Counter

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
from dotenv import load_dotenv
load_dotenv()

# --- STANDARD LOGGING SETUP ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger("CornerEngineStage3")

# --- 2. DYNAMIC PATHS FOR SERVERS (SUB-FOLDER FIX) ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")
MASTER_DIR = os.path.join(BASE_DIR, "master_aggregator")

# ==============================================================================
# 📦 THE BLACK BOX WRAPPER (CALLABLE BY THE MASTER API/SCHEDULER)
# ==============================================================================
def run_corner_engine_stage3(target_date=None):
    """
    Executes Corner Engine Phase 3 (Tactical Brain & Clustering).
    Math, logic, and ML models are 100% untouched.
    """
    # Ensure directories exist SAFELY (Thread-safe, no import side-effects)
    for directory in [OUTPUT_DIR, DATA_DIR, MASTER_DIR]:
        os.makedirs(directory, exist_ok=True)

    # ---------- CONFIG ----------
    API_KEY = os.getenv("SPORTMONKS_API_KEY")
    if not API_KEY:
        raise ValueError("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")
        
    BASE_URL = "https://api.sportmonks.com/v3/football"
    REQUEST_DELAY = 0.2
    LAST_N = 3
    LOOKBACK_DAYS = 365
    KMEANS_N_CLUSTERS = 4

    # ---------- Key stats for Profiling ----------
    KEY_STATS =[
        "Ball Possession %", "Successful Passes Percentage", "Passes", "Long Passes",
        "Shots Total", "Shots On Target", "Shots Insidebox", "Big Chances Created",
        "Attacks", "Dangerous Attacks", "Key Passes", "Total Crosses",
        "Accurate Crosses", "Tackles", "Duels Won", "Interceptions", "Saves",
        "Successful Dribbles Percentage", "Goals"
    ]

    # ---------- Intelligence Matrix Logic ----------
    def assign_intelligence_grade(h_styles, a_styles):
        """
        Matchup Logic Matrix:
        HIGH: Crossing Attacker vs Defensive (Classic corner mine)
        STRONG: Both Attacking (High tempo/shots)
        LOW: Possession vs Possession (Tactical trap)
        MEDIUM: Everything else
        """
        h_str = " ".join(h_styles)
        a_str = " ".join(a_styles)
        
        if ("Crossing/Counter" in h_str and "Defensive" in a_str):
            return "HIGH", "Wide Attacker vs Low Block: Maximum Corner Potential"
        
        if "Attacking" in h_str and "Attacking" in a_str:
            return "STRONG", "End-to-End Attacking: High Shot Volume Expected"
        
        if "Crossing/Counter" in h_str or "Crossing/Counter" in a_str:
            return "STRONG", "High Crossing Volume Identified"
            
        if "Possession-Oriented" in h_str and "Possession-Oriented" in a_str:
            return "LOW", "Tiki-Taka Trap: Teams likely to walk ball into net"
            
        return "MEDIUM", "Balanced Matchup: Standard Statistical Probability"

    # ---------- API Helper ----------
    def GET(path, params=None):
        if params is None: params = {}
        params.setdefault("api_token", API_KEY)
        url = f"{BASE_URL}{path}"
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                return resp.json()
        except: pass
        return {"data":[]}

    def get_team_history(team_id):
        end_dt = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
        start_dt = (datetime.now(timezone.utc).date() - timedelta(days=LOOKBACK_DAYS)).isoformat()
        params = {
            "include": "statistics.type",
            "filters": "fixtureStates:5",
            "sortBy": "starting_at",
            "order": "desc",
            "per_page": LAST_N
        }
        resp = GET(f"/fixtures/between/{start_dt}/{end_dt}/{team_id}", params=params)
        return resp.get("data",[])

    def normalize_stat_name(raw_name):
        if not raw_name: return None
        ln = raw_name.lower().strip()
        for k in KEY_STATS:
            if ln == k.lower().replace('%', '').strip(): return k
        return None

    def compute_team_averages_for_team(team_id):
        last_matches = get_team_history(team_id)
        if not last_matches: return None
        sums, counts = defaultdict(float), defaultdict(int)
        for fx in last_matches:
            stats = fx.get("statistics") or[]
            for s in stats:
                s_name_raw = s.get("type", {}).get("name")
                s_val = s.get("data", {}).get("value")
                s_name = normalize_stat_name(s_name_raw)
                if s_name and s_val is not None:
                    try:
                        val = float(str(s_val).replace('%', '').strip())
                        sums[s_name] += val
                        counts[s_name] += 1
                    except: pass
        return {stat: (round(sums[stat] / counts[stat], 2) if counts[stat] > 0 else 0.0) for stat in KEY_STATS}

    # ---------- Tactical Rule Thresholds ----------
    def check_defensive_thresholds(avg):
        t = {"Tackles": 14, "Interceptions": 8, "Duels Won": 40}
        passes = sum(1 for k, v in t.items() if avg.get(k, 0) >= v)
        if avg.get("Shots On Target", 0) < 3.5: passes += 1
        if passes >= 3: return["Defensive"], f"Passed {passes}/4 defensive rules"
        return[], ""

    def check_attacking_thresholds(avg):
        t = {"Attacks": 60, "Dangerous Attacks": 40, "Shots On Target": 3.5}
        passes = sum(1 for k, v in t.items() if avg.get(k, 0) >= v)
        if passes >= 2: return ["Attacking"], f"Passed {passes}/3 attacking rules"
        return[], ""

    def check_possession_thresholds(avg):
        if avg.get("Ball Possession %", 0) >= 58 and avg.get("Successful Passes Percentage", 0) >= 80:
            return ["Possession-Oriented"], "High control identified"
        return[], ""

    def check_crossing_thresholds(avg):
        if avg.get("Total Crosses", 0) >= 15 or avg.get("Accurate Crosses", 0) >= 4:
            return ["Crossing/Counter"], "Wing-heavy pattern found"
        return[], ""

    # ---------- Clustering ----------
    def run_clustering(teams_avgs):
        if len(teams_avgs) < 2: return None, None
        features =["Attacks", "Dangerous Attacks", "Shots On Target", "Ball Possession %", "Total Crosses", "Tackles"]
        rows, names = [],[]
        for name, avg in teams_avgs.items():
            rows.append([avg.get(f, 0.0) for f in features])
            names.append(name)
        df = pd.DataFrame(rows, columns=features, index=names)
        scaler = StandardScaler()
        X = scaler.fit_transform(df.values)
        k = min(KMEANS_N_CLUSTERS, len(df))
        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10).fit(X)
        df["cluster"] = kmeans.labels_
        centroids = pd.DataFrame(scaler.inverse_transform(kmeans.cluster_centers_), columns=features)
        return df, centroids

    def describe_cluster_centroid(centroid):
        if centroid.get("Total Crosses", 0) > 15: return ["Crossing/Counter"], "Cluster: Offensive Wing"
        if centroid.get("Ball Possession %", 0) > 55: return["Possession-Oriented"], "Cluster: Control"
        return ["Balanced"], "Cluster: Mixed"

    # ---------- Main Logic Execution ----------
    # DYNAMIC PATH: Automatically reading the file dropped by Code 2
    input_file = os.path.join(OUTPUT_DIR, "backend_2_output.json")
    
    if not os.path.exists(input_file):
        logger.error(f"{input_file} not found. Ensure Code 2 has run successfully first.")
        return[]

    with open(input_file, "r", encoding="utf-8") as f:
        corner_picks = json.load(f)

    logger.info(f"Tactical Brain: Auditing {len(corner_picks)} candidates...")

    fixture_map = {}
    team_data = {}

    # STEP 1: RESOLVE TEAM IDs (THE FIX FOR AGGREGATOR)
    for pick in corner_picks:
        fid = pick['fixture_id']
        fx = GET(f"/fixtures/{fid}", params={"include": "participants"})
        data = fx.get("data")
        if data:
            parts = data.get("participants",[])
            h = next((p for p in parts if p.get('meta', {}).get('location') == 'home'), None)
            a = next((p for p in parts if p.get('meta', {}).get('location') == 'away'), None)
            if h and a:
                fixture_map[fid] = {"hid": h['id'], "aid": a['id'], "hname": h['name'], "aname": a['name']}
                team_data[h['id']] = h['name']
                team_data[a['id']] = a['name']
        time.sleep(REQUEST_DELAY)

    # STEP 2: PROFILE STYLES
    teams_averages, team_styles = {}, {}
    for tid, tname in team_data.items():
        logger.info(f"Profiling {tname}...")
        avg = compute_team_averages_for_team(tid)
        if avg:
            teams_averages[tname] = avg
            styles =[]
            for func in[check_defensive_thresholds, check_attacking_thresholds, check_possession_thresholds, check_crossing_thresholds]:
                s, _ = func(avg)
                if s: styles.extend(s)
            team_styles[tname] = styles if styles else ["Balanced"]

    # STEP 3: ML CLUSTERING
    balanced = {t: avg for t, avg in teams_averages.items() if team_styles[t] == ["Balanced"]}
    if len(balanced) >= 2:
        c_df, centroids = run_clustering(balanced)
        if c_df is not None:
            for tname, row in c_df.iterrows():
                c_idx = int(row['cluster'])
                lbls, _ = describe_cluster_centroid(centroids.loc[c_idx])
                team_styles[tname] = lbls

    # STEP 4: MERGE AND SAVE
    final_output =[]
    for pick in corner_picks:
        fid = pick['fixture_id']
        if fid in fixture_map:
            f_info = fixture_map[fid]
            h_styles = team_styles.get(f_info['hname'], ["Unknown"])
            a_styles = team_styles.get(f_info['aname'], ["Unknown"])
            grade, note = assign_intelligence_grade(h_styles, a_styles)
            
            # UPDATE PICK WITH IDs FOR CODE 4
            pick.update({
                "home_id": f_info['hid'],
                "away_id": f_info['aid'],
                "home_style": h_styles,
                "away_style": a_styles,
                "tactical_intelligence_grade": grade,
                "tactical_note": note
            })
            final_output.append(pick)

    # DYNAMIC PATH: Saving directly into the safe Output Folder for Code 4 to read
    output_file = os.path.join(OUTPUT_DIR, "tactical_brain_output.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)
        
    logger.info(f"[SUCCESS] Tactical Brain complete. Data saved to {output_file} for the final Aggregator.")
    
    return final_output

# Allow local testing if someone presses "Run" on this specific file
if __name__ == "__main__":
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_corner_engine_stage3(today_date)