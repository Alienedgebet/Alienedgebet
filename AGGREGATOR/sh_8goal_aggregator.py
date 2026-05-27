import os
import sys
import time
import json
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
from dotenv import load_dotenv
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS ---
# This ensures all engines look in the same "data" and "output" folders
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

# ==============================================================================
# 📦 THE BLACK BOX WRAPPER (CALLABLE BY THE MASTER API/SCHEDULER)
# ==============================================================================
def run_sh_gg_8goal_aggregator(target_date):
    """
    Executes the SH/GG/Winner 8-Goal Filter Aggregator.
    Reads the output from the SH/GG engine and applies the rigorous
    8+ goals in last 5 matches rule from the Gold Over 2.5 engine.
    """
    # Ensure directories exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    # -------------------------
    # ⚙️ CONFIGURATION
    # -------------------------
    API_TOKEN = os.getenv("SPORTMONKS_API_KEY") or "hD4F4FIFwNW5BxKa6Y0fCCLtB0KkiNRxtULDdsrO3VPss1IMV4HJihBkxwI4"
    INPUT_FEED_FILE = os.path.join(OUTPUT_DIR, "sh_gg_winner_feed.json")
    OUTPUT_CSV_FILE = os.path.join(OUTPUT_DIR, f"FINAL_SH_GG_8GOAL_{target_date}.csv")
    REQ_DELAY = 0.2

    if not API_TOKEN:
        print("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")
        return[]

    # -------------------------
    # 🛠️ UTILITIES & API LOGIC (IMPORTED FROM GOLD ENGINE)
    # -------------------------
    def GET(endpoint, params=None):
        if params is None: params = {}
        params['api_token'] = API_TOKEN
        url = f"https://api.sportmonks.com/v3/football{endpoint}"
        for attempt in range(3):
            try:
                r = requests.get(url, params=params, timeout=20)
                if r.status_code == 200: return r.json()
                time.sleep(1)
            except:
                time.sleep(1)
        return {"data":[]}

    def get_scores_ht_ft(scores_list):
        """
        Safely handles both past and future matches. 
        If unplayed, defaults to 0-0.
        """
        h_ht, a_ht = 0, 0
        h_ft, a_ft = 0, 0
        
        if not scores_list:
            return (None, None), (None, None)

        for s in scores_list:
            desc = s.get("description", "")
            if "score" in s:
                p = s["score"].get("participant")
                g = int(s["score"].get("goals", 0))
            else:
                p = s.get("participant")
                g = int(s.get("goals", 0))

            if desc == "1ST_HALF":
                if p == "home": h_ht = g
                elif p == "away": a_ht = g

            if desc == "CURRENT" or desc == "2ND_HALF":
                if p == "home": h_ft = g
                elif p == "away": a_ft = g

        return (h_ht, a_ht), (h_ft, a_ft)

    def check_recent_form_math(team_id, team_name):
        """
        Retrieves the last 5 matches and calculates total goals scored by the team.
        Safely anchored to target_date to support backtesting.
        """
        end = target_date
        start = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=120)).strftime("%Y-%m-%d")

        params = {
            "include": "participants;scores",
            "per_page": 5,
            "filters": "fixtureStates:5",
            "order": "desc"
        }
        resp = GET(f"/fixtures/between/{start}/{end}/{team_id}", params=params)
        matches = resp.get("data",[])

        if not matches: return 0, 0, 0 

        games_with_2h_activity = 0
        total_team_goals = 0

        for m in matches:
            (h_ht, a_ht), (h_ft, a_ft) = get_scores_ht_ft(m.get("scores",[]))
            if h_ft is None: continue

            h_goals_2h = h_ft - h_ht
            a_goals_2h = a_ft - a_ht
            total_goals_2h = h_goals_2h + a_goals_2h

            if total_goals_2h > 0:
                games_with_2h_activity += 1

            team_was_home = True
            parts = m.get("participants",[])
            for i, p in enumerate(parts):
                if str(p.get("id")) == str(team_id):
                    loc = p.get("meta", {}).get("location", "")
                    if loc == "away":
                        team_was_home = False
                    elif loc == "":
                        if i == 1: team_was_home = False
                    break

            if team_was_home: total_team_goals += h_ft
            else: total_team_goals += a_ft

        total = len(matches)
        pct_activity = (games_with_2h_activity / total * 100) if total > 0 else 0

        return pct_activity, total, total_team_goals

    # -------------------------
    # 🚀 AGGREGATOR EXECUTION
    # -------------------------
    print(f"\n" + "="*145)
    print(f" 🚀 ALIENEDGE SH/GG 8-GOAL AGGREGATOR | DATE: {target_date} ")
    print("="*145)

    # 1. LOAD THE SH/GG/WINNER FEED
    if not os.path.exists(INPUT_FEED_FILE):
        print(f"[⚠️] Feed file {INPUT_FEED_FILE} not found. Ensure the SH/GG engine has run first.")
        return[]

    try:
        with open(INPUT_FEED_FILE, "r") as f:
            feed_data = json.load(f)
        print(f"[✅] Loaded {len(feed_data)} raw fixtures from {INPUT_FEED_FILE}")
    except Exception as e:
        print(f"[CRITICAL] Failed to parse JSON feed: {e}")
        return[]

    if not feed_data:
        print("[!] Feed is empty. No matches to process.")
        return[]

    # 2. APPLY THE 8-GOAL ATTACK FILTER
    approved_matches = []
    print(f"[INFO] Running 8-Goal Attack verification on {len(feed_data)} matches...\n")

    for item in feed_data:
        fid = item.get("fixture_id", "N/A")
        league_name = item.get("league", "Unknown")
        match_time = item.get("kickoff_datetime", "Unknown")
        
        home_team = item.get("teams", {}).get("home", {})
        away_team = item.get("teams", {}).get("away", {})
        
        h_id, h_name = str(home_team.get("id", "")), home_team.get("name", "Unknown")
        a_id, a_name = str(away_team.get("id", "")), away_team.get("name", "Unknown")
        
        pick_labels = item.get("pick_labels",[])
        labels_str = " | ".join(pick_labels)

        if not h_id or not a_id: continue

        # Fetch Goals utilizing Gold Engine logic
        h_2h_act, h_tot, h_goals = check_recent_form_math(h_id, h_name)
        time.sleep(REQ_DELAY)
        a_2h_act, a_tot, a_goals = check_recent_form_math(a_id, a_name)
        time.sleep(REQ_DELAY)

        # 🚨 THE CRUCIBLE: BOTH TEAMS MUST HAVE 8+ GOALS IN LAST 5
        if h_goals >= 8 and a_goals >= 8:
            print(f"✅ APPROVED -> {h_name} ({h_goals}G) vs {a_name} ({a_goals}G) | {labels_str}")
            
            approved_matches.append({
                "Fixture_ID": fid,
                "League": league_name,
                "Time": match_time,
                "Fixture": f"{h_name} vs {a_name}",
                "H_Goals_L5": h_goals,
                "A_Goals_L5": a_goals,
                "Labels": labels_str,
                "Status": "🔥 8+ Goals Verified"
            })
        else:
            print(f"❌ REJECTED -> {h_name} ({h_goals}G) vs {a_name} ({a_goals}G) | Insufficient goals.")

    # 3. OUTPUT GENERATION
    print("\n\n" + "★"*145)
    print(f" 🏆 ALIENEDGE ELITE SH/GG POOL: 8-GOAL FILTER PASSED ")
    print("★"*145)

    if not approved_matches:
        print("   No matches survived the 8-goal filter today. Market is tight.")
        return[]

    df_final = pd.DataFrame(approved_matches)
    
    # Save the Finalized Dataframe for the master alert system
    df_final.to_csv(OUTPUT_CSV_FILE, index=False)
    
    # Console Pretty Print
    print(df_final.drop(columns=['Fixture_ID']).to_string(index=False))
    print(f"\n[✅] Saved {len(approved_matches)} Elite matches to {OUTPUT_CSV_FILE}")

    return approved_matches

# ==============================================================================
# IF RUN DIRECTLY (TESTING)
# ==============================================================================
if __name__ == "__main__":
    # Pandas display options for terminal
    pd.set_option('display.max_rows', None)
    pd.set_option('display.width', 1000)
    
    # Grab target date from system
    test_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    run_sh_gg_8goal_aggregator(test_date)