import os
import sys
import time
import json
import math
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
# The API key is read from the environment / .env file:
#   SPORTMONKS_API_KEY=your_key_here
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS ---
# This ensures the engine saves to the 'output' folder regardless of environment
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

# ==============================================================================
# 📦 THE BLACK BOX WRAPPER (CALLABLE BY THE MASTER PIPELINE)
# ==============================================================================
def run_sh_master_vortex(target_date):
    """
    Executes the SH Volatility Index (SHVI) Engine.
    Math: 13-Point Segmental Audit.
    Logic: Time Machine protected.

    The filters, the 13-point scoring and the output files are unchanged.
    Fixes applied in this version are marked with "FIX".

    target_date: string "YYYY-MM-DD"
    """
    # Ensure directories exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    # -------------------------
    # CONFIGURATION
    # -------------------------
    API_KEY = os.getenv("SPORTMONKS_API_KEY")
    BASE_URL = "https://api.sportmonks.com/v3/football"
    
    # Forensic Constants
    SAMPLE_SIZE = 5
    LOOKBACK_DAYS = 150
    REQUEST_DELAY = 0.2
    
    if not API_KEY:
        print("CRITICAL: SPORTMONKS_API_KEY is missing!")
        return[]

    # FIX: failures were swallowed silently, so an outage or rate limit just made
    # fixtures vanish from the report. They are now recorded and reported.
    API_FAILURES = []
    FIXTURE_ERRORS = []

    # -------------------------
    # UTILITIES (V3 COMPLIANT)
    # -------------------------
    def GET(path, params=None):
        # Note: If running through Main.py, this 'requests.get' is hijacked by the Warden
        if params is None: params = {}
        params.setdefault("api_token", API_KEY)
        last_issue = None
        # FIX: up to 3 attempts, with a proper backoff on rate limiting (429).
        # Before there was a single attempt, and REQUEST_DELAY was never used.
        for attempt in range(3):
            try:
                r = requests.get(f"{BASE_URL}{path}", params=params, timeout=30)
                if r.status_code == 200:
                    payload = r.json()
                    time.sleep(REQUEST_DELAY)
                    return payload
                last_issue = f"HTTP {r.status_code}"
                time.sleep(2 ** attempt if r.status_code == 429 else 1)
            except Exception as e:
                last_issue = f"{type(e).__name__}: {e}"
                time.sleep(1)
        API_FAILURES.append((path, last_issue))
        if len(API_FAILURES) <= 5:
            print(f"API Error: {path} -> {last_issue}", flush=True)
        return {"data":[]}

    def get_scores_ht_ft(scores_list):
        """
        Forensically separates First Half (FH) and Second Half (SH) goals.

        FIX 1: the half-time score is None when no 1ST_HALF entry exists. It
        used to default to 0, which made every goal count as a second-half goal
        for matches with missing half-time data.
        FIX 2: full time prefers CURRENT, then FULL_TIME, and uses 2ND_HALF only
        as a last fallback. Before, all three overwrote the same value, so
        whichever came last in the list won.
        """
        h_ht, a_ht = None, None
        cur = {"home": None, "away": None}
        full = {"home": None, "away": None}
        sh = {"home": None, "away": None}
        for s in (scores_list or []):
            desc = s.get("description", "")
            # Handle nested V3 structure
            score_obj = s.get("score") if "score" in s else s
            p = score_obj.get("participant")
            g = int(score_obj.get("goals", 0))

            if desc == "1ST_HALF":
                if p == "home": h_ht = g
                elif p == "away": a_ht = g
            if desc == "CURRENT" and p in cur:
                cur[p] = g
            elif desc == "FULL_TIME" and p in full:
                full[p] = g
            elif desc == "2ND_HALF" and p in sh:
                sh[p] = g

        def pick(side):
            for src in (cur, full, sh):
                if src[side] is not None:
                    return src[side]
            return 0

        return (h_ht, a_ht), (pick("home"), pick("away"))

    def _was_home(fixture, team_id):
        """FIX: location check is safe against a missing meta block."""
        return any(
            str(p.get('id')) == str(team_id) and (p.get('meta') or {}).get('location') == 'home'
            for p in fixture.get('participants', [])
        )

    def _split_home_away(parts):
        """FIX: the fixture's home/away teams were taken from list order
        (parts[0] = home, parts[1] = away). The explicit meta.location is now
        used, and list order is only the fallback when it is missing."""
        home, away = None, None
        for p in parts:
            loc = (p.get("meta") or {}).get("location", "")
            if loc == "home" and home is None:
                home = p
            elif loc == "away" and away is None:
                away = p
        if home is None or away is None:
            return parts[0], parts[1]
        return home, away

    # -------------------------
    # FORENSIC SEGMENTAL ANALYSIS
    # -------------------------
    volatility_cache = {}

    def analyze_team_volatility(team_id, check_date_str):
        """
        TIME MACHINE logic: Only looks at games BEFORE the target_date.
        Analyzes scoring/conceding frequency per half.

        FIX: a team's result is cached (the same team can appear on a slate
        more than once), and matches with no half-time data are skipped
        instead of being counted as if every goal came in the second half.
        """
        if team_id in volatility_cache:
            return volatility_cache[team_id]

        failures_before = len(API_FAILURES)

        target_dt = datetime.strptime(check_date_str, "%Y-%m-%d")
        end_date = (target_dt - timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = (target_dt - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

        params = {
            "include": "scores;participants;events",
            "per_page": 20,
            "filters": "fixtureStates:5",
            "order": "desc"
        }
        resp = GET(f"/fixtures/between/{start_date}/{end_date}/{team_id}", params=params)
        data = resp.get("data",[])
        
        # Enforce strict chronological order
        valid_matches = [m for m in data if (m.get("starting_at") or "").split(" ")[0] < check_date_str][:SAMPLE_SIZE]

        if not valid_matches:
            result = {"total": 0}
            if len(API_FAILURES) == failures_before:
                volatility_cache[team_id] = result
            return result

        fh_s, fh_c = 0, 0
        sh_s, sh_c = 0, 0
        total_fh_goals = 0
        late_goals = 0
        counted = 0

        for m in valid_matches:
            (h_ht, a_ht), (h_ft, a_ft) = get_scores_ht_ft(m.get("scores",[]))
            if h_ht is None or a_ht is None:
                continue
            counted += 1
            
            # Find team location in history
            is_home = _was_home(m, team_id)

            if is_home:
                t_fh_s, t_fh_c = h_ht, a_ht
                t_sh_s, t_sh_c = (h_ft - h_ht), (a_ft - a_ht)
            else:
                t_fh_s, t_fh_c = a_ht, h_ht
                t_sh_s, t_sh_c = (a_ft - a_ht), (h_ft - h_ht)

            # Record frequency (Did they score/concede > 0?)
            if t_fh_s > 0: fh_s += 1
            if t_fh_c > 0: fh_c += 1
            if t_sh_s > 0: sh_s += 1
            if t_sh_c > 0: sh_c += 1
            
            total_fh_goals += (t_fh_s + t_fh_c)

            # 70 min+ Goal Audit (The Final Strike)
            for ev in m.get("events",[]):
                # FIX: a null minute no longer crashes the comparison
                if (ev.get("minute") or 0) >= 70 and str(ev.get("participant_id")) == str(team_id):
                    if ev.get("type_id") in[14, 52]: # Goal or Penalty
                        late_goals += 1
                        break 

        count = counted
        if count == 0:
            result = {"total": 0}
        else:
            result = {
                "ht_r": fh_s/count, "ht_c_r": fh_c/count, # First Half Rates
                "sh_r": sh_s/count, "sh_c_r": sh_c/count, # Second Half Rates
                "avg_fh_g": total_fh_goals/count,
                "late_goals": late_goals,
                "total": count
            }
        if len(API_FAILURES) == failures_before:
            volatility_cache[team_id] = result
        return result

    # -------------------------
    # MAIN ENGINE PIPELINE
    # -------------------------
    print(f"\n[ENGINE] 🌪️ SHVI VORTEX ACTIVATED FOR {target_date}")
    
    # 1. Fetch Full Daily Slate
    all_fixtures =[]
    page = 1
    while True:
        resp = GET(f"/fixtures/date/{target_date}", params={"include": "participants;scores;league", "per_page": 50, "page": page})
        data = resp.get("data",[])
        if not data: break
        all_fixtures.extend(data)
        if len(data) < 50: break
        page += 1

    print(f" > Auditing {len(all_fixtures)} fixtures for 13-point volatility...")

    results =[]
    league_names = {}

    for idx, fx in enumerate(all_fixtures, 1):
        try:
            parts = fx.get("participants",[])
            if len(parts) < 2: continue

            # FIX: home/away now taken from meta.location, not list order.
            home_p, away_p = _split_home_away(parts)
            h_id, h_name = str(home_p["id"]), home_p["name"]
            a_id, a_name = str(away_p["id"]), away_p["name"]

            # H2H SKIP RULE: Minimum 4 matches to ensure data integrity
            # FIX: only finished meetings are counted (fixtureStates:5), so an
            # unplayed meeting can no longer pass the minimum.
            h2h_data = GET(f"/fixtures/head-to-head/{h_id}/{a_id}",
                           params={"filters": "fixtureStates:5", "per_page": 10})
            if len(h2h_data.get("data",[])) < 4:
                continue

            # Step 1: Individual Forensic Analysis
            h_v = analyze_team_volatility(h_id, target_date)
            a_v = analyze_team_volatility(a_id, target_date)

            if h_v.get("total", 0) < 4 or a_v.get("total", 0) < 4:
                continue

            # Step 2: Apply Hard Filters (The Survival Gate)
            if h_v["sh_r"] < 0.50 or a_v["sh_r"] < 0.50: continue # Both must score 2H in 50%+
            comb_sh_r = h_v["sh_r"] + a_v["sh_r"]
            if comb_sh_r < 1.10: continue # Must show collective 2H dominance
            if h_v["sh_c_r"] < 0.35 or a_v["sh_c_r"] < 0.35: continue # Must have leaky 2H defenses

            # Step 3: The 13-Point VORTEX SCORING
            shvi = 0
            # Trends (+8 pts max)
            if h_v["sh_r"] > h_v["ht_r"]: shvi += 2
            if a_v["sh_r"] > a_v["ht_r"]: shvi += 2
            if h_v["sh_c_r"] > h_v["ht_c_r"]: shvi += 2
            if a_v["sh_c_r"] > a_v["ht_c_r"]: shvi += 2
            
            # Volume Indicators (+3 pts max)
            if comb_sh_r >= 1.30: shvi += 2
            avg_fh = (h_v["avg_fh_g"] + a_v["avg_fh_g"]) / 2
            if 0.8 <= avg_fh <= 1.6: shvi += 1 # Sweet spot for 2nd half escalation
            
            # Late Game Threat (+2 pts max)
            if h_v["late_goals"] > 0 and a_v["late_goals"] > 0: shvi += 2

            # Step 4: Finalize Match Object
            l_id = str(fx.get("league_id", ""))
            if l_id not in league_names:
                l_resp = GET(f"/leagues/{l_id}")
                l_data = l_resp.get("data") or {}
                league_names[l_id] = l_data.get("name", "Unknown") if isinstance(l_data, dict) else "Unknown"

            (h_ht, a_ht), (h_ft, a_ft) = get_scores_ht_ft(fx.get("scores",[]))
            # An unplayed fixture has no half-time score; show 0 as before
            h_ht = 0 if h_ht is None else h_ht
            a_ht = 0 if a_ht is None else a_ht

            results.append({
                "fixture": f"{h_name} vs {a_name}",
                "league": league_names[l_id],
                "shvi_score": shvi,
                "sh_pressure": int((comb_sh_r + h_v['sh_c_r'] + a_v['sh_c_r']) * 100),
                "ht": f"{h_ht}-{a_ht}",
                "ft": f"{h_ft}-{a_ft}",
                "sh_scoring_rate": f"{int(h_v['sh_r']*100)}% / {int(a_v['sh_r']*100)}%",
                "avg_fh_goals": round(avg_fh, 2),
                "late_threat": "🔥 HIGH" if h_v['late_goals'] > 0 and a_v['late_goals'] > 0 else "NORMAL"
            })

        except Exception as exc:
            # FIX: the error is logged instead of silently skipped
            fid_err = fx.get("id", "<unknown>") if isinstance(fx, dict) else "<unknown>"
            FIXTURE_ERRORS.append((fid_err, exc))
            if len(FIXTURE_ERRORS) <= 5:
                print(f"[SHVI][ERROR] fixture {fid_err} skipped: {type(exc).__name__}: {exc}", flush=True)
            continue

    # FIX: report problems instead of hiding them
    if API_FAILURES:
        print(f"[SHVI][WARN] {len(API_FAILURES)} API call(s) failed after retries. "
              f"Affected fixtures may be missing from the report.", flush=True)
    if FIXTURE_ERRORS:
        print(f"[SHVI][WARN] {len(FIXTURE_ERRORS)} fixture(s) skipped due to errors.", flush=True)

    # Step 5: Sorting & Saving
    if results:
        df = pd.DataFrame(results).sort_values(by="shvi_score", ascending=False)
        
        # Save both formats to Output folder
        csv_path = os.path.join(OUTPUT_DIR, f"shvi_vortex_report_{target_date}.csv")
        json_path = os.path.join(OUTPUT_DIR, f"shvi_vortex_report_{target_date}.json")
        
        df.to_csv(csv_path, index=False)
        df.to_json(json_path, orient="records", indent=4)
        
        print("\n" + "="*80)
        print(f"🏆 SHVI VORTEX COMPLETE: {len(df)} VOLATILE MATCHES FOUND")
        print("="*80)
        # Display Top 10
        print(df[["fixture", "shvi_score", "sh_pressure", "ht", "ft"]].head(10).to_string(index=False))
        
        return results
    else:
        print(" > No matches survived the SHVI Vortex filters today.")
        # FIX: returns an empty list instead of None, so a caller that loops
        # over the result cannot crash.
        return []

# ==============================================================================
# IF RUN DIRECTLY (TESTING / CRON)
# ==============================================================================
# Usage:
#   python sh_master_vortex_server.py                -> tomorrow (UTC)
#   python sh_master_vortex_server.py 2026-10-12     -> that date
# No interactive prompt, so it is safe under cron / systemd / schedulers.
if __name__ == "__main__":
    if len(sys.argv) > 1:
        _date = sys.argv[1].strip()
        try:
            datetime.strptime(_date, "%Y-%m-%d")
        except ValueError:
            raise SystemExit(f"Invalid date '{_date}'. Use the format YYYY-MM-DD.")
    else:
        _date = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    run_sh_master_vortex(_date)
