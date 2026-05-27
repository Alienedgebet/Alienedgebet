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

from collections import defaultdict

from dotenv import load_dotenv



# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---

load_dotenv()



# --- 2. DYNAMIC PATHS FOR SERVERS ---

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OUTPUT_DIR = os.path.join(BASE_DIR, "output")

DATA_DIR = os.path.join(BASE_DIR, "data")

MASTER_DIR = os.path.join(BASE_DIR, "master_aggregator")



# ==============================================================================

# 📦 THE BLACK BOX WRAPPER (CALLABLE BY THE MASTER API/SCHEDULER)

# ==============================================================================

def run_win_apex_aggregator(target_date=None):

    """

    Executes the Apex Win Aggregator (Super-Matrix V8).

    Reads the base forecast, risk files, DNA, and Psychology to output Master Win Picks.

    """

    # Ensure directories exist

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    os.makedirs(DATA_DIR, exist_ok=True)

    os.makedirs(MASTER_DIR, exist_ok=True)



    # ---------------------------------------------------------

    # 1. CONFIGURATION & DYNAMIC PATHS

    # ---------------------------------------------------------

    API_KEY = os.getenv("SPORTMONKS_API_KEY") or "hD4F4FIFwNW5BxKa6Y0fCCLtB0KkiNRxtULDdsrO3VPss1IMV4HJihBkxwI4"

    BASE_URL = "https://api.sportmonks.com/v3/football"



    if not target_date:

        TODAY_STR = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    else:

        TODAY_STR = target_date



    FILE_WIN_FORECAST   = os.path.join(OUTPUT_DIR, f"ranked_win_forecast_{TODAY_STR}.csv")

    FILE_UNDERDOG       = os.path.join(OUTPUT_DIR, f"audited_underdog_backtest_{TODAY_STR}.csv")

    FILE_WIN_PSYCHOLOGY = os.path.join(OUTPUT_DIR, f"ALIENEDGE_WIN_PREDICTIONS_{TODAY_STR}.csv")

    FILE_U2S_PSYCHOLOGY = os.path.join(OUTPUT_DIR, f"ALIENEDGE_U2S_PSYCHOLOGY_{TODAY_STR}.csv")

    FILE_CALIBRATION    = os.path.join(OUTPUT_DIR, f"MASTER_CALIBRATION_{TODAY_STR}.csv")

    FILE_DNA            = os.path.join(DATA_DIR, "team_dna_profiles.json")

    FILE_VIP_FEED       = os.path.join(OUTPUT_DIR, "sh_gg_winner_feed.json")

    FILE_FINAL_OUTPUT   = os.path.join(MASTER_DIR, f"WIN_SUPER_MATRIX_FINAL_{TODAY_STR}.csv")



    # ---------------------------------------------------------

    # 2. UTILITIES

    # ---------------------------------------------------------

    def GET(path, params=None):

        if params is None: params = {}

        params.setdefault('api_token', API_KEY)

        try:

            r = requests.get(f"{BASE_URL}{path}", params=params, timeout=20)

            if r.status_code == 200: return r.json()

        except: pass

        return {}



    def clean_n(name):

        n = str(name).lower()

        for word in["u19", "fc", "sc", "united", "city", "club", "afc", "rc", "as", "deportivo", "atletico"]:

            n = n.replace(word, "")

        return re.sub(r'[^a-z0-9]', '', n).strip()



    def get_match_key(name):

        n = str(name).lower()

        n = re.sub(r'\bu19\b|\bfc\b', '', n)

        if ' vs ' in n: teams = n.split(' vs ')

        elif '-' in n: teams = n.split('-')

        else: teams = [n]

        teams = [re.sub(r'[^a-z0-9]', '', t.strip()) for t in teams]

        teams.sort()

        return "".join(teams)



    # ---------------------------------------------------------

    # 3. 🎲 QUANT-LEVEL MONTE CARLO INTELLIGENCE MATRIX

    # ---------------------------------------------------------

    def run_monte_carlo_matrix(engine_prob, dominance_gap, psych_score, is_veto, is_choked_opp, dna_align, is_risky):

        try: p_val = float(str(engine_prob).replace('%', ''))

        except: p_val = 35.0  # LOWERED TO 35% TO CATCH ELITE VALUE DOGS



        target_lambda = max(0.8, (p_val / 30.0))

        opp_lambda = 1.1



        t_mult = 1.0

        o_mult = 1.0



        synergy_boost = 0.0

        if dna_align:

            synergy_boost += 0.08

        if psych_score != "N/A" and isinstance(psych_score, (int, float)):

            synergy_boost += (float(psych_score) / 400.0)

        if dominance_gap != "N/A" and isinstance(dominance_gap, (int, float)) and dominance_gap > 0:

            synergy_boost += min(0.07, float(dominance_gap) / 200.0)



        t_mult *= (1.0 + min(0.25, synergy_boost))



        if is_choked_opp:

            o_mult *= 0.80

            t_mult *= 1.10



        if is_risky:

            o_mult *= 1.20



        if is_veto:

            t_mult *= 0.80

            o_mult *= 1.15



        t_mult = max(0.80, min(1.25, t_mult))

        o_mult = max(0.80, min(1.25, o_mult))



        target_lambda *= t_mult

        opp_lambda *= o_mult



        sim_target = np.random.poisson(target_lambda, 5000)

        sim_opp = np.random.poisson(opp_lambda, 5000)



        wins = np.sum(sim_target > sim_opp)

        draws = np.sum(sim_target == sim_opp)



        m_prob = round((wins / 5000) * 100, 2)

        d_prob = round((draws / 5000) * 100, 2)



        return m_prob, d_prob



    # ---------------------------------------------------------

    # 4. MAIN EXECUTION (DATA HARVESTING & CROSS-EXAMINATION)

    # ---------------------------------------------------------

    print("\n" + "="*145)

    print(f" 🚀 ALIENEDGE APEX WIN AGGREGATOR (SUPER-MATRIX INTELLIGENCE V8) - {TODAY_STR}")

    print("="*145)



    # A. READ UNDERDOG DATA (Identifies Risky Matches)

    risky_fixtures = set()

    if os.path.exists(FILE_UNDERDOG):

        df_ud = pd.read_csv(FILE_UNDERDOG)

        prob_col = 'Audit_Real_Prob' if 'Audit_Real_Prob' in df_ud.columns else 'dog_score_prob'

        for _, row in df_ud.iterrows():

            try:

                prob = float(str(row.get(prob_col, '0')).replace('%', ''))

                if prob > 50.0 and pd.notna(row.get('fixture_id')):

                    risky_fixtures.add(int(row['fixture_id']))

            except: continue

        print(f">> [UNDERDOG ENGINE] Loaded. Found {len(risky_fixtures)} RISKY fixtures (>50% Dog Prob).")

    else:

        print(f">> [WARNING] {FILE_UNDERDOG} not found. Skipping risk injection.")



    # B. READ WIN FORECAST (The Base Math - NOW 35% THRESHOLD)

    list_engine = {}

    if os.path.exists(FILE_WIN_FORECAST):

        df_win = pd.read_csv(FILE_WIN_FORECAST)

        for _, row in df_win.iterrows():

            try:

                p_val = float(str(row.get('poisson_win_prob', '0')).replace('%', ''))

                # 📉 LOWERED TO 35% TO CATCH MASSIVE VALUE ALIGNMENTS

                if p_val >= 35.0:

                    key = get_match_key(row['fixture'])

                    fid = row.get('fixture_id')

                    is_risky = fid and int(fid) in risky_fixtures

                    list_engine[key] = {

                        "name": row['fixture'],

                        "team": row['team_name'],

                        "side": str(row['side']).lower(),

                        "prob": p_val,

                        "odds": row.get('win_odds', row.get('Win_Odds', 'N/A')),

                        "fixture_id": fid,

                        "is_risky": is_risky,

                        "risk_label": "⚠️ RISKY" if is_risky else "✅ NORMAL"

                    }

            except: continue

        print(f">> [WIN FORECAST] Loaded {len(list_engine)} baseline matches (>35% prob).")

    else:

        print(f">> [FATAL ERROR] {FILE_WIN_FORECAST} not found. Engine needs a baseline to run.")

        return[]



    # C. READ WIN PSYCHOLOGY (Locks & Vetoes)

    list_psych_locks = {}

    list_psych_vetoes = {}

    if os.path.exists(FILE_WIN_PSYCHOLOGY):

        df_psych = pd.read_csv(FILE_WIN_PSYCHOLOGY)

        for _, row in df_psych.iterrows():

            key = get_match_key(row['Fixture'])

            tier_str = str(row.get('Tier', ''))

            preferred_team = str(row.get('Master_Pick', 'None'))



            data_package = {

                "fixture": row['Fixture'],

                "score": row.get('Audit_Score', 0),

                "tier": tier_str,

                "preferred": preferred_team,

                "logic": str(row.get('Home_Logic', '')) + " | " + str(row.get('Away_Logic', ''))

            }



            if "🚨 OVERTURNED" in tier_str or "🛑 CAUTION" in tier_str or "TRAP" in tier_str:

                if "🚨 OVERTURNED" in tier_str:

                    match = re.search(r"prefers\s+([^)]+)\)", tier_str)

                    if match: data_package["preferred"] = match.group(1).strip()

                list_psych_vetoes[key] = data_package

            elif "💎" in tier_str or "🔥" in tier_str:

                list_psych_locks[key] = data_package

        print(f">>[PSYCHOLOGY] Loaded {len(list_psych_locks)} Locks and {len(list_psych_vetoes)} Vetoes.")

    else:

        print(f">> [WARNING] {FILE_WIN_PSYCHOLOGY} not found. Skipping psychological vetos.")



    # D. READ U2S PSYCHOLOGY (The Chokehold)

    list_u2s_chokehold = {}

    if os.path.exists(FILE_U2S_PSYCHOLOGY):

        df_u2s = pd.read_csv(FILE_U2S_PSYCHOLOGY)

        for _, row in df_u2s.iterrows():

            if "🛑" in str(row.get('Tier', '')) or "CHOKEHOLD" in str(row.get('Tier', '')):

                key = get_match_key(row['Fixture'])

                list_u2s_chokehold[key] = {

                    "fixture": row['Fixture'],

                    "underdog": row['Underdog'],

                    "triggers": row['Triggers']

                }

        print(f">> [U2S CHOKEHOLD] Loaded {len(list_u2s_chokehold)} suffocated underdogs.")

    else:

        print(f">> [WARNING] {FILE_U2S_PSYCHOLOGY} not found. Skipping chokehold mechanics.")



    # E. READ MASTER CALIBRATION (Handshake Rules)

    list_handshake_raw = {}

    if os.path.exists(FILE_CALIBRATION):

        df_hs = pd.read_csv(FILE_CALIBRATION)

        for _, row in df_hs.iterrows():

            key = get_match_key(row['fixture'])

            try:

                p, d = float(row.get('parity_gap', 0)), float(row.get('Dominance_Gap', 0))

                rule_name = None

                if p <= -5 and d >= 20: rule_name = "💎 💎 ELITE SHIELD (-5 Parity / +20 Gap)"

                elif d >= 15 and d >= (2 * abs(p)) and not (-4 <= p <= 1): rule_name = "💎 🛡️ SPECIAL RULE 2"

                elif d >= 15: rule_name = "💎 🏦 ELITE BANKER (+15 Gap Wall)"

                elif d >= 10: rule_name = "💎 ✅ SYSTEMIC WIN (+10 Gap)"

                if rule_name: list_handshake_raw[key] = {"name": row['fixture'], "rule": rule_name, "p": p, "d": d}

            except: pass

        print(f">>[HANDSHAKE] Loaded {len(list_handshake_raw)} tactical anomalies.")

    else:

        print(f">> [WARNING] {FILE_CALIBRATION} not found. Skipping handshake anomalies.")



    # F. API FETCH & DNA MAPPING

    list_dna = {}

    api_map = {}

    if os.path.exists(FILE_DNA):

        with open(FILE_DNA, "r") as f: dna_db = json.load(f)

        print(f">> [DNA ENGINE] Database found. Scanning fixtures for Elite Tactical Intent...")



        page = 1

        while True:

            resp = GET(f"/fixtures/date/{TODAY_STR}", params={"include": "participants", "per_page": 50, "page": page})

            data = resp.get("data",[])

            if not data: break

            for fx in data:

                api_map[get_match_key(fx['name'])] = fx

            if len(data) < 50: break

            page += 1

            time.sleep(0.1)



        risk_map = {"High": 3, "Medium": 2, "Low": 1}

        for key, fx in api_map.items():

            hid = next((pt['id'] for pt in fx['participants'] if pt['meta']['location'] == 'home'), None)

            aid = next((pt['id'] for pt in fx['participants'] if pt['meta']['location'] == 'away'), None)

            if not hid or not aid: continue

            h_dna, a_dna = dna_db.get(str(hid), {}), dna_db.get(str(aid), {})

            if h_dna and a_dna:

                h_i, h_t = h_dna.get("Market_Power_Scores", {}).get("Goal_Intent", 0), h_dna.get("Tactical_DNA", {}).get("Tempo", 0)

                h_r = risk_map.get(h_dna.get("Tactical_DNA", {}).get("Risk_Appetite", "Low"), 1)

                a_i, a_t = a_dna.get("Market_Power_Scores", {}).get("Goal_Intent", 0), a_dna.get("Tactical_DNA", {}).get("Tempo", 0)

                a_r = risk_map.get(a_dna.get("Tactical_DNA", {}).get("Risk_Appetite", "Low"), 1)



                if (h_i > a_i) and (h_t > a_t) and (h_r >= a_r):

                    list_dna[key] = {"fav_side": "home", "fixture_id": fx['id']}

                elif (a_i > h_i) and (a_t > h_t) and (a_r >= h_r):

                    list_dna[key] = {"fav_side": "away", "fixture_id": fx['id']}



        print(f"   [+] Successfully found {len(list_dna)} matches with Superior DNA Alignment.")

    else:

        print(f">> [WARNING] {FILE_DNA} not found. Skipping DNA extraction.")



    # G. VIP FEED CHECK

    list_vip_feed = {}

    if os.path.exists(FILE_VIP_FEED):

        try:

            with open(FILE_VIP_FEED, "r") as f:

                feed_data = json.load(f)

                for item in feed_data:

                    flags = item.get("flags", {})

                    if flags.get("home_h2h_win_100", False) or flags.get("away_h2h_win_100", False):

                        h_win = flags.get("home_h2h_win_100", False)

                        h_name = item.get("teams", {}).get("home", {}).get("name", "Unknown")

                        a_name = item.get("teams", {}).get("away", {}).get("name", "Unknown")

                        f_name = f"{h_name} vs {a_name}"

                        key = get_match_key(f_name)

                        list_vip_feed[key] = {

                            "name": f_name,

                            "fixture_id": item.get("fixture_id", "N/A"),

                            "target_team": h_name if h_win else a_name,

                            "win_side": "home" if h_win else "away"

                        }

            print(f">> [VIP FEED] Loaded {len(list_vip_feed)} strict H2H VIP anomalies.")

        except: pass



    # =========================================================

    # 🏆 MATRIX CROSS-REFERENCE & THE RANKING SHIFT

    # =========================================================

    print("\n>> 🧠 INITIATING SUPER-MATRIX CROSS-EXAMINATION & MONTE CARLO OVERDRIVE...")

    all_keys = set(list_engine.keys()).union(list_vip_feed.keys()).union(list_psych_locks.keys()).union(list_psych_vetoes.keys())

    final_rows =[]



    for key in all_keys:

        eng = list_engine.get(key)

        hs = list_handshake_raw.get(key)

        dna = list_dna.get(key)

        vip = list_vip_feed.get(key)

        p_lock = list_psych_locks.get(key)

        p_veto = list_psych_vetoes.get(key)

        choke = list_u2s_chokehold.get(key)



        f_id = eng['fixture_id'] if eng else (vip['fixture_id'] if vip else api_map.get(key, {}).get('id', "N/A"))



        target_name = "N/A"

        target_side = "N/A"

        if eng:

            target_name = eng['team']

            target_side = eng['side']

        elif vip:

            target_name = vip['target_team']

            target_side = vip['win_side']

        elif p_lock: target_name = p_lock['preferred']

        elif p_veto and p_veto['preferred'] != "None": target_name = p_veto['preferred']



        if target_name == "N/A" or target_name == "None": continue



        dna_align = False

        if dna and (target_side == dna['fav_side'] or target_side == "N/A"):

            dna_align = True



        is_psych_lock = False

        psych_score = "N/A"

        psych_logic = "N/A"

        if p_lock and clean_n(p_lock['preferred']) in clean_n(target_name):

            is_psych_lock = True

            psych_score = p_lock['score']

            psych_logic = p_lock['logic']



        is_psych_veto = False

        veto_reason = "N/A"

        if p_veto:

            is_psych_veto = True

            veto_reason = p_veto['tier']

            if p_veto['preferred'] != "None" and clean_n(p_veto['preferred']) not in clean_n(target_name):

                veto_reason = f"🚨 OVERTURNED (Psych Prefers {p_veto['preferred']})"



        is_choked_opp = False

        if choke and clean_n(choke['underdog']) not in clean_n(target_name):

            is_choked_opp = True



        is_risky = eng['is_risky'] if eng else False



        engine_base_prob = eng['prob'] if eng else (65.0 if vip else 35.0)

        dom_gap = hs['d'] if hs else "N/A"



        m_prob, d_prob = run_monte_carlo_matrix(

            engine_prob=engine_base_prob,

            dominance_gap=dom_gap,

            psych_score=psych_score,

            is_veto=is_psych_veto,

            is_choked_opp=is_choked_opp,

            dna_align=dna_align,

            is_risky=is_risky

        )



        final_category = "N/A"

        cat_priority = 99



        if is_psych_veto:

            final_category = "🚨 CATEGORY 3: THE VETO BOARD"

            cat_priority = 3

        elif eng and is_psych_lock and is_choked_opp and (dna_align or vip):

            final_category = "🌌 CATEGORY 1: TOTAL CONVERGENCE"

            cat_priority = 1

        elif eng and is_psych_lock:

            final_category = "💎 CATEGORY 2: SUPREME AGREEMENT"

            cat_priority = 2

        elif eng and (dna_align or vip or hs):

            final_category = "🔥 CATEGORY 4: SOLID MATH WIN"

            cat_priority = 4

        else:

            final_category = "📊 CATEGORY 5: BASE PLAYABLE"

            cat_priority = 5



        risk_status = "✅ NORMAL"

        if is_psych_veto: risk_status = "🛑 PSYCH VETO"

        elif is_risky and not is_choked_opp: risk_status = "⚠️ RISKY"



        final_rows.append({

            "fixture_id": f_id,

            "Fixture": eng['name'] if eng else (vip['name'] if vip else api_map.get(key, {}).get('name', key)),

            "Target": target_name,

            "Category": final_category,

            "Cat_Priority": cat_priority,

            "Monte_Win_Prob": m_prob,

            "Monte_Draw_Prob": d_prob,

            "Underdog_Risk": risk_status,

            "Psych_Score": psych_score,

            "Psych_Logic": str(psych_logic)[:80] + "..." if len(str(psych_logic)) > 80 else psych_logic,

            "Chokehold_Status": "🛑 OPPONENT CHOKED" if is_choked_opp else "Clear",

            "Veto_Reason": veto_reason

        })



    # =========================================================

    # 💾 FINAL OUTPUT & ULTIMATE PRINT

    # =========================================================

    if not final_rows:

        print("\n>> [FATAL ERROR] No matches processed in Matrix.")

        return[]



    df_final = pd.DataFrame(final_rows)

    df_final = df_final.sort_values(by=["Cat_Priority", "Monte_Win_Prob", "Monte_Draw_Prob"], ascending=[True, False, True])



    cat1_df = df_final[df_final['Cat_Priority'] == 1]

    cat2_df = df_final[df_final['Cat_Priority'] == 2]

    cat3_df = df_final[df_final['Cat_Priority'] == 3]



    print("\n\n" + "★"*145)

    print(f" 🏆 ALIENEDGE FINAL AGGREGATOR INTELLIGENCE (THE SUPER-MATRIX) ")

    print("★"*145)



    print("\n" + "🌌"*50)

    print(" 🌌 CATEGORY 1: TOTAL CONVERGENCE (The Holy Grail) 🌌")

    print("🌌"*50)

    print("   Win Engine + Win Psych Lock + U2S Chokehold + DNA. Absolute Certainty.\n")

    if not cat1_df.empty:

        for i, (_, row) in enumerate(cat1_df.iterrows(), 1):

            print(f"{i}. {row['Fixture']} | Target: {row['Target']} | Win: {row['Monte_Win_Prob']}% | Draw Risk: {row['Monte_Draw_Prob']}%")

            print(f"   * Psych Score: +{row['Psych_Score']} | Logic: {row['Psych_Logic']}")

            print(f"   * Status: {row['Chokehold_Status']}\n")

    else: print("   [!] No matches met the Category 1 criteria today.\n")



    print("\n" + "💎"*50)

    print(" 💎 CATEGORY 2: SUPREME AGREEMENT (Win + Psych) 💎")

    print("💎"*50)

    print("   The Win Engine and the Tactical Psychology Engine perfectly align.\n")

    if not cat2_df.empty:

        for i, (_, row) in enumerate(cat2_df.iterrows(), 1):

            print(f"{i}. {row['Fixture']} | Target: {row['Target']} | Win: {row['Monte_Win_Prob']}% | Draw Risk: {row['Monte_Draw_Prob']}%")

            print(f"   * Psych Score: +{row['Psych_Score']} | Logic: {row['Psych_Logic']}\n")

    else: print("   [!] No Category 2 matches found today.\n")



    print("\n" + "🚨"*50)

    print(" 🚨 CATEGORY 3: THE VETO BOARD (Traps & Overturns) 🚨")

    print("🚨"*50)

    print("   The Base Math liked these, but the Tactical Psychology explicitly vetoed them.\n")

    if not cat3_df.empty:

        for i, (_, row) in enumerate(cat3_df.iterrows(), 1):

            print(f"{i}. {row['Fixture']} | Initial Target: {row['Target']} | Win: {row['Monte_Win_Prob']}% | Draw Risk: {row['Monte_Draw_Prob']}%")

            print(f"   * 🛑 STATUS: {row['Veto_Reason']}\n")

    else: print("   [!] No matches vetoed today.\n")



    df_final.to_csv(FILE_FINAL_OUTPUT, index=False)

    print(f"\n[🏆] Master Matrix complete. Feed updated: {FILE_FINAL_OUTPUT}")

    

    return df_final.to_dict(orient="records")



# --- LOCAL TESTING BLOCK ---

if __name__ == "__main__":

    pd.set_option('display.max_rows', None)

    pd.set_option('display.width', 2000)

    run_win_apex_aggregator() 