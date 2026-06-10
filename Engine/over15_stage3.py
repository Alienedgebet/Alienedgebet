import os
import time
import json
import math
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
from dotenv import load_dotenv
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS (SUB-FOLDER FIX) ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

# ==============================================================================
# 📦 THE BLACK BOX WRAPPER (CALLABLE BY THE MASTER API/SCHEDULER)
# ==============================================================================
def run_over15_stage3(target_date):
    """
    Executes Over 1.5 Engine Stage 3 (The Handshake / Premium Killswitch).
    Reads candidate picks directly from ALIENEDGE_O15_PICKS_{target_date}.csv.
    Filters explicitly for Over 1.5 Tier 1 and Tier 2 matches.
    """
    # Ensure directories exist safely
    for directory in [OUTPUT_DIR, DATA_DIR]:
        os.makedirs(directory, exist_ok=True)
        
    API_KEY = os.getenv("SPORTMONKS_API_KEY") or "7ST9IhxYqJG7zaGlC47MICTW5bFKe8HyJGIZfIK7t52TkAOKHe8EsmXGrogM"
    BASE_URL = "https://api.sportmonks.com/v3/football"

    # Head input is the new unified Over 1.5 picks file
    INPUT_FILE = os.path.join(OUTPUT_DIR, f"ALIENEDGE_O15_PICKS_{target_date}.csv")

    # Rule Thresholds
    RULE_MIN_GAMES = 4
    RULE_MIN_ATTACK = 2.0
    RULE_MIN_DEFENSE = 2.0
    RULE_ODDS_MIN = 1.40
    RULE_ODDS_MAX = 2.20
    RULE_LOW_SCORE_TOLERANCE = 0.60
    
    if not API_KEY:
        print("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")
        return []

    # -------------------------
    # UTILS
    # -------------------------
    def GET(path, params=None):
        if params is None: params = {}
        params.setdefault("api_token", API_KEY)
        try:
            r = requests.get(f"{BASE_URL}{path}", params=params, timeout=20)
            r.raise_for_status()
            return r.json()
        except:
            time.sleep(1)
            return {}

    def poisson_prob(lambda_val):
        if lambda_val <= 0: return 0.0
        p0 = math.exp(-lambda_val)
        p1 = p0 * lambda_val
        p2 = p1 * (lambda_val / 2.0)
        return max(0.0, 1.0 - (p0 + p1 + p2))

    def calculate_poisson_score(h_avg_s, a_avg_s, h_avg_c, a_avg_c):
        h_exp = h_avg_s * (1 + (a_avg_c - 1.4)/3.0)
        a_exp = a_avg_s * (1 + (h_avg_c - 1.4)/3.0)
        return poisson_prob(h_exp + a_exp)

    def extract_final_score_string(scores):
        home, away = 0, 0
        found = False
        for entry in (scores or []):
            if not isinstance(entry, dict): continue
            s_obj = entry.get("score") or entry
            p = s_obj.get("participant") or entry.get("participant")
            g = s_obj.get("goals") if isinstance(s_obj, dict) else entry.get("goals")
            
            if g is not None:
                try:
                    val = int(g)
                    if p == "home": home = max(home, val); found = True
                    if p == "away": away = max(away, val); found = True
                except: continue
                
        if not found: return "0-0"
        return f"{home}-{away}"

    def get_total_goals(scores):
        h_str = extract_final_score_string(scores)
        try:
            parts = h_str.split("-")
            return int(parts[0]) + int(parts[1])
        except:
            return 0

    def get_advanced_stats(team_id, date_to):
        start_date = (datetime.strptime(date_to, "%Y-%m-%d") - timedelta(days=180)).strftime("%Y-%m-%d")
        resp = GET(f"/fixtures/between/{start_date}/{date_to}/{team_id}", 
                   params={"include":"scores;participants", "sortBy":"starting_at", "order":"desc", "per_page": 5})
        fixtures = (resp.get("data") or [])[:5]
        
        scored, conceded, count, low_count = 0, 0, 0, 0
        for f in fixtures:
            total = get_total_goals(f.get("scores", []))
            if total <= 2: low_count += 1
            
            score_str = extract_final_score_string(f.get("scores", []))
            try:
                h, a = map(int, score_str.split("-"))
            except:
                h, a = 0, 0
                
            is_home = False
            for p in f.get("participants", []):
                if str(p.get("id")) == str(team_id) and p.get("meta", {}).get("location") == "home":
                    is_home = True
            
            scored += h if is_home else a
            conceded += a if is_home else h
            count += 1
        return scored, conceded, count, low_count

    def check_strict_h2h_debug(h_id, a_id):
        resp = GET(f"/fixtures/head-to-head/{h_id}/{a_id}", 
                   params={"include":"scores", "sortBy":"starting_at", "order":"desc", "per_page": 10})
        
        all_data = resp.get("data") or []
        last_5_games = all_data[:5] 
        
        score_history = []
        over_count = 0
        
        for f in last_5_games:
            score_str = extract_final_score_string(f.get("scores", []))
            total = get_total_goals(f.get("scores", []))
            
            score_history.append(score_str)
            if total >= 3:
                over_count += 1
                
        passed = (over_count >= 3)
        return passed, over_count, score_history

    def get_fixture_details(fixture_id):
        resp = GET(f"/fixtures/{fixture_id}", params={"include":"league;participants;odds"})
        return resp.get("data")

    # -------------------------
    # MAIN EXECUTION LOGIC
    # -------------------------
    print("\n--- OVER 1.5 HANDSHAKE AGGREGATOR ---")
    
    all_picks = {}
    
    if os.path.exists(INPUT_FILE):
        try:
            df = pd.read_csv(INPUT_FILE)
            if not df.empty:
                # Filter strictly for both Over 1.5 Tier 1 and Tier 2 selections
                filtered_df = df[df["o15_tier"].str.contains("TIER 1|TIER 2", na=False, case=False)]
                
                print("==========================================================================")
                print("⚡ OVER 1.5 TIER 1 & TIER 2 CANDIDATES LOADED FROM HEAD:")
                print("==========================================================================")
                for idx, r in enumerate(filtered_df.itertuples(), 1):
                    print(f"  {idx:>2}. {r.fixture:<40} | Tier: {r.o15_tier:<28} | Score: {r.o15_score}")
                print("==========================================================================\n")
                
                id_col = next((c for c in df.columns if "id" in c.lower() and "league" not in c.lower()), None)
                if id_col:
                    for _, row in filtered_df.iterrows():
                        fid = str(row[id_col])
                        if fid not in all_picks: all_picks[fid] = {"strategies":[]}
                        all_picks[fid]["strategies"].append("O15_Precision_Engine")
        except Exception as e: 
            print(f"Error reading {INPUT_FILE}: {e}")
    else:
        print(f"[!] Warning: {INPUT_FILE} not found. Ensure unified engine ran successfully.")

    unique_ids = list(all_picks.keys())
    print(f"Matches to check: {len(unique_ids)}")
    
    if not unique_ids: 
        return []

    results = []
    today_str = target_date 
    
    for fid in unique_ids:
        details = get_fixture_details(fid)
        if not details: continue
        
        parts = details.get("participants", [])
        if len(parts) < 2: continue
        
        h_id, a_id = str(parts[0]["id"]), str(parts[1]["id"])
        match_name = f"{parts[0]['name']} vs {parts[1]['name']}"
        league_name = (details.get("league") or {}).get("name", "Unknown")
        
        # ----------------------------------------------------
        # THE STRICT H2H KILL SWITCH
        # ----------------------------------------------------
        passed, count, history = check_strict_h2h_debug(h_id, a_id)
        
        if not passed:
            print(f"[REJECTED] {match_name} | Reason: Only {count}/5 Overs in H2H History.")
            print("-" * 30)
            continue
        else:
            print(f"[ACCEPTED] {match_name} | Reason: {count}/5 Overs in H2H History.")
            print("-" * 30)

        # Odds Check
        odds_val = None
        for o in details.get("odds", []):
             if "goals over/under" in str(o.get("market_description","")).lower() and \
                "2.5" in str(o.get("total","")) and \
                str(o.get("label","")).lower() == "over":
                 try: odds_val = float(o.get("value"))
                 except: pass
                 break
        
        # Stats
        h_s, h_c, h_cnt, h_low = get_advanced_stats(h_id, today_str)
        a_s, a_c, a_cnt, a_low = get_advanced_stats(a_id, today_str)
        
        h_avg_s = h_s / max(1, h_cnt)
        a_avg_s = a_s / max(1, a_cnt)
        h_avg_c = h_c / max(1, h_cnt)
        a_avg_c = a_c / max(1, a_cnt)
        
        poisson_pct = round(calculate_poisson_score(h_avg_s, a_avg_s, h_avg_c, a_avg_c) * 100, 1)
        
        # Grading
        score = 0
        fails = []
        if "friendly" in league_name.lower(): fails.append("BadLeague")
        else: score += 1
        if h_cnt < 4 or a_cnt < 4: fails.append("LowData")
        else: score += 1
        if (h_avg_s + a_avg_s) < RULE_MIN_ATTACK: fails.append("WeakAttack")
        else: score += 1
        if (h_avg_c + a_avg_c) < RULE_MIN_DEFENSE: fails.append("StrongDef")
        else: score += 1
        if odds_val and (odds_val < RULE_ODDS_MIN or odds_val > RULE_ODDS_MAX): 
            fails.append(f"BadOdds({odds_val})")
        else: score += 1
        if (h_low/max(1, h_cnt)) >= RULE_LOW_SCORE_TOLERANCE: fails.append("BoringHome")
        else: score += 1
            
        results.append({
            "Match": match_name,
            "Odds": odds_val,
            "Poisson%": poisson_pct,
            "Grade": f"{score}/6",
            "GradeNum": score,
            "H2H_Record": str(history),
            "PickedBy": ",".join(all_picks[fid]["strategies"]),
            "Failures": " ".join(fails)
        })

    if results:
        df = pd.DataFrame(results)
        df["PickCount"] = df["PickedBy"].apply(lambda x: len(x.split(',')))
        df = df.sort_values(["Poisson%", "GradeNum"], ascending=[False, False])
        
        # --- SAVE SAFELY TO THE DYNAMIC OUTPUT FOLDER ---
        csv_fn = os.path.join(OUTPUT_DIR, "over15_stage3_final.csv")
        json_fn = os.path.join(OUTPUT_DIR, "over15_stage3_final.json")
        
        df.to_csv(csv_fn, index=False)
        df.to_json(json_fn, orient="records", indent=2)
        
        print(f"\n[O1.5 Stage 3] Saved strict final list to {csv_fn}")
        return df.to_dict(orient="records")
    else:
        print("\n[O1.5 Stage 3] No matches passed strict criteria.")
        return []