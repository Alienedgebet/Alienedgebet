import os
import sys
import math
import time
import requests
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from dateutil import parser
from collections import defaultdict, Counter

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
from dotenv import load_dotenv
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS (Architecture Ready) ---
# Finds the root folder to manage 'data' and 'output' correctly across any server
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

# ==============================================================================
# 📦 THE BLACK BOX WRAPPER (OVER 2.5 GOALS - STAGE 2 FORENSIC)
# ==============================================================================
def run_over25_forecast_engine(target_date):
    """
    Executes Over 2.5 Goals Engine Stage 2.
    Math, logic, and H2H Kill-Switch are 100% untouched.
    Wrapped for professional server scheduling and complex VS architectures.
    """
    # Ensure directories exist so the code never crashes on saving
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    # -------------------------
    # CONFIG (100% UNTOUCHED ENGINE PARAMS)
    # -------------------------
    API_TOKEN = os.getenv("SPORTMONKS_API_KEY")
    BASE_URL = "https://api.sportmonks.com/v3/football"
    
    # Market IDs
    MARKET_ID_1X2 = 1
    MARKET_ID_OU  = 12
    MARKET_ID_GG  = 9

    REQUEST_DELAY = 0.2
    MAX_RETRIES = 5

    if not API_TOKEN:
        print("CRITICAL: SPORTMONKS_API_KEY is missing from environment!")
        return []

    # -------------------------
    # INTERNAL HELPERS (ENCAPSULATED)
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
        return {"data": []}

    def normalize_odd_value(value):
        try:
            val = float(value)
            if 1.01 <= val <= 30.0: return val
            if val > 100: return (val / 100) + 1
            if val < -100: return (100 / abs(val)) + 1
            return None
        except: return None

    def get_fixture_odds_safe_sniper(fixture_id):
        """Hits the dedicated endpoint to ensure Over 2.5 is NEVER empty."""
        raw_data = GET(f"/odds/pre-match/fixtures/{fixture_id}")
        odds_list = raw_data.get("data", [])
        result = {"home_win": None, "draw": None, "away_win": None, "o25": None, "gg": None}
        if not odds_list: return result
        for o in odds_list:
            mid = o.get("market_id")
            if mid == MARKET_ID_1X2:
                label = str(o.get("label", "")).lower()
                val = normalize_odd_value(o.get("value"))
                if val:
                    if "1" in label or "home" in label: result["home_win"] = val
                    elif "2" in label or "away" in label: result["away_win"] = val
                    elif "x" in label or "draw" in label: result["draw"] = val
            desc = str(o.get("market_description", "")).lower()
            if not desc: desc = str(o.get("name", "")).lower()
            is_ou = (mid == MARKET_ID_OU)
            if not is_ou:
                 if ("goals" in desc or "over/under" in desc) and not any(x in desc for x in ["corner", "card", "asian", "handicap"]):
                     is_ou = True
            if is_ou:
                label = str(o.get("label", "")).lower()
                total = str(o.get("total", ""))
                if "over" in label and ("2.5" in total or "2.5" in label):
                    val = normalize_odd_value(o.get("value"))
                    if val:
                        if result["o25"] is None or val < result["o25"]: result["o25"] = val
            is_gg = (mid == MARKET_ID_GG)
            if not is_gg:
                if "both teams to score" in desc or "btts" in desc:
                    if not any(x in desc for x in ["half", "result", "win", "total", "corner", "card", "booking"]):
                        is_gg = True
            if is_gg:
                label = str(o.get("label", "")).lower()
                if label in ["yes", "gg", "btts-yes"]:
                    val = normalize_odd_value(o.get("value"))
                    if val: result["gg"] = val
        return result

    def fetch_all_fixtures_for_date(date_str):
        """STRICT UNLIMITED PAGINATION: Captures every fixture (500+)"""
        all_fx = []
        page = 1
        while True:
            params = {"include": "participants;scores;league;season", "per_page": 50, "page": page}
            resp = GET(f"/fixtures/date/{date_str}", params=params)
            data = resp.get("data", [])
            if not data: break
            all_fx.extend(data)
            if len(data) < 50: break
            page += 1
            time.sleep(REQUEST_DELAY)
        return all_fx

    def extract_goals_v3(scores):
        home, away = None, None
        for entry in (scores or []):
            if not isinstance(entry, dict): continue
            s_obj = entry.get("score") or entry
            p = s_obj.get("participant") or entry.get("participant")
            g = s_obj.get("goals")
            if g is not None:
                val = int(g)
                if p == "home": home = val if home is None else max(home, val)
                elif p == "away": away = val if away is None else max(away, val)
        return home, away

    def get_match_stats(fx, team_id):
        hg, ag = extract_goals_v3(fx.get("scores", []))
        if hg is None or ag is None: return None
        is_home = any(int(p.get("id")) == int(team_id) and (p.get("meta") or {}).get("location") == "home" for p in fx.get("participants", []))
        scored = hg if is_home else ag
        conceded = ag if is_home else hg
        return {"s": scored, "c": conceded, "t": scored + conceded, "over": (scored + conceded) >= 3}

    def get_league_positions(season_id):
        data = GET(f"/standings/seasons/{season_id}")
        standings = data.get("data", [])
        pos_map = {}
        for entry in standings:
            tid = entry.get("participant_id")
            pos = entry.get("position")
            if tid and pos: pos_map[int(tid)] = int(pos)
        return pos_map

    # -------------------------
    # MAIN STAGE 2 AUDIT LOOP
    # -------------------------
    print(f"[STAGE 2 OVER ENGINE] Starting deep scan for {target_date}...")
    fixtures = fetch_all_fixtures_for_date(target_date)
    
    if not fixtures:
        print("No fixtures found.")
        return []

    team_ids = {p['id'] for fx in fixtures for p in fx.get("participants", []) if p.get('id')}
    team_histories = {}
    league_pos_cache = {}

    print(f"[INFO] Profiling {len(team_ids)} teams (35-game lookback)...")
    for tid in team_ids:
        h_data = GET(f"/fixtures/between/{(datetime.now()-timedelta(days=365)).date()}/{(datetime.now()-timedelta(days=1)).date()}/{tid}", 
                     params={"include":"scores;participants", "filters":"fixtureStates:5", "order":"desc", "per_page": 35})
        team_histories[tid] = h_data.get("data", [])
        time.sleep(0.02)

    raw_output = []

    for fx in fixtures:
        try:
            fid = fx['id']
            sid = fx.get("season_id")
            league_name = fx.get("league", {}).get("name", "Unknown League")
            parts = fx.get("participants", [])
            if len(parts) < 2: continue
            
            h_p = next(p for p in parts if p.get("meta", {}).get("location") == "home")
            a_p = next(p for p in parts if p.get("meta", {}).get("location") == "away")
            hid, aid = int(h_p['id']), int(a_p['id'])

            # 1. STANDINGS GAP
            if sid and sid not in league_pos_cache: league_pos_cache[sid] = get_league_positions(sid)
            pos_map = league_pos_cache.get(sid, {})
            h_pos, a_pos = pos_map.get(hid), pos_map.get(aid)
            pos_gap = abs(h_pos - a_pos) if (h_pos and a_pos) else 99

            # 2. SNIPER ODDS
            odds = get_fixture_odds_safe_sniper(fid)

            # 3. H2H KILL-SWITCH
            h2h_data = GET(f"/fixtures/head-to-head/{hid}/{aid}", params={"include":"scores;participants", "per_page": 5})
            h2h_matches = h2h_data.get("data", [])[:5]
            h2h_h_sum = 0; h2h_a_sum = 0; h2h_overs_total = 0; h2h_last_3_all_over = True
            
            for i, m in enumerate(h2h_matches):
                hst = get_match_stats(m, hid)
                if hst:
                    h2h_h_sum += hst["t"]
                    if hst["over"]: h2h_overs_total += 1
                    if i < 3 and not hst["over"]: h2h_last_3_all_over = False
                ast = get_match_stats(m, aid)
                if ast: h2h_a_sum += ast["t"]
            if len(h2h_matches) < 3: h2h_last_3_all_over = False

            # 4. FORM METRICS
            #
            # 2026-09-29. `window` is now a parameter (default 5, which is
            # EXACTLY the previous behaviour) so the same history can be
            # summarised over a shorter window without a second provider
            # round-trip. The engine evaluates the window twice per side --
            # once at 5, which feeds every existing number unchanged, and once
            # at 3, which is written alongside it for the board's 5/3 toggle.
            #
            # Nothing downstream reads the 3-window: poisson_over, council
            # votes, parity_diff and the O2.5 filter gates all still come from
            # the 5-window figures. The toggle changes what the BOARD SHOWS,
            # never which fixtures are recommended.
            #
            # get_match_stats is pure but was being re-evaluated two-to-three
            # times per match inside the sum() generators below. Each call
            # re-walks scores and participants, so the redundant calls are
            # now hoisted: compute once per match, reuse. Same values, less
            # work -- and with two windows evaluated the saving doubles.
            def get_complex_metrics(tid, history, venue, window=5):
                ov_n = history[:window]
                v_n = []
                for m in history:
                    if any(p['id'] == tid and (p.get('meta') or {}).get('location') == venue for p in m.get('participants', [])):
                        v_n.append(m)
                    if len(v_n) == window: break
                ov_gs = ov_gc = 0
                v_sum = 0
                ov_overs = 0
                for m in ov_n:
                    st = get_match_stats(m, tid)
                    if not st: continue
                    ov_gs += st["s"]
                    ov_gc += st["c"]
                    if st["over"]: ov_overs += 1
                for m in v_n:
                    st = get_match_stats(m, tid)
                    if st: v_sum += st["t"]
                return {"gs": ov_gs, "gc": ov_gc, "overs": ov_overs,
                        "v_sum": v_sum, "ov_sum": (ov_gs + ov_gc)}

            h_m = get_complex_metrics(hid, team_histories.get(hid, []), "home")
            a_m = get_complex_metrics(aid, team_histories.get(aid, []), "away")
            # Same history, shorter window. Display-only -- see above.
            h_m3 = get_complex_metrics(hid, team_histories.get(hid, []), "home", window=3)
            a_m3 = get_complex_metrics(aid, team_histories.get(aid, []), "away", window=3)

            # 5. PARITY DIFFERENCE
            h_total_parity = h_m["v_sum"] + h_m["ov_sum"] + h2h_h_sum
            a_total_parity = a_m["v_sum"] + a_m["ov_sum"] + h2h_a_sum
            parity_diff = h_total_parity - a_total_parity

            # 6. POISSON PROBABILITY
            lamb = ((h_m["gs"] + h_m["gc"]) / 5 + (a_m["gs"] + a_m["gc"]) / 5) / 2
            poisson_over = round((1 - (math.exp(-lamb) * (1 + lamb + (lamb**2)/2))) * 100, 2)

            # 7. COUNCIL VOTES (9 LAYERS)
            votes = 0
            if odds["o25"] and odds["o25"] < 1.85: votes += 1
            if poisson_over > 60: votes += 1
            if h_m["overs"] >= 3: votes += 1
            if a_m["overs"] >= 3: votes += 1
            if h2h_overs_total >= 3: votes += 1
            if h_m["gs"] >= 8: votes += 1
            if a_m["gs"] >= 8: votes += 1
            if pos_gap <= 8: votes += 1
            if parity_diff > 0: votes += 1

            raw_output.append({
                "fixture_id": fid,
                "league": league_name,
                "fixture": f"{h_p['name']} vs {a_p['name']}",
                "o25_odds": odds["o25"],
                "kill_switch_pass": h2h_last_3_all_over,
                "poisson_over_prob_num": poisson_over,
                "council_votes": f"{votes}/9",
                "pos_gap": pos_gap,
                "parity_diff": parity_diff,
                "h2h_overs_last_5": h2h_overs_total,
                "combined_gs_last_5": h_m["gs"] + a_m["gs"],
                # 2026-09-29. Per-side goals scored/conceded over the window.
                #
                # These were ALREADY computed above — get_complex_metrics
                # returns {"gs": scored, "gc": conceded, ...} per side, and
                # both h_m and a_m are used for the Poisson lambda and for
                # parity_diff. They were simply never written, so the four
                # numbers the Weekly board needs existed only in memory and
                # were discarded at save time.
                #
                # gs = goals scored, gc = goals conceded, each summed over that
                # side's venue-specific window. They are NOT the raw team
                # totals: get_complex_metrics builds ov_5 from `history[:5]`
                # (overall form) and v_5 from the venue-matched slice, and gs/gc
                # are summed from ov_5. The column names therefore say
                # "last_5" because that is the window that produced them.
                #
                # Written as plain ints so the CSV stays numeric and the
                # frontend can compare sides without parsing a string.
                "home_goals_scored_last_5": int(h_m["gs"]),
                "away_goals_scored_last_5": int(a_m["gs"]),
                "home_goals_conceded_last_5": int(h_m["gc"]),
                "away_goals_conceded_last_5": int(a_m["gc"]),
                # 2026-09-29. The same four figures over a 3-match window,
                # from the SAME history slice in the SAME provider call.
                #
                # Display-only. No filter gate, vote, Poisson term or parity
                # figure reads these columns -- every one of those still uses
                # the 5-window values above. They exist so the board can offer
                # a 5/3 toggle without a second engine run or a second set of
                # provider calls.
                #
                # A 3-window is inherently noisier than a 5-window, so these
                # are NOT a drop-in "more accurate" alternative: they are the
                # recent read, and the board labels which one is showing.
                "home_goals_scored_last_3": int(h_m3["gs"]),
                "away_goals_scored_last_3": int(a_m3["gs"]),
                "home_goals_conceded_last_3": int(h_m3["gc"]),
                "away_goals_conceded_last_3": int(a_m3["gc"]),
            })
        except: continue

    # Assembly
    df = pd.DataFrame(raw_output)
    if not df.empty:
        df = df.sort_values(by=["kill_switch_pass", "poisson_over_prob_num"], ascending=[False, False]).reset_index(drop=True)
    
    # SAVE SAFELY IN THE DYNAMIC DIRECTORY
    output_filename = os.path.join(OUTPUT_DIR, f"master_over_stage2_{target_date}.csv")
    df.to_csv(output_filename, index=False)
    
    print(f"[SUCCESS] Stage 2 Forensic Audit complete. Saved {len(df)} matches to {output_filename}")
    return df.to_dict(orient="records")

# Standard execution block
if __name__ == "__main__":
    run_over25_forecast_engine(datetime.now(timezone.utc).strftime("%Y-%m-%d"))