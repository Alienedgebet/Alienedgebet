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
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

# ==============================================================================
# 📦 THE BLACK BOX WRAPPER (CALLABLE BY THE MASTER API/SCHEDULER)
# ==============================================================================
def run_gg_engine_stage2(target_date):
    """
    Executes GG Engine Stage 2 (Key Player & Forensic Audit).
    All mathematical weights, tiering logic, and key-player analysis
    are 100% untouched and preserved from the original back-end.
    """
    # Ensure directories exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    # -------------------------
    # CONFIG (100% UNTOUCHED ENGINE PARAMS)
    # -------------------------
    API_KEY = os.getenv("SPORTMONKS_API_KEY") or "ilM1T5gw3IYpJEmnnlLnaB9wKfmF0U6qtvmuV18am7uaGjNN21er7umReP7P"
    BASE_URL = "https://api.sportmonks.com/v3/football"
    TEAM_LOOKBACK_DAYS = 365
    REQUEST_DELAY_SEC = 0.18
    LAST_N_GAMES = 5
    KEYPLAYER_LAST_N = 3   
    LEAGUE_TEMPO_DAYS = 90   
    BOOKMAKER_ID = 2
    ODDS_CSV = os.path.join(DATA_DIR, "odds.csv")
    DOMINANCE_THRESHOLD = 8   
    VALUE_EDGE_MIN_DIFF = 0.05  
    MIN_RECENT_MATCHES_REQUIRED = 3  

    # 🟢[UPGRADE: FLEXIBLE STANDINGS DISTANCE]
    MIN_TABLE_DISTANCE = 1
    MAX_TABLE_DISTANCE = 10

    if not API_KEY:
        print("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")
        return[]

    # -------------------------
    # HTTP HELPERS (100% UNTOUCHED)
    # -------------------------
    def GET(path: str, params=None, timeout=30):
        if params is None: params = {}
        params.setdefault("api_token", API_KEY)
        url = f"{BASE_URL}{path}"
        r = requests.get(url, params=params, timeout=timeout)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code} for {url}\n{r.text}")
        return r.json()

    def sleep_short(mult=1.0):
        time.sleep(REQUEST_DELAY_SEC * mult)

    # -------------------------
    # KEY-PLAYER HELPERS (100% UNTOUCHED)
    # -------------------------
    def get_last_n_fixtures_for_key(team_id, n=KEYPLAYER_LAST_N):
        end_dt = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        start_dt = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=TEAM_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        try:
            resp = GET(f"/fixtures/between/{start_dt}/{end_dt}/{team_id}", params={
                "include": "lineups", "filter": "fixtureStates:5", "order": "desc", "per_page": n
            })
            return resp.get("data", [])[:n]
        except: return[]

    def extract_starters_from_lineups(lineups, team_id):
        out =[]
        for l in (lineups or[]):
            try:
                tid = l.get("team_id") or l.get("teamId") or l.get("team")
                ttype = l.get("type_id") or l.get("typeId") or l.get("type")
                pid = l.get("player_id") or l.get("playerId") or l.get("player")
                if str(tid) == str(team_id) and (ttype is None or int(ttype) == 11):
                    if pid is not None: out.append(pid)
            except: continue
        return out

    def get_key_players_recent_starts(team_id, n=KEYPLAYER_LAST_N):
        fixtures = get_last_n_fixtures_for_key(team_id, n)
        starters_per_game =[extract_starters_from_lineups(fx.get("lineups"), team_id) for fx in fixtures]
        all_starters =[pid for starters in starters_per_game for pid in starters]
        count = Counter(all_starters)
        min_starts = max(1, int(n * 0.66 + 0.5))
        return set(pid for pid, c in count.items() if c >= min_starts)

    def get_key_players_minutes(team_id, season_id):
        if not season_id: return set()
        try:
            resp = GET(f"/teams/{team_id}/squad/{season_id}", params={"include": "player.statistics"})
            players = resp.get("data", []) or[]
        except: return set()
        minutes = {}
        for p in players:
            player_obj = p.get("player") if isinstance(p, dict) else None
            stats = player_obj.get("statistics",[]) if player_obj else p.get("statistics",[])
            pid_key = player_obj.get("id") if player_obj else p.get("player_id")
            for s in stats or[]:
                try:
                    if str(s.get("season_id")) == str(season_id):
                        mins = s.get("minutes") or s.get("minutes_played") or 0
                        if mins and pid_key: minutes[pid_key] = max(minutes.get(pid_key, 0), int(mins))
                except: continue
        return set(pid for pid, _ in sorted(minutes.items(), key=lambda x: -x[1])[:11])

    def get_sidelined_players_from_fixture(sidelined, team_id):
        out = set()
        for s in (sidelined or[]):
            try:
                if str(s.get("team_id") or s.get("teamId")) == str(team_id):
                    pid = s.get("player_id") or s.get("playerId")
                    if pid: out.add(pid)
            except: continue
        return out

    def get_today_starters_from_fixture(lineups, team_id):
        return set(extract_starters_from_lineups(lineups, team_id))

    def get_current_season_id_for_league(league_id):
        if not league_id: return None
        try:
            resp = GET(f"/leagues/{league_id}", params={"include": "currentSeason"})
            return resp.get("data", {}).get("current_season_id")
        except: return None

    # -------------------------
    # CORE ENGINE HELPERS (100% UNTOUCHED)
    # -------------------------
    def extract_final_goals_from_scores(scores):
        home, away = None, None
        for entry in (scores or[]):
            if not isinstance(entry, dict): continue
            s = entry.get("score") or {}
            p, g = s.get("participant"), s.get("goals")
            try:
                if isinstance(g, str) and str(g).isdigit(): g = int(g)
            except: pass
            if not isinstance(g, int): continue
            if p == "home": home = g if home is None else max(home, g)
            elif p == "away": away = g if away is None else max(away, g)
        return home, away

    def is_home(fx, team_id):
        return any(str(p.get("id")) == str(team_id) and p.get("meta", {}).get("location") == "home" for p in fx.get("participants",[]))

    def is_away(fx, team_id):
        return any(str(p.get("id")) == str(team_id) and p.get("meta", {}).get("location") == "away" for p in fx.get("participants",[]))

    def get_team_and_opponent_goals_from_fixture(fx, team_id):
        hg, ag = extract_final_goals_from_scores(fx.get("scores",[]))
        if hg is None or ag is None: return None, None
        if is_home(fx, team_id): return hg, ag
        return ag, hg

    def is_btts(fx):
        hg, ag = extract_final_goals_from_scores(fx.get("scores",[]))
        return (hg is not None and ag is not None and hg > 0 and ag > 0)

    def count_btts_last_n(fixtures, n=LAST_N_GAMES):
        return sum(1 for f in (fixtures or [])[:n] if is_btts(f))

    def btts_ratio(fixtures, n=LAST_N_GAMES):
        return count_btts_last_n(fixtures, n) / float(max(1, n))

    def btts_streak(fixtures, n=LAST_N_GAMES):
        streak = 0
        for f in (fixtures or[])[:n]:
            if is_btts(f): streak += 1
            else: break
        return streak

    def get_weighted_goals(fixtures, team_id, n=LAST_N_GAMES):
        weights = np.arange(n, 0, -1)
        last_n = (fixtures or [])[:n]
        scored = np.array([(get_team_and_opponent_goals_from_fixture(f, team_id)[0] or 0) for f in last_n], dtype=float)
        conceded = np.array([(get_team_and_opponent_goals_from_fixture(f, team_id)[1] or 0) for f in last_n], dtype=float)
        if len(scored) < n:
            scored = np.pad(scored, (0, n - len(scored)), 'constant')
            conceded = np.pad(conceded, (0, n - len(conceded)), 'constant')
        denom = weights.sum() or 1
        return float(np.dot(scored, weights) / denom), float(np.dot(conceded, weights) / denom)

    def scoring_consistency(fixtures, team_id, n=LAST_N_GAMES):
        vals =[get_team_and_opponent_goals_from_fixture(f, team_id)[0] for f in (fixtures or [])[:n] if get_team_and_opponent_goals_from_fixture(f, team_id)[0] is not None]
        if not vals: return 0.0
        return 1.0 / (1.0 + float(np.std(vals)))

    def pressure_index(fixtures, team_id, early_minute=30, n=LAST_N_GAMES):
        early_scored = total = 0
        for f in (fixtures or[])[:n]:
            events = f.get("timeline") or f.get("events") or[]
            for e in events:
                try:
                    typ = (e.get("type") or "").lower()
                    if "goal" in typ:
                        pid = e.get("participant_id") or e.get("team_id")
                        if str(pid) == str(team_id) and int(e.get("minute", 99)) <= early_minute:
                            early_scored += 1; break
                except: continue
            total += 1
        return early_scored / total if total > 0 else 0.0

    def compute_league_tempo_and_venue_avgs(league_id, lookback_days=LEAGUE_TEMPO_DAYS):
        end = datetime.strptime(target_date, "%Y-%m-%d").date()
        start = end - timedelta(days=lookback_days)
        resp = GET(f"/fixtures/between/{start}/{end}/{league_id}", params={"include":"scores"})
        fixtures = resp.get("data",[])
        total_goals = total_matches = 0
        for fx in fixtures:
            hg, ag = extract_final_goals_from_scores(fx.get("scores",[]))
            if hg is not None and ag is not None:
                total_goals += (hg + ag); total_matches += 1
        return {"league_avg_goals": (total_goals / total_matches) if total_matches else 0.0}

    def fetch_all_fixtures_for_date(date_str):
        all_fx =[]
        page = 1
        while True:
            resp = GET(f"/fixtures/date/{date_str}", params={"include":"participants;lineups;sidelined;scores;odds","per_page":50,"page":page})
            data = resp.get("data",[])
            if not data: break
            all_fx.extend(data)
            if len(data) < 50: break
            page += 1; sleep_short()
        return all_fx

    def fetch_last_finished_fixtures_for_team(team_id, max_needed=50):
        end_dt = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        start_dt = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=TEAM_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        resp = GET(f"/fixtures/between/{start_dt}/{end_dt}/{team_id}", params={
            "include":"participants;scores;state;lineups;formations;statistics;timeline",
            "filters":"fixtureStates:5","sortBy":"starting_at","order":"desc","per_page":max_needed
        })
        return resp.get("data",[])[:max_needed]

    def fetch_team_standing(league_id, season_id):
        try:
            data = GET(f"/standings/seasons/{season_id}", params={"filter": f"standingLeagues:{league_id}"})
            return data.get("data",[])
        except: return[]

    def sigmoid(x):
        try: return 1.0 / (1.0 + math.exp(-x))
        except: return 0.0

    def dominance_checks(pick):
        details =[
            float(pick.get("home_gg_ratio",0)) >= 0.6, float(pick.get("away_gg_ratio",0)) >= 0.6,
            int(pick.get("home_gg_count",0)) >= 3, int(pick.get("away_gg_count",0)) >= 3,
            int(pick.get("h2h_gg_count",0)) >= 3, float(pick.get("league_avg_goals",0)) >= 2.6,
            float(pick.get("home_consistency",0)) >= 0.5, float(pick.get("away_consistency",0)) >= 0.5,
            (float(pick.get("home_weighted_scored",0)) >= 1.2 or float(pick.get("away_weighted_scored",0)) >= 1.2),
            float(pick.get("pressure_index",0)) >= 0.25
        ]
        return sum(1 for d in details if d)

    def compatibility_index(h_s_w, a_c_w, a_s_w, h_c_w):
        try:
            m1 = 1.0 - abs(h_s_w - a_c_w) / max(1.0, (h_s_w + a_c_w))
            m2 = 1.0 - abs(a_s_w - h_c_w) / max(1.0, (a_s_w + h_c_w))
            return max(0.0, min(1.0, (m1 + m2) / 2.0))
        except: return 0.0

    # -------------------------
    # MAIN PIPELINE EXECUTION
    # -------------------------
    print(f"[GG Stage 2] Key Player Engine Execution for {target_date}")
    fixtures = fetch_all_fixtures_for_date(target_date)
    
    if not fixtures:
        print("No fixtures found.")
        return[]

    league_cache = {}
    league_ids = {fx.get("league_id") for fx in fixtures if fx.get("league_id")}
    for lid in league_ids:
        league_cache[lid] = compute_league_tempo_and_venue_avgs(lid)
        sleep_short()

    team_cache = {}
    picks =[]

    for fx in fixtures:
        try:
            parts = fx.get("participants",[])
            if len(parts) < 2: continue
            h_p = next((p for p in parts if p.get("meta", {}).get("location") == "home"), parts[0])
            a_p = next((p for p in parts if p.get("meta", {}).get("location") == "away"), parts[1])

            hid, aid = int(h_p["id"]), int(a_p["id"])
            lid, sid = fx.get("league_id"), fx.get("season_id")

            for tid in (hid, aid):
                if tid not in team_cache:
                    team_cache[tid] = fetch_last_finished_fixtures_for_team(tid)
                    sleep_short()

            l5h =[f for f in team_cache[hid] if is_home(f, hid)][:LAST_N_GAMES]
            l5a = [f for f in team_cache[aid] if is_away(f, aid)][:LAST_N_GAMES]
            if len(l5h) < MIN_RECENT_MATCHES_REQUIRED or len(l5a) < MIN_RECENT_MATCHES_REQUIRED: continue
            
            h2h = GET(f"/fixtures/head-to-head/{hid}/{aid}", params={"include":"scores;participants"})
            h2h_data = h2h.get("data", [])[:LAST_N_GAMES]

            # --- MATH LAYERS ---
            h_w_s, h_w_c = get_weighted_goals(l5h, hid); a_w_s, a_w_c = get_weighted_goals(l5a, aid)
            h_scored = sum((get_team_and_opponent_goals_from_fixture(f, hid)[0] or 0) for f in l5h)
            h_concede = sum((get_team_and_opponent_goals_from_fixture(f, hid)[1] or 0) for f in l5h)
            a_scored = sum((get_team_and_opponent_goals_from_fixture(f, aid)[0] or 0) for f in l5a)
            a_concede = sum((get_team_and_opponent_goals_from_fixture(f, aid)[1] or 0) for f in l5a)
            
            tempo = league_cache.get(lid, {}).get("league_avg_goals", 2.5)
            h_gg_c, a_gg_c, h2h_gg_c = count_btts_last_n(l5h), count_btts_last_n(l5a), count_btts_last_n(h2h_data)
            
            layers = {
                "home_avg_goals": h_scored/5, "away_avg_goals": a_scored/5, "home_concede": h_concede/5, "away_concede": a_concede/5,
                "home_weighted_scored": h_w_s, "away_weighted_scored": a_w_s, "home_weighted_conceded": h_w_c, "away_weighted_conceded": a_w_c,
                "league_avg_goals": tempo, "home_gg_count": h_gg_c, "away_gg_count": a_gg_c, "h2h_gg_count": h2h_gg_c,
                "home_gg_ratio": h_gg_c/5, "away_gg_ratio": a_gg_c/5, "home_consistency": scoring_consistency(l5h, hid),
                "away_consistency": scoring_consistency(l5a, aid), "compatibility_index": compatibility_index(h_w_s, a_w_c, a_w_s, h_w_c),
                "pressure_index": (pressure_index(l5h, hid) + pressure_index(l5a, aid))/2.0
            }
            
            weights = {"home_avg_goals": 0.07, "away_avg_goals": 0.07, "home_concede": 0.04, "away_concede": 0.04, "home_weighted_scored": 0.06, "away_weighted_scored": 0.06, "league_avg_goals": 0.18, "home_gg_count": 0.05, "away_gg_count": 0.05, "h2h_gg_count": 0.035, "home_gg_ratio": 0.03, "away_gg_ratio": 0.03, "home_consistency": 0.03, "away_consistency": 0.03, "compatibility_index": 0.07, "pressure_index": 0.04}
            
            raw_score = sum(layers[k] * weights[k] for k in weights)
            gg_prob_pct = round(sigmoid(raw_score - 1.0) * 100, 2)

            # --- KEY PLAYER AUDIT ---
            h_key = get_key_players_recent_starts(hid) | get_key_players_minutes(hid, sid)
            a_key = get_key_players_recent_starts(aid) | get_key_players_minutes(aid, sid)
            h_miss = len([p for p in h_key if p not in get_today_starters_from_fixture(fx.get("lineups"), hid)])
            a_miss = len([p for p in a_key if p not in get_today_starters_from_fixture(fx.get("lineups"), aid)])

            # --- STANDINGS (UPGRADED OUTSIDE ENGINE) ---
            standings = fetch_team_standing(lid, sid)
            pos_map = {int(s["participant_id"]): int(s["position"]) for s in standings if s.get("participant_id")}
            h_pos, a_pos = pos_map.get(hid, 99), pos_map.get(aid, 99)

            # Calculate safe absolute distance, ignoring unranked Cup teams (99 or 0)
            valid_ranks = (1 <= h_pos <= 90) and (1 <= a_pos <= 90)
            pos_diff = abs(h_pos - a_pos) if valid_ranks else 999
            meets_table_req = (valid_ranks and MIN_TABLE_DISTANCE <= pos_diff <= MAX_TABLE_DISTANCE)

            # --- DEDUPLICATED COUNTS ---
            f_map = {}
            for f in l5h + l5a + h2h_data:
                fid_tmp = f.get("id")
                if fid_tmp and fid_tmp not in f_map:
                    g1, g2 = extract_final_goals_from_scores(f.get("scores", []))
                    f_map[fid_tmp] = {"gg": bool(g1 and g2 and g1>0 and g2>0), "t": (g1+g2) if (g1 and g2) else 0}
            total_gg_count, total_goal_count = sum(1 for v in f_map.values() if v["gg"]), sum(v["t"] for v in f_map.values())

            # 🟢[UPGRADE: LAST 3 ADDED FOR THE FILTER]
            picks.append({
                "fixture_id": fx.get("id"), 
                "league_id": lid, 
                "home_team": h_p['name'], "away_team": a_p['name'],
                "home_missing_key_players_count": h_miss, "away_missing_key_players_count": a_miss,
                "h2h_goal_parity": abs(sum(g[0] for g in[(extract_final_goals_from_scores(m.get("scores")) or (0,0)) for m in h2h_data]) - sum(g[1] for g in[(extract_final_goals_from_scores(m.get("scores")) or (0,0)) for m in h2h_data])),
                "concede_parity": abs(h_concede - a_concede), 
                "home_gg_count": h_gg_c, "away_gg_count": a_gg_c, "h2h_gg_count": h2h_gg_c,
                
                # 🟢 INJECTED THE LAST 3 MOMENTUM METRICS HERE:
                "home_gg_last3": count_btts_last_n(l5h, 3),
                "away_gg_last3": count_btts_last_n(l5a, 3),

                "home_goal_count": h_scored, "away_goal_count": a_scored, "total_gg_count": total_gg_count, "total_goal_count": total_goal_count,
                "tier": "Tier 1A" if (meets_table_req and total_gg_count >= 9) else "Below Threshold",
                "table_distance": pos_diff if valid_ranks else "N/A", 
                "gg_prob_pct": gg_prob_pct, "home_position": h_pos, "away_position": a_pos, "dominance_score": dominance_checks(layers)
            })
        except: continue

    df = pd.DataFrame(picks)
    if df.empty: return[]
    df = df.sort_values("gg_prob_pct", ascending=False).head(20)
    
    # SAVE SAFELY IN THE DYNAMIC DIRECTORY
    output_file_path = os.path.join(OUTPUT_DIR, "picks_gg2.csv")
    df.to_csv(output_file_path, index=False)
    print(f"\n[GG Stage 2] Saved top {len(df)} picks to {output_file_path}")

    return df.to_dict(orient="records")

if __name__ == "__main__":
    run_gg_engine_stage2(datetime.now(timezone.utc).strftime("%Y-%m-%d"))