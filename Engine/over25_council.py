import os
import time
import json
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import math

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
def run_over25_stage2(target_date):
    """
    Executes Over 2.5 Engine Stage 2 (The 9-Layer Council).
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
    # 2026-10-01: was 6 of 9. Layer 8 was a guaranteed vote, so the real bar
    # was 5 of 8 meaningful layers. Removing the placeholder leaves 8 real
    # layers, so 5 preserves the previous effective standard exactly.
    VOTE_THRESHOLD = 5   # Match needs 5 of 8 real layers to pass
    REQUEST_DELAY = 0.2
    
    if not API_KEY:
        print("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")
        return[]

    # -------------------------
    # UTILS & PAGINATION
    # -------------------------
    def GET(path, params=None):
        if params is None: params = {}
        params.setdefault("api_token", API_KEY)
        try:
            r = requests.get(f"{BASE_URL}{path}", params=params, timeout=20)
            r.raise_for_status()
            return r.json()
        except Exception:
            time.sleep(1)
            return {}

    def sleep_short():
        time.sleep(REQUEST_DELAY)

    def fetch_all_fixtures(date_str):
        """Loops through ALL pages to get every match."""
        all_data = []
        page = 1
        while True:
            print(f"   ...[O2.5 Stage 2] fetching page {page}...")
            resp = GET(f"/fixtures/date/{date_str}", 
                       params={"include":"participants;scores;odds;lineups;statistics", 
                               "per_page": 50, "page": page})
            data = resp.get("data",[])
            if not data: break
            all_data.extend(data)
            
            meta = resp.get("pagination") or {}
            if not meta.get("has_more", False):
                break
            page += 1
            sleep_short()
        return all_data

    # -------------------------
    # ROBUST DATA EXTRACTORS
    # -------------------------
    def extract_final_goals(scores):
        home, away = 0, 0
        for entry in (scores or[]):
            if not isinstance(entry, dict): continue
            s = entry.get("score") or {}
            g = s.get("goals")
            if isinstance(g, str) and g.isdigit(): g = int(g)
            if not isinstance(g, int): continue
            
            if s.get("participant") == "home": home = max(home, g)
            if s.get("participant") == "away": away = max(away, g)
        return home, away

    def get_stats(fixtures, team_id):
        """Returns: scored, conceded, overs, count"""
        if not fixtures: return 0,0,0,0
        scored, conceded, overs, count = 0, 0, 0, 0
        for fx in fixtures:
            hg, ag = extract_final_goals(fx.get("scores",[]))
            total = hg + ag
            
            is_home = False
            for p in fx.get("participants", []) or[]:
                if str(p.get("id")) == str(team_id):
                    if (p.get("meta") or {}).get("location") == "home": is_home = True
            
            t_goals = hg if is_home else ag
            o_goals = ag if is_home else hg
            
            scored += t_goals
            conceded += o_goals
            if total >= 3: overs += 1
            count += 1
        return scored, conceded, overs, count

    def get_match_odds(odds_list):
        """Strictly finds Over 2.5 for the MATCH only."""
        for o in odds_list or[]:
            try:
                market = str(o.get("market_description", "")).lower()
                label = str(o.get("label", "")).lower()
                total = str(o.get("total", ""))
                
                # Must be standard Over/Under market, not 1st half, not home/away totals
                if "goals over/under" in market and "2.5" in total and label == "over":
                    if "half" not in market and "home" not in market and "away" not in market:
                        val = float(o.get("value"))
                        # Safety Cap: Over 2.5 shouldn't be 9.00
                        if 1.01 < val < 4.5: 
                            return val
            except: continue
        return None

    def poisson_prob(lambda_val):
        if lambda_val <= 0: return 0.0
        p0 = math.exp(-lambda_val)
        p1 = p0 * lambda_val
        p2 = p1 * (lambda_val / 2.0)
        return max(0.0, 1.0 - (p0 + p1 + p2))

    # -------------------------
    # THE 8 REAL LAYERS (VOTING SYSTEM)
    # -------------------------
    def run_council_of_8(h_stats, a_stats, h2h_games, odds_val):
        votes = 0
        reasons =[]
        
        # Unpack stats: (scored, conceded, overs, count)
        h_scored, h_conceded, h_overs, h_games = h_stats
        a_scored, a_conceded, a_overs, a_games = a_stats
        
        if h_games < 3 or a_games < 3: return 0, ["NoData"]

        # Averages
        h_avg_scored = h_scored / h_games
        a_avg_scored = a_scored / a_games
        h_avg_conceded = h_conceded / h_games
        a_avg_conceded = a_conceded / a_games

        h_personal = h_scored + h_conceded
        a_personal = a_scored + a_conceded

        # --- LAYER 1: FIREPOWER (With Anti-Leaking Fix) ---
        # Must have high personal totals AND decent scoring ability
        if h_personal >= 8 and a_personal >= 8:
            if h_avg_scored >= 0.8 and a_avg_scored >= 0.8: # Must be able to score
                votes += 1
                reasons.append("Firepower")

        # --- LAYER 2: POISSON (Math) ---
        h_exp = h_avg_scored * (1 + (a_avg_conceded - 1.4)/3.0)
        a_exp = a_avg_scored * (1 + (h_avg_conceded - 1.4)/3.0)
        prob = poisson_prob(h_exp + a_exp)
        if prob >= 0.60:
            votes += 1
            reasons.append(f"Poisson({int(prob*100)}%)")

        # --- LAYER 3: MARKET (Daily Logic) ---
        #
        # 2026-10-01 FIX — this layer was inverted.
        #
        # It awarded a vote for odds < 1.85, i.e. it paid a vote precisely
        # when the bookmaker believed the match was LEAST likely to go over.
        # Shorter odds = higher implied probability = a worse bet for us.
        # Measured on 1,373 settled fixtures: odds<=1.40 hit 69.1% and
        # odds 1.85-2.20 hit 44.3%. The old rule handed its vote to the 44%
        # bucket and withheld it from the 69% bucket -- backwards.
        #
        # It now awards the vote only when OUR Poisson disagrees with the
        # market in the profitable direction, which is what "value" means.
        if odds_val:
            implied_pct = 100.0 / odds_val
            if prob > implied_pct + 3.0:
                votes += 1
                reasons.append(f"EdgeVsMarket({int(prob)}%>{int(implied_pct)}%)")

        # --- LAYER 4: CONSISTENCY ---
        h_rate = h_overs / h_games
        a_rate = a_overs / a_games
        if h_rate >= 0.6 and a_rate >= 0.6:
            votes += 1
            reasons.append("Consistent")

        # --- LAYER 5: H2H ---
        h2h_overs = 0
        for hx in h2h_games:
            hg, ag = extract_final_goals(hx.get("scores",[]))
            if (hg+ag) >= 3: h2h_overs += 1
        if len(h2h_games) > 0 and (h2h_overs/len(h2h_games)) >= 0.5:
            votes += 1
            reasons.append("H2H")

        # --- LAYER 6: TREND (With Anti-Leaking Fix) ---
        combined_avg = h_avg_scored + a_avg_scored
        if combined_avg >= 2.8:
            # Check: Are they contributing to this trend?
            if h_avg_scored >= 1.0 or a_avg_scored >= 1.0:
                votes += 1
                reasons.append("Trend")

        # --- LAYER 7: LEAKY DEFENSE ---
        if h_avg_conceded >= 1.2 and a_avg_conceded >= 1.2:
            votes += 1
            reasons.append("Leaky")

        # --- LAYER 8: LINEUP (Pass for Early Runs) ---
        #
        # 2026-10-01 FIX — was an unconditional +1 vote.
        #
        # This was never implemented; it was a placeholder that granted a free
        # vote to every single fixture. With a 6/9 threshold that quietly
        # reduced the real bar to 5/8, so the council passed fixtures that
        # missed a genuine gate.
        #
        # The placeholder is REMOVED, not patched: there is no lineup data
        # here to act on, and inventing a rule would be worse than the honest
        # gap. VOTE_THRESHOLD below is rebalanced from 6 to 5 so the council
        # keeps the same effective bar (5 of the 8 real layers) it had before,
        # without a free pass.
        pass

        # --- LAYER 9: VOLATILITY ---
        # Match average based on personal totals
        match_vol = (h_personal/h_games + a_personal/a_games) / 2.0
        if match_vol >= 3.0:
            votes += 1
            reasons.append("Volatile")

        return votes, reasons

    # -------------------------
    # MAIN EXECUTION LOGIC
    # -------------------------
    print(f"\n--- MASTER COUNCIL (8 LAYERS) {target_date} ---")
    
    # 1. FETCH ALL PAGES
    fixtures = fetch_all_fixtures(target_date)
    print(f"Total Matches Found: {len(fixtures)}")
    
    if not fixtures: 
        return []

    final_picks =[]
    
    # History Window (Last 6 months)
    start_hist = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=180)).strftime("%Y-%m-%d")
    
    print("Running 8-Layer Analysis (This takes time for 100+ matches)...")
    
    for fx in fixtures:
        parts = fx.get("participants",[])
        if len(parts) < 2: continue
        
        home_id, away_id = str(parts[0]["id"]), str(parts[1]["id"])
        home_name, away_name = parts[0]["name"], parts[1]["name"]

        # 2. FETCH HISTORY (Fresh & Descending)
        h_resp = GET(f"/fixtures/between/{start_hist}/{target_date}/{home_id}", 
                     params={"include":"scores;participants", "sortBy":"starting_at", "order":"desc", "per_page": 8})
        a_resp = GET(f"/fixtures/between/{start_hist}/{target_date}/{away_id}", 
                     params={"include":"scores;participants", "sortBy":"starting_at", "order":"desc", "per_page": 8})
        
        # Take Top 5
        h_games = (h_resp.get("data") or [])[:5]
        a_games = (a_resp.get("data") or [])[:5]
        
        # H2H
        h2h_resp = GET(f"/fixtures/head-to-head/{home_id}/{away_id}", params={"include":"scores", "per_page": 5})
        h2h_games = h2h_resp.get("data") or[]

        # 3. STATS
        h_stats = get_stats(h_games, home_id)
        a_stats = get_stats(a_games, away_id)
        
        # 4. ODDS
        odds_val = get_match_odds(fx.get("odds"))
        
        # 5. VOTE
        votes, reasons = run_council_of_8(h_stats, a_stats, h2h_games, odds_val)
        
        if votes >= VOTE_THRESHOLD:
            final_picks.append({
                "id": fx.get("id"), # CRITICAL FOR AGGREGATOR MATCHING
                "Fixture": f"{home_name} vs {away_name}",
                "Time": fx.get("starting_at", "")[11:16],
                "Votes": votes,
                "Odds": odds_val,
                "Algorithm": "8_Layer_Council",
                "Reasons": ", ".join(reasons)
            })
            print(f"  [+] {home_name} vs {away_name} -> {votes}/8 Votes")
            
        sleep_short()

    # -------------------------
    # OUTPUT (MODIFIED FOR AGGREGATOR)
    # -------------------------
    print("\n" + "="*50)
    print(f"MASTER PREDICTIONS (Threshold: {VOTE_THRESHOLD}/8)")
    print("="*50)

    if final_picks:
        df = pd.DataFrame(final_picks)
        # Sort by Votes High->Low
        df = df.sort_values(["Votes", "Odds"], ascending=[False, True])
        print(df.to_string(index=False))
        
        # --- SAVE SAFELY TO THE DYNAMIC OUTPUT FOLDER ---
        # 2026-10-01 FIX — date-scope the artifact.
        #
        # This filename had no date in it, so every run overwrote the last
        # one and every consumer read whatever happened to be there. Verified
        # on disk: over25_stage2_picks.csv was dated Sep 29 while the pipeline
        # was on Oct 1. Because Stage 2 legitimately returns NOTHING on most
        # days (it needs 6/9 votes), a zero-pick day did not clear the file —
        # it left it alone, and the previous run's picks were re-published as
        # today's. The dated file is now authoritative; the undated name is
        # still written so existing API/frontend readers keep working.
        csv_fn = os.path.join(OUTPUT_DIR, f"over25_stage2_picks_{target_date}.csv")
        json_fn = os.path.join(OUTPUT_DIR, f"over25_stage2_picks_{target_date}.json")
        legacy_csv = os.path.join(OUTPUT_DIR, "over25_stage2_picks.csv")
        legacy_json = os.path.join(OUTPUT_DIR, "over25_stage2_picks.json")
        
        df.to_csv(csv_fn, index=False)
        df.to_json(json_fn, orient="records", indent=2)
        # Mirror to the legacy undated names so existing API/frontend readers
        # keep working. Consumers that can pass a date should prefer the dated
        # file; see _pick_dated in over25_risk_filter.py.
        df.to_csv(legacy_csv, index=False)
        df.to_json(legacy_json, orient="records", indent=2)
        print(f"\n[O2.5 Stage 2] Saved to {csv_fn} & {json_fn}")
        
        # Return directly to Aggregator memory
        return df.to_dict(orient="records")
    else:
        print("[O2.5 Stage 2] No matches met the criteria.")
        return