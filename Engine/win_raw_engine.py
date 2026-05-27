import os
import sys
import requests
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta, timezone
from dateutil import parser
from collections import defaultdict

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
def run_win_raw_engine(target_date):
    """
    Executes the Win Filter Raw Engine.
    All mathematical rules, metrics, parity scores, and odds logic 
    are 100% untouched and preserved from the original back-end.
    """
    # Ensure directories exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    # -------------------------
    # PRODUCTION CONFIG
    # -------------------------
    API_TOKEN = os.getenv("SPORTMONKS_API_KEY") or "hD4F4FIFwNW5BxKa6Y0fCCLtB0KkiNRxtULDdsrO3VPss1IMV4HJihBkxwI4"
    BASE_URL = "https://api.sportmonks.com/v3/football"

    # Market IDs for Sniper
    MARKET_1X2 = 1
    MARKET_OU = 12
    MARKET_GG = 9

    REQUEST_DELAY = 0.2

    if not API_TOKEN:
        print("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")
        return[]

    # -------------------------
    # HTTP & UNLIMITED PAGINATION (STRICT)
    # -------------------------
    def GET(path, params=None):
        if params is None: params = {}
        params.setdefault("api_token", API_TOKEN)
        url = f"{BASE_URL}{path}"
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 200: return r.json()
        except: pass
        return {"data":[]}

    def sleep_short():
        time.sleep(REQUEST_DELAY)

    def fetch_all_fixtures_for_date(date_str):
        """STRICT UNLIMITED PAGINATION: Fetches every single match (500+)"""
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

            if not data:
                break

            all_fx.extend(data)
            page += 1
            sleep_short()
        return all_fx

    # -------------------------
    # RUTHLESS V3 GOAL EXTRACTION (VERIFIED)
    # -------------------------
    def extract_goals_v3(scores):
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
        """Returns raw stats for a specific team in a match."""
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
            "total": hg + ag, "is_even": (hg + ag) % 2 == 0
        }

    # -------------------------
    # ACCURATE ODDS SNIPER
    # -------------------------
    def sniper_fetch_odds(fixture_id):
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
    # MAIN ENGINE EXECUTION
    # -------------------------
    print(f"\n[INFO] Win Raw Engine Start: Unlimited Pagination ({target_date})")

    fixtures = fetch_all_fixtures_for_date(target_date)
    if not fixtures: 
        print(f"[WARN] No fixtures found for {target_date}")
        return[]

    team_ids = set()
    for fx in fixtures:
        for p in fx.get("participants",[]): team_ids.add(p['id'])
    
    team_histories = {}
    print(f"[INFO] Analyzing {len(team_ids)} teams...")
    
    # Safely convert target_date to handle lookbacks correctly
    target_dt = datetime.strptime(target_date, "%Y-%m-%d")
    start_dt = (target_dt - timedelta(days=365)).strftime("%Y-%m-%d")
    end_dt = (target_dt - timedelta(days=1)).strftime("%Y-%m-%d")

    for tid in team_ids:
        # Fetch 40 matches to ensure we find 5 specific venue matches
        h_data = GET(f"/fixtures/between/{start_dt}/{end_dt}/{tid}", 
                     params={"include":"scores;participants", "filters":"fixtureStates:5", "order":"desc", "per_page": 40})
        team_histories[tid] = h_data.get("data", [])
        sleep_short()

    raw_output =[]

    for fx in fixtures:
        try:
            fid = fx['id']
            parts = fx.get("participants",[])
            if len(parts) < 2: continue
            
            h_p = next(p for p in parts if p.get("meta", {}).get("location") == "home")
            a_p = next(p for p in parts if p.get("meta", {}).get("location") == "away")
            hid, aid = int(h_p['id']), int(a_p['id'])

            odds = sniper_fetch_odds(fid)
            
            # H2H - STRICTLY LAST 5 MEETINGS
            h2h_data = GET(f"/fixtures/head-to-head/{hid}/{aid}", params={"include":"scores;participants", "per_page": 5})
            h2h_matches = h2h_data.get("data", [])[:5]
            
            h2h_stats = {"h_wins": 0, "h_parity_sum": 0, "a_parity_sum": 0, "count": len(h2h_matches)}
            for m in h2h_matches:
                h_st = get_match_stats(m, hid)
                a_st = get_match_stats(m, aid)
                if h_st:
                    if h_st["res"] == "W": h2h_stats["h_wins"] += 1
                    h2h_stats["h_parity_sum"] += h_st["total"]
                if a_st:
                    h2h_stats["a_parity_sum"] += a_st["total"]

            # COMPLEX METRIC CALCULATOR
            def get_side_metrics(tid, history, venue_type):
                # 1. Last 5 Overall
                ov_wins = 0; ov_gs = 0; ov_gc = 0; ov_losses = 0; ov_cs_fail = 0; ov_even = 0; no_draw_3 = True
                for i, m in enumerate(history[:5]):
                    st = get_match_stats(m, tid)
                    if st:
                        ov_gs += st["scored"]; ov_gc += st["conceded"]
                        if st["res"] == "W": ov_wins += 1
                        elif st["res"] == "L": ov_losses += 1
                        if st["conceded"] > 0: ov_cs_fail += 1
                        if st["is_even"]: ov_even += 1
                        if i < 3 and st["res"] == "D": no_draw_3 = False
                
                # 2. Last 5 at Venue
                venue_5 =[]
                for m in history:
                    is_v = any(p['id'] == tid and (p.get('meta') or {}).get('location') == venue_type for p in m.get('participants',[]))
                    if is_v: venue_5.append(m)
                    if len(venue_5) == 5: break
                
                v_wins = 0; v_parity_sum = 0
                for m in venue_5:
                    st = get_match_stats(m, tid)
                    if st:
                        v_wins += st["res"] == "W"
                        v_parity_sum += st["total"]

                return {
                    "wins": ov_wins, "gs": ov_gs, "gc": ov_gc, "losses": ov_losses,
                    "cs_fail": ov_cs_fail, "even": ov_even, "no_draw_3": no_draw_3,
                    "v_wins": v_wins, "v_parity": v_parity_sum, "ov_parity": (ov_gs + ov_gc)
                }

            h_m = get_side_metrics(hid, team_histories.get(hid,[]), "home")
            a_m = get_side_metrics(aid, team_histories.get(aid,[]), "away")

            # PARITY & NO-DRAW-BOTH
            both_no_draw_3 = h_m["no_draw_3"] and a_m["no_draw_3"]
            h_total_p = h_m["v_parity"] + h_m["ov_parity"] + h2h_stats["h_parity_sum"]
            a_total_p = a_m["v_parity"] + a_m["ov_parity"] + h2h_stats["a_parity_sum"]
            parity_score = h_total_p - a_total_p

            for side in ["home", "away"]:
                t_m, o_m = (h_m, a_m) if side == "home" else (a_m, h_m)
                w_odd = odds["home"] if side == "home" else odds["away"]
                h2h_win_cnt = h2h_stats["h_wins"] if side == "home" else (h2h_stats["count"] - h2h_stats["h_wins"])
                
                raw_output.append({
                    "fixture_id": fid,
                    "fixture": f"{h_p['name']} vs {a_p['name']}",
                    "side": side,
                    "team_name": h_p['name'] if side == "home" else a_p['name'],
                    "win_odds": w_odd,
                    "last_5_wins_overall": t_m["wins"],
                    "last_5_wins_at_venue": t_m["v_wins"],
                    "last_5_goals_scored": t_m["gs"],
                    "opp_last_5_goals_scored": o_m["gs"],
                    "opp_last_5_losses": o_m["losses"],
                    "opp_last_5_conceded_raw": o_m["gc"],
                    "opp_no_clean_sheet_count": o_m["cs_fail"],
                    "h2h_wins_last_5": h2h_win_cnt,
                    "last_3_no_draw_BOTH": both_no_draw_3,
                    "parity_score": parity_score if side == "home" else -parity_score,
                    "parity_even_count": t_m["even"]
                })

        except Exception: pass

    df = pd.DataFrame(raw_output)
    if df.empty:
        print("[WARN] No raw output generated.")
        return[]

    # Save to dynamic OUTPUT folder
    output_file_path = os.path.join(OUTPUT_DIR, f"production_raw_engine_{target_date}.csv")
    df.to_csv(output_file_path, index=False)
    
    print(f"\n[SUCCESS] Win Raw Engine completed. Saved {len(df)} records to {output_file_path}")
    
    return df.to_dict(orient="records")

# Allow local testing
if __name__ == "__main__":
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_win_raw_engine(today_date)