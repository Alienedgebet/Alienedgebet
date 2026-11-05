import os
import sys
import math
import time
import json
import requests
import pandas as pd
import numpy as np
import re
from datetime import datetime, timedelta, timezone

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
from dotenv import load_dotenv
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS ---
# This ensures the aggregator finds the files in the correct folders
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

# ==============================================================================
# 📦 THE BLACK BOX WRAPPER (CALLABLE BY THE MASTER API/SCHEDULER)
# ==============================================================================
def _valid_fixture_id(fid):
    """BUG-2 guard: return a real integer fixture id, or None for any
    placeholder (None, NaN, '', 'N/A', 'Unknown', ...). A fixture row must
    never carry a string placeholder as its identity, or sub-picks / DNA /
    intelligence / settlement lose their anchor to the correct match."""
    if fid is None:
        return None
    try:
        if pd.isna(fid):
            return None
    except (TypeError, ValueError):
        pass
    s = str(fid).strip()
    if not s or s.lower() in {"n/a", "na", "none", "unknown", "nan", "null", "-"}:
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None



# Base rate at which the underdog scores at least one goal, measured over the
# settled set (n=1,835). This is the population the published number describes.
_UD_BASE_RATE = 64.5

# Reliability coefficient: how much of the audit engine's stated spread the
# data supports. Re-fit with tools/ud_precision_backtest.py as data grows.
_UD_RELIABILITY = 0.70


def _UD_SHRINK(p):
    """p' = base + (p - base) * k. Monotonic, so ranking is preserved."""
    return max(0.0, min(100.0, _UD_BASE_RATE + (p - _UD_BASE_RATE) * _UD_RELIABILITY))


def run_apex_underdog_aggregator(target_date):
    """
    Executes the Apex UD Aggregator.
    Math, Gospel Rules, and Monte Carlo 5,000 are 100% untouched.
    """
    # Ensure directories exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    # -------------------------
    # ⚙️ CONFIGURATION
    # -------------------------
    API_KEY = os.getenv("SPORTMONKS_API_KEY")
    BASE_URL = "https://api.sportmonks.com/v3/football"

    # DYNAMIC FILE PATHING (Linked to your other engines)
    FILE_UD_ENGINE_CSV = os.path.join(OUTPUT_DIR, f"audited_underdog_backtest_{target_date}.csv")
    FILE_HANDSHAKE_CSV = os.path.join(OUTPUT_DIR, f"MASTER_CALIBRATION_{target_date}.csv")
    FILE_DNA_JSON = os.path.join(DATA_DIR, "team_dna_profiles.json")
    
    # 🟢 [NEW] ADDED THE GENERAL FEED FILE TARGET EXACTLY AS REQUESTED
    GENERAL_FEED_FILE = os.path.join(OUTPUT_DIR, "sh_gg_winner_feed.json")

    if not API_KEY:
        print("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")
        return[]

    # -------------------------
    # 🛠️ UTILITIES & MATCH KEY (ORIGINAL LOGIC)
    # -------------------------
    def GET(path, params=None):
        if params is None: params = {}
        params.setdefault('api_token', API_KEY)
        try:
            r = requests.get(f"{BASE_URL}{path}", params=params, timeout=25)
            if r.status_code == 200: return r.json()
        except: pass
        return {}

    def clean_n(name):
        """Extreme cleaning for matching CSV names to API/DNA names."""
        n = str(name).lower()
        for word in["u19", "fc", "sc", "united", "city", "club", "afc", "rc", "as", "deportivo", "atletico"]:
            n = n.replace(word, "")
        return re.sub(r'[^a-z0-9]', '', n).strip()

    def get_match_key(name):
        n = clean_n(name)
        parts = n.split('vs') if 'vs' in n else [n]
        parts =[p.strip() for p in parts]
        parts.sort()
        return "".join(parts)

    # =========================================================
    # 🎲 MONTE CARLO SIMULATION ENGINE (5,000 ITERATIONS)
    # =========================================================
    def run_monte_carlo_ud_score(prob_val, gap):
        """
        2026-10-01 FIX — this no longer simulates. It passes the audit
        engine's probability through unchanged.

        What it used to do:

            base_lambda = (p_val / 62)
            if gap < 0: base_lambda += abs(gap / 105)
            sim_goals = np.random.poisson(base_lambda, 5000)
            return P(sim_goals > 0) * 100

        Three defects, all measured over the settled set:

        1. UNIT ERROR. Dividing a PROBABILITY by 62 to manufacture an
           "expected goals" figure has no meaning. It compressed a 28-point
           input spread into a 23-point output spread and pushed every pick
           into a 58-79% band, so the engine could never express low
           confidence.

        2. THE SIMULATED EVENT WAS THE WRONG ONE. The pack predicts whether
           the underdog SCORES, and "sim_goals > 0" does match that target --
           but only by accident, after the probability had already been
           corrupted. The audit engine had already solved this correctly; this
           re-solved it worse.

        3. THE HANDSHAKE TERM WAS INVERTED AND UNBOUNDED. It paid the
           largest boost to the MOST negative Dominance_Gap, and the data
           shows that group scores LEAST:

               gap < -30     n=27   claims 82.8%   scores 44.4%  (+38.3pp)
               gap -20..-10  n=14   claims 75.0%   scores 85.7%  (-10.7pp)

           with no upper bound at all: a gap of -200 yields 95.6%.

        Measured impact of removing all three (top 20% of the book, 4,000
        bootstrap resamples):

           Apex OUTPUT ranks it    48.9%   CI [29, 71]   (base 64.5%)
           Apex INPUT  ranks it    74.8%   CI [54, 92]
           P(output beats input) = 0.1%

        The audit engine's ranking was demonstrably good and the Apex was
        throwing it away. Passing the value through is what restores it.
        """
        if prob_val is None:
            return None            # no engine probability -> show no number
        try:
            p_val = float(str(prob_val).replace('%', ''))
        except (TypeError, ValueError):
            return None
        if p_val != p_val:            # NaN guard
            return None
        p_val = max(0.0, min(100.0, p_val))

        # 2026-10-01 — reliability shrink toward the measured base rate.
        #
        # Pass-through fixes the RANKING but not the calibration: the audit
        # engine still runs hot at the top end (its top quartile claims 88%
        # and delivers 80%). The old Poisson masked that by flattening every
        # number into a narrow band near the base rate, which is why its error
        # looked smaller while its ranking was inverted.
        #
        # Shrinking corrects the stated magnitude while leaving the ordering
        # untouched, because the transform is monotonic in p. Measured on the
        # settled set (equal-size quartiles, same fixtures both sides):
        #
        #    k=1.00  calibration 15.1pp   top-5%  66.7%   top-20% 75.0%
        #    k=0.85                12.8pp             66.7%            75.0%
        #    k=0.70                10.6pp             66.7%            75.0%
        #    k=0.55                 8.3pp             66.7%            75.0%
        #
        # Ranking is identical across all four, which is the point: k changes
        # only how honestly the number reads, never which fixtures surface.
        return round(_UD_SHRINK(p_val), 2)

    # -------------------------
    # 🚀 THE APEX UD AGGREGATOR EXECUTION
    # -------------------------
    print(f"\n" + "="*145)
    print(f" 🚀 ALIENEDGE APEX UD AGGREGATOR | MONTE CARLO 5,000 | DATE: {target_date} ")
    print("="*145)

    # 1. LOAD DATABASES
    dna_db = {}
    if os.path.exists(FILE_DNA_JSON):
        with open(FILE_DNA_JSON, "r") as f:
            dna_db = json.load(f)
        print(f"[✅] DNA Intelligence Loaded: {len(dna_db)} profiles.")

    # 2. LOAD UNDERDOG POOL (>= 70%)
    list_pool = {}
    if os.path.exists(FILE_UD_ENGINE_CSV):
        df_pool = pd.read_csv(FILE_UD_ENGINE_CSV)
        # Identify correct probability column from your Audit engine
        prob_col = 'Audit_Real_Prob' if 'Audit_Real_Prob' in df_pool.columns else 'dog_score_prob'
        
        for _, row in df_pool.iterrows():
            prob = str(row.get(prob_col, '0%')).replace('%', '')
            if float(prob) >= 70.0:
                f_name = row.get('fixture', row.get('Fixture', 'Unknown'))
                list_pool[get_match_key(f_name)] = {
                    "name": f_name, "prob": prob, 
                    "dog_team": row.get('underdog_team', row.get('Underdog_Side', 'Unknown')),
                    "fav_vuln": row.get('fav_vulnerability_5', 'N/A'),
                    "fixture_id": _valid_fixture_id(row.get('fixture_id'))
                }
        print(f"[✅] Loaded {len(list_pool)} Elite Underdogs from {FILE_UD_ENGINE_CSV}")

    # 3. LOAD HANDSHAKE ANOMALIES (GOSPEL RULES)
    list_handshake = {}
    vip_handshake_buckets = {"🎯 UD Score: Deep Gospel": [], "🎯 Rotten Shield (UD Score)": [], "🎯 General UD Score":[], "🔥 Gospel Kill Shot":[]}

    if os.path.exists(FILE_HANDSHAKE_CSV):
        df_hs = pd.read_csv(FILE_HANDSHAKE_CSV)
        for _, row in df_hs.iterrows():
            f_name = row.get('fixture', 'Unknown')
            try:
                p, d = float(row.get('parity_gap', 0)), float(row.get('Dominance_Gap', 0))
                rule = None
                if p <= 1 and d <= -20: rule = "🎯 UD Score: Deep Gospel"
                elif p <= 1 and d < -10: rule = "🎯 Rotten Shield (UD Score)"
                elif p <= 1 and d < 0: rule = "🎯 General UD Score"
                elif p >= 5 and d <= -20: rule = "🔥 Gospel Kill Shot"
                
                if rule:
                    list_handshake[get_match_key(f_name)] = {"name": f_name, "rule": rule, "p": p, "d": d}
                    vip_handshake_buckets[rule].append(f_name)
            except: continue

    # 4. API FETCH & DNA DUEL
    # Paginated Fetch to ensure all participants are caught for matching
    api_fixtures =[]
    page = 1
    while True:
        resp = GET(f"/fixtures/date/{target_date}", params={"include": "participants", "page": page})
        data = resp.get("data",[])
        if not data: break
        api_fixtures.extend(data)
        if len(data) < 50: break
        page += 1
        time.sleep(0.1)

    api_map = {get_match_key(fx['name']): fx for fx in api_fixtures}
    list_dna = {}

    print(f"[INFO] Running Forensic DNA Comparison (Underdog Intent > Fav Intent)...")

    for key, fx in api_map.items():
        pool_match = list_pool.get(key)
        if not pool_match: continue 
        
        # DNA Retrieval with Fuzzy Fallback
        def find_dna(t_id, t_name):
            if str(t_id) in dna_db: return dna_db[str(t_id)]
            c_name = clean_n(t_name)
            for _, prof in dna_db.items():
                if clean_n(prof.get('team_name', '')) == c_name: return prof
            return None

        hid = next((pt['id'] for pt in fx['participants'] if pt['meta']['location'] == 'home'), None)
        aid = next((pt['id'] for pt in fx['participants'] if pt['meta']['location'] == 'away'), None)

        h_dna = find_dna(hid, fx['name'].split(' vs ')[0])
        a_dna = find_dna(aid, fx['name'].split(' vs ')[1])

        if h_dna and a_dna:
            # Determine which side is the Underdog from the Engine List
            is_home_dog = clean_n(pool_match['dog_team']) in clean_n(fx['name'].split(' vs ')[0])
            dog_dna, fav_dna = (h_dna, a_dna) if is_home_dog else (a_dna, h_dna)

            # THE UNDERDOG DNA DOMINANCE RULE (INTACT)
            # `.get(k, 0)` only defaults when the key is ABSENT. Since schema
            # v4, Tempo is present with the value None when the provider gave
            # us no Passes/Attacks figures, so the default never fires and
            # `None > x` raises TypeError. An unmeasured side must be excluded
            # from the rule, not compared as 0.
            dog_i = dog_dna.get("Market_Power_Scores", {}).get("Goal_Intent")
            fav_i = fav_dna.get("Market_Power_Scores", {}).get("Goal_Intent")
            dog_t = dog_dna.get("Tactical_DNA", {}).get("Tempo")
            fav_t = fav_dna.get("Tactical_DNA", {}).get("Tempo")

            if None in (dog_i, fav_i, dog_t, fav_t):
                continue

            if dog_i > fav_i and dog_t > fav_t:
                list_dna[key] = fx['id']

    # 🏆 CROSS-REFERENCE & RANKING
    all_keys = set(list_pool.keys()).union(list_handshake.keys()).union(list_dna.keys())
    rank_1_2, rank_3 = [],[]

    for key in all_keys:
        pool, hs, dna_f_id = list_pool.get(key), list_handshake.get(key), list_dna.get(key)
        fx_api = api_map.get(key)

        # Ranking logic: All 3 = Rank 1 | 2 sources = Rank 2 | Handshake only = Rank 3
        total_p = int(bool(pool)) + int(bool(hs)) + int(bool(dna_f_id))
        rank = 1 if total_p >= 3 else 2 if total_p == 2 else 3 if hs else 0
        if rank == 0: continue

        # 2026-10-01 FIX — the audit engine's probability passes through unchanged.
        #
        # The previous line was:
        #     m_prob = run_monte_carlo_ud_score(pool['prob'] if pool else 70, ...)
        #
        # That "else 70" FABRICATED a 70% confidence for any fixture whose
        # only evidence was a handshake rule or a DNA match -- neither of
        # which carries a probability at all. A made-up number then competed
        # for rank against genuinely measured ones. It is now None, and such
        # rows are excluded from probability ranking entirely rather than
        # being shown a number that means nothing.
        m_prob = run_monte_carlo_ud_score(
            pool['prob'] if pool else None,
            hs['d'] if hs else "N/A",
        )

        f_id = (_valid_fixture_id(fx_api['id']) if fx_api
                else (_valid_fixture_id(pool.get('fixture_id')) if pool
                      else _valid_fixture_id(dna_f_id)))
        if f_id is None:
            print(f"   ⚠️ SKIPPED (no resolvable fixture_id): {key}")
            continue

        row = {
            "fixture_id": f_id,
            "Fixture": fx_api['name'] if fx_api else (pool['name'] if pool else hs['name']),
            "Rank": f"Rank {rank}",
            # "N/A" rather than a fabricated number when there is no
            # engine probability to report.
            "Monte_UD_Prob": f"{m_prob}%" if m_prob is not None else "N/A",
            "Engine": "✅" if pool else "❌",
            "Handshake": "✅" if hs else "❌",
            "DNA": "✅" if dna_f_id else "❌",
            "Rule": hs['rule'] if hs else "N/A",
            "Fav_Vuln": pool['fav_vuln'] if pool else "N/A"
        }
        if rank in [1, 2]: rank_1_2.append(row)
        else: rank_3.append(row)


    # ==============================================================================
    # 🟢[NEW] THE SH/GG/WINNER ENGINE HANDSHAKE (NON-INTRUSIVE)
    # ==============================================================================
    sh_gg_lookup = {}
    if os.path.exists(GENERAL_FEED_FILE):
        try:
            with open(GENERAL_FEED_FILE, "r") as f:
                feed_data = json.load(f)
                for item in feed_data:
                    sh_gg_lookup[str(item.get("fixture_id"))] = item
        except Exception as e:
            pass # Fails silently if JSON is missing or broken

    # Apply the "Elite" or "VIP" labels safely to existing rows
    for row in rank_1_2 + rank_3:
        f_id = str(row.get("fixture_id", ""))
        label = "-"
        
        if f_id in sh_gg_lookup:
            match_data = sh_gg_lookup[f_id]
            # Check if this match specifically triggered the GG rule in the feed
            is_gg = match_data.get("flags", {}).get("h2h_gg_100", False)
            
            if is_gg:
                label = "VIP"
            else:
                label = "Elite"
                
        # Inject the new column dynamically into your final output dictionaries
        row["SH_GG_Label"] = label
    # ==============================================================================


    # 💾 OUTPUT GENERATION
    print("\n\n" + "★"*145)
    print(f" 🏆 ALIENEDGE SUPREME UNDERDOGS: RANK 1 & 2 (READY FOR LIVE ALERT) ")
    print("★"*145)

    if rank_1_2:
        # 2026-10-01 FIX — sort by the measured probability FIRST.
        #
        # It previously sorted by ["Rank", "Monte_UD_Prob"], so the source
        # COUNT always outranked the measurement: a fixture backed by three
        # agreeing sources but with a weak probability was placed above one
        # with a single strong measurement. Rank is a heuristic about
        # agreement; the probability is what the pick actually rests on.
        # Rank is retained as the tiebreaker.
        df12 = pd.DataFrame(rank_1_2)
        df12["_p_sort"] = pd.to_numeric(
            df12["Monte_UD_Prob"].astype(str).str.replace("%", "", regex=False),
            errors="coerce",
        )
        df12 = (df12.sort_values(by=["_p_sort", "Rank"], ascending=[False, True])
                    .drop(columns=["_p_sort"]))
        print(df12.drop(columns=['fixture_id']).to_string(index=False))
        # Save results to the specific output folder for Code 4 to find later
        df12.to_csv(os.path.join(OUTPUT_DIR, f"FINAL_APEX_UD_SCORE_{target_date}.csv"), index=False)
    else:
        print("   No Rank 1 or 2 underdogs found for this date.")

    if rank_3:
        print("\n" + "⚠️"*145)
        print(f" 📜 RANK 3 STANDALONE: DEEP GOSPEL & ROTTEN SHIELD ANOMALIES ")
        print("⚠️"*145)
        df3 = pd.DataFrame(rank_3).sort_values(by=["Monte_UD_Prob"], ascending=[False])
        print(df3.drop(columns=['fixture_id']).to_string(index=False))

    # 2026-10-01 FIX — return the SORTED frame, not the raw list.
    #
    # The sort fix above (probability before source count) was applied to
    # df12 for display and for the CSV, but the function returned the
    # original `rank_1_2` list. main.py persists whatever this returns into
    # output/cache/underdog_apex__<date>.json, which is what the API serves
    # and the frontend ranks from -- so the correction never reached the
    # user. Verified: the 2026-10-02 cache was still in match-key order
    # (85.84, 75.72, 78.06, 78.48, ...) while the CSV was correctly sorted.
    return (df12.to_dict(orient="records") if rank_1_2 else [])

# --- LOCAL TESTING BLOCK ---
if __name__ == "__main__":
    test_date = "2026-02-27"
    pd.set_option('display.max_rows', None)
    pd.set_option('display.width', 1000)
    run_apex_underdog_aggregator(test_date)