import os
import sys
import time
import json
import math
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from dateutil import parser
from collections import defaultdict, Counter

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
from dotenv import load_dotenv
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS ---
# This matches the folder structure you use for Stage 1 and Stage 2
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

# ==============================================================================
# 📦 THE BLACK BOX WRAPPER (CALLABLE BY THE MASTER API/SCHEDULER)
# ==============================================================================
def run_gg_engine_stage1(target_date):
    """
    Executes GG Engine Stage 1.
    All mathematical weights, consistency logic, and sigmoid probability
    are 100% untouched and preserved from the original back-end.
    """
    # Ensure directories exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    # -------------------------
    # CONFIG (100% UNTOUCHED)
    # -------------------------
    API_KEY = os.getenv("SPORTMONKS_API_KEY") or "hD4F4FIFwNW5BxKa6Y0fCCLtB0KkiNRxtULDdsrO3VPss1IMV4HJihBkxwI4"
    BASE_URL = "https://api.sportmonks.com/v3/football"
    TEAM_LOOKBACK_DAYS = 365
    REQUEST_DELAY_SEC = 0.18
    LAST_N_GAMES = 5
    KEYPLAYER_LAST_N = 3   
    LEAGUE_TEMPO_DAYS = 90   
    BOOKMAKER_ID = 2
    DOMINANCE_THRESHOLD = 8   
    VALUE_EDGE_MIN_DIFF = 0.05  
    MIN_RECENT_MATCHES_REQUIRED = 3  

    # --- GLOBAL SESSION CACHE (100% UNTOUCHED) ---
    CACHE_TEAM_HISTORY = {}
    CACHE_LEAGUE_TEMPO = {}
    CACHE_STANDINGS = {}

    if not API_KEY:
        print("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")
        return []

    # -------------------------
    # HTTP HELPERS (100% UNTOUCHED)
    # -------------------------
    def GET(path, params=None, timeout=30):
        if params is None: params = {}
        params.setdefault("api_token", API_KEY)
        url = f"{BASE_URL}{path}"
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code != 200: return {"data": []}
            return r.json()
        except: return {"data": []}

    def sleep_short(mult=1.0):
        time.sleep(REQUEST_DELAY_SEC * mult)

    # -------------------------
    # PAGINATION LOGIC (100% UNTOUCHED)
    # -------------------------
    def fetch_fixtures_for_date(date_str, page=1):
        resp = GET(f"/fixtures/date/{date_str}", params={
            "include": "participants;lineups;scores",
            "page": page,
            "per_page": 50
        })
        return resp.get("data", []), resp.get("meta", {})

    def fetch_all_fixtures_for_date(date_str):
        all_fx = []
        page = 1
        while True:
            data, _ = fetch_fixtures_for_date(date_str, page=page)
            if not data: break
            all_fx.extend(data)
            if len(data) < 50: break
            page += 1
            sleep_short()
        return all_fx

    # -------------------------
    # GOAL EXTRACTION (100% UNTOUCHED)
    # -------------------------
    def extract_final_goals_from_scores(scores):
        home, away = None, None
        for entry in (scores or []):
            if entry.get("description") == "CURRENT":
                s = entry.get("score") or {}
                p, g = s.get("participant"), s.get("goals")
                if not isinstance(g, int): continue
                if p == "home": home = g
                elif p == "away": away = g
        return home, away

    def get_team_and_opponent_goals_from_fixture(fx, team_id):
        hg, ag = extract_final_goals_from_scores(fx.get("scores", []))
        if hg is None or ag is None: return None, None
        is_team_home = any(str(p.get("id")) == str(team_id) and p.get("meta", {}).get("location") == "home" for p in fx.get("participants", []))
        return (hg, ag) if is_team_home else (ag, hg)

    # -------------------------
    # ENGINE HELPERS (100% UNTOUCHED)
    # -------------------------
    def is_home(fx, team_id):
        return any(str(p.get("id")) == str(team_id) and p.get("meta", {}).get("location") == "home" for p in fx.get("participants", []))

    def is_away(fx, team_id):
        return any(str(p.get("id")) == str(team_id) and p.get("meta", {}).get("location") == "away" for p in fx.get("participants", []))

    def is_btts(fx):
        hg, ag = extract_final_goals_from_scores(fx.get("scores", []))
        return bool(hg is not None and ag is not None and hg > 0 and ag > 0)

    def count_btts_last_n(fixtures, n=LAST_N_GAMES):
        return sum(1 for f in (fixtures or [])[:n] if is_btts(f))

    def get_weighted_goals(fixtures, team_id, n=LAST_N_GAMES):
        weights = np.arange(n, 0, -1)
        last_n = (fixtures or [])[:n]
        scored, conceded = [], []
        for f in last_n:
            res = get_team_and_opponent_goals_from_fixture(f, team_id)
            scored.append(res[0] if res[0] is not None else 0)
            conceded.append(res[1] if res[1] is not None else 0)
        
        scored, conceded = np.array(scored, dtype=float), np.array(conceded, dtype=float)
        if len(scored) < n:
            scored = np.pad(scored, (0, n - len(scored)), 'constant')
            conceded = np.pad(conceded, (0, n - len(conceded)), 'constant')
        
        denom = weights.sum() or 1
        return float(np.dot(scored, weights) / denom), float(np.dot(conceded, weights) / denom)

    def scoring_consistency(fixtures, team_id, n=LAST_N_GAMES):
        vals = [get_team_and_opponent_goals_from_fixture(f, team_id)[0] for f in (fixtures or [])[:n] if get_team_and_opponent_goals_from_fixture(f, team_id)[0] is not None]
        if not vals: return 0.0
        return 1.0 / (1.0 + float(np.std(vals)))

    def pressure_index(fixtures, team_id, early_minute=30, n=LAST_N_GAMES):
        early_scored = total = 0
        for f in (fixtures or [])[:n]:
            events = f.get("timeline") or f.get("events") or []
            for e in events:
                if "goal" in (e.get("type") or "").lower():
                    pid = e.get("participant_id") or e.get("team_id")
                    if str(pid) == str(team_id) and int(e.get("minute", 99)) <= early_minute:
                        early_scored += 1; break
            total += 1
        return early_scored / total if total else 0.0

    def compatibility_index(h_s_w, a_c_w, a_s_w, h_c_w):
        try:
            m1 = 1.0 - abs(h_s_w - a_c_w) / max(1.0, (h_s_w + a_c_w))
            m2 = 1.0 - abs(a_s_w - h_c_w) / max(1.0, (a_s_w + h_c_w))
            return max(0.0, min(1.0, (m1 + m2) / 2.0))
        except: return 0.0

    # -------------------------
    # KEY-PLAYER LOGIC (100% UNTOUCHED)
    # -------------------------
    def get_key_players_recent_starts(team_id, n=KEYPLAYER_LAST_N):
        end_dt = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        start_dt = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=TEAM_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        resp = GET(f"/fixtures/between/{start_dt}/{end_dt}/{team_id}", params={"include": "lineups", "filter": "fixtureStates:5", "order": "desc", "per_page": n})
        starters_per_game = [extract_starters_from_lineups(fx.get("lineups"), team_id) for fx in resp.get("data", [])]
        all_starters = [pid for starters in starters_per_game for pid in starters]
        count = Counter(all_starters)
        min_starts = max(1, int(n * 0.66 + 0.5))
        return set(pid for pid, c in count.items() if c >= min_starts)

    def get_key_players_minutes(team_id, season_id):
        if not season_id: return set()
        resp = GET(f"/teams/{team_id}/squad/{season_id}", params={"include": "player.statistics"})
        players = resp.get("data", []) or []
        minutes = {}
        for p in players:
            stats = p.get("player", {}).get("statistics", []) or p.get("statistics", []) or []
            pid = p.get("player", {}).get("id") or p.get("player_id")
            for s in stats:
                if str(s.get("season_id")) == str(season_id):
                    mins = s.get("minutes") or 0
                    if pid: minutes[pid] = max(minutes.get(pid, 0), int(mins))
        return set(pid for pid, _ in sorted(minutes.items(), key=lambda x: -x[1])[:11])

    def extract_starters_from_lineups(lineups, team_id):
        return [l.get("player_id") for l in (lineups or []) if str(l.get("team_id")) == str(team_id) and int(l.get("type_id", 0)) == 11]

    def extract_positions_recursive(data, pos_map):
        if isinstance(data, dict):
            pid = data.get("participant_id") or data.get("team_id")
            if not pid and "participant" in data and isinstance(data["participant"], dict): pid = data["participant"].get("id")
            pos = data.get("position")
            if pid and pos:
                try: pos_map[int(pid)] = int(pos)
                except: pass
            for v in data.values(): extract_positions_recursive(v, pos_map)
        elif isinstance(data, list):
            for i in data: extract_positions_recursive(i, pos_map)

    # -------------------------
    # CACHED FETCHERS (100% UNTOUCHED)
    # -------------------------
    def fetch_team_history_cached(team_id):
        if team_id in CACHE_TEAM_HISTORY: return CACHE_TEAM_HISTORY[team_id]
        end_dt = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        start_dt = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=TEAM_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        resp = GET(f"/fixtures/between/{start_dt}/{end_dt}/{team_id}", params={"include":"participants;scores;lineups;timeline","filter":"fixtureStates:5","order":"desc"})
        res = resp.get("data", [])
        CACHE_TEAM_HISTORY[team_id] = res
        return res

    def fetch_league_tempo_cached(league_id):
        if league_id in CACHE_LEAGUE_TEMPO: return CACHE_LEAGUE_TEMPO[league_id]
        start = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=LEAGUE_TEMPO_DAYS)).strftime("%Y-%m-%d")
        resp = GET(f"/fixtures/between/{start}/{target_date}/{league_id}", params={"include":"scores"})
        data = resp.get("data", [])
        total = sum((extract_final_goals_from_scores(fx.get("scores", []))[0] or 0) + (extract_final_goals_from_scores(fx.get("scores", []))[1] or 0) for fx in data if fx.get("scores"))
        res = total / len(data) if data else 2.5
        CACHE_LEAGUE_TEMPO[league_id] = res
        return res

    def sigmoid(x):
        try: return 1.0 / (1.0 + math.exp(-x))
        except: return 0.0

    def dominance_checks(layers):
        details = [float(layers.get("h_gg_r",0)) >= 0.6, float(layers.get("a_gg_r",0)) >= 0.6, int(layers.get("home_gg_count",0)) >= 3, int(layers.get("away_gg_count",0)) >= 3, int(layers.get("h2h_gg_count",0)) >= 3]
        return sum(1 for d in details if d)

    # -------------------------
    # MAIN PIPELINE EXECUTION
    # -------------------------
    print(f"GG1A Engine: Starting scan for {target_date}...")
    all_fx = fetch_all_fixtures_for_date(target_date)
    
    picks = []

    for fx in all_fx:
        try:
            parts = fx.get("participants", [])
            if len(parts) < 2: continue
            
            h_p = next((p for p in parts if p.get("meta", {}).get("location") == "home"), None)
            a_p = next((p for p in parts if p.get("meta", {}).get("location") == "away"), None)
            if not h_p or not a_p: continue
            
            h_id, a_id, lid, sid = h_p['id'], a_p['id'], fx.get("league_id"), fx.get("season_id")

            h_full = fetch_team_history_cached(h_id); a_full = fetch_team_history_cached(a_id)
            l5h = [f for f in h_full if is_home(f, h_id)][:5]; l5a = [f for f in a_full if is_away(f, a_id)][:5]
            if len(l5h) < MIN_RECENT_MATCHES_REQUIRED or len(l5a) < MIN_RECENT_MATCHES_REQUIRED: continue
            
            h2h_resp = GET(f"/fixtures/head-to-head/{h_id}/{a_id}", params={"include":"scores;participants"})
            h2h = h2h_resp.get("data", [])
            
            h_gg_count, a_gg_count, h2h_gg_count = count_btts_last_n(l5h), count_btts_last_n(l5a), count_btts_last_n(h2h)
            h_w_s, h_w_c = get_weighted_goals(l5h, h_id); a_w_s, a_w_c = get_weighted_goals(l5a, a_id)
            h_scored = sum((get_team_and_opponent_goals_from_fixture(f, h_id)[0] or 0) for f in l5h)
            h_conceded = sum((get_team_and_opponent_goals_from_fixture(f, h_id)[1] or 0) for f in l5h)
            a_scored = sum((get_team_and_opponent_goals_from_fixture(f, a_id)[0] or 0) for f in l5a)
            a_conceded = sum((get_team_and_opponent_goals_from_fixture(f, a_id)[1] or 0) for f in l5a)
            
            h2h_h_goals = sum((get_team_and_opponent_goals_from_fixture(hf, h_id)[0] or 0) for hf in h2h[:5])
            h2h_a_goals = sum((get_team_and_opponent_goals_from_fixture(hf, h_id)[1] or 0) for hf in h2h[:5])

            tempo = fetch_league_tempo_cached(lid)
            comp_idx = compatibility_index(h_w_s, a_w_c, a_w_s, h_w_c)
            p_idx = (pressure_index(l5h, h_id) + pressure_index(l5a, a_id))/2.0
            
            layers = {"home_avg_goals": h_scored/5, "away_avg_goals": a_scored/5, "home_concede": h_conceded/5, "away_concede": a_conceded/5, "home_weighted_scored": h_w_s, "away_weighted_scored": a_w_s, "h2h_avg_goals": (h2h_h_goals+h2h_a_goals)/5, "league_avg_goals": tempo, "home_gg_count": h_gg_count, "away_gg_count": a_gg_count, "h2h_gg_count": h2h_gg_count, "home_gg_ratio": h_gg_count/5, "away_gg_ratio": a_gg_count/5, "home_consistency": scoring_consistency(l5h, h_id), "away_consistency": scoring_consistency(l5a, a_id), "compatibility_index": comp_idx, "pressure_index": p_idx, "h_gg_r": h_gg_count/5, "a_gg_r": a_gg_count/5}
            weights = {"home_avg_goals": 0.07, "away_avg_goals": 0.07, "home_concede": 0.04, "away_concede": 0.04, "home_weighted_scored": 0.06, "away_weighted_scored": 0.06, "h2h_avg_goals": 0.07, "league_avg_goals": 0.18, "home_gg_count": 0.05, "away_gg_count": 0.05, "h2h_gg_count": 0.035, "home_gg_ratio": 0.03, "away_gg_ratio": 0.03, "home_consistency": 0.03, "away_consistency": 0.03, "compatibility_index": 0.07, "pressure_index": 0.04}
            
            raw_score = sum(layers.get(k, 0) * weights.get(k, 0) for k in weights)
            prob_pct = round(sigmoid((raw_score - 1.0)) * 100.0, 2)

            # Standard Standings Lookup
            pos_map = {}
            standings_resp = GET(f"/standings", params={"filter": f"standingLeagues:{lid}", "filter": f"standingSeasons:{sid}"})
            extract_positions_recursive(standings_resp.get("data", []), pos_map)
            h_pos, a_pos = pos_map.get(h_id, 0), pos_map.get(a_id, 0)
            
            h_key = get_key_players_recent_starts(h_id) | get_key_players_minutes(h_id, sid)
            a_key = get_key_players_recent_starts(a_id) | get_key_players_minutes(a_id, sid)
            h_miss = len([p for p in h_key if str(p) not in map(str, extract_starters_from_lineups(fx.get("lineups"), h_id))])
            a_miss = len([p for p in a_key if str(p) not in map(str, extract_starters_from_lineups(fx.get("lineups"), a_id))])

            f_map = {}
            for f in l5h + l5a + h2h[:5]:
                fid_temp = f.get("id")
                if fid_temp and fid_temp not in f_map:
                    g1, g2 = extract_final_goals_from_scores(f.get("scores", []))
                    f_map[fid_temp] = {"gg": bool(g1 is not None and g2 is not None and g1>0 and g2>0), "t": (g1+g2) if (g1 is not None and g2 is not None) else 0}
            total_gg, total_goals = sum(1 for v in f_map.values() if v["gg"]), sum(v["t"] for v in f_map.values())
            
            picks.append({
                "fixture_id": fx.get("id"),
                "home_team": h_p['name'], "away_team": a_p['name'],
                "home_missing_key_players_count": h_miss, "away_missing_key_players_count": a_miss,
                "h2h_goal_parity": abs(h2h_h_goals - h2h_a_goals), "concede_parity": abs(h_conceded - a_conceded),
                "home_gg_count": h_gg_count, "away_gg_count": a_gg_count, "h2h_gg_count": h2h_gg_count,
                "home_goal_count": int(h_scored), "away_goal_count": int(a_scored), "total_gg_count": total_gg, "total_goal_count": total_goals,
                "tier": "Tier 1A" if (1 <= h_pos <= 8 and 1 <= a_pos <= 8 and total_gg >= 9) else "Below Threshold",
                "home_gg_last3": count_btts_last_n(l5h, 3), "away_gg_last3": count_btts_last_n(l5a, 3),
                "data_integrity_pass": True, "dominance_score": dominance_checks(layers), "gg_prob_pct": prob_pct, "home_position": h_pos, "away_position": a_pos, "both_top8": (1 <= h_pos <= 8 and 1 <= a_pos <= 8)
            })
        except: continue

    df = pd.DataFrame(picks)
    if df.empty: return []
    df = df.sort_values("gg_prob_pct", ascending=False).head(20)
    
    # --- OUTPUT ---
    # SAVE SAFELY IN THE DYNAMIC DIRECTORY
    output_file_path = os.path.join(OUTPUT_DIR, "picks_gg1.csv")
    df.to_csv(output_file_path, index=False)
    print(f"\n[GG Stage 1] Saved top {len(df)} picks to {output_file_path}")

    return df.to_dict(orient="records")

# Allow local testing
if __name__ == "__main__":
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_gg_engine_stage1(today_date)