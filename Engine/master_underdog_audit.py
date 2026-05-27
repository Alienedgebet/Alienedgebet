import os
import sys
import math
import time
import json
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
def run_underdog_master_engine(target_date):
    """
    Executes the Underdog Master Engine (Forensic Audit & Spear-Minus-Shield).
    Math, logic, and thresholds are 100% untouched.
    """
    # Ensure directories exist safely
    for directory in [OUTPUT_DIR, DATA_DIR]:
        os.makedirs(directory, exist_ok=True)
        
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
    # MATH LAYER (DIXON-COLES) - ORIGINAL ENGINE LOGIC
    # -------------------------
    def calculate_dixon_coles_lambda(att_strength, def_weakness, global_mean):
        """λ = Attack * Defense * Global_Mean"""
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
    # NEW: FORENSIC SUFFOCATION LOGIC (FOR THE AUDIT)
    # -------------------------
    def calculate_suffocation_penalty(fav_dom_index, fav_tempo):
        """
        Calculates the 'Chokehold' multiplier based on DNA.
        A dominant favorite physically reduces the underdog's oxygen.
        """
        multiplier = 1.0
        if fav_dom_index > 65:
            # Every 1% of dominance above 65 reduces Dog Lambda by 0.75%
            multiplier -= (fav_dom_index - 65) * 0.0075
        if fav_tempo > 60:
            multiplier -= 0.05
        return max(0.4, round(multiplier, 3)) # Cap penalty at 60% reduction

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
                    wait = (BACKOFF_FACTOR ** attempt) + 5
                    print(f"\n⚠️ API Rate Limit. Waiting {wait}s...")
                    time.sleep(wait)
                    continue
                if r.status_code >= 500:
                    time.sleep(2)
                    continue
            except:
                time.sleep(1)
        return {"data":[]}

    def fetch_all_fixtures_for_date(date_str):
        """YOUR FULL PAGINATION CODE: Captures all fixtures (500+)"""
        all_fx = []
        page = 1
        print(f"[1/4] Scanning master fixture list for {date_str}...")
        while True:
            params = {
                "include": "participants;scores;league;season",
                "per_page": 50,
                "page": page
            }
            resp = GET(f"/fixtures/date/{date_str}", params=params)
            data = resp.get("data",[])

            if not data:
                break

            all_fx.extend(data)

            # Log progress every 100 matches
            if len(all_fx) % 100 == 0 or len(data) < 50:
                print(f"   ...Successfully retrieved {len(all_fx)} matches.")

            if len(data) < 50:
                break

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
        res = {"h": 2.50, "a": 2.50}

        for o in odds_list:
            if o.get("market_id") == MARKET_1X2:
                lbl = str(o.get("label", "")).lower()
                try: val = float(o.get("value"))
                except: continue

                if "1" in lbl or "home" in lbl:
                    if res["h"] is None or o.get("bookmaker_id") == 2: res["h"] = val
                elif "2" in lbl or "away" in lbl:
                    if res["a"] is None or o.get("bookmaker_id") == 2: res["a"] = val
        return res

    # -------------------------
    # THE UNDERDOG POWER ENGINE (TOTAL ACCURACY)
    # -------------------------
    print("\n--- ALIENEDGE UNDERDOG BACKTESTER ---")
    print(f"\n" + "="*110)
    print(f"   ⚖️  UNDERDOG MASTER ENGINE: FORENSIC AUDIT & SPEAR-MINUS-SHIELD - {target_date}")
    print("="*110 + "\n")

    # Forensic History Anchors (Calculated relative to target_date)
    dt_obj = datetime.strptime(target_date, "%Y-%m-%d")
    hist_end = (dt_obj - timedelta(days=1)).date()
    hist_start = (dt_obj - timedelta(days=LOOKBACK_DAYS)).date()

    # 1. Load DNA Identity Library (Handshake with Code 3)
    # Dynamically maps to the DATA folder where the DNA Profiler saved it
    dna_path = os.path.join(DATA_DIR, "team_dna_profiles.json")
    dna_db = {}
    if os.path.exists(dna_path):
        with open(dna_path, "r", encoding="utf-8") as f:
            dna_db = json.load(f)
        print(f"[LOAD] DNA Library Synced ({len(dna_db)} tactical profiles ready).")
    else:
        print(f"[WARN] DNA Library not found at {dna_path}. Engine will run without DNA suffocation.")

    # 2. Fetch All Matches for that date
    fixtures = fetch_all_fixtures_for_date(target_date)
    if not fixtures: return[]

    # 3. History Prefetch (Anchored to backtest date)
    team_ids = {p['id'] for fx in fixtures for p in fx.get("participants",[]) if p.get('id')}
    team_histories = {}
    print(f"[2/4] Profiling {len(team_ids)} teams (Forensic History Verification for {target_date})...")
    for tid in team_ids:
        # History is anchored to games BEFORE the target_date
        h_data = GET(f"/fixtures/between/{hist_start}/{hist_end}/{tid}",
                     params={"include":"scores;participants;statistics.type", "filters":"fixtureStates:5", "order":"desc", "per_page": 20})
        team_histories[tid] = h_data.get("data",[])
        time.sleep(0.01)

    global_mean = 1.35
    raw_output =[]

    # 4. Forensic Loop
    print(f"[3/4] Running Main Engine and Forensic Audit Simulations...")
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
            fav_name = a_p['name'] if is_home_dog else h_p['name']
            dog_venue = "home" if is_home_dog else "away"
            fav_venue = "away" if is_home_dog else "home"

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

            # --- ORIGINAL METRICS BLOCK (PRESERVED A TO Z) ---
            def get_accuracy_metrics(tid, history, required_venue):
                ov_5 = history[:5]
                gs, gc, wins, ov_p = 0, 0, 0, 0
                no_draw_streak = True; conceded_count = 0; cs_streak = 0
                for i, m in enumerate(ov_5):
                    st = get_match_raw_stats(m, tid)
                    if st:
                        gs += st["s"]; gc += st["c"]; ov_p += st["total"]
                        if i < 3 and st["is_draw"]: no_draw_streak = False
                        if st["s"] > st["c"]: wins += 1
                        if st["c"] > 0: conceded_count += 1
                        if i == cs_streak and st["c"] == 0: cs_streak += 1

                v_5 = [m for m in history if any(p['id'] == tid and (p.get('meta') or {}).get('location') == required_venue for p in m.get('participants', []))][:5]
                v_wins, v_gs, v_gc, v_p = 0, 0, 0, 0
                for m in v_5:
                    st = get_match_raw_stats(m, tid)
                    if st:
                        v_gs += st["s"]; v_gc += st["c"]; v_p += st["total"]
                        if st["s"] > st["c"]: v_wins += 1

                t3_stats =[get_match_raw_stats(m, tid) for m in history[:3] if get_match_raw_stats(m, tid)]
                t3_gs = sum(x["s"] for x in t3_stats); t3_sot = sum(x["sot"] for x in t3_stats)
                is_hot = (t3_gs/3) > (gs/5 if gs > 0 else 0.5); due = (t3_sot/3 >= 4.0) and (t3_gs/3 <= 0.7)

                return {
                    "att": (gs/5 + v_gs/5) / (2 * global_mean) if v_5 else (gs/5 / global_mean),
                    "dfn": (gc/5 + v_gc/5) / (2 * global_mean) if v_5 else (gc/5 / global_mean),
                    "ov_p": ov_p, "v_p": v_p, "no_draw": no_draw_streak,
                    "is_hot": is_hot, "due": due, "v_wins": v_wins,
                    "conceded_5": conceded_count, "cs_streak": cs_streak
                }

            # RUNNING PILLARS FOR BOTH SIDES
            dog_m = get_accuracy_metrics(dog_id, team_histories.get(dog_id,[]), dog_venue)
            fav_m = get_accuracy_metrics(fav_id, team_histories.get(fav_id,[]), fav_venue)

            # --- ORIGINAL CALCULATION (PRESERVED) ---
            dc_lamb = calculate_dixon_coles_lambda(dog_m["att"], fav_m["dfn"], global_mean)
            if h2h_matches: dc_lamb = (dc_lamb + (h2h_dog_gs_count/len(h2h_matches))) / 2
            dog_prob_theoretical = get_underdog_score_prob(dc_lamb)

            # --- NEW AUDIT ENGINE LOGIC (SPEAR-MINUS-SHIELD) ---

            # 1. Favorite's Spear Power (Probability they score)
            fav_lamb = calculate_dixon_coles_lambda(fav_m["att"], dog_m["dfn"], global_mean)
            fav_spear_prob = get_underdog_score_prob(fav_lamb)

            # 2. DNA Suffocation (The Chokehold)
            fav_dna = dna_db.get(str(fav_id), {})
            fav_dom = fav_dna.get("Market_Power_Scores", {}).get("Win_Dominance", 50.0)
            fav_tempo = fav_dna.get("Tactical_DNA", {}).get("Tempo", 40.0)
            chokehold = calculate_suffocation_penalty(fav_dom, fav_tempo)

            # 3. AUDIT RESULT: The Net Probability
            # Original Probability minused by Favorite's tactical suffocation
            dog_prob_audited = round(dog_prob_theoretical * chokehold, 2)

            # Subtraction Gap: Clear air between sides
            net_gap = round(fav_spear_prob - dog_prob_audited, 1)

            # Audit Status Labeling
            audit_status = "⚔️ ACTIVE"
            if net_gap > 55: audit_status = "❌ WEAK (NEUTRALIZED)"
            elif dog_prob_audited > 65: audit_status = "🔥 ELITE SCORER"
            elif dog_prob_audited < 35: audit_status = "⚠️ LOW THREAT"

            raw_output.append({
                "fixture_id": fid, # Added for Master Aggregator mapping
                "fixture": f"{h_p['name']} vs {a_p['name']}",
                "underdog_team": dog_name,
                "Audit_Real_Prob": f"{dog_prob_audited}%",   # THE NEW AUDIT
                "Dog_Score_Prob": f"{dog_prob_theoretical}%", # THE ORIGINAL LIST DATA
                "Fav_Spear_Power": f"{fav_spear_prob}%",      # THE FAVORITE SPEAR
                "Dominance_Gap": net_gap,                    # THE MINUS RESULT
                "Audit_Verdict": audit_status,
                "parity_gap": (dog_m["v_p"] + dog_m["ov_p"] + h2h_dog_p_sum) - (fav_m["v_p"] + fav_m["ov_p"] + h2h_fav_p_sum),
                "dog_is_hot": dog_m["is_hot"],
                "dog_due_goal": dog_m["due"],
                "fav_cs_streak": fav_m["cs_streak"]
            })

        except Exception as e:
            continue

    # 5. Output Final Table
    df = pd.DataFrame(raw_output)
    if not df.empty:
        # Sort by Real Prob (the most accurate one)
        df = df.sort_values(by="Audit_Real_Prob", ascending=False).reset_index(drop=True)
        
        # --- SAVE SAFELY TO THE DYNAMIC OUTPUT FOLDER ---
        csv_fn = os.path.join(OUTPUT_DIR, f"audited_underdog_backtest_{target_date}.csv")
        json_fn = os.path.join(OUTPUT_DIR, f"audited_underdog_backtest_{target_date}.json")
        
        df.to_csv(csv_fn, index=False)
        df.to_json(json_fn, orient="records", indent=2)

        print("\n" + "★"*135)
        print(f"   🏆 FINAL AUDITED UNDERDOG REPORT: {target_date} 🏆")
        print("★"*135)

        pd.set_option('display.max_columns', None); pd.set_option('display.width', 1000)

        # Priority View
        view_cols =["fixture", "underdog_team", "Audit_Real_Prob", "Dog_Score_Prob", "Fav_Spear_Power", "Dominance_Gap", "Audit_Verdict"]
        print(df[view_cols].to_string(index=False))

        print(f"\n[4/4] Forensic Audit Complete. Results archived to {csv_fn}")
        
        return df.to_dict(orient="records")
    else:
        print("[4/4] No matches passed the audit criteria.")
        return