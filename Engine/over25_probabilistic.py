import os
import time
import json
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from dateutil import parser

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
from dotenv import load_dotenv
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS (SUB-FOLDER FIX) ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

# ==============================================================================
# 📦 THE BLACK BOX WRAPPER (CALLABLE BY THE MASTER API/SCHEDULER)
# ==============================================================================
def run_over25_stage1(target_date):
    """
    Executes Over 2.5 Engine Stage 1.
    Math, logic, and thresholds are 100% untouched.
    """
    # Ensure directories exist safely
    for directory in [OUTPUT_DIR, DATA_DIR]:
        os.makedirs(directory, exist_ok=True)
        
    # -------------------------
    # CONFIGURATION
    # -------------------------
    API_KEY = os.getenv("SPORTMONKS_API_KEY")      
    BASE_URL = "https://api.sportmonks.com/v3/football"
    TEAM_LOOKBACK_DAYS = 365
    REQUEST_DELAY_SEC = 0.18
    LAST_N_GAMES = 5
    BOOKMAKER_ID = 2
    ODDS_CSV = os.path.join(DATA_DIR, "odds.csv") # Dynamically routed to data folder

    NUM_PAST_FIXTURES = 100
    LEAGUE_SCALE = 0.3
    
    if not API_KEY:
        print("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")
        return[]

    # -------------------------
    # HELPERS
    # -------------------------
    def GET(path, params=None):
        if params is None: params = {}
        params.setdefault("api_token", API_KEY)
        try:
            r = requests.get(f"{BASE_URL}{path}", params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception:
            time.sleep(1)
            return {}

    def extract_final_goals_from_scores(scores):
        home, away = None, None
        for entry in scores or[]:
            s = (entry or {}).get("score", {})
            p, g = s.get("participant"), s.get("goals")
            if p == "home" and isinstance(g, int):
                home = g if home is None else max(home, g)
            if p == "away" and isinstance(g, int):
                away = g if away is None else max(away, g)
        return home, away

    def is_home(fx, team_id):
        return any(p.get("id")==team_id and (p.get("meta") or {}).get("location")=="home" for p in fx.get("participants",[]))

    def is_away(fx, team_id):
        return any(p.get("id")==team_id and (p.get("meta") or {}).get("location")=="away" for p in fx.get("participants",[]))

    def get_team_and_opponent_goals_from_fixture(fx, team_id):
        hg, ag = extract_final_goals_from_scores(fx.get("scores",[]))
        if hg is None or ag is None: return None, None
        for p in fx.get("participants",[]):
            if p.get("id")==team_id:
                loc = (p.get("meta") or {}).get("location")
                return (hg, ag) if loc=="home" else (ag, hg)
        return None, None

    def form_volatility(fixtures, team_id, n=10):
        ppg =[]
        for i in range(1, n+1):
            subset = (fixtures or [])[:i]
            vals =[max(0, (get_team_and_opponent_goals_from_fixture(f, team_id)[0] or 0)) for f in subset]
            if vals: ppg.append(np.mean(vals))
        return float(np.std(ppg)) if ppg else 0.0

    def opponent_defensive_weakness(fixtures, team_id, n=5):
        no_clean, conceded = [],[]
        for fx in (fixtures or [])[:n]:
            tg, og = get_team_and_opponent_goals_from_fixture(fx, team_id)
            if tg is None or og is None: continue
            if og > 0: no_clean.append(1)
            conceded.append(og)
        return sum(no_clean), float(np.mean(conceded)) if conceded else 0.0

    def count_over25(fixtures):
        c = 0
        for fx in fixtures:
            hg, ag = extract_final_goals_from_scores(fx.get("scores",[]))
            if hg is not None and ag is not None and (hg + ag) >= 3:
                c += 1
        return c

    def count_wins(fixtures, team_id):
        wins = 0
        for fx in fixtures:
            tg, og = get_team_and_opponent_goals_from_fixture(fx, team_id)
            if tg is not None and og is not None and tg > og:
                wins += 1
        return wins

    def parse_decimal_odds(x):
        try: return float(x)
        except: return None

    def load_odds_csv(path=ODDS_CSV):
        try:
            df = pd.read_csv(path)
            if {"fixture_id","decimal_odds"}.issubset(df.columns):
                return df.astype({"fixture_id": str})
        except: pass
        return None

    # -------------------------
    # LEAGUE WEIGHTING
    # -------------------------
    def compute_league_over25_weight(league_id, num_fixtures=NUM_PAST_FIXTURES, scale=LEAGUE_SCALE):
        end_dt = datetime.now(timezone.utc).date() - timedelta(days=1)
        start_dt = end_dt - timedelta(days=365*2)
        over_count, total_count, page = 0, 0, 1
        while total_count < num_fixtures:
            try:
                resp = GET(f"/fixtures/between/{start_dt}/{end_dt}/{league_id}", params={"per_page":50,"page":page, "include":"scores"})
            except Exception:
                break
            fixtures = resp.get("data",[])
            if not fixtures: break
            for fx in fixtures:
                if total_count >= num_fixtures: break
                hg, ag = extract_final_goals_from_scores(fx.get("scores",[]))
                if hg is None or ag is None: continue
                total_count += 1
                if hg + ag >= 3: over_count += 1
            page += 1
            time.sleep(REQUEST_DELAY_SEC)
        if total_count == 0: return 0.0
        return round((over_count / total_count) * scale, 3)

    def fetch_fixtures_for_date(date_str):
        all_fx, page =[], 1
        while True:
            try:
                data = GET(f"/fixtures/date/{date_str}", params={"per_page":50,"page":page, "include":"participants;scores;odds"})
            except Exception:
                break
            fx = data.get("data",[])
            if not fx: break
            all_fx.extend(fx)
            page += 1
            time.sleep(REQUEST_DELAY_SEC)
        return all_fx

    def compute_all_league_weights(fixtures_list):
        league_ids = {f["league_id"] for f in fixtures_list if "league_id" in f}
        weights = {}
        for lid in league_ids:
            try:
                w = compute_league_over25_weight(lid)
                weights[lid] = w
                print(f"League ID {lid} weight: {w}")
            except Exception as e:
                print(f"League {lid} fetch error: {e}")
                weights[lid] = 0.0
        return weights

    # -------------------------
    # ODDS HELPER
    # -------------------------
    def fetch_over25_odds(fixture, bookmaker_id=BOOKMAKER_ID, csv_df=None):
        odds_list = fixture.get("odds", []) or[]
        for o in odds_list:
            try:
                if (o.get("bookmaker_id") == bookmaker_id and
                    o.get("market_description","").lower().startswith("goals over/under") and
                    str(o.get("total")) == "2.5" and
                    o.get("label","").lower() == "over"):
                    return float(o.get("value"))
            except:
                continue
        if csv_df is not None:
            row = csv_df[csv_df["fixture_id"] == str(fixture.get("id"))]
            if not row.empty:
                return float(row.iloc[0]["decimal_odds"])
        return None

    # -------------------------
    # FETCHERS
    # -------------------------
    def fetch_last_finished_fixtures_for_team(team_id, max_needed=50):
        end_dt = datetime.now(timezone.utc).date() - timedelta(days=1)
        start_dt = end_dt - timedelta(days=TEAM_LOOKBACK_DAYS)
        try:
            data = GET(f"/fixtures/between/{start_dt}/{end_dt}/{team_id}", params={"include":"participants;scores;state","filters":"fixtureStates:5","sortBy":"starting_at","order":"desc","per_page":max_needed})
            return (data.get("data") or [])[:max_needed]
        except:
            return[]

    def fetch_last_h2h(team1, team2, n=5):
        try:
            data = GET(f"/fixtures/head-to-head/{team1}/{team2}", params={"include":"scores;participants","sortBy":"starting_at","order":"desc","per_page":n})
            return (data.get("data") or [])[:n]
        except:
            return[]

    # -------------------------
    # SIX LAYER FUNCTIONS
    # -------------------------
    def recent_form_trend(fixtures_list, team_id):
        last_n = fixtures_list[:LAST_N_GAMES]
        scored =[get_team_and_opponent_goals_from_fixture(f, team_id)[0] or 0 for f in last_n]
        conceded =[get_team_and_opponent_goals_from_fixture(f, team_id)[1] or 0 for f in last_n]
        if not scored: return {"home_offense_trend": 0, "home_defense_trend": 0}
        return {"home_offense_trend": np.mean(scored), "home_defense_trend": np.mean(conceded)}

    def weighted_goals(fixtures_list, team_id):
        last_n = fixtures_list[:LAST_N_GAMES]
        if not last_n: return {"home_weighted_scored": 0, "home_weighted_conceded": 0}
        weights_arr = np.arange(len(last_n), 0, -1)
        scored = np.array([get_team_and_opponent_goals_from_fixture(f, team_id)[0] or 0 for f in last_n])
        conceded = np.array([get_team_and_opponent_goals_from_fixture(f, team_id)[1] or 0 for f in last_n])
        
        return {"home_weighted_scored": np.dot(scored, weights_arr)/weights_arr.sum(),
                "home_weighted_conceded": np.dot(conceded, weights_arr)/weights_arr.sum()}

    def venue_adjustment(fixtures_list, team_id, location="home"):
        last_n = [f for f in fixtures_list[:LAST_N_GAMES] if ((is_home(f, team_id) if location=="home" else is_away(f, team_id)))]
        scored = np.mean([get_team_and_opponent_goals_from_fixture(f, team_id)[0] or 0 for f in last_n]) if last_n else 0
        conceded = np.mean([get_team_and_opponent_goals_from_fixture(f, team_id)[1] or 0 for f in last_n]) if last_n else 0
        return {"home_venue_scored": scored, "home_venue_conceded": conceded}

    def fatigue_factor(team_fixtures):
        today = datetime.now(timezone.utc)
        recent_games = []
        for f in team_fixtures[:LAST_N_GAMES*2]:
            try:
                fx_dt = parser.isoparse(f["starting_at"])
                if fx_dt.tzinfo is None:
                    fx_dt = fx_dt.replace(tzinfo=timezone.utc)

                if abs((fx_dt - today).days) < 10:
                    recent_games.append(f)
            except:
                continue
        return len(recent_games)/10  # 0-1 scale

    def h2h_volatility(fixtures_list, team_id):
        goals =[get_team_and_opponent_goals_from_fixture(f, team_id)[0] or 0 for f in fixtures_list]
        volatility = np.std(goals) if goals else 0
        big_match_factor = 1 + (np.mean(goals) > 2 if goals else 0)
        return {"h2h_volatility": volatility, "big_match_factor": big_match_factor}

    # -------------------------
    # MAIN EXECUTION LOGIC
    # -------------------------
    odds_csv_df = load_odds_csv()
    fixtures = fetch_fixtures_for_date(target_date)
    print(f"{len(fixtures)} fixtures found for {target_date}")

    if not fixtures: 
        return[]

    league_weights = compute_all_league_weights(fixtures)
    team_cache, picks = {}, []

    for fx in fixtures:
        parts = fx.get("participants", []) or[]
        if len(parts) < 2: continue

        home = next((p for p in parts if (p.get("meta") or {}).get("location")=="home"), parts[0])
        away = next((p for p in parts if (p.get("meta") or {}).get("location")=="away"), parts[1])

        home_id, away_id = str(home["id"]), str(away["id"])
        home_name, away_name = home.get("name"), away.get("name")
        league_id = fx.get("league_id")
        league_over25 = league_weights.get(league_id, 0.0)
        
        # EXTRACT TIME for Aggregator
        start_time = fx.get("starting_at", "")[11:16]

        for tid in (home_id, away_id):
            if tid not in team_cache:
                team_cache[tid] = fetch_last_finished_fixtures_for_team(tid)
                time.sleep(REQUEST_DELAY_SEC)

        last5_home = team_cache.get(home_id, [])[:LAST_N_GAMES]
        last5_away = team_cache.get(away_id, [])[:LAST_N_GAMES]

        # --- Basic stats ---
        h_scored = sum([get_team_and_opponent_goals_from_fixture(f,int(home_id))[0] or 0 for f in last5_home])
        h_conceded = sum([get_team_and_opponent_goals_from_fixture(f,int(home_id))[1] or 0 for f in last5_home])
        a_scored = sum([get_team_and_opponent_goals_from_fixture(f,int(away_id))[0] or 0 for f in last5_away])
        a_conceded = sum([get_team_and_opponent_goals_from_fixture(f,int(away_id))[1] or 0 for f in last5_away])

        h2h_fx = fetch_last_h2h(int(home_id), int(away_id), LAST_N_GAMES)
        h2h_goals = sum([sum(get_team_and_opponent_goals_from_fixture(f,int(home_id)) or [0,0]) for f in h2h_fx])

        home_over25_count = count_over25(last5_home)
        away_over25_count = count_over25(last5_away)
        h2h_over25_count  = count_over25(h2h_fx)

        home_wins = count_wins(last5_home, int(home_id))
        away_wins = count_wins(last5_away, int(away_id))

        # --- Layer calculations ---
        home_form = recent_form_trend(last5_home, int(home_id))
        away_form = recent_form_trend(last5_away, int(away_id))
        home_weighted = weighted_goals(last5_home, int(home_id))
        away_weighted = weighted_goals(last5_away, int(away_id))
        home_venue = venue_adjustment(last5_home, int(home_id), "home")
        away_venue = venue_adjustment(last5_away, int(away_id), "away")
        home_fat = fatigue_factor(last5_home)
        away_fat = fatigue_factor(last5_away)
        h2h_vol = h2h_volatility(h2h_fx, int(home_id))

        # xG proxy
        home_xg = h_scored/max(1,LAST_N_GAMES) - h_conceded/max(1,LAST_N_GAMES)
        away_xg = a_scored/max(1,LAST_N_GAMES) - a_conceded/max(1,LAST_N_GAMES)

        # Over 2.5 odds
        ov25 = fetch_over25_odds(fx, BOOKMAKER_ID, odds_csv_df)

        # --- Composite score ---
        layers = {
            "home_avg_goals": h_scored / max(1,LAST_N_GAMES),
            "home_concede": h_conceded / max(1,LAST_N_GAMES),
            "away_avg_goals": a_scored / max(1,LAST_N_GAMES),
            "away_concede": a_conceded / max(1,LAST_N_GAMES),
            "home_offense_trend": home_form["home_offense_trend"],
            "home_defense_trend": home_form["home_defense_trend"],
            "away_offense_trend": away_form["home_offense_trend"],
            "away_defense_trend": away_form["home_defense_trend"],
            "home_weighted_scored": home_weighted["home_weighted_scored"],
            "home_weighted_conceded": home_weighted["home_weighted_conceded"],
            "away_weighted_scored": away_weighted["home_weighted_scored"],
            "away_weighted_conceded": away_weighted["home_weighted_conceded"],
            "home_venue_scored": home_venue["home_venue_scored"],
            "home_venue_conceded": home_venue["home_venue_conceded"],
            "away_venue_scored": away_venue["home_venue_scored"],
            "away_venue_conceded": away_venue["home_venue_conceded"],
            "home_volatility": form_volatility(last5_home, int(home_id)),
            "away_volatility": form_volatility(last5_away, int(away_id)),
            "home_opp_avg_concede": opponent_defensive_weakness(last5_away, int(away_id))[1],
            "away_opp_avg_concede": opponent_defensive_weakness(last5_home, int(home_id))[1],
            "h2h_avg_goals": h2h_goals / max(len(h2h_fx),1),
            "h2h_volatility": h2h_vol["h2h_volatility"],
            "big_match_factor": h2h_vol["big_match_factor"],
            "league_over25": league_over25,
            "home_fatigue": -home_fat,
            "away_fatigue": -away_fat,
            "xg_diff": home_xg - away_xg
        }

        weights = {
            "home_avg_goals": 0.08,
            "home_concede": 0.05,
            "away_avg_goals": 0.08,
            "away_concede": 0.05,
            "home_offense_trend": 0.05,
            "home_defense_trend": 0.05,
            "away_offense_trend": 0.05,
            "away_defense_trend": 0.05,
            "home_weighted_scored": 0.05,
            "home_weighted_conceded": 0.05,
            "away_weighted_scored": 0.05,
            "away_weighted_conceded": 0.05,
            "home_venue_scored": 0.03,
            "home_venue_conceded": 0.03,
            "away_venue_scored": 0.03,
            "away_venue_conceded": 0.03,
            "home_volatility": 0.02,
            "away_volatility": 0.02,
            "home_opp_avg_concede": 0.03,
            "away_opp_avg_concede": 0.03,
            "h2h_avg_goals": 0.05,
            "h2h_volatility": 0.02,
            "big_match_factor": 0.05,
            "league_over25": 0.1,
            "home_fatigue": -0.05,
            "away_fatigue": -0.05,
            "xg_diff": 0.05
        }

        final_score = sum(layers[k]*weights[k] for k in layers)

        picks.append({
            "id": fx.get("id"),  # <--- CRITICAL FOR AGGREGATOR
            "fixture": f"{home_name} vs {away_name}",
            "time": start_time, # <--- CRITICAL FOR AGGREGATOR
            "league_id": league_id,
            "over_2_5_odds": ov25,
            "final_score": round(final_score,4),
            **layers
        })

    # -------------------------
    # OUTPUT (MODIFIED FOR AGGREGATOR COMPATIBILITY)
    # -------------------------
    df = pd.DataFrame(picks)
    if not df.empty:
        # CONVERT SCORE TO PROBABILITY (Using Sigmoid for normalization)
        df["probability_val"] = df["final_score"].apply(lambda x: 1 / (1 + np.exp(-(x - 1.3) * 2.0)))
        
        # FILTER (> 60%)
        df_filtered = df[df["probability_val"] > 0.60].copy()

        if not df_filtered.empty:
            # Map columns to Aggregator standard
            df_filtered["Fixture"] = df_filtered["fixture"]
            df_filtered["Time"] = df_filtered["time"]
            df_filtered["Odds"] = df_filtered["over_2_5_odds"]
            df_filtered["Confidence"] = df_filtered["probability_val"].apply(lambda x: f"{int(x*100)}%")
            df_filtered["Algorithm"] = "Probabilistic_6_Layer"
            
            # Select proper columns INCLUDING 'id'
            df_export = df_filtered[["id", "Fixture", "Time", "Odds", "Confidence", "Algorithm"]]
            df_export = df_export.sort_values("Confidence", ascending=False)
            
            # --- SAVE SAFELY TO THE DYNAMIC OUTPUT FOLDER ---
            csv_fn = os.path.join(OUTPUT_DIR, "over25_stage1_picks.csv")
            json_fn = os.path.join(OUTPUT_DIR, "over25_stage1_picks.json")
            
            df_export.to_csv(csv_fn, index=False)
            df_export.to_json(json_fn, orient="records", indent=2)
            
            print(f"\n[CODE 2 / O2.5 Stage 1] Saved {len(df_filtered)} picks (> 60%) to {csv_fn}")
            print(df_export.to_string(index=False))
            
            # Return straight to the Master Aggregator memory
            return df_export.to_dict(orient="records")
        else:
            print("\n[CODE 2 / O2.5 Stage 1] No picks found above 60% probability.")
            return[]
    else:
        print("No fixtures to rank.")
        return[]

# Allow local testing if someone presses "Run" on this specific file
if __name__ == "__main__":
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_over25_stage1(today_date)