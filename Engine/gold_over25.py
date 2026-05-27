import os
import sys
import json
import time
import argparse
import requests
from datetime import datetime, timedelta

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
def run_gold_over_25_engine(target_date):
    """
    Executes the Gold Over 2.5 Engine.
    All logic, filters, and H2H strict checks
    are 100% untouched and preserved from the original back-end.
    """
    # Ensure directories exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    # -------------------------
    # CONFIG (100% UNTOUCHED LOGIC)
    # -------------------------
    API_TOKEN = os.getenv("SPORTMONKS_API_KEY") or "hD4F4FIFwNW5BxKa6Y0fCCLtB0KkiNRxtULDdsrO3VPss1IMV4HJihBkxwI4"
    CHECK_DATE = target_date
    MIN_H2H_GAMES = 2
    REQ_DELAY = 0.2
    OUTPUT_FILE = os.path.join(OUTPUT_DIR, "gold_over_25_feed.json")

    if not API_TOKEN:
        print("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")
        return[]

    # ==============================================================================
    # 2. UTILS (100% UNTOUCHED)
    # ==============================================================================
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

    # ==============================================================================
    # 3. ANALYSIS ENGINES (ORIGINAL LOGIC - UNTOUCHED)
    # ==============================================================================
    def check_recent_form_math(team_id, team_name):
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")

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

    def check_h2h_strict(h_id, a_id):
        resp = GET(f"/fixtures/head-to-head/{h_id}/{a_id}", params={"include": "participants;scores", "per_page": 10, "order": "desc"})
        history = resp.get("data",[])

        if len(history) < MIN_H2H_GAMES: return None

        history = history[:5]
        wins_h, wins_a = 0, 0
        gg, o25, o15 = 0, 0, 0 

        for h in history:
            (past_h_ht, past_a_ht), (past_h_ft, past_a_ft) = get_scores_ht_ft(h.get("scores",[]))
            if past_h_ft is None: continue

            h_id_was_home = True 
            parts = h.get("participants",[])
            for i, p in enumerate(parts):
                if str(p.get("id")) == str(h_id):
                    loc = p.get("meta", {}).get("location", "")
                    if loc == "away": h_id_was_home = False
                    elif loc == "" and i == 1: h_id_was_home = False
                    break

            if h_id_was_home:
                target_h_goals, target_a_goals = past_h_ft, past_a_ft
            else:
                target_h_goals, target_a_goals = past_a_ft, past_h_ft

            if target_h_goals > target_a_goals: wins_h += 1
            elif target_a_goals > target_h_goals: wins_a += 1

            if target_h_goals > 0 and target_a_goals > 0: gg += 1
            if (target_h_goals + target_a_goals) > 1.5: o15 += 1
            if (target_h_goals + target_a_goals) > 2.5: o25 += 1

        total = len(history)
        return {
            "h_win_100": (wins_h == total),
            "a_win_100": (wins_a == total),
            "gg_100": (gg == total),
            "o15_100": (o15 == total), 
            "o25_100": (o25 == total),
            "count": total
        }

    # ==============================================================================
    # 4. MAIN RUNNER (MACHINE READABLE OUTPUT)
    # ==============================================================================
    print(f"Aggregator Feeder Started: Target[{CHECK_DATE}]")

    all_fx =[]
    page = 1
    while True:
        # Note: Added 'league' to includes so the aggregator gets the League Name
        params = {"include": "participants;scores;league", "per_page": 50, "page": page}
        resp = GET(f"/fixtures/date/{CHECK_DATE}", params=params)
        data = resp.get("data",[])
        if not data: break
        all_fx.extend(data)
        if len(data) < 50: break
        page += 1

    results =[]

    for i, fx in enumerate(all_fx):
        parts = fx.get("participants",[])
        if len(parts) < 2: continue

        fid = str(fx["id"])
        h_id, h_name = str(parts[0]["id"]), parts[0]["name"]
        a_id, a_name = str(parts[1]["id"]), parts[1]["name"]
        
        # Metadata for Alert System
        league_name = fx.get("league", {}).get("name", "Unknown League")
        
        # FIX: Safely parse the "starting_at" string to get datetime and timestamp
        start_datetime = fx.get("starting_at", "")
        start_timestamp = 0
        
        if isinstance(start_datetime, str) and start_datetime:
            try:
                dt_obj = datetime.strptime(start_datetime, "%Y-%m-%d %H:%M:%S")
                start_timestamp = int(dt_obj.timestamp())
            except ValueError:
                pass

        # 🚨 FILTER 1: H2H MUST BE 100% OVER 1.5 GOALS
        h2h = check_h2h_strict(h_id, a_id)
        if not h2h or not h2h.get("o15_100"): continue

        # 🚨 FILTER 2: BOTH TEAMS MUST HAVE SCORED >= 8 GOALS IN LAST 5
        h_2h_activity, h_total, h_goals = check_recent_form_math(h_id, h_name)
        a_2h_activity, a_total, a_goals = check_recent_form_math(a_id, a_name)

        if h_goals < 8 or a_goals < 8: continue

        # Constructing the Machine-Readable Payload
        match_payload = {
            "engine": "Gold_Over_2.5",
            "fixture_id": fid,
            "league": league_name,
            "kickoff_timestamp": start_timestamp,
            "kickoff_datetime": start_datetime,
            "teams": {
                "home": {"id": h_id, "name": h_name},
                "away": {"id": a_id, "name": a_name}
            },
            "flags": {
                "both_teams_high_attack": True,  # Ensures both scored 8+ recently
                "h2h_o15_100_percent": True,     # Guaranteed by filter
                "both_2h_goal_100_percent": bool(h_2h_activity == 100 and a_2h_activity == 100),
                "home_h2h_win_100": h2h["h_win_100"],
                "away_h2h_win_100": h2h["a_win_100"],
                "h2h_gg_100": h2h["gg_100"],
                "h2h_o25_100": h2h["o25_100"]
            },
            "metrics": {
                "home_goals_last_5": h_goals,
                "away_goals_last_5": a_goals,
                "h2h_matches_analyzed": h2h["count"]
            }
        }
        
        print(f"Matched -> {league_name} | {h_name} vs {a_name} | Time: {start_datetime}")
        results.append(match_payload)

    # Save cleanly for the aggregator to pull
    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=4)
        
    print(f"Exported {len(results)} payload objects to {OUTPUT_FILE}.")
    
    # Return directly for the Master API to consume
    return results

if __name__ == "__main__":
    # Added ArgParse for Headless/Automated Execution
    # parse_known_args() prevents crashes in Jupyter/Colab environments
    parser = argparse.ArgumentParser(description="Gold Over 2.5 Engine Feeder")
    parser.add_argument("--date", type=str, default=datetime.now().strftime("%Y-%m-%d"), help="Target date YYYY-MM-DD")
    args, unknown = parser.parse_known_args()
    
    # Run the wrapped engine
    run_gold_over_25_engine(args.date)