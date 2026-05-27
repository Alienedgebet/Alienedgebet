import os
import sys
import math
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from dateutil import parser
from collections import defaultdict
from dotenv import load_dotenv

# -------------------------
# PRODUCTION CONFIGURATION & PATHS
# -------------------------
load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

API_TOKEN = os.getenv("SPORTMONKS_API_KEY") or "hD4F4FIFwNW5BxKa6Y0fCCLtB0KkiNRxtULDdsrO3VPss1IMV4HJihBkxwI4"
BASE_URL = "https://api.sportmonks.com/v3/football"

# Market IDs for Accurate Odds Sniper
MARKET_1X2 = 1
MARKET_OU = 12
MARKET_GG = 9

REQUEST_DELAY = 0.2
MAX_RETRIES = 5

# -------------------------
# POISSON PROBABILITY MATH
# -------------------------
def calculate_poisson(k, lamb):
    """Standard Poisson Formula: (e^-λ * λ^k) / k!"""
    if lamb <= 0: lamb = 0.01
    return (math.exp(-lamb) * (lamb**k)) / math.factorial(k)

def assign_poisson_probs(home_lamb, away_lamb):
    """Simulates match outcomes up to 6-6 goals to get win/draw percentages."""
    prob_h = 0
    prob_a = 0
    prob_d = 0
    
    # 0 to 6 goal matrix for total accuracy
    for h in range(7):
        for a in range(7):
            p = calculate_poisson(h, home_lamb) * calculate_poisson(a, away_lamb)
            if h > a: prob_h += p
            elif a > h: prob_a += p
            else: prob_d += p
            
    return round(prob_h * 100, 2), round(prob_d * 100, 2), round(prob_a * 100, 2)

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
            if r.status_code == 200: return r.json()
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
        except:
            time.sleep(1)
    return {"data":[]}

def sleep_short():
    time.sleep(REQUEST_DELAY)

def fetch_all_fixtures_for_date(date_str):
    """YOUR FULL PAGINATION CODE: Captures all fixtures (500+)"""
    all_fx =[]
    page = 1
    while True:
        params = {
            "include": "participants;scores",
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
        sleep_short()

    return all_fx

# -------------------------
# RUTHLESS DATA EXTRACTION (VERIFIED V3)
# -------------------------
def extract_goals_v3(scores):
    """Accurately parses nested goals for Sportmonks v3."""
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

def get_match_stats(fx, team_id):
    """Returns raw metrics for a specific team in a match."""
    hg, ag = extract_goals_v3(fx.get("scores",[]))
    if hg is None or ag is None: return None
    
    is_home = False
    for p in fx.get("participants",[]):
        if int(p.get("id")) == int(team_id):
            if (p.get("meta") or {}).get("location") == "home":
                is_home = True
            break
            
    scored = hg if is_home else ag
    conceded = ag if is_home else hg
    res = "W" if scored > conceded else ("D" if scored == conceded else "L")
    return {
        "scored": scored, "conceded": conceded, "res": res, 
        "total": scored + conceded, "is_even": (hg + ag) % 2 == 0
    }

# -------------------------
# ACCURATE ODDS SNIPER
# -------------------------
def sniper_fetch_odds(fixture_id):
    """Guarantees odds accuracy via dedicated pre-match endpoint."""
    data = GET(f"/odds/pre-match/fixtures/{fixture_id}")
    odds_list = data.get("data",[])
    res = {"home": None, "away": None}
    for o in odds_list:
        if o.get("market_id") == MARKET_1X2:
            lbl = str(o.get("label", "")).lower()
            val = o.get("value")
            if val:
                if "1" in lbl or "home" in lbl: res["home"] = float(val)
                elif "2" in lbl or "away" in lbl: res["away"] = float(val)
    return res

# -------------------------
# WIN FORECAST PRODUCTION ENGINE
# -------------------------
def run_win_forecast_engine(target_date=None):
    if not target_date:
        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
    print(f"[INFO] Production Engine Start: {target_date}")

    # 1. Fetch All Daily Matches
    fixtures = fetch_all_fixtures_for_date(target_date)
    if not fixtures:
        print("[ERROR] No fixtures found.")
        return

    # 2. Collect History
    team_ids = set()
    for fx in fixtures:
        for p in fx.get("participants",[]): 
            if p.get('id'): team_ids.add(p['id'])
    
    team_histories = {}
    print(f"[INFO] Extracting history for {len(team_ids)} teams...")
    for tid in team_ids:
        # Fetch 40 games to find enough Home/Away specific matches
        h_data = GET(f"/fixtures/between/{(datetime.now()-timedelta(days=365)).date()}/{(datetime.now()-timedelta(days=1)).date()}/{tid}", 
                     params={"include":"scores;participants", "filters":"fixtureStates:5", "order":"desc", "per_page": 40})
        team_histories[tid] = h_data.get("data",[])
        sleep_short()

    raw_output = []

    # 3. Analysis Layer
    print(f"[INFO] Running Analysis on {len(fixtures)} fixtures...")
    for fx in fixtures:
        try:
            fid = fx['id']
            parts = fx.get("participants",[])
            if len(parts) < 2: continue
            
            h_p = next(p for p in parts if p.get("meta", {}).get("location") == "home")
            a_p = next(p for p in parts if p.get("meta", {}).get("location") == "away")
            hid, aid = int(h_p['id']), int(a_p['id'])

            odds = sniper_fetch_odds(fid)
            
            # RECTIFICATION 1: Strict Last 5 H2H
            # FIX: Added order:desc and fixtureStates:5 to pull actual finished matches accurately
            h2h_data = GET(f"/fixtures/head-to-head/{hid}/{aid}", params={"include":"scores;participants", "per_page": 5, "order": "desc", "filters": "fixtureStates:5"})
            h2h_matches = h2h_data.get("data", [])[:5]
            
            h_h2h_wins = 0; a_h2h_wins = 0; h_h2h_parity_sum = 0; a_h2h_parity_sum = 0; h2h_h_gs = 0; h2h_a_gs = 0
            for m in h2h_matches:
                hst = get_match_stats(m, hid)
                ast = get_match_stats(m, aid)
                if hst:
                    if hst["res"] == "W": h_h2h_wins += 1
                    h_h2h_parity_sum += hst["total"]; h2h_h_gs += hst["scored"]
                if ast:
                    if ast["res"] == "W": a_h2h_wins += 1 # FIX: Explicitly calculate away wins instead of counting draws!
                    a_h2h_parity_sum += ast["total"]; h2h_a_gs += ast["scored"]

            # Metric Calculation
            def get_complex_metrics(tid, history, venue_type):
                # Last 5 Overall
                ov_5 = history[:5]
                ov_wins = 0; ov_gs = 0; ov_gc = 0; ov_loss = 0; ov_cs_fail = 0; ov_even = 0; no_draw_3 = True
                for i, m in enumerate(ov_5):
                    st = get_match_stats(m, tid)
                    if st:
                        ov_gs += st["scored"]; ov_gc += st["conceded"]
                        if st["res"] == "W": ov_wins += 1
                        elif st["res"] == "L": ov_loss += 1
                        if st["conceded"] > 0: ov_cs_fail += 1
                        if st["is_even"]: ov_even += 1
                        if i < 3 and st["res"] == "D": no_draw_3 = False
                
                # RECTIFICATION 2: Last 5 Venue-Specific (Strictly HT at Home / AT at Away)
                v_5 = []
                for m in history:
                    is_v = any(p['id'] == tid and (p.get('meta') or {}).get('location') == venue_type for p in m.get('participants',[]))
                    if is_v: v_5.append(m)
                    if len(v_5) == 5: break
                
                v_wins = 0; v_gs = 0; v_gc = 0
                for m in v_5:
                    st = get_match_stats(m, tid)
                    if st:
                        v_gs += st["scored"]; v_gc += st["conceded"]
                        if st["res"] == "W": v_wins += 1

                return {
                    "wins": ov_wins, "gs": ov_gs, "gc": ov_gc, "losses": ov_loss,
                    "cs_fail": ov_cs_fail, "even": ov_even, "no_draw_3": no_draw_3,
                    "v_wins": v_wins, "v_parity": (v_gs + v_gc), "ov_parity": (ov_gs + ov_gc),
                    "lambda": (ov_gs + v_gs) / 10 if (ov_gs + v_gs) > 0 else 0.5
                }

            h_m = get_complex_metrics(hid, team_histories.get(hid,[]), "home")
            a_m = get_complex_metrics(aid, team_histories.get(aid,[]), "away")

            # POISSON ASSIGNMENT
            h_final_lamb = (h_m["lambda"] + (h2h_h_gs/5 if h2h_matches else h_m["lambda"])) / 2
            a_final_lamb = (a_m["lambda"] + (h2h_a_gs/5 if h2h_matches else a_m["lambda"])) / 2
            p_win, p_draw, p_away = assign_poisson_probs(h_final_lamb, a_final_lamb)

            # RECTIFICATION 3: Complex Parity Formula
            h_total_p = h_m["v_parity"] + h_m["ov_parity"] + h_h2h_parity_sum
            a_total_p = a_m["v_parity"] + a_m["ov_parity"] + a_h2h_parity_sum
            parity_diff = h_total_p - a_total_p
            
            # RECTIFICATION 4: NO-DRAW BOTH Check (Last 3)
            both_no_draw_3 = h_m["no_draw_3"] and a_m["no_draw_3"]

            for side in ["home", "away"]:
                t_m, o_m = (h_m, a_m) if side == "home" else (a_m, h_m)
                w_odd = odds["home"] if side == "home" else odds["away"]
                
                # FIX: Use the accurate H2H win counts
                h2h_win_cnt = h_h2h_wins if side == "home" else a_h2h_wins
                prob = p_win if side == "home" else p_away

                raw_output.append({
                    "fixture_id": fid,
                    "fixture": f"{h_p['name']} vs {a_p['name']}",
                    "side": side,
                    "team_name": h_p['name'] if side == "home" else a_p['name'],
                    "win_odds": w_odd,
                    "poisson_win_prob_num": prob, # Keep numeric for sorting
                    "poisson_win_prob": f"{prob}%",
                    "poisson_draw_prob": f"{p_draw}%",
                    "last_5_wins_overall": t_m["wins"],
                    "last_5_wins_at_venue": t_m["v_wins"],
                    "last_5_goals_scored": t_m["gs"],
                    "opp_last_5_goals_scored": o_m["gs"],
                    "opp_last_5_losses": o_m["losses"],
                    "opp_last_5_conceded_raw": o_m["gc"],
                    "opp_no_clean_sheet_count": o_m["cs_fail"],
                    "h2h_wins_last_5": h2h_win_cnt,
                    "last_3_no_draw_BOTH": both_no_draw_3,
                    "parity_score": parity_diff if side == "home" else -parity_diff,
                    "parity_even_count": t_m["even"]
                })

        except Exception: pass

    # 4. RANKING SYSTEM (Highest Poisson Win Prob to Lowest)
    df = pd.DataFrame(raw_output)
    if not df.empty:
        df = df.sort_values(by="poisson_win_prob_num", ascending=False).reset_index(drop=True)
        # Drop the numeric helper column
        df = df.drop(columns=["poisson_win_prob_num"])

    # Final Save into the correct folder dynamically!
    output_path = os.path.join(OUTPUT_DIR, f"ranked_win_forecast_{target_date}.csv")
    df.to_csv(output_path, index=False)

    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    print(f"\n[Done] Base Win Forecast saved to {output_path}")
    print(df.to_string(index=False))

if __name__ == "__main__":
    run_win_forecast_engine()