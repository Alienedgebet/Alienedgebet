import os
import json
import re
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from dotenv import load_dotenv
from collections import defaultdict

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS (SUB-FOLDER FIX) ---
# TWO dirnames keeps us perfectly inside the Alienedgebet folder
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")
MASTER_DIR = os.path.join(BASE_DIR, "master_aggregator")

# Pandas display settings for clean console output
pd.set_option('display.max_rows', None)
pd.set_option('display.width', 2000)
pd.set_option('display.max_columns', None)

class ApexO25Aggregator:
    def __init__(self):
        self.api_key = os.getenv("SPORTMONKS_API_KEY") or "hD4F4FIFwNW5BxKa6Y0fCCLtB0KkiNRxtULDdsrO3VPss1IMV4HJihBkxwI4"
        self.base_url = "https://api.sportmonks.com/v3/football"
        os.makedirs(MASTER_DIR, exist_ok=True)
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        os.makedirs(DATA_DIR, exist_ok=True)

    def GET(self, path, params=None):
        if params is None: params = {}
        params.setdefault('api_token', self.api_key)
        try:
            r = requests.get(f"{self.base_url}{path}", params=params, timeout=20)
            if r.status_code == 200: return r.json()
        except: pass
        return {}

    def clean_n(self, name):
        """Cleaning for matching CSV names across all engines."""
        n = str(name).lower()
        for word in["u19", "fc", "sc", "united", "city", "club", "afc", "rc", "as", "deportivo", "atletico"]:
            n = n.replace(word, "")
        return re.sub(r'[^a-z0-9]', '', n).strip()

    def get_match_key(self, name):
        """Alphabetical sorting ensures 'A vs B' matches 'B vs A'."""
        n = str(name).lower()
        n = re.sub(r'\bu19\b|\bfc\b', '', n)
        if ' vs ' in n: teams = n.split(' vs ')
        elif '-' in n: teams = n.split('-')
        else: teams = [n]
        teams =[re.sub(r'[^a-z0-9]', '', t.strip()) for t in teams]
        teams.sort()
        return "".join(teams)

    # =========================================================
    # 🎲 QUANT-LEVEL O2.5 MONTE CARLO INTELLIGENCE MATRIX
    # =========================================================
    def run_monte_carlo_o25_matrix(self, grade_str, gap, psych_score, is_veto, has_elite_dna, is_vip):
        """
        Simulates 5,000 matches for Over 2.5 logic.
        Monte = f(base_grade, gap, psych_score, elite_dna, is_veto, is_vip)
        """
        grade_map = {"6/6": 3.4, "5/6": 3.1, "4/6": 2.8}
        
        # Safe extraction of the base grade
        base_lambda = 2.4
        for key in grade_map:
            if key in str(grade_str):
                base_lambda = grade_map[key]
                break

        mult = 1.0
        synergy_boost = 0.0

        # De-correlated Synergy Boost
        if has_elite_dna or is_vip: 
            synergy_boost += 0.12
        if gap != "N/A" and isinstance(gap, (int, float)):
            synergy_boost += min(0.08, abs(float(gap)) / 200.0)
        if psych_score != "N/A" and isinstance(psych_score, (int, float)):
            synergy_boost += (float(psych_score) / 300.0) # e.g. +30 = +0.10
            
        # Apply combined boost (Capped mathematically at +30% for Over 2.5)
        mult *= (1.0 + min(0.30, synergy_boost))

        # The Veto Guillotine (Mathematically suppresses goal expectancy for Defensive traps)
        if is_veto:
            mult *= 0.65 

        # Hard Normalization Boundaries (0.60 to 1.35)
        mult = max(0.60, min(1.35, mult))
        
        final_lambda = base_lambda * mult

        # Run 5,000 Parallel Universes
        simulated_goals = np.random.poisson(final_lambda, 5000)
        
        # O2.5 Condition = Match ends with 3 or more goals
        o25_hits = np.sum(simulated_goals > 2)
        # U2.5 Risk = Match ends with 0, 1, or 2 goals
        u25_hits = np.sum(simulated_goals <= 2)
        
        m_prob = round((o25_hits / 5000) * 100, 2)
        u25_risk = round((u25_hits / 5000) * 100, 2)
        
        return m_prob, u25_risk

    def run_process(self, target_date=None):
        if not target_date:
            target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        print("\n" + "="*145)
        print(f" 🚀 ALIENEDGE APEX OVER 2.5 AGGREGATOR (SUPER-MATRIX V9) - {target_date} ")
        print("="*145)

        # 🛠️ SURGICAL FIX: Now reads Stage 3 exclusively to protect the Premium list
        FILE_ENGINE_CSV = os.path.join(OUTPUT_DIR, "over25_stage3_final.csv")
        FILE_DNA_JSON = os.path.join(DATA_DIR, "team_dna_profiles.json")
        FILE_VIP_JSON = os.path.join(OUTPUT_DIR, "gold_over_25_feed.json")
        FILE_PSYCH_CSV = os.path.join(OUTPUT_DIR, f"ALIENEDGE_O25_PREDICTIONS_{target_date}.csv")

        # =========================================================
        # 📥 THE ULTIMATE HARVEST (FETCHING THE LISTS)
        # =========================================================

        # 📊 LIST A: BASE OVER 2.5 ENGINE (From Stage 3)
        list_engine = {}
        if os.path.exists(FILE_ENGINE_CSV):
            try:
                df_eng = pd.read_csv(FILE_ENGINE_CSV)
                for _, row in df_eng.iterrows():
                    # 🛠️ SURGICAL FIX: The "Silent Assassin" column name fix
                    f_name = str(row.get('Fixture', row.get('fixture', row.get('Match', 'Unknown'))))
                    f_grade = str(row.get('Votes', row.get('Grade', row.get('poisson_prob', 'N/A'))))
                    
                    if f_name == 'Unknown': continue
                    
                    key = self.get_match_key(f_name)
                    list_engine[key] = {"name": f_name, "grade": f_grade}
            except Exception as e: 
                print(f"   [!] Failed to parse Stage 3 CSV: {e}")

        # 📊 LIST B & C: O2.5 PSYCHOLOGY (LOCKS vs VETOES)
        list_psych_locks = {}
        list_psych_vetoes = {}
        if os.path.exists(FILE_PSYCH_CSV):
            try:
                df_psych = pd.read_csv(FILE_PSYCH_CSV)
                for _, row in df_psych.iterrows():
                    f_name = str(row.get('Fixture', row.get('fixture', 'Unknown')))
                    key = self.get_match_key(f_name)
                    tier_str = str(row.get('Tier', ''))
                    
                    data_pack = {
                        "fixture": f_name,
                        "score": row.get('Score', 0),
                        "tier": tier_str,
                        "triggers": row.get('Reasons', '')
                    }
                    
                    if "🛑" in tier_str or "AVOID" in tier_str or "UNDER" in tier_str:
                        list_psych_vetoes[key] = data_pack
                    elif "💎" in tier_str or "🔥" in tier_str or "DIAMOND" in tier_str:
                        list_psych_locks[key] = data_pack
            except Exception as e:
                print(f"   [!] Failed to parse O2.5 Psychology CSV: {e}")

        # 📊 LIST D: VIP GOLD OVER 2.5 FEED
        list_vip_feed = {}
        if os.path.exists(FILE_VIP_JSON):
            try:
                with open(FILE_VIP_JSON, 'r') as f:
                    vip_data = json.load(f)
                    items = vip_data if isinstance(vip_data, list) else vip_data.values()
                    for row in items:
                        h_name = row.get("teams", {}).get("home", {}).get("name", "Unknown")
                        a_name = row.get("teams", {}).get("away", {}).get("name", "Unknown")
                        fixture_name = f"{h_name} vs {a_name}"
                        key = self.get_match_key(fixture_name)
                        
                        list_vip_feed[key] = {
                            "name": fixture_name,
                            "rule": "💎 VIP O2.5 List"
                        }
            except Exception as e:
                print(f"   [!] Failed to parse VIP JSON: {e}")

        # =========================================================
        # 📺 THE DEPARTMENT ROLL CALL (PRINTING TOP 50 EXACT LISTS)
        # =========================================================
        print("\n" + "="*145)
        print(" 🏢 O2.5 DEPARTMENT ROLL CALL (RAW ENGINE OUTPUTS)")
        print("="*145)
        
        base_engine_list = list(list_engine.values())[:50]
        print(f"\n[LIST A] BASE OVER 2.5 ENGINE (Top 50): {len(list_engine)} Total Found")
        for i, item in enumerate(base_engine_list, 1):
            print(f"   {i:>2}. {item['name'][:45]:<45} -> Grade: {item['grade']}")

        psych_locks_list = list(list_psych_locks.values())[:50]
        print(f"\n[LIST B] O2.5 PSYCHOLOGY - VERIFIED LOCKS (Top 50): {len(list_psych_locks)} Total Found")
        for i, item in enumerate(psych_locks_list, 1):
            print(f"   {i:>2}. {item['fixture'][:45]:<45} -> Score: +{item['score']} | {item['tier']}")

        psych_vetoes_list = list(list_psych_vetoes.values())[:50]
        print(f"\n[LIST C] O2.5 PSYCHOLOGY - VETOES & UNDER TRAPS (Top 50): {len(list_psych_vetoes)} Total Found")
        for i, item in enumerate(psych_vetoes_list, 1):
            print(f"   {i:>2}. {item['fixture'][:45]:<45} -> Reason: {str(item['triggers'])[:60]}")

        vip_feed_list = list(list_vip_feed.values())[:50]
        print(f"\n[LIST D] VIP GOLD O2.5 FEED (Top 50): {len(list_vip_feed)} Total Found")
        for i, item in enumerate(vip_feed_list, 1):
            print(f"   {i:>2}. {item['name'][:45]:<45} -> {item['rule']}")

        print("\n>> 🧠 INITIATING SUPER-MATRIX CROSS-EXAMINATION & MONTE CARLO OVERDRIVE...")

        # =========================================================
        # SUPPORTING DATA (DNA LOOKUP)
        # =========================================================
        list_dna = {}
        dna_db = {}
        api_map = {}
        
        if os.path.exists(FILE_DNA_JSON):
            try:
                with open(FILE_DNA_JSON, "r") as f: dna_db = json.load(f)
                
                # Fetch matches safely via pagination
                page = 1
                while True:
                    api_data = self.GET(f"/fixtures/date/{target_date}", params={"include": "participants", "page": page, "per_page": 50})
                    data = api_data.get("data",[])
                    if not data: break
                    
                    for fx in data:
                        api_map[self.get_match_key(fx['name'])] = fx
                    
                    if len(data) < 50: break
                    page += 1
                
                for key, fx in api_map.items():
                    hid = next((pt['id'] for pt in fx['participants'] if pt['meta']['location'] == 'home'), None)
                    aid = next((pt['id'] for pt in fx['participants'] if pt['meta']['location'] == 'away'), None)
                    if not hid or not aid: continue
                    h_dna, a_dna = dna_db.get(str(hid), {}), dna_db.get(str(aid), {})
                    
                    if h_dna and a_dna:
                        h_intent = h_dna.get("Market_Power_Scores", {}).get("Goal_Intent", 0)
                        a_intent = a_dna.get("Market_Power_Scores", {}).get("Goal_Intent", 0)
                        h_tempo = h_dna.get("Tactical_DNA", {}).get("Tempo", 0)
                        a_tempo = a_dna.get("Tactical_DNA", {}).get("Tempo", 0)
                        h_risk = h_dna.get("Tactical_DNA", {}).get("Risk_Appetite", "Low")
                        a_risk = a_dna.get("Tactical_DNA", {}).get("Risk_Appetite", "Low")
                        h_arch, a_arch = h_dna.get("Archetype", ""), a_dna.get("Archetype", "")

                        intent_pass = (h_intent > 55 and a_intent > 55)
                        tempo_pass = (h_tempo > 50 and a_tempo > 50)
                        risk_pass = (h_risk == "High" or a_risk == "High")
                        arch_pass = ("OVER" in h_arch or "OVER" in a_arch)

                        if (intent_pass and tempo_pass and risk_pass) or arch_pass:
                            list_dna[key] = fx.get('id')
            except Exception as e: 
                print(f"   [!] DNA Verification error: {e}")

        # =========================================================
        # 🏆 MATRIX CROSS-REFERENCE & THE RANKING SHIFT
        # =========================================================
        all_keys = set(list_engine.keys()).union(list_vip_feed.keys()).union(list_psych_locks.keys())
        final_rows =[]

        for key in all_keys:
            eng = list_engine.get(key)
            vip = list_vip_feed.get(key)
            dna_id = list_dna.get(key)
            p_lock = list_psych_locks.get(key)
            p_veto = list_psych_vetoes.get(key)

            f_id = dna_id or api_map.get(key, {}).get('id', 'Unknown')
            
            # Base names
            if eng: f_name = eng['name']
            elif vip: f_name = vip['name']
            elif p_lock: f_name = p_lock['fixture']
            else: f_name = api_map.get(key, {}).get('name', 'Unknown')

            # Feature flags
            has_base = bool(eng)
            has_vip = bool(vip)
            has_elite_dna = bool(dna_id)
            is_psych_lock = bool(p_lock)
            is_psych_veto = bool(p_veto)

            psych_score = p_lock['score'] if is_psych_lock else (p_veto['score'] if is_psych_veto else "N/A")
            psych_triggers = p_lock['triggers'] if is_psych_lock else (p_veto['triggers'] if is_psych_veto else "N/A")
            grade = eng['grade'] if eng else ("5/6" if has_vip else "4/6") # Base assumptions if missing
            
            # 🎲 THE SUPREME MONTE CARLO O2.5 CALCULATION
            m_prob, u25_risk = self.run_monte_carlo_o25_matrix(
                grade_str=grade,
                gap="N/A", 
                psych_score=psych_score,
                is_veto=is_psych_veto,
                has_elite_dna=has_elite_dna,
                is_vip=has_vip
            )

            # 🧠 RANKING SHIFT & CATEGORY ASSIGNMENT
            final_category = "N/A"
            cat_priority = 99
            
            if is_psych_veto:
                final_category = "🚨 CATEGORY 4: THE VETO BOARD"
                cat_priority = 4
            elif (has_base or has_vip) and is_psych_lock and has_elite_dna:
                final_category = "🌌 CATEGORY 1: TOTAL CHAOS (The Bloodbath)"
                cat_priority = 1
            elif (has_base or has_vip) and is_psych_lock:
                final_category = "💎 CATEGORY 2: SUPREME AGREEMENT"
                cat_priority = 2
            elif (has_base or has_vip) and has_elite_dna:
                final_category = "🔥 CATEGORY 3: SOLID MATH"
                cat_priority = 3
            elif has_base or has_vip:
                final_category = "📊 CATEGORY 5: BASE PLAYABLE"
                cat_priority = 5

            if cat_priority > 5: continue # Skip if unclassified

            vip_status = "💎 VIP" if has_vip else "-"
            
            row = {
                "fixture_id": f_id,
                "Fixture": f_name,
                "Category": final_category,
                "Cat_Priority": cat_priority,
                "Super_Monte_Prob": m_prob,
                "U25_Risk": u25_risk,
                "Base_Grade": grade,
                "DNA_Status": "✅ ADVANTAGE" if has_elite_dna else "Neutral",
                "Psych_Score": psych_score,
                "Psych_Triggers": str(psych_triggers)[:80] + "..." if len(str(psych_triggers)) > 80 else str(psych_triggers),
                "VIP_Status": vip_status,
                "Veto_Status": "🛑 VETOED (U2.5 Trap)" if is_psych_veto else "Clear"
            }
            final_rows.append(row)

        # =========================================================
        # 💾 FINAL OUTPUT & ULTIMATE PRINT
        # =========================================================
        if not final_rows:
            print("\n>> [FATAL ERROR] No matches processed in O2.5 Matrix.")
            return[]

        df_final = pd.DataFrame(final_rows)
        # Sort by Category Priority, then highest O2.5 Prob, then lowest U2.5 Risk
        df_final = df_final.sort_values(by=["Cat_Priority", "Super_Monte_Prob", "U25_Risk"], ascending=[True, False, True])

        cat1_df = df_final[df_final['Cat_Priority'] == 1]
        cat2_df = df_final[df_final['Cat_Priority'] == 2]
        cat3_df = df_final[df_final['Cat_Priority'] == 3]
        cat4_df = df_final[df_final['Cat_Priority'] == 4]

        print("\n\n" + "★"*145)
        print(f" 🏆 ALIENEDGE FINAL OVER 2.5 AGGREGATOR (THE SUPER-MATRIX) ")
        print("★"*145)

        print("\n" + "🌌"*50)
        print(" 🌌 CATEGORY 1: TOTAL CHAOS (The Bloodbath) 🌌")
        print("🌌"*50)
        print("   Base Math + Elite DNA + Psych Lock. No defense, maximum attacks, absolute shootout.\n")
        if not cat1_df.empty:
            for i, (_, row) in enumerate(cat1_df.iterrows(), 1):
                print(f"{i}. {row['Fixture']} | Super-Monte O2.5: {row['Super_Monte_Prob']}% | Under 2.5 Risk: {row['U25_Risk']}%")
                print(f"   * Psych Score: +{row['Psych_Score']} | Logic: {row['Psych_Triggers']}\n")
        else: print("[!] No matches met Category 1 criteria today.\n")

        print("\n" + "💎"*50)
        print(" 💎 CATEGORY 2: SUPREME AGREEMENT (Math + Psych) 💎")
        print("💎"*50)
        print("   The Math and the Tactical Psychology Engine perfectly align for Over 2.5.\n")
        if not cat2_df.empty:
            for i, (_, row) in enumerate(cat2_df.iterrows(), 1):
                print(f"{i}. {row['Fixture']} | Super-Monte O2.5: {row['Super_Monte_Prob']}% | Under 2.5 Risk: {row['U25_Risk']}%")
                print(f"   * Psych Score: +{row['Psych_Score']} | Logic: {row['Psych_Triggers']}\n")
        else: print("   [!] No Category 2 matches found today.\n")

        print("\n" + "🔥"*50)
        print(" 🔥 CATEGORY 3: SOLID MATH (Base Math + DNA/VIP) 🔥")
        print("🔥"*50)
        if not cat3_df.empty:
            for i, (_, row) in enumerate(cat3_df.iterrows(), 1):
                print(f"{i}. {row['Fixture']} | Super-Monte O2.5: {row['Super_Monte_Prob']}% | Under 2.5 Risk: {row['U25_Risk']}% | DNA: {row['DNA_Status']}\n")
        else: print("[!] No Category 3 matches found today.\n")

        print("\n" + "🚨"*50)
        print(" 🚨 CATEGORY 4: THE VETO BOARD (Under 2.5 Traps) 🚨")
        print("🚨"*50)
        print("   The Base Math liked these, but Psychology intercepted a trap (Defensive play or possession suffocation).\n")
        if not cat4_df.empty:
            for i, (_, row) in enumerate(cat4_df.iterrows(), 1):
                print(f"{i}. {row['Fixture']} | Super-Monte O2.5: {row['Super_Monte_Prob']}% | Under 2.5 Risk: {row['U25_Risk']}%")
                print(f"   * 🛑 STATUS: {row['Psych_Triggers']}\n")
        else: print("   [!] No matches vetoed today.\n")

        # Save to Live CSV
        live_path = os.path.join(MASTER_DIR, "O25_MASTER_LIVE.csv")
        df_final.to_csv(live_path, index=False)
        print(f"\n[🏆] Master O2.5 Matrix complete. Feed updated: {live_path}")
        
        return df_final.to_dict(orient="records")

# --- LOCAL TESTING ---
def run_over25_aggregator(target_date=None):
    agg = ApexO25Aggregator()
    return agg.run_process(target_date)

if __name__ == "__main__":
    run_over25_aggregator(datetime.now(timezone.utc).strftime("%Y-%m-%d"))