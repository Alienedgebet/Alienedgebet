import os
import sys
import time
import requests
import pandas as pd
import json
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# --- 1. HOSTING & ENVIRONMENT SETUP ---
# The API key is read from the environment / .env file:
#   SPORTMONKS_API_KEY=your_key_here
load_dotenv()

# ==============================================================================
# CONFIGURATION & VS CODE STRICT PATHS
# ==============================================================================
API_TOKEN = os.getenv("SPORTMONKS_API_KEY")
BASE_URL  = "https://api.sportmonks.com/v3/football"

# --- STRICT VS CODE ARCHITECTURE (Sub-folder compatible) ---
BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR   = os.path.join(BASE_DIR, "data")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(DATA_DIR,   exist_ok=True)

# FIX: the 100% 2H-activity gate now needs this many finished matches with
# readable half-time data. Before, a team with 1-2 matches could pass as "100%".
MIN_FORM_GAMES = 5
REQUEST_DELAY = 0.2

# Event type IDs counted as goals in the late-goal check. Unchanged from the
# original. Please verify these against SportMonks' types endpoint (own goals /
# penalties may have separate IDs).
LATE_GOAL_TYPE_IDS = [14, 52]

# GLOBAL CACHES TO PREVENT DUPLICATE API CALLS
# FIX: team stats are now keyed by (team_id, date). Keyed by team_id alone, a
# second call for a different date in the same process (backtests, an
# aggregator running several dates) reused stats built for the first date.
TEAM_STATS_CACHE = {}
LEAGUE_CACHE = {}

# FIX: failures used to be swallowed silently. They are now recorded so that
# failed calls are reported and never cached as if they were real "no data".
API_FAILURES = []

# Column order for the output files (keeps the CSV valid even when empty)
OUTPUT_COLUMNS = [
    "fixture", "ht_score", "ft_score", "h_id", "a_id", "league_id",
    "shvi_score", "shvi_label", "sh_pressure", "country", "comb_sh_r",
    "avg_fh_goals", "h_sh_r_disp", "a_sh_r_disp", "h_sh_c_r_disp",
    "a_sh_c_r_disp", "Category",
]

# ==============================================================================
# TITANIUM HTTP HELPER (ANTI-CRASH & ANTI-RATE LIMIT)
# ==============================================================================
def GET(endpoint, params=None):
    if params is None: params = {}
    params.setdefault('api_token', API_TOKEN)
    url = f"{BASE_URL}{endpoint}"

    max_retries = 5
    backoff = 2.0
    last_issue = None
    
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, timeout=15)
            if r.status_code == 200:
                payload = r.json()
                time.sleep(REQUEST_DELAY)
                return payload
            elif r.status_code == 429:
                # Rate limit hit! Pause and wait before trying again.
                last_issue = "HTTP 429"
                time.sleep(backoff * (attempt + 1))
                continue
            else:
                # Other API errors (like 500 server error)
                last_issue = f"HTTP {r.status_code}"
                time.sleep(1.0)
                continue
        except Exception as exc:
            # Network failure or timeout
            last_issue = f"{type(exc).__name__}: {exc}"
            time.sleep(backoff)
            continue
            
    # If it fails all 5 times, return empty data safely (but record it)
    API_FAILURES.append((endpoint, last_issue))
    if len(API_FAILURES) <= 5:
        print(f"[SHVI][API-FAIL] {endpoint} -> {last_issue}", flush=True)
    return {"data": []}

# ==============================================================================
# UTILS & EXTRACTION LOGIC
# ==============================================================================
def get_scores_ht_ft(scores_list):
    """
    FIX 1: the half-time score is None when no 1ST_HALF entry exists. It used to
    default to 0, which made every goal count as a second-half goal for matches
    with missing half-time data (and could fake a "100% 2H activity" record).
    FIX 2: full time prefers CURRENT, then FULL_TIME, and uses 2ND_HALF only as
    a last fallback. Before, all three overwrote the same value, so whichever
    came last in the list won.
    """
    h_ht, a_ht = None, None
    cur = {"home": None, "away": None}
    full = {"home": None, "away": None}
    sh = {"home": None, "away": None}

    for s in (scores_list or []):
        desc = s.get("description", "")
        if "score" in s:
            p = s["score"].get("participant")
            g = int(s["score"].get("goals", 0))
        else:
            p = s.get("participant")
            g = int(s.get("goals", 0))

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
    """Was `team_id` the home side? An explicit meta.location wins; when it is
    blank the second participant is assumed to be the away side."""
    for i, p in enumerate(fixture.get("participants", [])):
        if str(p.get("id")) == str(team_id):
            loc = (p.get("meta") or {}).get("location", "")
            if loc == "away":
                return False
            if loc == "":
                return i != 1
            return True
    return True

def _split_home_away(parts):
    """FIX: the fixture's home/away teams were taken from list order
    (parts[0] = home, parts[1] = away). The explicit meta.location is now used,
    and list order is only the fallback when it is missing."""
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

# ==============================================================================
# SINGLE MEGA-FUNCTION (Replaces original duplicate functions)
# ==============================================================================
def get_team_stats_cached(team_id, check_date_str):
    """
    Fetches the team's last 5 matches ONCE and calculates BOTH the
    Phase 1 (2H Activity) AND Phase 2 (SHVI Detailed) stats simultaneously.
    Saves the result in a cache so it never fetches the same team twice
    for the same date. A failed API call is never cached.

    `total_matches` is now the number of matches with readable half-time data
    (matches with no half-time score are skipped, not counted).
    """
    cache_key = (team_id, check_date_str)
    if cache_key in TEAM_STATS_CACHE:
        return TEAM_STATS_CACHE[cache_key]

    failures_before = len(API_FAILURES)

    target_date_obj = datetime.strptime(check_date_str, "%Y-%m-%d")
    end = (target_date_obj - timedelta(days=1)).strftime("%Y-%m-%d")
    start = (target_date_obj - timedelta(days=120)).strftime("%Y-%m-%d")

    params = {
        "include": "scores;participants;events",
        "per_page": 10,
        "filters": "fixtureStates:5",
        "order": "desc"
    }
    resp = GET(f"/fixtures/between/{start}/{end}/{team_id}", params=params)

    # Filter for valid dates and get strictly the last 5
    valid_matches = [m for m in resp.get("data", []) if (m.get("starting_at") or "").split(" ")[0] < check_date_str][:5]

    stats = {
        "total_matches": 0,
        "2h_activity_rate": 0,
        "ht_r": 0, "ht_c_r": 0, "sh_r": 0, "sh_c_r": 0,
        "avg_fh_g": 0, "late_goals": 0
    }

    games_with_2h_activity = 0
    fh_scored, fh_conceded = 0, 0
    sh_scored, sh_conceded = 0, 0
    total_fh_goals = 0
    late_goals = 0
    counted = 0

    for m in valid_matches:
        (h_ht, a_ht), (h_ft, a_ft) = get_scores_ht_ft(m.get("scores", []))
        if h_ht is None or a_ht is None:
            continue
        counted += 1

        # Check 2H Activity (Phase 1 Logic)
        if (h_ft + a_ft) - (h_ht + a_ht) > 0:
            games_with_2h_activity += 1

        # Determine Home/Away for Phase 2 Logic
        is_home = _was_home(m, team_id)

        if is_home:
            t_fh_s, t_fh_c = h_ht, a_ht
            t_sh_s, t_sh_c = (h_ft - h_ht), (a_ft - a_ht)
        else:
            t_fh_s, t_fh_c = a_ht, h_ht
            t_sh_s, t_sh_c = (a_ft - a_ht), (h_ft - h_ht)

        if t_fh_s > 0: fh_scored += 1
        if t_fh_c > 0: fh_conceded += 1
        if t_sh_s > 0: sh_scored += 1
        if t_sh_c > 0: sh_conceded += 1
        total_fh_goals += (t_fh_s + t_fh_c)

        # Check Late Goals (70-90 min)
        for ev in m.get("events", []):
            # FIX: a null minute no longer crashes the comparison
            if (ev.get("minute") or 0) >= 70 and str(ev.get("participant_id", "")) == str(team_id) and ev.get("type_id") in LATE_GOAL_TYPE_IDS:
                late_goals += 1
                break

    if counted > 0:
        stats["total_matches"] = counted
        stats["2h_activity_rate"] = (games_with_2h_activity / counted) * 100
        stats["ht_r"] = fh_scored / counted
        stats["ht_c_r"] = fh_conceded / counted
        stats["sh_r"] = sh_scored / counted
        stats["sh_c_r"] = sh_conceded / counted
        stats["avg_fh_g"] = total_fh_goals / counted
        stats["late_goals"] = late_goals

    # FIX: never cache a result built from a failed call
    if len(API_FAILURES) == failures_before:
        TEAM_STATS_CACHE[cache_key] = stats
    return stats

# ==============================================================================
# SH VOLATILITY INDEX (SHVI) ENGINE
# ==============================================================================
def apply_shvi_upgrade(base_results, check_date_str, verbose=False):
    if verbose:
        print("\n==============================================================================")
        print("🚀 APPLYING SH VOLATILITY INDEX (STRICT FILTER MODE)")
        print("==============================================================================")

    upgraded_matches = []

    for fid, data in base_results.items():
        # FIX: one bad record no longer kills the whole run
        try:
            h_id, a_id = data["h_id"], data["a_id"]
            league_id = data["league_id"]

            # Cache League API calls too
            if league_id not in LEAGUE_CACHE:
                failures_before = len(API_FAILURES)
                resp = GET(f"/leagues/{league_id}", params={"include": "country"})
                # FIX: a league with country: null no longer raises AttributeError
                country_name = ((resp.get("data") or {}).get("country") or {}).get("name", "Unknown")
                # FIX: a failed lookup is not cached as "Unknown"
                if len(API_FAILURES) == failures_before:
                    LEAGUE_CACHE[league_id] = country_name
            else:
                country_name = LEAGUE_CACHE[league_id]

            # Use the CACHED stats (Instant! Zero API calls here!)
            h_s = TEAM_STATS_CACHE[(h_id, check_date_str)]
            a_s = TEAM_STATS_CACHE[(a_id, check_date_str)]

            if h_s["total_matches"] == 0 or a_s["total_matches"] == 0:
                continue

            # ==========================================
            # HARD FILTERS: ANY FAILURE = INSTANT DELETE
            # ==========================================
            if h_s["sh_r"] < 0.50 or a_s["sh_r"] < 0.50: continue

            comb_sh_r = h_s["sh_r"] + a_s["sh_r"]
            if comb_sh_r < 1.10: continue

            if h_s["sh_c_r"] < 0.35 or a_s["sh_c_r"] < 0.35: continue

            total_m = h_s["total_matches"] + a_s["total_matches"]
            avg_fh_goals = ((h_s["avg_fh_g"] * h_s["total_matches"]) + (a_s["avg_fh_g"] * a_s["total_matches"])) / total_m
            if avg_fh_goals < 0.5: continue

            sh_pressure = (h_s["sh_r"] + a_s["sh_r"] + h_s["sh_c_r"] + a_s["sh_c_r"]) * 100
            if sh_pressure < 200: continue

            # ==========================================
            # MATCH SURVIVED: CALCULATE SHVI
            # ==========================================
            shvi = 0
            if h_s["sh_r"] > h_s["ht_r"]: shvi += 2
            if a_s["sh_r"] > a_s["ht_r"]: shvi += 2
            if h_s["sh_c_r"] > h_s["ht_c_r"]: shvi += 2
            if a_s["sh_c_r"] > a_s["ht_c_r"]: shvi += 2
            if comb_sh_r >= 1.30: shvi += 2
            if 0.8 <= avg_fh_goals <= 1.6: shvi += 1
            if h_s["late_goals"] > 0 and a_s["late_goals"] > 0: shvi += 2

            # Assign Volatility Label
            if shvi >= 10: label = "🔥 Very explosive SH"
            elif shvi >= 7: label = "⚡ Good SH match"
            elif shvi >= 4: label = "⚖️ Neutral"
            else: label = "🛑 Avoid"

            data["shvi_score"] = shvi
            data["shvi_label"] = label
            data["sh_pressure"] = int(sh_pressure)
            data["country"] = country_name
            data["comb_sh_r"] = int(comb_sh_r * 100)
            data["avg_fh_goals"] = round(avg_fh_goals, 2)
            data["h_sh_r_disp"], data["a_sh_r_disp"] = int(h_s["sh_r"] * 100), int(a_s["sh_r"] * 100)
            data["h_sh_c_r_disp"], data["a_sh_c_r_disp"] = int(h_s["sh_c_r"] * 100), int(a_s["sh_c_r"] * 100)
            
            # Categorize for validation sorting
            if shvi >= 10: data["Category"] = "🔥 TIER 1 - EXPLOSIVE SH"
            elif shvi >= 7: data["Category"] = "⚡ TIER 2 - GOOD SH"
            else: data["Category"] = "⚖️ TIER 3 - NEUTRAL"

            upgraded_matches.append(data)

        except Exception as exc:
            print(f"[SHVI][ERROR] fixture {fid} skipped in SHVI stage: "
                  f"{type(exc).__name__}: {exc}", flush=True)
            continue

    upgraded_matches.sort(key=lambda x: x["shvi_score"], reverse=True)

    if verbose:
        for m in upgraded_matches:
            ht = m.get("ht_score", "0-0")
            ft = m.get("ft_score", "0-0")
            print(f"[{m['country'].upper()}] {m['fixture']} [HT: {ht} | FT: {ft}]")
            print(f"   => SHVI: {m['shvi_score']}/13 ({m['shvi_label']}) | Pressure: {m['sh_pressure']}")
            print(f"   => SH Rates: Home {m['h_sh_r_disp']}% / Away {m['a_sh_r_disp']}% (Combined {m['comb_sh_r']}%)")
            print(f"   => SH Conceded: Home {m['h_sh_c_r_disp']}% / Away {m['a_sh_c_r_disp']}%")
            print(f"   => Avg Match FH Goals: {m['avg_fh_goals']:.1f}")
            print("-" * 75)

    return upgraded_matches

# ==============================================================================
# FILE WRITING (ALWAYS PRODUCES VALID FILES)
# ==============================================================================
def _save_outputs(upgraded_data, target_date):
    """FIX: files are always written, even when nothing survives, so the
    Auditor / aggregator never reads a stale file from a previous run. The CSV
    always has a header row (an empty headerless CSV makes pandas fail with
    "No columns to parse from file"). Both are written to a temp file first and
    swapped in, so a crash mid-write cannot leave a half-written file."""
    json_file = os.path.join(OUTPUT_DIR, f"shvi_strict_filtered_{target_date}.json")
    csv_file = os.path.join(OUTPUT_DIR, f"shvi_strict_filtered_{target_date}.csv")

    tmp_json = json_file + ".tmp"
    with open(tmp_json, "w", encoding='utf-8') as f:
        json.dump(upgraded_data, f, indent=4, ensure_ascii=False)
    os.replace(tmp_json, json_file)

    if upgraded_data:
        df = pd.DataFrame(upgraded_data)
        extra_cols = [c for c in df.columns if c not in OUTPUT_COLUMNS]
        df = df[[c for c in OUTPUT_COLUMNS if c in df.columns] + extra_cols]
    else:
        df = pd.DataFrame(columns=OUTPUT_COLUMNS)
    tmp_csv = csv_file + ".tmp"
    df.to_csv(tmp_csv, index=False)
    os.replace(tmp_csv, csv_file)

    return json_file, csv_file

# ==============================================================================
# MAIN RUNNER WRAPPER
# ==============================================================================
def run_shvi_engine(target_date=None, verbose=False):
    """
    Executes the SHVI Streak Miner Engine.
    Fully wrapped for the VS Code Pipeline.
    verbose=False keeps it silent for API/Aggregator calls, BUT ALWAYS SAVES CSV/JSON.
    """
    if not API_TOKEN or API_TOKEN == "YOUR_API_KEY_HERE":
        raise ValueError("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")

    if target_date is None:
        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Fresh failure log per run
    API_FAILURES.clear()

    if verbose:
        print(f"\n--- ⛏️ STREAK MINER (STRICT SHVI MODE - HYPER OPTIMIZED) ---")
        print(f"Target: {target_date}")

    # 1. FETCH TODAY'S FIXTURES (With Titanium Anti-Loop Memory)
    all_fx = []
    seen = set()
    page = 1
    while True:
        params = {"include": "participants;scores", "per_page": 50, "page": page}
        failures_before = len(API_FAILURES)
        resp = GET(f"/fixtures/date/{target_date}", params=params)
        data = resp.get("data", [])
        if len(API_FAILURES) > failures_before:
            # FIX: a failed page used to look like "end of slate" and silently
            # truncated the day. It is now flagged.
            if not all_fx:
                raise RuntimeError(f"Could not fetch fixtures for {target_date} (API failure).")
            print(f"[SHVI][WARN] Fixture page {page} failed - the slate may be incomplete.", flush=True)
            break
        if not data: break
        
        added_new = False
        for f in data:
            fid = f.get("id")
            if fid not in seen:
                seen.add(fid)
                all_fx.append(f)
                added_new = True
                
        if not added_new: break
        page += 1

    if verbose:
        print(f"Total Matches to Analyze: {len(all_fx)}\n")
        print("⏳ Processing matches (this will be much faster now)...\n")
        
    results = {}
    fixture_errors = 0

    for i, fx in enumerate(all_fx):
        # FIX: one malformed fixture no longer crashes the whole run
        try:
            parts = fx.get("participants", [])
            if len(parts) < 2: continue

            fid = str(fx["id"])
            league_id = str(fx.get("league_id", ""))
            # FIX: home/away from meta.location, not list order
            home_p, away_p = _split_home_away(parts)
            h_id, h_name = str(home_p["id"]), home_p["name"]
            a_id, a_name = str(away_p["id"]), away_p["name"]

            (h_ht, a_ht), (h_ft, a_ft) = get_scores_ht_ft(fx.get("scores", []))
            # An unplayed fixture has no half-time score; show 0 as before
            h_ht = 0 if h_ht is None else h_ht
            a_ht = 0 if a_ht is None else a_ht

            # SHORT-CIRCUIT LOGIC: Only fetch Away team if Home team passes 100% test!
            # FIX: the 100% test now also needs MIN_FORM_GAMES readable matches.
            h_stats = get_team_stats_cached(h_id, target_date)
            if h_stats["total_matches"] < MIN_FORM_GAMES or h_stats["2h_activity_rate"] != 100:
                continue # Instantly skip this match, saving 1 API call

            a_stats = get_team_stats_cached(a_id, target_date)
            if a_stats["total_matches"] < MIN_FORM_GAMES or a_stats["2h_activity_rate"] != 100:
                continue # Instantly skip

            # If it reaches here, BOTH teams have 100% 2H Activity!
            results[fid] = {
                "fixture": f"{h_name} vs {a_name}",
                "ht_score": f"{h_ht}-{a_ht}",
                "ft_score": f"{h_ft}-{a_ft}",
                "h_id": h_id,
                "a_id": a_id,
                "league_id": league_id,
            }
        except Exception as exc:
            fixture_errors += 1
            if fixture_errors <= 5:
                fid_err = fx.get("id", "<unknown>") if isinstance(fx, dict) else "<unknown>"
                print(f"[SHVI][ERROR] fixture {fid_err} skipped: {type(exc).__name__}: {exc}", flush=True)
            continue

    upgraded_data = []
    
    if results:
        upgraded_data = apply_shvi_upgrade(results, target_date, verbose=verbose)
    else:
        if verbose:
            print("\nNo matches passed the initial engine. Upgrade bypassed.")

    # ==============================================================
    # GUARANTEED SAVE: The Auditor reads these files!
    # Always written, even when empty (see _save_outputs).
    # ==============================================================
    json_file, csv_file = _save_outputs(upgraded_data, target_date)

    if verbose:
        print(f"\n✅ Filtered SHVI results saved to {json_file} and {csv_file}")
        if not upgraded_data:
            print("⚠️ Zero matches survived the strict filters today. No bets recommended.")

    # FIX: report problems instead of hiding them
    if API_FAILURES:
        print(f"[SHVI][WARN] {len(API_FAILURES)} API call(s) failed after retries. "
              f"Some teams/fixtures may be missing from the results.", flush=True)
    if fixture_errors:
        print(f"[SHVI][WARN] {fixture_errors} fixture(s) skipped due to errors.", flush=True)

    return upgraded_data

# ==============================================================================
# INDEPENDENT CALL WRAPPERS (FOR VS CODE AGGREGATORS)
# ==============================================================================
def get_shvi_predictions(target_date=None, verbose=False):
    """Call this from your aggregator to instantly receive the SHVI picks list."""
    return run_shvi_engine(target_date, verbose)

# --- LOCAL RUN EXECUTION ---
# Usage:
#   python shvi_streak_miner_server.py                -> tomorrow (UTC)
#   python shvi_streak_miner_server.py 2026-10-12     -> that date
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
    # When running manually, verbose=True prints the results to the screen
    run_shvi_engine(_date, verbose=True)
