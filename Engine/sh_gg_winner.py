import os
import sys
import time
import json
import requests
from datetime import datetime, timedelta, timezone

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
def run_sh_gg_winner_engine(target_date):
    """
    Executes the Second Half, GG & Winner Engine.
    All mathematical weights, streak rules, and filtering logic
    are 100% untouched and preserved from the original back-end.
    """
    
    # Ensure directories exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    # -------------------------
    # CONFIG (100% UNTOUCHED LOGIC)
    # -------------------------
    API_TOKEN = os.getenv("SPORTMONKS_API_KEY") or "hD4F4FIFwNW5BxKa6Y0fCCLtB0KkiNRxtULDdsrO3VPss1IMV4HJihBkxwI4"
    MIN_H2H_GAMES = 2
    REQ_DELAY = 0.2
    
    # Dynamic Output Path
    OUTPUT_FILE = os.path.join(OUTPUT_DIR, "sh_gg_winner_feed.json")

    # -------------------------
    # UTILS (NESTED FOR ENCAPSULATION)
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
        If unplayed, defaults to None so math engines ignore them safely.
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

    # -------------------------
    # ANALYSIS ENGINES (100% UNTOUCHED MATH)
    # -------------------------
    def check_recent_form_math(team_id, team_name):
        """
        Checks last 5 matches using simple math (FT - HT > 0).
        Safely tied to the aggregator's target_date for backtesting capabilities.
        """
        end = target_date
        start = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=120)).strftime("%Y-%m-%d")

        params = {
            "include": "scores",
            "per_page": 5,
            "filters": "fixtureStates:5",
            "order": "desc"
        }
        resp = GET(f"/fixtures/between/{start}/{end}/{team_id}", params=params)
        matches = resp.get("data",[])

        if not matches: return 0, 0 

        games_with_2h_activity = 0

        for m in matches:
            (h_ht, a_ht), (h_ft, a_ft) = get_scores_ht_ft(m.get("scores",[]))
            if h_ft is None: continue 

            h_goals_2h = h_ft - h_ht
            a_goals_2h = a_ft - a_ht
            total_goals_2h = h_goals_2h + a_goals_2h

            if total_goals_2h > 0:
                games_with_2h_activity += 1

        total = len(matches)
        pct_activity = (games_with_2h_activity / total * 100) if total > 0 else 0

        return pct_activity, total

    def check_h2h_strict(h_id, a_id):
        resp = GET(f"/fixtures/head-to-head/{h_id}/{a_id}", params={"include": "participants;scores", "per_page": 10, "order": "desc"})
        history = resp.get("data",[])

        if len(history) < MIN_H2H_GAMES: return None

        history = history[:5]
        wins_h, wins_a = 0, 0
        gg, o25 = 0, 0

        for h in history:
            (past_h_ht, past_a_ht), (past_h_ft, past_a_ft) = get_scores_ht_ft(h.get("scores",[]))
            if past_h_ft is None: continue 

            h_id_was_home = True 
            parts = h.get("participants",[])
            for i, p in enumerate(parts):
                if str(p.get("id")) == str(h_id):
                    loc = p.get("meta", {}).get("location", "")
                    if loc == "away":
                        h_id_was_home = False
                    elif loc == "":
                        if i == 1: h_id_was_home = False
                    break
            
            if h_id_was_home:
                target_h_goals, target_a_goals = past_h_ft, past_a_ft
            else:
                target_h_goals, target_a_goals = past_a_ft, past_h_ft

            if target_h_goals > target_a_goals: wins_h += 1
            elif target_a_goals > target_h_goals: wins_a += 1

            if target_h_goals > 0 and target_a_goals > 0: gg += 1
            if (target_h_goals + target_a_goals) > 2.5: o25 += 1

        total = len(history)
        return {
            "h_win_100": (wins_h == total),
            "a_win_100": (wins_a == total),
            "gg_100": (gg == total),
            "o25_100": (o25 == total),
            "count": total
        }

    # -------------------------
    # MAIN PIPELINE EXECUTION
    # -------------------------
    print(f"\n[SH GG Winner] Engine Execution Started for Target[{target_date}]")

    all_fx =[]
    page = 1
    while True:
        params = {"include": "participants;scores;league", "per_page": 50, "page": page}
        resp = GET(f"/fixtures/date/{target_date}", params=params)
        data = resp.get("data",[])
        if not data: break
        all_fx.extend(data)
        if len(data) < 50: break
        page += 1
        time.sleep(REQ_DELAY)

    results =[]

    for i, fx in enumerate(all_fx):
        parts = fx.get("participants",[])
        if len(parts) < 2: continue

        fid = str(fx["id"])
        h_id, h_name = str(parts[0]["id"]), parts[0]["name"]
        a_id, a_name = str(parts[1]["id"]), parts[1]["name"]

        # Metadata for Alert System
        league_name = fx.get("league", {}).get("name", "Unknown League")
        start_datetime = fx.get("starting_at", "")
        start_timestamp = 0
        
        if isinstance(start_datetime, str) and start_datetime:
            try:
                dt_obj = datetime.strptime(start_datetime, "%Y-%m-%d %H:%M:%S")
                start_timestamp = int(dt_obj.timestamp())
            except ValueError:
                pass

        # 1. H2H
        h2h = check_h2h_strict(h_id, a_id)

        # 2. 2H Goals (Math Method)
        h_2h_activity, h_total = check_recent_form_math(h_id, h_name)
        a_2h_activity, a_total = check_recent_form_math(a_id, a_name)

        streaks =[]

        if h_2h_activity == 100 and a_2h_activity == 100:
            streaks.append("🔥 BOTH 2H GOAL (100%)")

        if h2h:
            if h2h["h_win_100"]: streaks.append("💀 HOME H2H WINNER (100%)")
            if h2h["a_win_100"]: streaks.append("💀 AWAY H2H WINNER (100%)")
            if h2h["gg_100"]: streaks.append("⚽ H2H GG (100%)")
            if h2h["o25_100"]: streaks.append("⚽ H2H O2.5 (100%)")

        # Your original logic only exports matches that hit AT LEAST one streak
        if streaks:
            # Constructing the Machine-Readable Payload
            match_payload = {
                "engine": "Second_Half_GG_Winner",
                "fixture_id": fid,
                "league": league_name,
                "kickoff_timestamp": start_timestamp,
                "kickoff_datetime": start_datetime,
                "teams": {
                    "home": {"id": h_id, "name": h_name},
                    "away": {"id": a_id, "name": a_name}
                },
                "pick_labels": streaks,  
                "flags": {
                    "both_2h_goal_100_percent": bool(h_2h_activity == 100 and a_2h_activity == 100),
                    "home_h2h_win_100": bool(h2h and h2h["h_win_100"]),
                    "away_h2h_win_100": bool(h2h and h2h["a_win_100"]),
                    "h2h_gg_100": bool(h2h and h2h["gg_100"]),
                    "h2h_o25_100": bool(h2h and h2h["o25_100"])
                },
                "metrics": {
                    "home_2h_rate": h_2h_activity,
                    "away_2h_rate": a_2h_activity,
                    "h2h_matches_analyzed": h2h["count"] if h2h else 0
                }
            }
            results.append(match_payload)

    # Save cleanly for the aggregator to pull/backup
    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=4)
        
    print(f"[SH GG Winner] Exported {len(results)} payload objects to {OUTPUT_FILE}")

    # Return directly to memory so the Master API can use it instantly
    return results

# ==============================================================================
# IF RUN DIRECTLY (TESTING)
# ==============================================================================
if __name__ == "__main__":
    # If someone runs this file directly via terminal instead of through the Aggregator
    test_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_sh_gg_winner_engine(test_date)