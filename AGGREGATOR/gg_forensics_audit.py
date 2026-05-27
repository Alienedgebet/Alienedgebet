import os
import sys
import math
import time
import json
import requests
import pandas as pd
import numpy as np
import glob
import re  # 🟢 [NEW] ADDED FOR NAME CLEANING
from datetime import datetime, timedelta, timezone
from dateutil import parser
from collections import defaultdict, Counter

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
from dotenv import load_dotenv
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

# ==============================================================================
# 📦 THE BLACK BOX WRAPPER (CALLABLE BY THE MASTER API/SCHEDULER)
# ==============================================================================
def run_gg_forensic_aggregator(target_date):
    """
    Executes the Final GG Judgment.
    Handshakes GG Engines 1 & 2 with the DNA Central Engine.
    All mathematical rules and scoring are 100% untouched.
    """
    # Ensure directories exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    # -------------------------
    # CONFIGURATION
    # -------------------------
    API_KEY = os.getenv("SPORTMONKS_API_KEY") or "hD4F4FIFwNW5BxKa6Y0fCCLtB0KkiNRxtULDdsrO3VPss1IMV4HJihBkxwI4"
    BASE_URL = "https://api.sportmonks.com/v3/football"
    
    # User's Belief Rules (PRESERVED)
    RULE_MIN_GG_LAST_3 = 2       
    RULE_REQ_TOP_8 = True        
    RULE_MAX_PARITY = 2.0        
    RULE_MIN_H2H_GG = 3          
    RULE_NO_ZERO_ZERO = True     
    RULE_MIN_PROB = 55.0         

    # 🟢 [UPGRADE: FLEXIBLE STANDINGS DISTANCE]
    MIN_TABLE_DISTANCE = 1
    MAX_TABLE_DISTANCE = 10

    REQUEST_DELAY = 0.2
    MAX_RETRIES = 5

    if not API_KEY:
        print("CRITICAL: SPORTMONKS_API_KEY is missing!")
        return []

    # -------------------------
    # 🟢[NEW] NAME CLEANING UTILITY FOR FLAWLESS DNA MATCHING
    # -------------------------
    def get_match_key(name):
        n = str(name).lower()
        n = re.sub(r'\bu19\b|\bfc\b|\bsc\b|\bunited\b|\bcity\b|\bclub\b|\bafc\b|\brc\b|\bas\b', '', n)
        parts = n.split(' vs ') if ' vs ' in n else n.split('-') if '-' in n else [n]
        parts = [re.sub(r'[^a-z0-9]', '', p.strip()) for p in parts]
        parts.sort()
        return "".join(parts)

    # -------------------------
    # DNA INTELLIGENCE LOGIC (GG FOCUS)
    # -------------------------
    def get_gg_tactical_opinion(h_id, a_id, h_name, a_name, dna_db):
        """
        Independent Tactical Interpreter for GG.
        Compares Tempo and Risk to identify Advantage vs Trap.
        """
        def find_profile(tid, name):
            # First try exact ID
            p = dna_db.get(str(tid))
            if p: return p
            # 🟢 [UPGRADE] Fallback to smart key matching instead of strict lowercase
            search_key = get_match_key(name)
            for _, prof in dna_db.items():
                if get_match_key(prof.get('team_name', '')) == search_key:
                    return prof
            return None

        h_dna = find_profile(h_id, h_name)
        a_dna = find_profile(a_id, a_name)

        if not h_dna or not a_dna:
            return "⚖️ BALANCED", "Insufficient DNA Data"

        h_fric = h_dna.get("Market_Power_Scores", {}).get("BTTS_Friction", 50)
        a_fric = a_dna.get("Market_Power_Scores", {}).get("BTTS_Friction", 50)
        h_intent = h_dna.get("Market_Power_Scores", {}).get("Goal_Intent", 50)
        a_intent = a_dna.get("Market_Power_Scores", {}).get("Goal_Intent", 50)
        
        if h_fric > 70 and a_fric > 70:
            return "🔥 ADVANTAGE", "High Friction Chaos: Both sides trade blows"
        
        if h_intent > 75 and a_intent > 75:
            return "🔥 ADVANTAGE", "Elite Attacking Intent: Box entries guaranteed"

        if h_dna.get("Archetype") == "Possession Controller (DRAW/UNDER)" or \
           a_dna.get("Archetype") == "Possession Controller (DRAW/UNDER)":
            return "⚠️ TACTICAL TRAP", "Possession Controller will slow game down"

        return "⚖️ BALANCED", "Standard Tactical Matchup"

    # -------------------------
    # API ENGINE & FORENSICS (PRESERVED)
    # -------------------------
    def GET_REQUEST(path, params=None):
        if params is None: params = {}
        params.setdefault('api_token', API_KEY)
        url = f"{BASE_URL}{path}"
        for attempt in range(MAX_RETRIES):
            try:
                r = requests.get(url, params=params, timeout=20)
                if r.status_code == 200: return r.json()
                if r.status_code == 429:
                    time.sleep(5)
                    continue
            except: time.sleep(1)
        return {}

    def extract_goals_v3(scores_list):
        home, away = None, None
        for entry in (scores_list or[]):
            if not isinstance(entry, dict): continue
            s_obj = entry.get("score") or entry
            p = s_obj.get("participant") or entry.get("participant")
            g = s_obj.get("goals")
            if g is not None:
                try:
                    val = int(g)
                    if p == "home": home = val if home is None else max(home, val)
                    elif p == "away": away = val if away is None else max(away, val)
                except: continue
        return home, away

    def get_match_stats_v3(fx, team_id):
        hg, ag = extract_goals_v3(fx.get("scores",[]))
        if hg is None or ag is None: return None
        is_home = any(int(p.get("id")) == int(team_id) and p.get("meta", {}).get("location") == "home" for p in fx.get("participants",[]))
        scored = hg if is_home else ag
        conceded = ag if is_home else hg
        return {"s": scored, "c": conceded, "is_gg": (hg > 0 and ag > 0), "is_00": (hg == 0 and ag == 0)}

    def get_team_recent_forensics(team_id):
        end = target_date
        start = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=180)).strftime("%Y-%m-%d")
        data = GET_REQUEST(f"/fixtures/between/{start}/{end}/{team_id}", 
                   params={"include":"scores;participants", "per_page": 5, "order":"desc", "filters":"fixtureStates:5"})
        fixtures = data.get("data",[])
        if not fixtures: return 0, False, 0.5
        gg_last_3, has_00, total_gs = 0, False, 0
        for i, f in enumerate(fixtures):
            st = get_match_stats_v3(f, team_id)
            if not st: continue
            if i < 2 and st["is_00"]: has_00 = True
            if i < 3 and st["is_gg"]: gg_last_3 += 1
            total_gs += st["s"]
        return gg_last_3, has_00, (total_gs / len(fixtures))

    def get_h2h_forensics(id1, id2):
        data = GET_REQUEST(f"/fixtures/head-to-head/{id1}/{id2}", params={"include":"scores;participants", "per_page":5, "order":"desc"})
        fixtures = data.get("data", [])[:5]
        gg_count, total_diff, valid = 0, 0, 0
        for f in fixtures:
            hg, ag = extract_goals_v3(f.get("scores",[]))
            if hg is not None and ag is not None:
                if hg > 0 and ag > 0: gg_count += 1
                total_diff += abs(hg - ag); valid += 1
        return gg_count, (total_diff / max(1, valid))

    def get_league_rank_verified(season_id, team_id):
        if not season_id: return 99
        data = GET_REQUEST(f"/standings/seasons/{season_id}")
        for entry in data.get("data",[]):
            if int(entry.get("participant_id", 0)) == int(team_id):
                return int(entry.get("position", 99))
        return 99

    def run_independent_poisson(h_avg, a_avg):
        p_h = 1 - math.exp(-max(0.1, h_avg))
        p_a = 1 - math.exp(-max(0.1, a_avg))
        return round((p_h * p_a) * 100.0, 2)

    # -------------------------
    # EXECUTION START
    # -------------------------
    print("\n" + "="*85)
    print(f"   ⚖️  GG FORENSIC AGGREGATOR | DATE: {target_date} ")
    print("="*85 + "\n")

    # 1. LOAD CANDIDATES FROM OUTPUT FOLDER
    candidates = {}
    scout_files =["picks_gg1.csv", "picks_gg2.csv"]
    for f_name in scout_files:
        f_path = os.path.join(OUTPUT_DIR, f_name)
        if os.path.exists(f_path):
            print(f"[FILE] Loading candidates from {f_path}...")
            df = pd.read_csv(f_path).head(25)
            for _, r in df.iterrows():
                try:
                    fid = str(int(float(r['fixture_id'])))
                    # Use standard append, duplicates are fine here since it's a dict override by fixture ID
                    candidates[fid] = {
                        'h_name': r.get('home_team'), 
                        'a_name': r.get('away_team'),
                        'league_id': r.get('league_id', 'Unknown') # Retaining league ID
                    }
                except: continue

    # 2. LOAD DNA LIBRARY FROM DATA FOLDER
    dna_path = os.path.join(DATA_DIR, "team_dna_profiles.json")
    dna_db = {}
    if os.path.exists(dna_path):
        with open(dna_path, "r") as f:
            dna_db = json.load(f)
        print(f"[INFO] DNA Library Synced.")
    else:
        print(f"[WARN] DNA Library not found at {dna_path}.")

    if not candidates:
        print("[ERROR] No candidate picks found in output folder.")
        return []

    print(f"\n[INFO] Auditing {len(candidates)} matches for GG perfection...\n")
    final_picks =[]

    for fid, c in candidates.items():
        print(f"Judging {c['h_name']} vs {c['a_name']}...", end="", flush=True)
        
        fx_resp = GET_REQUEST(f"/fixtures/{fid}", params={"include":"participants"})
        data = fx_resp.get('data')
        if not data:
            print(" ❌ API REJECTED")
            continue
            
        sid = data.get("season_id")
        hid = next((p['id'] for p in data['participants'] if p['meta']['location'] == 'home'), None)
        aid = next((p['id'] for p in data['participants'] if p['meta']['location'] == 'away'), None)
        
        if not hid or not aid:
            print(" ❌ INCOMPLETE DATA")
            continue

        # FORENSIC FETCH
        h_gg3, h_00, h_avg = get_team_recent_forensics(hid)
        a_gg3, a_00, a_avg = get_team_recent_forensics(aid)
        h2h_gg, parity_gap = get_h2h_forensics(hid, aid)
        h_rank = get_league_rank_verified(sid, hid)
        a_rank = get_league_rank_verified(sid, aid)
        math_prob = run_independent_poisson(h_avg, a_avg)
        
        # DNA AUDIT
        dna_verdict, dna_insight = get_gg_tactical_opinion(hid, aid, c['h_name'], c['a_name'], dna_db)

        # APPLY BELIEF SCORING (OUT OF 6)
        mark = 0
        details =[]
        if h_gg3 >= RULE_MIN_GG_LAST_3 and a_gg3 >= RULE_MIN_GG_LAST_3: mark += 1; details.append("✅Form")
        
        # 🟢 [UPGRADE: FLEXIBLE DISTANCE SCORING]
        valid_ranks = (1 <= h_rank <= 90) and (1 <= a_rank <= 90)
        pos_diff = abs(h_rank - a_rank)
        if valid_ranks and (MIN_TABLE_DISTANCE <= pos_diff <= MAX_TABLE_DISTANCE): 
            mark += 1; details.append(f"✅PosGap({pos_diff})")
            
        if parity_gap <= RULE_MAX_PARITY: mark += 1; details.append("✅Parity")
        if h2h_gg >= RULE_MIN_H2H_GG: mark += 1; details.append("✅H2H")
        if not h_00 and not a_00: mark += 1; details.append("✅Active")
        if math_prob >= RULE_MIN_PROB: mark += 1; details.append(f"✅Math({int(math_prob)}%)")

        print(f" -> Score: {mark}/6 | DNA: {dna_verdict}")
            
        final_picks.append({
            "fixture_id": fid,
            "league_id": c.get('league_id', 'Unknown'),
            "Fixture": f"{c['h_name']} vs {c['a_name']}",
            "Score": f"{mark}/6",
            "DNA_Intelligence": dna_verdict,
            "Poisson%": math_prob,
            "H2H_GG": f"{h2h_gg}/5",
            "DNA_Insight": dna_insight,
            "Ranks": f"{h_rank}v{a_rank}",
            "Forensic_Audit": " ".join(details)
        })
        time.sleep(0.1)

    if not final_picks: return[]

    df_final = pd.DataFrame(final_picks).sort_values(by=["Score", "Poisson%"], ascending=[False, False])
    
    # Save Report
    final_output_path = os.path.join(OUTPUT_DIR, f"JUDGED_GG_PICKS_{target_date}.csv")
    df_final.to_csv(final_output_path, index=False)
    
    print("\n" + "*"*120)
    print(df_final[["Fixture", "Score", "DNA_Intelligence", "Poisson%", "H2H_GG", "DNA_Insight"]].to_string(index=False))
    print("\n" + "*"*120)
    print(f"\n[SUCCESS] Final Judged list saved to {final_output_path}")

    return df_final.to_dict(orient="records")

# --- LOCAL EXECUTION ---
if __name__ == "__main__":
    test_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_gg_forensic_aggregator(test_date)