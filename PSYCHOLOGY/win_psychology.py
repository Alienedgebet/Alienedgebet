import os

import sys

import time

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

# 📦 THE BLACK BOX WRAPPER (CALLABLE BY THE MASTER API/SCHEDULER)

# ==============================================================================

def run_win_psychology_engine(target_date=None):

    """

    Executes the AlienEdge Win Psychology Engine.

    Reads from the Master Win Engine and applies strict forensic filters.

    """

    # Ensure directories exist

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    os.makedirs(DATA_DIR, exist_ok=True)



    # ---------------------------------------------------------

    # 1. CONFIGURATION & SETUP

    # ---------------------------------------------------------

    API_KEY = os.getenv("SPORTMONKS_API_KEY") or "hD4F4FIFwNW5BxKa6Y0fCCLtB0KkiNRxtULDdsrO3VPss1IMV4HJihBkxwI4"

    if not API_KEY:

        print("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")

        return[]



    BASE_URL = "https://api.sportmonks.com/v3/football"



    if not target_date:

        TODAY_STR = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    else:

        TODAY_STR = target_date



    # --- DYNAMIC FILE PATHING ---

    INPUT_FILE = os.path.join(OUTPUT_DIR, f"ranked_win_forecast_{TODAY_STR}.csv")

    FILE_CATALYST = os.path.join(OUTPUT_DIR, f"audited_underdog_backtest_{TODAY_STR}.csv")

    OUTPUT_CSV = os.path.join(OUTPUT_DIR, f"ALIENEDGE_WIN_PREDICTIONS_{TODAY_STR}.csv")



    logging.basicConfig(level=logging.INFO, format='%(asctime)s - [WIN ENGINE] - %(message)s')



    # ---------------------------------------------------------

    # 🛡️ BULLETPROOF API HELPER & CACHE SYSTEM

    # ---------------------------------------------------------

    API_CACHE = {}

    REQUEST_DELAY = 0.2



    def GET(path, params=None):

        if params is None: params = {}

        params.setdefault("api_token", API_KEY)



        cache_key = path + "?" + "&".join([f"{k}={v}" for k, v in sorted(params.items()) if k != "api_token"])

        if cache_key in API_CACHE:

            return API_CACHE[cache_key]



        backoff = 2.0

        for attempt in range(5):

            try:

                resp = requests.get(f"{BASE_URL}{path}", params=params, timeout=30)

                if resp.status_code == 200:

                    data = resp.json()

                    API_CACHE[cache_key] = data

                    time.sleep(REQUEST_DELAY)

                    return data

                elif resp.status_code == 429:

                    time.sleep(backoff)

                    backoff *= 1.5

                    continue

                else:

                    return {"data":[]}

            except Exception:

                time.sleep(1)

                continue

        return {"data":[]}



    def clean_n(name):

        n = str(name).lower()

        for word in["u19", "u23", "fc", "sc", "united", "city", "club", "afc", "rc", "as", "deportivo", "atletico"]:

            n = n.replace(word, "")

        return re.sub(r'[^a-z0-9]', '', n).strip()



    def get_match_key(name):

        n = clean_n(name)

        parts = n.split('vs') if 'vs' in n else [n]

        parts =[p.strip() for p in parts]

        parts.sort()

        return "".join(parts)



    # ---------------------------------------------------------

    # 📊 THE BULLETPROOF 3-LAYER GOAL EXTRACTOR (HT & FT)

    # ---------------------------------------------------------

    def extract_goals_by_period(fx, period="FT"):

        home_g, away_g = None, None

        for entry in fx.get("scores",[]):

            if not isinstance(entry, dict): continue

            s_obj = entry.get("score") or entry

            desc = str(entry.get("description", s_obj.get("description", ""))).upper()



            if any(w in desc for w in["PENALTY", "EXTRA", "AGG"]): continue



            p = s_obj.get("participant") or entry.get("participant")

            g = s_obj.get("goals") if isinstance(s_obj, dict) else entry.get("goals")



            if g is not None:

                try:

                    val = int(g)

                    if period == "FT":

                        if p == "home": home_g = max(home_g or 0, val)

                        elif p == "away": away_g = max(away_g or 0, val)

                    elif period == "HT":

                        if "1ST" in desc or "HT" in desc or "HALF" in desc:

                            if p == "home": home_g = max(home_g or 0, val)

                            elif p == "away": away_g = max(away_g or 0, val)

                except: pass



        return home_g, away_g



    def get_team_and_opp_goals(fx, team_id, period="FT"):

        hg, ag = extract_goals_by_period(fx, period)

        if hg is None or ag is None: return None, None



        for p in fx.get("participants",[]):

            if str(p.get("id")) == str(team_id):

                loc = (p.get("meta") or {}).get("location")

                if loc == "home": return hg, ag

                if loc == "away": return ag, hg



        local = fx.get("localteam_id") or fx.get("localteam") or fx.get("local_team_id")

        visitor = fx.get("visitorteam_id") or fx.get("visitorteam") or fx.get("visitor_team_id")

        if str(local) == str(team_id): return hg, ag

        if str(visitor) == str(team_id): return ag, hg



        parts = fx.get("participants",[])

        if len(parts) >= 2:

            if str(parts[0].get("id")) == str(team_id): return hg, ag

            if str(parts[1].get("id")) == str(team_id): return ag, hg



        return None, None



    def get_match_outcome_bulletproof(fx, team_id, period="FT"):

        tg, og = get_team_and_opp_goals(fx, team_id, period)

        if tg is None or og is None: return None

        if tg > og: return "W"

        if tg < og: return "L"

        return "D"



    def extract_stat_value(fx, team_id, stat_names):

        entries = fx.get("statistics",[])

        if isinstance(entries, dict):

            entries = entries.get(str(team_id),[])

        else:

            entries =[s for s in entries if str(s.get('participant_id', '')) == str(team_id)]



        for s in entries:

            t_name = str(s.get("type", {}).get("name", s.get("name", ""))).upper()

            if any(name.upper() in t_name for name in stat_names):

                val = s.get("data", {}).get("value") if isinstance(s.get("data"), dict) else s.get("value")

                try: return float(val)

                except: pass

        return 0.0



    # ---------------------------------------------------------

    # 🧠 WIN TACTICS ENGINE (The Psychological Profiler)

    # ---------------------------------------------------------

    def analyze_win_tactics(team_id, target_venue, opp_id, current_match_id):

        end_dt = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        start_dt = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")



        resp = GET(f"/fixtures/between/{start_dt}/{end_dt}/{team_id}",

                   params={"include": "statistics.type;participants;scores", "per_page": 40, "order":"desc", "filter": "fixtureStates:5"})



        fixtures =[f for f in resp.get("data", []) if str(f.get('id')) != str(current_match_id)]



        overall_history = fixtures[:5]

        venue_history =[f for f in fixtures if any(str(p.get("id")) == str(team_id) and p.get("meta", {}).get("location") == target_venue for p in f.get("participants", []))][:5]



        if len(venue_history) < 3: venue_history = overall_history



        # 1. 🎯 CLINICAL KILLER

        sot_list =[extract_stat_value(f, team_id, ["Shots On Target"]) for f in overall_history]

        bcc_list =[extract_stat_value(f, team_id,["Big Chances"]) for f in overall_history]

        avg_sot = sum(sot_list) / len(sot_list) if sot_list else 0.0

        avg_bcc = sum(bcc_list) / len(bcc_list) if bcc_list else 0.0

        is_clinical = (avg_sot >= 4.5 and avg_bcc >= 1.5)



        # 2. 🏰 VENUE FORTRESS & HOMESICK PENALTY (YOUR EXACT RULE)

        venue_ft_outcomes =[get_match_outcome_bulletproof(f, team_id, "FT") for f in venue_history]

        venue_wins = venue_ft_outcomes.count("W")



        if target_venue == "home":

            is_fortress = (venue_wins >= 4)

            is_homesick = False # Home teams can't be homesick

        else:

            is_fortress = (venue_wins >= 3)

            is_homesick = (venue_wins <= 2) # 0, 1, or 2 wins triggers the penalty



        # 3. ⚡ 1ST HALF KILLER

        venue_ht_outcomes =[get_match_outcome_bulletproof(f, team_id, "HT") for f in venue_history]

        ht_wins = venue_ht_outcomes.count("W")

        is_ht_killer = (ht_wins >= 3 and len(venue_ht_outcomes) >= 4)



        # 4. 🧱 BRICK WALL & 🔨 GLASS JAW

        conceded_list =[]

        ht_conceded_count = 0

        for f in overall_history:

            tg, og = get_team_and_opp_goals(f, team_id, "FT")

            if og is not None: conceded_list.append(og)

            ht_tg, ht_og = get_team_and_opp_goals(f, team_id, "HT")

            if ht_og is not None and ht_og > 0: ht_conceded_count += 1



        avg_conc = sum(conceded_list) / len(conceded_list) if conceded_list else 1.0



        is_brick_wall = (avg_conc <= 0.85 and len(conceded_list) >= 3)

        is_glass_jaw = (avg_conc > 1.8 and len(conceded_list) >= 3)

        is_ht_vulnerable = (ht_conceded_count >= 3 and len(overall_history) >= 4)



        # 5. 🩸 WOUNDED BEAST & 🐾 CORNERED ANIMAL

        overall_outcomes_5 =[get_match_outcome_bulletproof(f, team_id, "FT") for f in overall_history]

        overall_outcomes_2 = overall_outcomes_5[:2]



        shock_loss = (len(overall_outcomes_2) > 0 and overall_outcomes_2[0] == "L")

        winless_2 = (len(overall_outcomes_2) == 2 and "W" not in overall_outcomes_2)

        is_winless_5 = (len(overall_outcomes_5) >= 4 and "W" not in overall_outcomes_5)



        h2h_data = GET(f"/fixtures/head-to-head/{team_id}/{opp_id}", params={"include":"scores;participants", "per_page": 2, "order":"desc"})

        past_h2h =[h for h in h2h_data.get("data", []) if str(h.get('id')) != str(current_match_id) and h.get('state_id') == 5]

        h2h_hum = (past_h2h and get_match_outcome_bulletproof(past_h2h[0], team_id, "FT") == "L")



        is_wounded = (shock_loss or winless_2 or h2h_hum)



        return {

            "is_clinical": is_clinical,

            "is_fortress": is_fortress,

            "is_homesick": is_homesick,

            "is_ht_killer": is_ht_killer,

            "is_brick_wall": is_brick_wall,

            "is_glass_jaw": is_glass_jaw,

            "is_ht_vulnerable": is_ht_vulnerable,

            "is_wounded": is_wounded,

            "is_winless_5": is_winless_5,

            "avg_sot": round(avg_sot, 1),

            "avg_bcc": round(avg_bcc, 1),

            "avg_conc": round(avg_conc, 2)

        }



    # ---------------------------------------------------------

    # ⚖️ THE 100-POINT WIN SYNDICATE ENGINE

    # ---------------------------------------------------------

    def calculate_win_score(team_traits, opp_traits, team_spear, opp_spear, is_home):

        score = 0

        reasons =[]



        # --- POSITIVE POINTS (Lethality) ---

        if team_traits["is_clinical"]: score += 15; reasons.append("🎯 Clinical (+15)")

        if team_traits["is_fortress"]: score += 15; reasons.append("🏰 Fortress (+15)")

        if team_traits["is_ht_killer"]: score += 15; reasons.append("⚡ 1H Killer (+15)")

        if team_traits["is_wounded"]: score += 15; reasons.append("🩸 Wounded (+15)")

        if team_traits["is_ht_killer"] and opp_traits["is_ht_vulnerable"]: score += 10; reasons.append("⏱️ Early Kill (+10)")



        # --- ⚔️ THE SPEAR POWER BOOST ---

        if team_spear > 65.0: score += 15; reasons.append(f"🔥 Elite Scorer {team_spear}% (+15)")

        elif team_spear > 50.0: score += 5; reasons.append(f"⚔️ Active Scorer {team_spear}% (+5)")



        # --- THE OPPONENT VETOES ---

        if opp_spear > 75.0 and team_spear > 75.0:

            score -= 30; reasons.append(f"🛑 Shootout Threat {opp_spear}% (-30)")



        if team_spear > opp_spear:

            score += 20; reasons.append("⚔️ Superior Spear Power (+20)")

            if (team_spear - opp_spear) >= 15.0:

                score += 10; reasons.append("🔥 Massive Spear Gap (+10)")



        if opp_traits["is_brick_wall"]: score -= 25; reasons.append("🧱 Brick Wall (-25)")

        if opp_traits["is_glass_jaw"] and opp_spear < 40.0: score += 20; reasons.append("🔨 Glass Jaw (+20)")



        # Symmetrical Check: If opponent hasn't won in 5 games, they are dangerous

        if opp_traits["is_winless_5"]: score -= 20; reasons.append("🐾 Cornered Animal (-20)")



        # --- ✈️ THE REDUCED AWAY TEAM TRAPS ---

        if not is_home:

            # Only penalize if they specifically struggle away (0-2 wins)

            if team_traits["is_homesick"]: score -= 10; reasons.append("✈️ Homesick Penalty (-10)")

            if opp_spear > 55.0: score -= 15; reasons.append("🌋 Hostile Crowd (-15)")



        if not reasons: reasons.append("No triggers met")

        return score, reasons



    # ---------------------------------------------------------

    # 🚀 MAIN EXECUTION (THE MASTER & AUDITOR)

    # ---------------------------------------------------------

    print(f"\n>> [AlienEdge WIN ENGINE] Initializing Symmetrical Dual-Spear Protocol... ({TODAY_STR})")



    raw_data =[]

    if not os.path.exists(INPUT_FILE):

        print(f"🛑 FATAL ERROR: {INPUT_FILE} not found. Please run Code 1 first.")

        return[]



    try:

        df_in = pd.read_csv(INPUT_FILE)

        grouped = df_in.groupby('fixture_id')

        for fid, group in grouped:

            fix_name = group.iloc[0]['fixture']



            h_row = group[group['side'] == 'home']

            a_row = group[group['side'] == 'away']



            h_poisson = float(str(h_row.iloc[0]['poisson_win_prob']).replace('%','')) if not h_row.empty else 0.0

            a_poisson = float(str(a_row.iloc[0]['poisson_win_prob']).replace('%','')) if not a_row.empty else 0.0



            raw_data.append({

                "fixture_id": fid,

                "fixture_name": fix_name,

                "h_poisson": h_poisson,

                "a_poisson": a_poisson

            })

    except Exception as e:

        print(f"🛑 Error reading {INPUT_FILE}: {e}")

        return[]



    cat_db = {}

    if os.path.exists(FILE_CATALYST):

        try:

            cat_csv = pd.read_csv(FILE_CATALYST)

            for _, row in cat_csv.iterrows():

                try:

                    fix_key = get_match_key(str(row['fixture']))

                    dog_name = str(row['underdog_team'])

                    dog_prob = float(str(row['Audit_Real_Prob']).replace('%', '').strip())

                    fav_prob = float(str(row['Fav_Spear_Power']).replace('%', '').strip())

                    cat_db[fix_key] = {"dog_name": dog_name, "dog_prob": dog_prob, "fav_prob": fav_prob}

                except: continue

        except: pass



    todays_fixtures_map = {}

    print("   🔍 Fetching API IDs to link with your CSV (Unlimited Pagination)...")

    page = 1

    while True:

        resp = GET(f"/fixtures/date/{TODAY_STR}", params={"include": "participants", "per_page": 50, "page": page})

        data = resp.get("data",[])

        if not data: break

        for fx in data:

            parts = fx.get("participants",[])

            h = next((p for p in parts if p.get('meta', {}).get('location') == 'home'), None)

            a = next((p for p in parts if p.get('meta', {}).get('location') == 'away'), None)

            if h and a: todays_fixtures_map[fx['id']] = {"hid": h['id'], "aid": a['id']}

        page += 1

        time.sleep(REQUEST_DELAY)



    processed_list =[]

    for match in raw_data:

        try:

            fid = match["fixture_id"]

            fix_name = match["fixture_name"]



            if fid not in todays_fixtures_map: continue



            home_id = todays_fixtures_map[fid]["hid"]

            away_id = todays_fixtures_map[fid]["aid"]

            home_name = fix_name.split(" vs ")[0] if " vs " in fix_name else "Home"

            away_name = fix_name.split(" vs ")[1] if " vs " in fix_name else "Away"



            cat_info = cat_db.get(get_match_key(fix_name), {})

            dog_name = cat_info.get("dog_name", "")



            if clean_n(home_name) == clean_n(dog_name):

                h_spear = cat_info.get("dog_prob", 0.0)

                a_spear = cat_info.get("fav_prob", 0.0)

            else:

                h_spear = cat_info.get("fav_prob", 0.0)

                a_spear = cat_info.get("dog_prob", 0.0)



            h_traits = analyze_win_tactics(home_id, "home", away_id, fid)

            a_traits = analyze_win_tactics(away_id, "away", home_id, fid)



            # ⚖️ SYMMETRICAL AUDIT SCORES

            h_base_score, h_reasons = calculate_win_score(h_traits, a_traits, h_spear, a_spear, True)

            a_base_score, a_reasons = calculate_win_score(a_traits, h_traits, a_spear, h_spear, False)



            net_h_score = h_base_score - a_base_score

            net_a_score = a_base_score - h_base_score



            h_poisson = match["h_poisson"]

            a_poisson = match["a_poisson"]



            if h_poisson > a_poisson: base_pick, base_prob = home_name, h_poisson

            elif a_poisson > h_poisson: base_pick, base_prob = away_name, a_poisson

            else: base_pick, base_prob = "TIE", h_poisson



            # 🛑 OVERTURN GATEKEEPER

            poisson_gap = abs(h_poisson - a_poisson)



            if net_h_score >= 20 and net_h_score > net_a_score:

                audit_raw_winner = home_name

                win_net_score = net_h_score

                win_reasons = h_reasons

                new_spear = h_spear

                old_spear = a_spear

            elif net_a_score >= 20 and net_a_score > net_h_score:

                audit_raw_winner = away_name

                win_net_score = net_a_score

                win_reasons = a_reasons

                new_spear = a_spear

                old_spear = h_spear

            else:

                audit_raw_winner = "TIE / AVOID"

                win_net_score = max(net_h_score, net_a_score)

                win_reasons = h_reasons if net_h_score >= net_a_score else a_reasons



            audit_winner = audit_raw_winner

            if audit_raw_winner != base_pick and audit_raw_winner != "TIE / AVOID" and base_pick != "TIE":

                if poisson_gap < 15.0 and (new_spear - old_spear) > 10.0:

                    pass

                else:

                    audit_winner = "TIE / AVOID"



            if audit_winner == base_pick and audit_winner != "TIE / AVOID":

                tier = "💎 SYNDICATE LOCK (Verified)" if win_net_score >= 45 else "🔥 SOLID WIN (Verified)"

            elif audit_winner != "TIE / AVOID":

                tier = f"🚨 OVERTURNED (Auditor prefers {audit_winner})"

            else:

                tier = "🛑 CAUTION: TRAP (Code 1 Pick Avoided)"



            processed_list.append({

                "Fixture": fix_name,

                "Master_Pick": base_pick,

                "Master_Prob": f"{base_prob}%",

                "Audit_Score": win_net_score,

                "H_Base": h_base_score,

                "A_Base": a_base_score,

                "Tier": tier,

                "Spears": f"H:{h_spear}% | A:{a_spear}%",

                "Home_Logic": " | ".join(h_reasons),

                "Away_Logic": " | ".join(a_reasons)

            })



            print(f" > Audited {fix_name[:30]:<30} | H: {h_base_score:>3} | A: {a_base_score:>3} | Net: {win_net_score:>+4} | {tier}")



        except Exception as e:

            continue



    # ---------------------------------------------------------

    # 🏆 FINAL ALIENEDGE WIN PRINTS

    # ---------------------------------------------------------

    final_table = pd.DataFrame(processed_list)

    if final_table.empty: 

        print("\n>>[FATAL ERROR] No matches processed.")

        return[]



    final_table = final_table.sort_values(by=["Audit_Score"], ascending=False)



    diamond_df = final_table[final_table['Tier'].str.contains("💎")]

    solid_df = final_table[final_table['Tier'].str.contains("🔥")]

    overturned_df = final_table[final_table['Tier'].str.contains("🚨")]



    print("\n" + "💎"*40)

    print(" 💎 THE ALIENEDGE VERIFIED LOCKS 💎")

    print("💎"*40)

    print("   Code 1 picked them, and Code 2 verified they have a MASSIVE Net Score Gap.\n")

    if not diamond_df.empty:

        for i, (_, row) in enumerate(diamond_df.iterrows(), 1):

            print(f"{i}. {row['Fixture']} -> 🏆 BET: {row['Master_Pick']} (Poisson: {row['Master_Prob']} | Net Score: +{row['Audit_Score']})")

            print(f"   * Home Logic: {row['Home_Logic']}")

            print(f"   * Away Logic: {row['Away_Logic']}\n")

    else: print("   [!] No Verified Diamond Locks found today.\n")



    print("\n" + "🔥"*40)

    print(" 🔥 SOLID VERIFIED WINS 🔥")

    print("🔥"*40)

    if not solid_df.empty:

        for i, (_, row) in enumerate(solid_df.iterrows(), 1):

            print(f"{i}. {row['Fixture']} -> 🏆 BET: {row['Master_Pick']} (Poisson: {row['Master_Prob']} | Net Score: +{row['Audit_Score']})")

            print(f"   * Home Logic: {row['Home_Logic']}")

            print(f"   * Away Logic: {row['Away_Logic']}\n")

    else: print("   [!] No Solid Verified Wins found today.\n")



    print("\n" + "🚨"*40)

    print(" 🚨 OVERTURNED BY AUDITOR (The Spear Mismatch) 🚨")

    print("🚨"*40)

    print("   Code 1 picked a winner, but Code 2 discovered the other team has massive Spear Power.\n")

    if not overturned_df.empty:

        for i, (_, row) in enumerate(overturned_df.iterrows(), 1):

            print(f"{i}. {row['Fixture']} -> 🛑 CODE 1 PICKED: {row['Master_Pick']} ({row['Master_Prob']})")

            print(f"   * {row['Tier']} (Net Score: +{row['Audit_Score']})")

            print(f"   * Home Logic: {row['Home_Logic']}")

            print(f"   * Away Logic: {row['Away_Logic']}\n")

    else: print("   [!] No matches overturned today.\n")



    print("\n" + "="*140)

    print("📊 FULL WIN FORENSIC BOARD (Shows Master vs Auditor Net Score)")

    print("="*140)



    cols =["Fixture", "Master_Pick", "Master_Prob", "H_Base", "A_Base", "Audit_Score", "Tier", "Spears", "Home_Logic", "Away_Logic"]

    print(final_table[cols].to_string(index=False))



    final_table.to_csv(OUTPUT_CSV, index=False)

    print(f"\n💾 [Done] AlienEdge Win Predictions saved to: {OUTPUT_CSV}")

    

    return final_table.to_dict(orient="records")



# --- LOCAL TESTING BLOCK ---#

if __name__ == "__main__":

    pd.set_option('display.max_rows', None)

    pd.set_option('display.width', 1000)

    run_win_psychology_engine()