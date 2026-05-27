import os
import sys
import time
import json
import logging
import requests
import pandas as pd
import numpy as np
import re
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

# ==============================================================================
# 📦 THE BLACK BOX WRAPPER (CALLABLE BY THE MASTER PIPELINE)
# ==============================================================================
def run_supreme_corner_evolution(target_date):
    """
    Executes the Final Corner Supreme Evolution Aggregator.
    Handshakes Stage 3 Tactical Brain, DNA, and Underdog Catalyst.
    Math, logic, and thematic rankings are 100% PRESERVED.
    """
    # Ensure directories exist safely
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    # -------------------------
    # CONFIGURATION (UNTOUCHED)
    # -------------------------
    API_KEY = os.getenv("SPORTMONKS_API_KEY") or "hD4F4FIFwNW5BxKa6Y0fCCLtB0KkiNRxtULDdsrO3VPss1IMV4HJihBkxwI4"
    BASE_URL = "https://api.sportmonks.com/v3/football"

    # DYNAMIC FILE MAPPING (Syncing with your VS Folders)
    FILE_STAGE3 = os.path.join(OUTPUT_DIR, "tactical_brain_output.json")
    FILE_DNA = os.path.join(DATA_DIR, "team_dna_profiles.json")
    FILE_CATALYST = os.path.join(OUTPUT_DIR, f"audited_underdog_backtest_{target_date}.csv") 
    OUTPUT_CSV = os.path.join(OUTPUT_DIR, f"SUPREME_CORNERS_EVOLUTION_{target_date}.csv")

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - [SUPREME] - %(message)s')
    logger = logging.getLogger("SupremeEvolution")

    # ==============================================================================
    # 🧲 TEXT MATCHING & SCORE PARSING (INTERNAL HELPERS)
    # ==============================================================================
    def clean_n(name):
        n = str(name).lower()
        for word in ["u19", "u23", "fc", "sc", "united", "city", "club", "afc", "rc", "as", "deportivo", "atletico"]:
            n = n.replace(word, "")
        return re.sub(r'[^a-z0-9]', '', n).strip()

    def get_match_key(name):
        n = clean_n(name)
        parts = n.split('vs') if 'vs' in n else [n]
        parts = [p.strip() for p in parts]
        parts.sort()
        return "".join(parts)

    def extract_final_score(scores_list):
        """Safely extracts goals for U2.5 simulation."""
        home, away = 0, 0
        found = False
        for entry in (scores_list or []):
            if not isinstance(entry, dict): continue
            s_obj = entry.get("score") or entry
            desc = str(s_obj.get("description", "")).upper()
            if any(w in desc for w in ["PENALTY", "EXTRA", "AGG"]): continue
            
            p = s_obj.get("participant") or entry.get("participant")
            g = s_obj.get("goals") if isinstance(s_obj, dict) else entry.get("goals")
            
            if g is not None:
                try:
                    val = int(g)
                    if p == "home": home = max(home, val); found = True
                    elif p == "away": away = max(away, val); found = True
                except: pass
        if not found: return None, None
        return home, away

    # ==============================================================================
    # 🧮 MATHEMATICAL ENGINES (CORNERS + POISSON U2.5)
    # ==============================================================================
    def calculate_u25_poisson(h_scored, h_conc, a_scored, a_conc, sims=5000):
        """Calculates U2.5% using exact match history."""
        h_xg = max(0.1, (h_scored + a_conc) / 2.0)
        a_xg = max(0.1, (a_scored + h_conc) / 2.0)
        
        h_sim = np.random.poisson(h_xg, sims)
        a_sim = np.random.poisson(a_xg, sims)
        total_goals = h_sim + a_sim
        
        u25_prob = np.mean(total_goals < 3) * 100
        return round(u25_prob, 1)

    def run_negative_binomial_siege(expected_corners, wide_pressure_score, is_chasing_game):
        if is_chasing_game: expected_corners *= 1.15 
        expected_corners += (wide_pressure_score * 0.5)
        if expected_corners < 1.0: expected_corners = 1.0

        variance = expected_corners * 1.6 
        if variance <= expected_corners: variance = expected_corners + 0.1
        
        p = expected_corners / variance
        r = (expected_corners**2) / (variance - expected_corners)
        
        if p <= 0 or p >= 1 or r <= 0: return 0.0, expected_corners

        try:
            simulated_totals = np.random.negative_binomial(n=r, p=p, size=5000)
            m_prob = (np.sum(simulated_totals >= 10) / 5000) * 100
            return round(m_prob, 2), round(expected_corners, 2)
        except:
            return 0.0, expected_corners

    # ==============================================================================
    # 🕵️ FORENSIC AUDIT (API)
    # ==============================================================================
    def GET(path, params=None):
        if params is None: params = {}
        params.setdefault("api_token", API_KEY)
        while True:
            try:
                # Note: When called by Main.py, requests.get is patched by smart_get
                r = requests.get(f"{BASE_URL}{path}", params=params, timeout=15)
                if r.status_code == 200: return r.json()
                elif r.status_code == 429: time.sleep(5)
                else: return {"data": []}
            except: time.sleep(2)

    def extract_stat_entries(fx, team_id):
        stats_raw = fx.get("statistics", [])
        result = {}
        if not stats_raw: return result
        entries = stats_raw.get(str(team_id), []) if isinstance(stats_raw, dict) else [s for s in stats_raw if int(s.get('participant_id', 0)) == int(team_id)]
        for s in entries:
            t_obj = s.get("type", {})
            name = t_obj.get("name") if isinstance(t_obj, dict) else s.get("name")
            val = s.get("data", {}).get("value") if isinstance(s.get("data"), dict) else s.get("value")
            if name and val is not None: 
                try: result[str(name)] = float(val)
                except: pass
        return result

    def assign_inplay_style(stat_map):
        atk = stat_map.get("Attacks", 0.0)
        dang = stat_map.get("Dangerous Attacks", 0.0)
        cross = stat_map.get("Total Crosses", 0.0)
        acc = stat_map.get("Accurate Crosses", 0.0)
        labels = []
        if atk >= 75 and dang >= 45: labels.append("Attacking")
        if cross >= 16 and acc >= 4: labels.append("Crossing/Counter")
        return labels if labels else ["Balanced"]

    def compute_opponent_influence(team_id, history):
        resp = {"by_style": {}, "samples": 0}
        for fx in history[:20]:
            parts = fx.get("participants", [])
            opp_id = next((int(p['id']) for p in parts if int(p['id']) != int(team_id)), None)
            if not opp_id: continue
            opp_style = assign_inplay_style(extract_stat_entries(fx, opp_id))[0]
            team_corners = extract_stat_entries(fx, team_id).get("Corners", 0)
            s = resp["by_style"].setdefault(opp_style, {"sum": 0.0, "count": 0})
            s["sum"] += team_corners
            s["count"] += 1
            resp["samples"] += 1
        for k, v in resp["by_style"].items():
            resp["by_style"][k] = round(v["sum"]/v["count"], 2) if v["count"] > 0 else 0.0
        return resp

    def fetch_team_forensics(team_id, target_date_str):
        end_dt = (datetime.strptime(target_date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        start_dt = (datetime.strptime(target_date_str, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")
        
        resp = GET(f"/fixtures/between/{start_dt}/{end_dt}/{team_id}", 
                   params={"include": "statistics.type;participants;scores", "per_page": 10, "filter": "fixtureStates:5"})
        
        history = resp.get("data", [])
        if not history: 
            return {"wide_score": 0.0, "wide_label": "Standard", "avg_da": 0, "opp_inf": {"by_style": {}}, "style": "Balanced", "recency": 0.0, "avg_scored": 1.0, "avg_conc": 1.0}

        total_crosses, total_da, total_corners = [], [], []
        scored_list, conc_list = [], []

        for fx in history:
            stats = extract_stat_entries(fx, team_id)
            total_crosses.append(stats.get("Total Crosses", 0))
            total_da.append(stats.get("Dangerous Attacks", 0))
            total_corners.append(stats.get("Corners", 0))

            h_g, a_g = extract_final_score(fx.get("scores", []))
            if h_g is not None and a_g is not None:
                is_home = True
                for p in fx.get("participants", []):
                    if str(p.get("id")) == str(team_id):
                        is_home = (p.get("meta", {}).get("location") == "home")
                        break
                if is_home:
                    scored_list.append(h_g); conc_list.append(a_g)
                else:
                    scored_list.append(a_g); conc_list.append(h_g)

        avg_cross = sum(total_crosses) / len(total_crosses) if total_crosses else 0
        avg_da = sum(total_da) / len(total_da) if total_da else 0
        recency = sum(total_corners) / len(total_corners) if total_corners else 0
        
        avg_scored = sum(scored_list) / len(scored_list) if scored_list else 1.0
        avg_conc = sum(conc_list) / len(conc_list) if conc_list else 1.0

        wide_score = 2.0 if avg_cross >= 18.0 else 1.0 if avg_cross >= 14.0 else 0.0
        if avg_da > 0 and (avg_cross / avg_da) > 0.45: wide_score += 1.5

        return {
            "wide_score": wide_score, 
            "wide_label": "WING STORM 🌪️" if wide_score >= 2.0 else "Wide Bias" if wide_score >= 1.0 else "Standard",
            "avg_da": avg_da, 
            "opp_inf": compute_opponent_influence(team_id, history),
            "style": assign_inplay_style({"Dangerous Attacks": avg_da, "Total Crosses": avg_cross})[0],
            "recency": recency,
            "avg_scored": avg_scored,
            "avg_conc": avg_conc
        }

    # ==============================================================================
    # 🧠 SUPREME HANDSHAKE CLASS (WRAPPED)
    # ==============================================================================
    class CornerAggregator:
        def __init__(self, stage3_file, dna_file, catalyst_file, target_date_str):
            self.input_file = stage3_file
            self.dna_file = dna_file
            self.catalyst_file = catalyst_file
            self.target_date = target_date_str

        def load_data(self):
            raw_data, cat_db, dna_db = [], {}, {}
            if os.path.exists(self.input_file):
                with open(self.input_file, "r") as f: 
                    raw_data = json.load(f)
                    if isinstance(raw_data, dict): raw_data = raw_data.get("data", raw_data.get("matches", [raw_data]))
            
            if os.path.exists(self.dna_file):
                try:
                    with open(self.dna_file, "r") as f: dna_db = json.load(f)
                except: pass
                
            if os.path.exists(self.catalyst_file):
                df = pd.read_csv(self.catalyst_file)
                prob_col = next((c for c in df.columns if 'prob' in c.lower()), 'dog_score_prob')
                fix_col = next((c for c in df.columns if 'fixture' in c.lower() or 'match' in c.lower()), 'fixture')
                for _, row in df.iterrows():
                    try: cat_db[get_match_key(str(row[fix_col]))] = float(str(row[prob_col]).replace('%', '').strip())
                    except: continue
            return raw_data, dna_db, cat_db

        def run(self):
            print(f"\n>> [Supreme Aggregator] Initializing Game State Paradox Engine... (Target Date: {self.target_date})")
            raw_data, dna_db, cat_db = self.load_data()
            
            if not raw_data: 
                print(">>[FATAL ERROR] Stage 3 JSON missing.")
                return []

            processed_list = []
            for match in raw_data:
                try:
                    fix_name = str(match.get("fixture_name", "Unknown vs Unknown"))
                    home_name = fix_name.split(" vs ")[0] if " vs " in fix_name else "Home"
                    away_name = fix_name.split(" vs ")[1] if " vs " in fix_name else "Away"
                    home_id, away_id = match.get("home_id", 0), match.get("away_id", 0)
                    
                    base_pred = float(match.get("predicted_corners", 9.0) or 9.0)
                    diff = float(match.get("diff", 0.0) or 0.0)
                    corner_fav = home_name if diff > 0.5 else away_name if diff < -0.5 else "Tight/Unclear"

                    h_intel = fetch_team_forensics(home_id, self.target_date)
                    a_intel = fetch_team_forensics(away_id, self.target_date)

                    u25_prob = calculate_u25_poisson(h_intel['avg_scored'], h_intel['avg_conc'], a_intel['avg_scored'], a_intel['avg_conc'])

                    m_key = get_match_key(fix_name)
                    ud_prob = float(cat_db.get(m_key, 0.0))
                    is_chasing = (ud_prob > 50.0)

                    match_flow = "Standard Flow"
                    if u25_prob >= 55.0 and ud_prob >= 50.0:
                        match_flow = "⏳ TENSION COOKER"
                    elif u25_prob <= 45.0 and ud_prob <= 30.0:
                        match_flow = "🚨 BLOWOUT TRAP"

                    fav_intel = h_intel if float(match.get("prob", 0.5)) > 0.5 else a_intel
                    monte_prob, final_exp = run_negative_binomial_siege(base_pred, fav_intel['wide_score'], is_chasing)

                    dna_label = "Standard"
                    h_dna = dna_db.get(str(home_id))
                    if h_dna and h_dna.get("Market_Power_Scores", {}).get("Corner_Power", 0) > 80:
                        dna_label = "SUPREME_SIEGE"

                    score = 0
                    warn_flag = ""

                    if fav_intel['wide_label'] == "Wide Bias": score += 3
                    elif fav_intel['wide_label'] == "WING STORM 🌪️": 
                        score -= 2
                        warn_flag = "⚠️ PREDICTABILITY TRAP"

                    if dna_label == "SUPREME_SIEGE": score += 3
                    if match_flow == "⏳ TENSION COOKER": score += 4
                    elif ud_prob >= 60.0: score += 2 

                    if match_flow == "🚨 BLOWOUT TRAP":
                        score -= 5
                        warn_flag = "🛑 BLOWOUT AVOID"

                    if monte_prob >= 85.0: score += 2
                    elif monte_prob >= 75.0: score += 1

                    if score >= 8: rank = 1; tier = "💎 HOLY GRAIL"
                    elif score >= 5: rank = 2; tier = "🔥 VIP"
                    elif score >= 2: rank = 3; tier = "📊 PLAYABLE"
                    else: rank = 4; tier = "🛑 TRAP"

                    processed_list.append({
                        "Fixture": fix_name,
                        "Rank": rank,
                        "Master_Score": score,
                        "Tier": tier,
                        "Corner_Fav": corner_fav,
                        "Match_Flow": match_flow,
                        "U2.5%": f"{u25_prob}%",
                        "UD_Prob": f"{ud_prob}%",
                        "NB_Prob": f"{monte_prob}%",
                        "Exp_Total": final_exp,
                        "Wide_Label": fav_intel['wide_label'],
                        "DNA": dna_label,
                        "Warning": warn_flag
                    })
                    print(f" > Audited {fix_name[:25]:<25} | Score: {score:>2} | Flow: {match_flow} | U2.5: {u25_prob}% | UD: {ud_prob}%")
                except: continue

            df = pd.DataFrame(processed_list)
            if df.empty: return []
            
            df['UD_Float'] = df['UD_Prob'].str.rstrip('%').astype(float)
            df['U2.5_Float'] = df['U2.5%'].str.rstrip('%').astype(float)

            # --- THEMED LIST LOGIC (UNTOUCHED PRINT) ---
            special_df = df[(df['Wide_Label'] == 'Wide Bias') & (df['DNA'] == 'SUPREME_SIEGE') & (df['UD_Float'] >= 60.0) & (df['U2.5_Float'] > 44.0)]
            golden_df = df[(df['Wide_Label'] == 'Wide Bias') & (df['DNA'] == 'SUPREME_SIEGE') & (df['Match_Flow'] == '⏳ TENSION COOKER')]
            silver_df = df[(df['Wide_Label'] == 'Wide Bias') & (df['DNA'] == 'SUPREME_SIEGE') & (df['Match_Flow'] != '⏳ TENSION COOKER') & (df['UD_Float'] >= 60.0)]
            storm_df = df[(df['Wide_Label'] == 'WING STORM 🌪️') & (df['DNA'] == 'SUPREME_SIEGE') & (df['UD_Float'] >= 60.0)]

            print("\n" + "⭐"*50)
            print(" 🌟 THE SPECIAL LIST: WIDE BIAS + SUPREME SIEGE 🌟")
            print("⭐"*50)
            if not special_df.empty:
                for i, (_, row) in enumerate(special_df.iterrows(), 1):
                    print(f"{i}. {row['Fixture']} ({row['Match_Flow']})\n   * U2.5: {row['U2.5%']} | UD: {row['UD_Prob']} | DNA: {row['DNA']}\n")

            print("\n" + "★"*100)
            print(" 👑 THE GOLDEN TICKET LIST (Wide Bias + Supreme Siege + Tension Cooker) 👑")
            print("★"*100)
            if not golden_df.empty:
                for i, (_, row) in enumerate(golden_df.iterrows(), 1):
                    print(f"{i}. {row['Fixture']}\n   * Rank: {row['Rank']} ({row['Tier']})\n   * Corner Fav: {row['Corner_Fav']}\n   * Match Flow: {row['Match_Flow']}\n   * U2.5%: {row['U2.5%']}\n   * UD_Prob: {row['UD_Prob']}\n   * DNA / Style: {row['Wide_Label']} + {row['DNA']}\n")

            # Final Table Export
            df_final_display = df.drop(columns=['UD_Float', 'U2.5_Float']).sort_values(by=["Rank", "Master_Score", "NB_Prob"], ascending=[True, False, False])
            df_final_display.to_csv(OUTPUT_CSV, index=False)
            print(f"\n💾[Done] Results saved to: {OUTPUT_CSV}")
            return df_final_display.to_dict(orient="records")

    # EXECUTION
    agg = CornerAggregator(FILE_STAGE3, FILE_DNA, FILE_CATALYST, target_date)
    return agg.run()

if __name__ == "__main__":
    test_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_supreme_corner_evolution(test_date)