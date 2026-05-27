import os

import sys

import math

import time

import json

import requests

import pandas as pd

import numpy as np

import re

from datetime import datetime, timedelta, timezone



# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---

from dotenv import load_dotenv

load_dotenv()



# --- 2. DYNAMIC PATHS FOR SERVERS ---

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OUTPUT_DIR = os.path.join(BASE_DIR, "output")

DATA_DIR = os.path.join(BASE_DIR, "data")

MASTER_DIR = os.path.join(BASE_DIR, "master_aggregator")



# ==============================================================================

# 📦 THE BLACK BOX WRAPPER (CALLABLE BY THE MASTER API/SCHEDULER)

# ==============================================================================

def run_supreme_gg_aggregator(target_date=None):

    """

    Executes the Supreme GG Aggregator (Super-Matrix V9).

    Integrates the Base Engine, DNA, VIP Feeds, and the GG Psychology Engine.

    Dynamic Spear Power fully replaces static Away penalties.

    """

    if not target_date:

        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")



    # Ensure directories exist

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    os.makedirs(DATA_DIR, exist_ok=True)

    os.makedirs(MASTER_DIR, exist_ok=True)



    # -------------------------

    # ⚙️ CONFIGURATION

    # -------------------------

    API_KEY = os.getenv("SPORTMONKS_API_KEY") or "hD4F4FIFwNW5BxKa6Y0fCCLtB0KkiNRxtULDdsrO3VPss1IMV4HJihBkxwI4"

    BASE_URL = "https://api.sportmonks.com/v3/football"



    # DYNAMIC PATHS

    FILE_INPUT_AUDIT = os.path.join(OUTPUT_DIR, f"JUDGED_GG_PICKS_{target_date}.csv")

    FILE_HANDSHAKE_CSV = os.path.join(OUTPUT_DIR, f"MASTER_CALIBRATION_{target_date}.csv")

    FILE_DNA_JSON = os.path.join(DATA_DIR, "team_dna_profiles.json")

    GENERAL_FEED_FILE = os.path.join(OUTPUT_DIR, "sh_gg_winner_feed.json")

    FILE_PSYCH_CSV = os.path.join(OUTPUT_DIR, f"ALIENEDGE_GG_PSYCHOLOGY_FINAL_{target_date}.csv")

    FILE_CATALYST = os.path.join(OUTPUT_DIR, f"audited_underdog_backtest_{target_date}.csv")



    if not API_KEY:

        print("CRITICAL: SPORTMONKS_API_KEY is missing!")

        return[]



    # -------------------------

    # 🛠️ UTILITIES & KEY MATCHING

    # -------------------------

    def GET(path, params=None):

        if params is None: params = {}

        params.setdefault('api_token', API_KEY)

        try:

            r = requests.get(f"{BASE_URL}{path}", params=params, timeout=25)

            if r.status_code == 200: return r.json()

        except: pass

        return {}



    def get_match_key(name):

        n = str(name).lower()

        n = re.sub(r'\bu19\b|\bfc\b|\bsc\b|\bunited\b|\bcity\b|\bclub\b|\bafc\b|\brc\b|\bas\b', '', n)

        parts = n.split(' vs ') if ' vs ' in n else n.split('-') if '-' in n else [n]

        parts = [re.sub(r'[^a-z0-9]', '', p.strip()) for p in parts]

        parts.sort()

        return "".join(parts)



    # =========================================================

    # 🎲 QUANT-LEVEL GG MONTE CARLO INTELLIGENCE MATRIX

    # =========================================================

    def run_monte_carlo_gg_matrix(marks_str, dominance_gap, psych_score, is_veto, has_elite_dna, is_vip, h_spear, a_spear):

        """

        Simulates 5,000 matches for GG logic.

        Now dynamically weighted by actual Home and Away Spear Power.

        """

        try: marks = int(str(marks_str).split('/')[0])

        except: marks = 3



        # Base Lambda mapped to Marks (Expected goals in a neutral vacuum)

        base_lambda = {6: 2.3, 5: 2.0, 4: 1.7, 3: 1.4, 2: 1.1, 1: 0.8, 0: 0.6}.get(marks, 1.4)

        

        # --- DYNAMIC SPEAR POWER WEIGHTING ---

        # Instead of static 0.95 away penalty, we use their actual win/score probabilities

        h_weight = 1.0 + ((h_spear - a_spear) / 100.0)

        a_weight = 1.0 + ((a_spear - h_spear) / 100.0)

        

        # Add a tiny, realistic base home advantage (+0.05) independent of team power

        h_weight += 0.05

        a_weight -= 0.02



        # Normalize to prevent mathematical breakdown

        h_weight = max(0.75, min(1.25, h_weight))

        a_weight = max(0.75, min(1.25, a_weight))



        # --- SYNERGY CALCULATION ---

        mult = 1.0

        synergy_boost = 0.0



        if has_elite_dna or is_vip: 

            synergy_boost += 0.10

        if dominance_gap != "N/A" and isinstance(dominance_gap, (int, float)):

            synergy_boost += min(0.08, abs(float(dominance_gap)) / 200.0)

        if psych_score != "N/A" and isinstance(psych_score, (int, float)):

            synergy_boost += (float(psych_score) / 300.0) 

            

        # Apply combined boost (Capped mathematically at +30% for GG)

        mult *= (1.0 + min(0.30, synergy_boost))



        # The Veto Guillotine

        if is_veto:

            mult *= 0.60 



        # Hard Normalization Boundaries

        mult = max(0.50, min(1.35, mult))

        

        # Final Dynamic Lambdas

        home_lambda = (base_lambda * h_weight) * mult

        away_lambda = (base_lambda * a_weight) * mult



        # Run 5,000 Parallel Universes

        sim_home = np.random.poisson(home_lambda, 5000)

        sim_away = np.random.poisson(away_lambda, 5000)

        

        # GG Condition = Both teams score >= 1

        gg_hits = np.sum((sim_home > 0) & (sim_away > 0))

        # NGG Risk = At least one team scores 0

        ngg_hits = np.sum((sim_home == 0) | (sim_away == 0))

        

        m_prob = round((gg_hits / 5000) * 100, 2)

        ngg_prob = round((ngg_hits / 5000) * 100, 2)

        

        return m_prob, ngg_prob



    # -------------------------

    # 🚀 THE SUPREME GG AGGREGATOR EXECUTION

    # -------------------------

    print(f"\n" + "="*145)

    print(f" 🛡️ ALIENEDGE SUPREME GG AGGREGATOR (SUPER-MATRIX V9) | DATE: {target_date} ")

    print("="*145)



    # =========================================================

    # 📥 THE ULTIMATE HARVEST (FETCHING THE LISTS)

    # =========================================================



    # Fetch Catalyst (Underdog Data) for Spears

    cat_db = {}

    if os.path.exists(FILE_CATALYST):

        try:

            df_cat = pd.read_csv(FILE_CATALYST)

            prob_col = next((c for c in df_cat.columns if 'prob' in c.lower()), 'Audit_Real_Prob')

            fix_col = next((c for c in df_cat.columns if 'fixture' in c.lower() or 'match' in c.lower()), 'fixture')

            dog_col = next((c for c in df_cat.columns if 'underdog' in c.lower()), 'underdog_team')

            for _, row in df_cat.iterrows():

                try: 

                    key = get_match_key(str(row[fix_col]))

                    d_prob = float(str(row[prob_col]).replace('%', '').strip())

                    f_prob = float(str(row.get('Fav_Spear_Power', '0')).replace('%', '').strip())

                    cat_db[key] = {"dog_name": str(row[dog_col]), "dog_prob": d_prob, "fav_prob": f_prob}

                except: continue

        except: pass



    # 📊 LIST A: BASE GG ENGINE (From Audit)

    list_engine = {}

    if os.path.exists(FILE_INPUT_AUDIT):

        try:

            df_pool = pd.read_csv(FILE_INPUT_AUDIT)

            for _, row in df_pool.iterrows():

                f_name = row.get('Fixture', row.get('fixture', 'Unknown'))

                key = get_match_key(f_name)

                list_engine[key] = {

                    "name": f_name, 

                    "marks": row.get('Score', row.get('marks', '4/6')),

                    "dna_intel": row.get('DNA_Intelligence', '⚖️ BALANCED')

                }

        except: pass



    # 📊 LIST B & C: GG PSYCHOLOGY (LOCKS vs VETOES)

    list_psych_locks = {}

    list_psych_vetoes = {}

    if os.path.exists(FILE_PSYCH_CSV):

        try:

            df_psych = pd.read_csv(FILE_PSYCH_CSV)

            for _, row in df_psych.iterrows():

                key = get_match_key(row['Fixture'])

                tier_str = str(row.get('Tier', ''))

                

                data_pack = {

                    "fixture": row['Fixture'],

                    "score": row.get('Psych_Score', 0),

                    "tier": tier_str,

                    "triggers": row.get('Psych_Triggers', '')

                }

                

                if "🛑" in tier_str or "VETO" in tier_str:

                    list_psych_vetoes[key] = data_pack

                elif "💎" in tier_str or "🔥" in tier_str:

                    list_psych_locks[key] = data_pack

        except Exception as e:

            print(f"   [!] Failed to parse GG Psychology CSV: {e}")



    # 📊 LIST D: VIP H2H GG FEED (From Winner Engine Feed)

    list_vip_feed = {}

    if os.path.exists(GENERAL_FEED_FILE):

        try:

            with open(GENERAL_FEED_FILE, "r") as f:

                feed_data = json.load(f)

                for item in feed_data:

                    if item.get("flags", {}).get("h2h_gg_100", False):

                        h_name = item.get("teams", {}).get("home", {}).get("name", "Unknown")

                        a_name = item.get("teams", {}).get("away", {}).get("name", "Unknown")

                        f_name = f"{h_name} vs {a_name}"

                        key = get_match_key(f_name)

                        list_vip_feed[key] = {"name": f_name, "fixture_id": item.get("fixture_id", "N/A")}

        except: pass



    # =========================================================

    # 📺 THE DEPARTMENT ROLL CALL (PRINTING TOP 50 EXACT LISTS)

    # =========================================================

    print("\n" + "="*145)

    print(" 🏢 GG DEPARTMENT ROLL CALL (RAW ENGINE OUTPUTS)")

    print("="*145)

    

    base_engine_list = list(list_engine.values())[:50]

    print(f"\n[LIST A] BASE GG ENGINE (Top 50): {len(list_engine)} Total Found")

    for i, item in enumerate(base_engine_list, 1):

        print(f"   {i:>2}. {item['name'][:45]:<45} -> Marks: {item['marks']} | DNA: {item['dna_intel']}")



    psych_locks_list = list(list_psych_locks.values())[:50]

    print(f"\n[LIST B] GG PSYCHOLOGY - VERIFIED LOCKS (Top 50): {len(list_psych_locks)} Total Found")

    for i, item in enumerate(psych_locks_list, 1):

        print(f"   {i:>2}. {item['fixture'][:45]:<45} -> Score: +{item['score']} | {item['tier']}")



    psych_vetoes_list = list(list_psych_vetoes.values())[:50]

    print(f"\n[LIST C] GG PSYCHOLOGY - VETOES & TRAPS (Top 50): {len(list_psych_vetoes)} Total Found")

    for i, item in enumerate(psych_vetoes_list, 1):

        print(f"   {i:>2}. {item['fixture'][:45]:<45} -> Reason: {str(item['triggers'])[:60]}")



    vip_feed_list = list(list_vip_feed.values())[:50]

    print(f"\n[LIST D] VIP H2H GG FEED (Top 50): {len(list_vip_feed)} Total Found")

    for i, item in enumerate(vip_feed_list, 1):

        print(f"   {i:>2}. {item['name'][:45]:<45} -> 100% Historical GG Target")



    print("\n>> 🧠 INITIATING SUPER-MATRIX CROSS-EXAMINATION & MONTE CARLO OVERDRIVE...")



    # =========================================================

    # SUPPORTING DATA (HANDSHAKE & API MAP)

    # =========================================================

    list_handshake = {}

    if os.path.exists(FILE_HANDSHAKE_CSV):

        try:

            df_hs = pd.read_csv(FILE_HANDSHAKE_CSV)

            for _, row in df_hs.iterrows():

                f_name = row.get('fixture', 'Unknown')

                key = get_match_key(f_name)

                p, d = float(row.get('parity_gap', 0)), float(row.get('Dominance_Gap', 0))

                rule = "🔥 CHAOS" if (-5 <= p <= 5 and d <= -15) else "⚠️ POISONED" if (p <= -12 and d <= -25) else None

                if rule: list_handshake[key] = {"name": f_name, "rule": rule, "p": p, "d": d}

        except: pass



    api_resp = GET(f"/fixtures/date/{target_date}", params={"include": "participants"})

    api_map = {get_match_key(fx['name']): fx for fx in api_resp.get("data",[])}



    # =========================================================

    # 🏆 MATRIX CROSS-REFERENCE & THE RANKING SHIFT

    # =========================================================

    all_keys = set(list_engine.keys()).union(list_vip_feed.keys()).union(list_psych_locks.keys()).union(list_handshake.keys())

    final_rows =[]



    for key in all_keys:

        eng = list_engine.get(key)

        vip = list_vip_feed.get(key)

        hs = list_handshake.get(key)

        p_lock = list_psych_locks.get(key)

        p_veto = list_psych_vetoes.get(key)



        fx_api = api_map.get(key)

        f_id = fx_api['id'] if fx_api else (vip['fixture_id'] if vip else "N/A")

        

        # Base names

        if eng: f_name = eng['name']

        elif vip: f_name = vip['name']

        elif hs: f_name = hs['name']

        elif p_lock: f_name = p_lock['fixture']

        else: f_name = api_map.get(key, {}).get('name', 'Unknown')



        home_name = f_name.split(" vs ")[0] if " vs " in f_name else "Home"



        # Feature flags

        has_base = bool(eng)

        has_vip = bool(vip)

        has_hs = bool(hs)

        has_elite_dna = "ADVANTAGE" in str(eng['dna_intel']).upper() if eng else False

        is_psych_lock = bool(p_lock)

        is_psych_veto = bool(p_veto)



        psych_score = p_lock['score'] if is_psych_lock else (p_veto['score'] if is_psych_veto else "N/A")

        psych_triggers = p_lock['triggers'] if is_psych_lock else (p_veto['triggers'] if is_psych_veto else "N/A")

        marks = eng['marks'] if eng else ("4/6 (Est)" if has_vip else "3/6 (Est)")



        # Retrieve Spears for Dynamic Weighting

        cat_info = cat_db.get(key, {})

        dog_name = cat_info.get("dog_name", "")

        

        def clean_n(name):

            n = str(name).lower()

            return re.sub(r'[^a-z0-9]', '', n).strip()

            

        if clean_n(home_name) == clean_n(dog_name):

            h_spear, a_spear = cat_info.get("dog_prob", 50.0), cat_info.get("fav_prob", 50.0)

        else:

            h_spear, a_spear = cat_info.get("fav_prob", 50.0), cat_info.get("dog_prob", 50.0)



        # 🎲 THE SUPREME MONTE CARLO GG CALCULATION (Now with Dynamic Spears)

        dom_gap = hs['d'] if has_hs else 0

        m_prob, ngg_prob = run_monte_carlo_gg_matrix(

            marks_str=marks,

            dominance_gap=dom_gap,

            psych_score=psych_score,

            is_veto=is_psych_veto,

            has_elite_dna=has_elite_dna,

            is_vip=has_vip,

            h_spear=h_spear,

            a_spear=a_spear

        )



        # 🧠 RANKING SHIFT & CATEGORY ASSIGNMENT

        final_category = "N/A"

        cat_priority = 99

        

        if is_psych_veto:

            final_category = "🚨 CATEGORY 4: THE VETO BOARD"

            cat_priority = 4

        elif (has_base or has_vip) and is_psych_lock and has_elite_dna:

            final_category = "🌌 CATEGORY 1: TOTAL CONVERGENCE"

            cat_priority = 1

        elif (has_base or has_vip) and is_psych_lock:

            final_category = "💎 CATEGORY 2: SUPREME AGREEMENT"

            cat_priority = 2

        elif (has_base or has_vip) and (has_elite_dna or has_hs):

            final_category = "🔥 CATEGORY 3: SOLID MATH"

            cat_priority = 3

        elif has_base or has_vip:

            final_category = "📊 CATEGORY 5: BASE PLAYABLE"

            cat_priority = 5

        elif has_hs and not is_psych_veto:

            final_category = "📜 STANDALONE ANOMALY"

            cat_priority = 6



        if cat_priority > 6: continue # Skip if unclassified and non-base



        vip_status = "💎 VIP" if has_vip else "-"

        

        row = {

            "fixture_id": f_id,

            "Fixture": f_name,

            "Category": final_category,

            "Cat_Priority": cat_priority,

            "Monte_GG_Prob": m_prob,

            "NGG_Risk": ngg_prob,

            "Base_Marks": marks,

            "DNA_Status": "✅ ADVANTAGE" if has_elite_dna else "Neutral",

            "Psych_Score": psych_score,

            "Psych_Triggers": str(psych_triggers)[:75] + "..." if len(str(psych_triggers)) > 75 else str(psych_triggers),

            "VIP_Status": vip_status,

            "Veto_Status": "🛑 VETOED" if is_psych_veto else "Clear",

            "Spears": f"H:{h_spear}% | A:{a_spear}%"

        }

        final_rows.append(row)



    # =========================================================

    # 💾 FINAL OUTPUT & ULTIMATE PRINT

    # =========================================================

    if not final_rows:

        print("\n>> [FATAL ERROR] No matches processed in GG Matrix.")

        return[]



    df_final = pd.DataFrame(final_rows)

    # Sort by Category Priority, then highest GG Prob, then lowest NGG Risk

    df_final = df_final.sort_values(by=["Cat_Priority", "Monte_GG_Prob", "NGG_Risk"], ascending=[True, False, True])



    cat1_df = df_final[df_final['Cat_Priority'] == 1]

    cat2_df = df_final[df_final['Cat_Priority'] == 2]

    cat3_df = df_final[df_final['Cat_Priority'] == 3]

    cat4_df = df_final[df_final['Cat_Priority'] == 4]



    print("\n\n" + "★"*145)

    print(f" 🏆 ALIENEDGE FINAL GG AGGREGATOR (THE SUPER-MATRIX) ")

    print("★"*145)



    print("\n" + "🌌"*50)

    print(" 🌌 CATEGORY 1: TOTAL CONVERGENCE (The Holy Grail) 🌌")

    print("🌌"*50)

    print("   Base Math + Elite DNA + GG Psych Lock. Two terrible defenses vs elite attacks.\n")

    if not cat1_df.empty:

        for i, (_, row) in enumerate(cat1_df.iterrows(), 1):

            print(f"{i}. {row['Fixture']} | Super-Monte GG: {row['Monte_GG_Prob']}% | NGG Risk: {row['NGG_Risk']}%")

            print(f"   * Psych Score: +{row['Psych_Score']} | Logic: {row['Psych_Triggers']}")

            print(f"   * Spears: {row['Spears']}\n")

    else: print("   [!] No matches met Category 1 criteria today.\n")



    print("\n" + "💎"*50)

    print(" 💎 CATEGORY 2: SUPREME AGREEMENT (Math + Psych) 💎")

    print("💎"*50)

    print("   The Math and the Tactical Psychology Engine perfectly align for Mutual Destruction.\n")

    if not cat2_df.empty:

        for i, (_, row) in enumerate(cat2_df.iterrows(), 1):

            print(f"{i}. {row['Fixture']} | Super-Monte GG: {row['Monte_GG_Prob']}% | NGG Risk: {row['NGG_Risk']}%")

            print(f"   * Psych Score: +{row['Psych_Score']} | Logic: {row['Psych_Triggers']}\n")

    else: print("   [!] No Category 2 matches found today.\n")



    print("\n" + "🔥"*50)

    print(" 🔥 CATEGORY 3: SOLID MATH (Base Math + DNA/Anomalies) 🔥")

    print("🔥"*50)

    if not cat3_df.empty:

        for i, (_, row) in enumerate(cat3_df.iterrows(), 1):

            print(f"{i}. {row['Fixture']} | Super-Monte GG: {row['Monte_GG_Prob']}% | DNA: {row['DNA_Status']}\n")

    else: print("   [!] No Category 3 matches found today.\n")



    print("\n" + "🚨"*50)

    print(" 🚨 CATEGORY 4: THE VETO BOARD (Traps & Clean Sheets) 🚨")

    print("🚨"*50)

    print("   The Base Math liked these, but Psychology intercepted a trap (Toothless Attack or Lone Brick Wall).\n")

    if not cat4_df.empty:

        for i, (_, row) in enumerate(cat4_df.iterrows(), 1):

            print(f"{i}. {row['Fixture']} | Super-Monte GG: {row['Monte_GG_Prob']}% | 🛑 STATUS: {row['Psych_Triggers']}\n")

    else: print("   [!] No matches vetoed today.\n")



    # Save to Live CSV

    live_path = os.path.join(MASTER_DIR, "FINAL_GG_MASTER_LIVE.csv")

    df_final.to_csv(live_path, index=False)

    print(f"\n[🏆] Master GG Matrix complete. Feed updated: {live_path}")

    

    return df_final.to_dict(orient="records")



# --- LOCAL TESTING ---

if __name__ == "__main__":

    pd.set_option('display.max_rows', None)

    pd.set_option('display.width', 1000)

    run_supreme_gg_aggregator()