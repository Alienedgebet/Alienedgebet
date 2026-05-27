import os

import sys

import time

import json

import requests

from datetime import datetime, timedelta, timezone

from collections import defaultdict, Counter



import numpy as np

import pandas as pd

from sklearn.cluster import KMeans

from sklearn.preprocessing import StandardScaler

from dotenv import load_dotenv



# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---

load_dotenv()



# --- 2. DYNAMIC PATHS FOR SERVERS ---

# This ensures the aggregator finds the files in the correct folders

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUTPUT_DIR = os.path.join(BASE_DIR, "output")

DATA_DIR = os.path.join(BASE_DIR, "data")



# ==============================================================================

# 📦 THE BLACK BOX WRAPPER (CALLABLE BY THE MASTER API/SCHEDULER)

# ==============================================================================

def run_corner3_psychology_engine(target_date=None):

    """

    Executes the AlienEdge Corner Tactical Brain (Psychology Engine).

    Reads the base JSON, clusters tactical styles, and identifies Wounded Beasts.

    """

    # Ensure directories exist

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    os.makedirs(DATA_DIR, exist_ok=True)



    # ==============================================================================

    # 1. CONFIGURATION

    # ==============================================================================

    API_KEY = os.getenv("SPORTMONKS_API_KEY") or "hD4F4FIFwNW5BxKa6Y0fCCLtB0KkiNRxtULDdsrO3VPss1IMV4HJihBkxwI4"

    if not API_KEY:

        print("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")

        return[]



    BASE_URL = "https://api.sportmonks.com/v3/football"



    # --- DYNAMIC FILE PATHING ---

    INPUT_FILE = os.path.join(OUTPUT_DIR, "backend_2_output.json")

    OUTPUT_FILE = os.path.join(OUTPUT_DIR, "tactical_brain_output.json")



    REQUEST_DELAY = 0.3

    LAST_N = 3

    LOOKBACK_DAYS = 365

    KMEANS_N_CLUSTERS = 4



    # ==============================================================================

    # 🛡️ BULLETPROOF API HELPER & CACHE SYSTEM (STRICTLY PRESERVED)

    # ==============================================================================

    API_CACHE = {}

    STANDINGS_CACHE = {}



    def GET(path, params=None):

        if params is None: params = {}

        params.setdefault("api_token", API_KEY)



        # Cache key creation

        cache_key = path + "?" + "&".join([f"{k}={v}" for k, v in sorted(params.items()) if k != "api_token"])

        if cache_key in API_CACHE:

            return API_CACHE[cache_key]



        backoff = 3.0

        while True:

            try:

                resp = requests.get(f"{BASE_URL}{path}", params=params, timeout=30)

                if resp.status_code == 200:

                    data = resp.json()

                    API_CACHE[cache_key] = data

                    time.sleep(REQUEST_DELAY)

                    return data

                elif resp.status_code == 429:

                    print(f"   [!] API Rate Limit Hit (429). Cooling down...")

                    time.sleep(backoff)

                    backoff = min(backoff * 1.5, 60.0)

                    continue

                else:

                    return {"data":[]}

            except Exception as e:

                time.sleep(3)

                return {"data":[]}



    # ==============================================================================

    # 📊 LEAGUE TABLE LOGIC (STRICT TRANSPLANT FROM YOUR GG CODE)

    # ==============================================================================



    def get_league_standings_map(league_id, season_id):

        """

        UPGRADED: Uses the exact GG method.

        Bypasses the broken League endpoint by taking season_id directly from the match.

        """

        if not league_id or league_id == "Unknown" or not season_id:

            return {}



        cache_key = f"{league_id}_{season_id}"

        if cache_key in STANDINGS_CACHE:

            return STANDINGS_CACHE[cache_key]



        standings_resp = GET(f"/standings/seasons/{season_id}", params={"filters": f"standingLeagues:{league_id}"})

        standings_list = standings_resp.get("data", [])



        pos_map = {int(s["participant_id"]): int(s["position"]) for s in standings_list if s.get("participant_id") and s.get("position")}



        STANDINGS_CACHE[cache_key] = pos_map

        return pos_map



    def apply_positional_rules(h_pos, a_pos):

        """

        Forensic implementation of your 3 specific rules.

        Positions: 1 is top, 20 is bottom.

        """

        if not h_pos or not a_pos or h_pos >= 99 or a_pos >= 99:

            return "⚖️ UNRANKED", 0



        gap = abs(h_pos - a_pos)



        # RULE 1: Both teams ranked above 10th (11, 12, 13...) are DEAD

        if h_pos > 10 and a_pos > 10:

            return "💀 DEAD / UNDER", gap



        # RULE 2: Teams next to each other (Gap = 1) are AVOID

        if gap == 1:

            return "🛑 AVOID / UNDER", gap



        # RULE 3: One is Top 10, other is Bottom Half. If Gap > 5: DEAD

        is_h_top10 = (h_pos <= 10)

        is_a_top10 = (a_pos <= 10)

        if (is_h_top10 != is_a_top10) and gap > 5:

            return "💀 DEAD / UNDER", gap



        # RULE 4: Both are Top 10 (and not neighbors)

        if is_h_top10 and is_a_top10 and gap > 1:

            return "💎 PERFECT", gap



        return "📊 STABLE", gap



    # ==============================================================================

    # 🧠 TACTICAL PROFILING & KEY STATS (UNTOUCHED & PRESERVED)

    # ==============================================================================

    KEY_STATS =[

        "Ball Possession %", "Successful Passes Percentage", "Passes", "Long Passes",

        "Shots Total", "Shots On Target", "Shots Insidebox", "Big Chances Created",

        "Attacks", "Dangerous Attacks", "Key Passes", "Total Crosses",

        "Accurate Crosses", "Tackles", "Duels Won", "Interceptions", "Saves",

        "Successful Dribbles Percentage", "Goals"

    ]



    def get_team_history(team_id):

        end_dt = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()

        start_dt = (datetime.now(timezone.utc).date() - timedelta(days=LOOKBACK_DAYS)).isoformat()

        params = {

            "include": "statistics;statistics.type",

            "filters": "fixtureStates:5",

            "sortBy": "starting_at",

            "order": "desc",

            "per_page": LAST_N

        }

        return GET(f"/fixtures/between/{start_dt}/{end_dt}/{team_id}", params=params).get("data",[])



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

                s_val = s.get("data", {}).get("value") if isinstance(s.get("data"), dict) else s.get("value")

                s_name = normalize_stat_name(s_name_raw)

                if s_name and s_val is not None:

                    try:

                        val = float(str(s_val).replace('%', '').strip())

                        sums[s_name] += val; counts[s_name] += 1

                    except: pass

        return {stat: (round(sums[stat] / counts[stat], 2) if counts[stat] > 0 else 0.0) for stat in KEY_STATS}



    def check_defensive_thresholds(avg):

        t = {"Tackles": 14, "Interceptions": 8, "Duels Won": 40}

        passes = sum(1 for k, v in t.items() if avg.get(k, 0) >= v)

        if avg.get("Shots On Target", 0) < 3.5: passes += 1

        return (["Defensive"], f"Passed {passes}/4 defensive rules") if passes >= 3 else ([], "")



    def check_attacking_thresholds(avg):

        t = {"Attacks": 60, "Dangerous Attacks": 40, "Shots On Target": 3.5}

        passes = sum(1 for k, v in t.items() if avg.get(k, 0) >= v)

        return (["Attacking"], f"Passed {passes}/3 attacking rules") if passes >= 2 else ([], "")



    def check_possession_thresholds(avg):

        if avg.get("Ball Possession %", 0) >= 58 and avg.get("Successful Passes Percentage", 0) >= 80:

            return ["Possession-Oriented"], "High control identified"

        return[], ""



    def check_crossing_thresholds(avg):

        if avg.get("Total Crosses", 0) >= 15 or avg.get("Accurate Crosses", 0) >= 4:

            return["Crossing/Counter"], "Wing-heavy pattern found"

        return[], ""



    def assign_intelligence_grade(h_styles, a_styles):

        h_str = " ".join(h_styles); a_str = " ".join(a_styles)

        if ("Crossing/Counter" in h_str and "Defensive" in a_str):

            return "HIGH", "Wide Attacker vs Low Block: Maximum Corner Potential"

        if "Attacking" in h_str and "Attacking" in a_str:

            return "STRONG", "End-to-End Attacking: High Shot Volume Expected"

        if "Crossing/Counter" in h_str or "Crossing/Counter" in a_str:

            return "STRONG", "High Crossing Volume Identified"

        if "Possession-Oriented" in h_str and "Possession-Oriented" in a_str:

            return "LOW", "Tiki-Taka Trap: Teams likely to walk ball into net"

        return "MEDIUM", "Balanced Matchup: Standard Statistical Probability"



    # ==============================================================================

    # 5. 🩸 WOUNDED BEAST ENGINE (UNTOUCHED & PRESERVED)

    # ==============================================================================



    def extract_final_goals(scores_list):

        h, a = None, None

        for entry in (scores_list or[]):

            if not isinstance(entry, dict): continue

            s_obj = entry.get("score") or entry

            if str(s_obj.get("description")).upper() in["CURRENT", "FT", "FULL_TIME"]:

                p, g = s_obj.get("participant"), s_obj.get("goals")

                if g is not None:

                    if p == "home": h = max(h or 0, int(g))

                    elif p == "away": a = max(a or 0, int(g))

        return h, a



    def get_match_outcome(fx, team_id):

        hg, ag = extract_final_goals(fx.get("scores",[]))

        if hg is None or ag is None: return None

        is_home = any(str(p.get("id")) == str(team_id) and p.get("meta", {}).get("location") == "home" for p in fx.get("participants",[]))

        scored, conceded = (hg, ag) if is_home else (ag, hg)

        if scored > conceded: return "W"

        if scored < conceded: return "L"

        return "D"



    def check_wounded_beast(team_id, opp_id, current_match_id):

        end = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        start = (datetime.now(timezone.utc) - timedelta(days=180)).strftime("%Y-%m-%d")

        data = GET(f"/fixtures/between/{start}/{end}/{team_id}", params={"include":"scores;participants", "per_page": 10, "order":"desc", "filters":"fixtureStates:5"})

        fixtures = data.get("data",[])

        history =[f for f in fixtures if str(f.get('id')) != str(current_match_id)][:2]

        outcomes =[get_match_outcome(f, team_id) for f in history]

        shock_loss = len(outcomes) > 0 and outcomes[0] == "L"

        winless_drought = len(outcomes) >= 2 and outcomes[0] != "W" and outcomes[1] != "W"

        h2h_data = GET(f"/fixtures/head-to-head/{team_id}/{opp_id}", params={"include":"scores;participants", "per_page": 5, "order":"desc"})

        past_h2h =[h for h in h2h_data.get("data", []) if str(h.get('id')) != str(current_match_id) and h.get('state_id') == 5]

        h2h_hum = (past_h2h and get_match_outcome(past_h2h[0], team_id) == "L")

        return {"is_wounded": (shock_loss or winless_drought or h2h_hum), "shock_loss": shock_loss, "winless_drought": winless_drought, "h2h_humiliation": h2h_hum}



    # ==============================================================================

    # 6. ML CLUSTERING ENGINE (UNTOUCHED & PRESERVED)

    # ==============================================================================



    def run_clustering(teams_avgs):

        if len(teams_avgs) < 2: return None, None

        feats =["Attacks", "Dangerous Attacks", "Shots On Target", "Ball Possession %", "Total Crosses", "Tackles"]

        rows, names = [],[]

        for name, avg in teams_avgs.items():

            rows.append([avg.get(f, 0.0) for f in feats]); names.append(name)

        df = pd.DataFrame(rows, columns=feats, index=names)

        scaler = StandardScaler()

        X = scaler.fit_transform(df.values)

        kmeans = KMeans(n_clusters=min(KMEANS_N_CLUSTERS, len(df)), random_state=42, n_init=10).fit(X)

        df["cluster"] = kmeans.labels_

        centroids = pd.DataFrame(scaler.inverse_transform(kmeans.cluster_centers_), columns=feats)

        return df, centroids



    def describe_cluster_centroid(centroid):

        if centroid.get("Total Crosses", 0) > 15: return["Crossing/Counter"]

        if centroid.get("Ball Possession %", 0) > 55: return["Possession-Oriented"]

        return ["Balanced"]



    # ==============================================================================

    # 7. MAIN LOGIC (THE MASTER HARVEST)

    # ==============================================================================



    if not os.path.exists(INPUT_FILE):

        print(f"🛑 Error: {INPUT_FILE} missing. Ensure Code 1 or 2 ran first.")

        return[]



    try:

        with open(INPUT_FILE, "r") as f: 

            corner_picks = json.load(f)

    except Exception as e:

        print(f"🛑 Error reading {INPUT_FILE}: {e}")

        return []



    print(f"\n🧠 Tactical Brain[Vortex Edition]: Auditing {len(corner_picks)} matches...")



    # Step 1: Pre-resolve Fixtures and Team IDs

    fixture_map, team_data = {}, {}

    for pick in corner_picks:

        fid = pick.get('fixture_id')

        fx_resp = GET(f"/fixtures/{fid}", params={"include": "participants"})

        data = fx_resp.get("data")

        if data:

            parts = data.get("participants",[])

            h = next((p for p in parts if p.get('meta', {}).get('location') == 'home'), parts[0])

            a = next((p for p in parts if p.get('meta', {}).get('location') == 'away'), parts[1])

            fixture_map[fid] = {

                "hid": h['id'], "aid": a['id'],

                "hname": h['name'], "aname": a['name'],

                "lid": data.get("league_id"),

                "sid": data.get("season_id")

            }

            team_data[h['id']] = h['name']; team_data[a['id']] = a['name']



    # Step 2: Team Stylistic Profiling

    teams_averages, team_styles = {}, {}

    for tid, tname in team_data.items():

        print(f" Profiling {tname}...")

        avg = compute_team_averages_for_team(tid)

        if avg:

            teams_averages[tname] = avg

            styles = []

            for func in[check_defensive_thresholds, check_attacking_thresholds, check_possession_thresholds, check_crossing_thresholds]:

                s, _ = func(avg)

                if s: styles.extend(s)

            team_styles[tname] = styles if styles else ["Balanced"]



    # Step 3: ML Clustering Refinement

    balanced = {t: avg for t, avg in teams_averages.items() if team_styles.get(t) == ["Balanced"]}

    if len(balanced) >= 2:

        c_df, centroids = run_clustering(balanced)

        if c_df is not None:

            for tname, row in c_df.iterrows():

                team_styles[tname] = describe_cluster_centroid(centroids.loc[int(row['cluster'])])



    # Step 4: Final Forensic Merge

    final_output =[]

    print(f"\n{'-'*110}\n{'Match':<35} | {'H/A Pos':<10} | {'Friction':<20} | {'Wounded'}\n{'-'*110}")



    for pick in corner_picks:

        fid = pick.get('fixture_id')

        if fid in fixture_map:

            f_info = fixture_map[fid]

            hid, aid, lid, sid = f_info['hid'], f_info['aid'], f_info['lid'], f_info['sid']



            # Standings Fetch

            pos_map = get_league_standings_map(lid, sid)

            h_pos, a_pos = pos_map.get(int(hid), 99), pos_map.get(int(aid), 99)

            friction_label, gap = apply_positional_rules(h_pos, a_pos)



            # Style & Wounded Logic

            h_styles, a_styles = team_styles.get(f_info['hname'],["Unknown"]), team_styles.get(f_info['aname'], ["Unknown"])

            grade, note = assign_intelligence_grade(h_styles, a_styles)



            diff = float(pick.get("diff", 0.0))

            fav_id, opp_id, fav_name = (hid, aid, "Home") if diff >= 1.0 else (aid, hid, "Away") if diff <= -1.0 else (None, None, "None")



            wounded_data = {"is_wounded_beast": False, "wounded_reason": "None", "wounded_team_name": "None"}

            if fav_id:

                flags = check_wounded_beast(fav_id, opp_id, fid)

                if flags["is_wounded"]:

                    reasons =[r for r, f in[("Shock Loss", flags["shock_loss"]), ("Winless Drought", flags["winless_drought"]), ("H2H Humiliation", flags["h2h_humiliation"])] if f]

                    wounded_data = {"is_wounded_beast": True, "wounded_reason": " + ".join(reasons), "wounded_team_name": f_info['hname'] if fav_name == "Home" else f_info['aname']}



            pick.update({

                "home_id": hid, "away_id": aid, "home_style": h_styles, "away_style": a_styles,

                "tactical_intelligence_grade": grade, "tactical_note": note,

                "home_position": h_pos, "away_position": a_pos, "friction_grade": friction_label, "standings_gap": gap,

                "is_wounded_beast": wounded_data["is_wounded_beast"], "wounded_reason": wounded_data["wounded_reason"], "wounded_team_name": wounded_data["wounded_team_name"]

            })

            print(f"{pick.get('fixture_name', 'Unknown')[:35]:<35} | {h_pos}v{a_pos:<5} | {friction_label:<20} | {'YES 🩸' if wounded_data['is_wounded_beast'] else 'No'}")



        final_output.append(pick)



    # Save to dynamically routed output folder

    with open(OUTPUT_FILE, "w") as f: 

        json.dump(final_output, f, indent=2)

        

    print(f"\n✅ SUCCESS: Full Tactical Audit saved to {OUTPUT_FILE}")



    # Return data to the master orchestrator

    return final_output



# --- LOCAL TESTING BLOCK ---#

if __name__ == "__main__":

    run_corner3_psychology_engine()