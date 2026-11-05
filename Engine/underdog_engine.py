import os
import sys
import math
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from dateutil import parser
from collections import defaultdict, Counter

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
def run_underdog_engine(target_date):
    """
    Executes the Underdog Power Engine.
    Math, logic, and thresholds are 100% untouched.
    """
    # Ensure output directory exists safely
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # -------------------------
    # PRODUCTION CONFIGURATION
    # -------------------------
    API_TOKEN = os.getenv("SPORTMONKS_API_KEY")
    BASE_URL = "https://api.sportmonks.com/v3/football"

    # Market IDs
    MARKET_1X2 = 1
    MARKET_OU = 12
    MARKET_GG = 9

    # Production Pacing & Accuracy
    REQUEST_DELAY = 0.2
    MAX_RETRIES = 5
    BACKOFF_FACTOR = 1.8
    LOOKBACK_DAYS = 365

    # Underdog Pricing Boundary
    DOG_PRICE_THRESHOLD = 2.50

    if not API_TOKEN:
        print("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")
        return[]

    # -------------------------
    # MATH LAYER (DIXON-COLES)
    # -------------------------
    def calculate_dixon_coles_lambda(att_strength, def_weakness, global_mean):
        """λ = Underdog_Attack * Favorite_Defense * Global_Mean"""
        return max(0.01, att_strength * def_weakness * global_mean)

    def poisson_prob(k, lamb):
        """Standard Poisson Formula: (e^-λ * λ^k) / k!"""
        if lamb <= 0: lamb = 0.01
        return (math.exp(-lamb) * (lamb**k)) / math.factorial(k)

    def get_underdog_score_prob(lamb):
        """% chance of scoring 1 or more goals."""
        prob_zero = poisson_prob(0, lamb)
        return round((1 - prob_zero) * 100, 2)

    # -------------------------
    # HTTP & UNLIMITED PAGINATION (STRICT)
    # -------------------------
    def GET(path, params=None):
        if params is None: params = {}
        params.setdefault("api_token", API_TOKEN)
        url = f"{BASE_URL}{path}"
        for attempt in range(MAX_RETRIES):
            try:
                r = requests.get(url, params=params, timeout=30)
                if r.status_code == 200: 
                    return r.json()
                if r.status_code == 429:
                    time.sleep(BACKOFF_FACTOR ** attempt)
                    continue
                if r.status_code >= 500:
                    time.sleep(2)
                    continue
            except: 
                time.sleep(1)
        return {"data":[]}

    def fetch_all_fixtures_for_date(date_str):
        """YOUR FULL PAGINATION CODE: Captures all fixtures (500+)"""
        all_fx =[]
        page = 1
        while True:
            params = {
                "include": "participants;scores;league;season",
                "per_page": 50,
                "page": page
            }
            resp = GET(f"/fixtures/date/{date_str}", params=params)
            data = resp.get("data",[])
            
            # STOP when SportMonks returns no fixtures for this page
            if not data:
                break
                
            all_fx.extend(data)
            page += 1
            time.sleep(REQUEST_DELAY)
        return all_fx

    # -------------------------
    # RUTHLESS DATA EXTRACTION (VERIFIED V3)
    # -------------------------
    def extract_goals_v3(scores):
        """Deep verification of nested Sportmonks v3 goals: score -> goals."""
        home, away = None, None
        for entry in (scores or[]):
            if not isinstance(entry, dict): continue
            s_obj = entry.get("score") or entry
            p = s_obj.get("participant") or entry.get("participant")
            g = s_obj.get("goals") if isinstance(s_obj, dict) else entry.get("goals")
            if g is not None:
                val = int(g)
                if p == "home": home = val if home is None else max(home, val)
                elif p == "away": away = val if away is None else max(away, val)
        return home, away

    def get_match_raw_stats(fx, team_id):
        """Extracts Scored, Conceded, Outcome, and SOT for a side."""
        hg, ag = extract_goals_v3(fx.get("scores",[]))
        if hg is None: return None
        
        is_home = False
        for p in fx.get("participants",[]):
            if int(p.get("id")) == int(team_id):
                if (p.get("meta") or {}).get("location") == "home":
                    is_home = True
                break
                
        scored = hg if is_home else ag
        conceded = ag if is_home else hg
        
        # Accurate Draw check via score comparison
        is_draw = (hg == ag)
        res = "D" if is_draw else ("W" if scored > conceded else "L")
        
        # Extract SOT
        sot = 0
        stats = fx.get("statistics",[])
        if isinstance(stats, dict): stats = list(stats.values())
        for s in stats:
            t = s.get("type", {})
            name = t.get("name", "").lower() if isinstance(t, dict) else ""
            if "shots on target" in name and int(s.get("participant_id", 0)) == int(team_id):
                sot = int(s.get("data", {}).get("value") if isinstance(s.get("data"), dict) else (s.get("value") or 0))
                break
                
        return {
            "s": scored, "c": conceded, "res": res, 
            "total": hg + ag, "sot": sot, "is_draw": is_draw
        }

    # -------------------------
    # ACCURATE ODDS SNIPER (ADAPTIVE FALLBACK)
    # -------------------------
    def sniper_fetch_odds(fixture_id):
        """Guarantees odds accuracy via dedicated pre-match endpoint."""
        data = GET(f"/odds/pre-match/fixtures/{fixture_id}")
        odds_list = data.get("data",[])
        res = {"h": None, "a": None}
        
        for o in odds_list:
            if o.get("market_id") == MARKET_1X2:
                lbl = str(o.get("label", "")).lower()
                try: val = float(o.get("value"))
                except: continue
                
                if "1" in lbl or "home" in lbl:
                    if res["h"] is None or o.get("bookmaker_id") == 20: res["h"] = val
                elif "2" in lbl or "away" in lbl:
                    if res["a"] is None or o.get("bookmaker_id") == 20: res["a"] = val
        return res

    # -------------------------
    # THE UNDERDOG POWER ENGINE (TOTAL ACCURACY)
    # -------------------------
    print("\n--- ALIENEDGE UNDERDOG BACKTESTER ---")
    print(f"[INFO] Engine Start: Underdog Power & Vulnerability - {target_date}")

    # Forensic History Anchors (Calculated relative to target_date)
    dt_obj = datetime.strptime(target_date, "%Y-%m-%d")
    hist_end = (dt_obj - timedelta(days=1)).date()
    hist_start = (dt_obj - timedelta(days=LOOKBACK_DAYS)).date()

    # 1. Fetch All Matches for that date
    fixtures = fetch_all_fixtures_for_date(target_date)
    if not fixtures:
        print(f"[ERROR] No fixtures found for {target_date}")
        return[]

    # 2. History Prefetch
    team_ids = {p['id'] for fx in fixtures for p in fx.get("participants",[]) if p.get('id')}
    team_histories = {}
    print(f"[INFO] Analyzing {len(team_ids)} teams (Strict History Verification for {target_date})...")
    for tid in team_ids:
        # History is anchored to the day BEFORE the target_date
        h_data = GET(f"/fixtures/between/{hist_start}/{hist_end}/{tid}", 
                     params={"include":"scores;participants;statistics.type", "filters":"fixtureStates:5", "order":"desc", "per_page": 40})
        team_histories[tid] = h_data.get("data",[])
        time.sleep(0.05)

    global_mean = 1.35 
    raw_output =[]

    for fx in fixtures:
        try:
            fid = fx['id']
            parts = fx.get("participants",[])
            league_name = fx.get("league", {}).get("name", "Unknown")
            if len(parts) < 2: continue
            
            h_p = next(p for p in parts if p.get("meta", {}).get("location") == "home")
            a_p = next(p for p in parts if p.get("meta", {}).get("location") == "away")
            hid, aid = int(h_p['id']), int(a_p['id'])

            odds = sniper_fetch_odds(fid)
            if not odds["h"] or not odds["a"]: continue

            # Identify Underdog strictly by Price
            is_home_dog = odds["h"] > odds["a"]
            dog_id, fav_id = (hid, aid) if is_home_dog else (aid, hid)
            dog_name = h_p['name'] if is_home_dog else a_p['name']
            dog_venue = "home" if is_home_dog else "away"

            # RECTIFICATION: ACCURATE H2H DOG GOALS (STRICT CHECK)
            h2h_data = GET(f"/fixtures/head-to-head/{hid}/{aid}", params={"include":"scores;participants", "per_page": 5})
            h2h_matches = h2h_data.get("data", [])[:5]
            
            h2h_dog_gs_count = 0; h2h_dog_p_sum = 0; h2h_fav_p_sum = 0
            for m in h2h_matches:
                dst = get_match_raw_stats(m, dog_id)
                fst = get_match_raw_stats(m, fav_id)
                if dst:
                    h2h_dog_gs_count += dst["s"]
                    h2h_dog_p_sum += dst["total"]
                if fst:
                    h2h_fav_p_sum += fst["total"]

            # RECTIFICATION: ACCURATE METRICS BLOCK
            def get_accuracy_metrics(tid, history, required_venue):
                # 1. Last 5 Overall
                ov_5 = history[:5]
                gs, gc, wins, ov_p = 0, 0, 0, 0
                no_draw_streak = True
                conceded_count = 0 # For Vulnerability
                cs_streak = 0
                
                for i, m in enumerate(ov_5):
                    st = get_match_raw_stats(m, tid)
                    if st:
                        gs += st["s"]; gc += st["c"]; ov_p += st["total"]
                        # RECTIFICATION: Use numeric boolean for Draw Check
                        if i < 3 and st["is_draw"]: no_draw_streak = False
                        if st["res"] == "W": wins += 1
                        if st["c"] > 0: conceded_count += 1
                        
                        # Calculate Clean Sheet Streak (from most recent match backward)
                        if i == cs_streak and st["c"] == 0:
                            cs_streak += 1
                
                # 2. Last 5 Venue-Specific
                v_5 =[]
                for m in history:
                    is_v = any(p['id'] == tid and (p.get('meta') or {}).get('location') == required_venue for p in m.get('participants',[]))
                    if is_v: v_5.append(m)
                    if len(v_5) == 5: break
                
                v_wins, v_gs, v_gc, v_p = 0, 0, 0, 0
                for m in v_5:
                    st = get_match_raw_stats(m, tid)
                    if st:
                        v_gs += st["s"]; v_gc += st["c"]; v_p += st["total"]
                        if st["res"] == "W": v_wins += 1

                # Cerberus Momentum
                t3_stats =[get_match_raw_stats(m, tid) for m in history[:3] if get_match_raw_stats(m, tid)]
                t3_gs = sum(x["s"] for x in t3_stats)
                t3_sot = sum(x["sot"] for x in t3_stats)
                
                is_hot = (t3_gs/3) > (gs/5)
                # DUE: High shooting but low finishing
                due = (t3_sot/3 >= 4.0) and (t3_gs/3 <= 0.7)

                return {
                    "att": (gs/5 + v_gs/5) / (2 * global_mean),
                    "dfn": (gc/5 + v_gc/5) / (2 * global_mean),
                    "ov_p": ov_p, "v_p": v_p, "no_draw": no_draw_streak,
                    "is_hot": is_hot, "due": due, "v_wins": v_wins,
                    "conceded_5": conceded_count, "cs_streak": cs_streak
                }

            dog_m = get_accuracy_metrics(dog_id, team_histories.get(dog_id,[]), dog_venue)
            fav_m = get_accuracy_metrics(fav_id, team_histories.get(fav_id,[]), "away" if dog_venue == "home" else "home")

            # DIXON-COLES
            dc_lamb = calculate_dixon_coles_lambda(dog_m["att"], fav_m["dfn"], global_mean)
            if h2h_matches: dc_lamb = (dc_lamb + (h2h_dog_gs_count/len(h2h_matches))) / 2
            dog_prob = get_underdog_score_prob(dc_lamb)

            # RECTIFICATION: BOTH_NO_DRAW_3
            both_no_draw = dog_m["no_draw"] and fav_m["no_draw"]
            
            # PARITY: Sum(Venue+Overall+H2H)
            parity_gap = (dog_m["v_p"] + dog_m["ov_p"] + h2h_dog_p_sum) - (fav_m["v_p"] + fav_m["ov_p"] + h2h_fav_p_sum)

            raw_output.append({
                "fixture_id": fid,  # <-- Added strictly for Master Engine tracking
                "fixture": f"{h_p['name']} vs {a_p['name']}",
                "league": league_name,
                "underdog_team": dog_name,
                "dog_odds": odds["h"] if is_home_dog else odds["a"],
                "dog_score_prob_num": dog_prob,
                "dog_score_prob": f"{dog_prob}%",
                "parity_gap": parity_gap,
                "dog_att_strength": round(dog_m["att"], 2),
                "fav_def_weakness": round(fav_m["dfn"], 2),
                "dog_is_hot": dog_m["is_hot"],
                "dog_due_goal": dog_m["due"],
                "both_no_draw_3": both_no_draw,
                "fav_vulnerability_5": f"{fav_m['conceded_5']}/5", 
                "fav_cs_streak": fav_m["cs_streak"],            
                "h2h_dog_gs_last_5": h2h_dog_gs_count,
                "dog_venue_wins": dog_m["v_wins"]
            })

        except Exception as e: pass

    df = pd.DataFrame(raw_output)
    if not df.empty:
        # Sort by Underdog Power
        df = df.sort_values(by=["dog_score_prob_num", "dog_att_strength"], ascending=[False, False]).reset_index(drop=True)
        df = df.drop(columns=["dog_score_prob_num"])

        # --- SAVE SAFELY TO THE DYNAMIC OUTPUT FOLDER ---
        # FIXED: Only touched this section to exactly match what main.py requires
        csv_fn = os.path.join(OUTPUT_DIR, f"backtest_underdog_{target_date}.csv")
        json_fn = os.path.join(OUTPUT_DIR, f"backtest_underdog_{target_date}.json")
        
        df.to_csv(csv_fn, index=False)
        df.to_json(json_fn, orient="records", indent=2)
        
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 1000)
        print(f"\n[Underdog Engine] Saved {len(df)} picks to {csv_fn}")
        print(df.to_string(index=False))
        
        # Return directly to Aggregator memory
        return df.to_dict(orient="records")
    else:
        print("[Underdog Engine] No fixtures matched the engine criteria.")
        return