import os
import sys
import time
import json
import requests
from datetime import datetime, timedelta, timezone

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
# The API key is read from the environment / .env file:
#   SPORTMONKS_API_KEY=your_key_here
from dotenv import load_dotenv
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

# ==============================================================================
# 📦 THE BLACK BOX WRAPPER (CALLABLE BY THE MASTER API/SCHEDULER)
# ==============================================================================
def run_sh_gg_winner_engine(target_date):
    """
    Executes the Second Half, GG & Winner Engine.
    Streak rules and the output payload shape are preserved from the original
    back-end. Fixes applied in this version are marked with "FIX".

    target_date: string "YYYY-MM-DD"
    """
    
    # Ensure directories exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    # -------------------------
    # CONFIG
    # -------------------------
    API_TOKEN = os.getenv("SPORTMONKS_API_KEY")
    if not API_TOKEN:
        raise RuntimeError("SPORTMONKS_API_KEY is missing. Set it in your environment or .env file.")
    MIN_H2H_GAMES = 5
    # FIX: the 2H form flag now needs the same 5-game minimum as H2H. Before,
    # a team with 1-2 finished matches could show "100%" and trigger the flag.
    MIN_FORM_GAMES = 5
    REQ_DELAY = 0.2
    
    # Dynamic Output Path
    OUTPUT_FILE = os.path.join(OUTPUT_DIR, "sh_gg_winner_feed.json")

    # FIX: failures were swallowed silently, so an outage or rate limit looked
    # like "no H2H" / "0% activity". They are now recorded and reported.
    API_FAILURES = []
    FIXTURE_ERRORS = []

    # -------------------------
    # UTILS (NESTED FOR ENCAPSULATION)
    # -------------------------
    def GET(endpoint, params=None):
        if params is None: params = {}
        params['api_token'] = API_TOKEN
        url = f"https://api.sportmonks.com/v3/football{endpoint}"
        last_issue = None
        for attempt in range(3):
            try:
                r = requests.get(url, params=params, timeout=20)
                if r.status_code == 200:
                    payload = r.json()
                    time.sleep(REQ_DELAY)
                    return payload
                last_issue = f"HTTP {r.status_code}"
                # FIX: back off properly on rate limiting (429)
                time.sleep(2 ** attempt if r.status_code == 429 else 1)
            except Exception as exc:
                last_issue = f"{type(exc).__name__}: {exc}"
                time.sleep(1)
        API_FAILURES.append((endpoint, last_issue))
        if len(API_FAILURES) <= 5:
            print(f"[SH GG Winner][API-FAIL] {endpoint} -> {last_issue}", flush=True)
        return {"data":[]}

    def get_scores_ht_ft(scores_list):
        """
        Safely handles both past and future matches. 
        If unplayed, defaults to None so math engines ignore them safely.

        FIX 1: the half-time score is None when no 1ST_HALF entry exists. It
        used to default to 0, which made every goal count as a second-half goal
        for matches with missing half-time data.
        FIX 2: full time now prefers the CURRENT entry. Previously CURRENT and
        2ND_HALF both overwrote the full-time value, so whichever came last in
        the list won. 2ND_HALF is only used as a fallback when CURRENT is absent.
        """
        h_ht, a_ht = None, None
        cur_h, cur_a = None, None
        sh_h, sh_a = None, None

        if not scores_list:
            return (None, None), (None, None)

        for s in scores_list:
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

            if desc == "CURRENT":
                if p == "home": cur_h = g
                elif p == "away": cur_a = g
            elif desc == "2ND_HALF":
                if p == "home": sh_h = g
                elif p == "away": sh_a = g

        h_ft = cur_h if cur_h is not None else (sh_h if sh_h is not None else 0)
        a_ft = cur_a if cur_a is not None else (sh_a if sh_a is not None else 0)

        return (h_ht, a_ht), (h_ft, a_ft)

    # -------------------------
    # ANALYSIS ENGINES
    # -------------------------
    def _was_home(fixture, team_id):
        """Was `team_id` the home side in this fixture?

        Extracted (2026-10-04) from the identical inline block in
        check_h2h_strict, so there is exactly ONE home/away rule in this file.
        A second copy is how the two start disagreeing. Order is preserved from
        the original: an explicit meta.location wins; when it is blank the
        second participant is assumed to be the away side.
        """
        for i, p in enumerate(fixture.get("participants", [])):
            if str(p.get("id")) == str(team_id):
                loc = p.get("meta", {}).get("location", "")
                if loc == "away":
                    return False
                if loc == "":
                    return i != 1
                return True
        return True

    def _split_home_away(parts):
        """FIX: the fixture-level home/away teams were taken from list order
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

    form_cache = {}

    def check_recent_form_math(team_id, team_name):
        """
        Checks last 5 matches using simple math (FT - HT > 0).
        Safely tied to the aggregator's target_date for backtesting capabilities.

        FIX: a team's form is fetched once and cached (the same team could be
        fetched repeatedly), and the rate is calculated over matches with
        readable scores and half-time data only. Before, unreadable matches
        stayed in the denominator and quietly lowered the rate.
        """
        if team_id in form_cache:
            return form_cache[team_id]

        failures_before = len(API_FAILURES)

        end = target_date
        start = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=120)).strftime("%Y-%m-%d")

        params = {
            "include": "scores",
            "per_page": 5,
            "filters": "fixtureStates:5",
            "order": "desc"
        }
        resp = GET(f"/fixtures/between/{start}/{end}/{team_id}", params=params)
        matches = resp.get("data",[])

        if not matches:
            result = (0, 0, 0, 0)
            if len(API_FAILURES) == failures_before:
                form_cache[team_id] = result
            return result

        games_with_2h_activity = 0
        # (2026-10-04) ADDITIVE: accumulate the team's own full-time goals over
        # the same window. The numbers are already in hand here; they were simply
        # discarded. They let the Over 1.5 VIP block rank its survivors by recent
        # scoring volume without a second round of API calls. `goals_sampled` is
        # returned alongside because this window is NOT guaranteed to hold 5
        # matches — promoted or thin-history teams come back short, and a tier
        # asserted off 2 games must say so rather than look like one off 5.
        goals_sampled = 0
        valid_matches = 0

        for m in matches:
            (h_ht, a_ht), (h_ft, a_ft) = get_scores_ht_ft(m.get("scores",[]))
            if h_ft is None: continue 
            if h_ht is None or a_ht is None: continue

            valid_matches += 1

            h_goals_2h = h_ft - h_ht
            a_goals_2h = a_ft - a_ht
            total_goals_2h = h_goals_2h + a_goals_2h

            goals_sampled += h_ft if _was_home(m, team_id) else a_ft

            if total_goals_2h > 0:
                games_with_2h_activity += 1

        pct_activity = (games_with_2h_activity / valid_matches * 100) if valid_matches > 0 else 0

        result = (pct_activity, valid_matches, goals_sampled, valid_matches)
        if len(API_FAILURES) == failures_before:
            form_cache[team_id] = result
        return result

    def check_h2h_strict(h_id, a_id):
        # fixtureStates:5 = FINISHED only (2026-10-05). No state filter was sent
        # before, so unplayed meetings entered the sample and the unreadable ones
        # were skipped further down -- quietly shrinking the real denominator.
        resp = GET(f"/fixtures/head-to-head/{h_id}/{a_id}", params={
            "include": "participants;scores",
            "sortBy": "starting_at", "order": "desc",
            "per_page": 10, "filters": "fixtureStates:5"})
        history = resp.get("data",[])

        # Was 2. A pair that met twice was treated as a full H2H record, and the
        # five "100%" flags below were published off that sample without ever
        # saying how small it was. The user's rule is five.
        if len(history) < MIN_H2H_GAMES: return None

        history = history[:5]
        wins_h, wins_a = 0, 0
        gg, o25 = 0, 0

        for h in history:
            (past_h_ht, past_a_ht), (past_h_ft, past_a_ft) = get_scores_ht_ft(h.get("scores",[]))
            if past_h_ft is None: continue 

            h_id_was_home = _was_home(h, h_id)

            if h_id_was_home:
                target_h_goals, target_a_goals = past_h_ft, past_a_ft
            else:
                target_h_goals, target_a_goals = past_a_ft, past_h_ft

            if target_h_goals > target_a_goals: wins_h += 1
            elif target_a_goals > target_h_goals: wins_a += 1

            if target_h_goals > 0 and target_a_goals > 0: gg += 1
            if (target_h_goals + target_a_goals) > 2.5: o25 += 1

        total = len(history)
        return {
            "h_win_100": (wins_h == total),
            "a_win_100": (wins_a == total),
            "gg_100": (gg == total),
            "o25_100": (o25 == total),
            "count": total
        }

    # -------------------------
    # MAIN PIPELINE EXECUTION
    # -------------------------
    print(f"\n[SH GG Winner] Engine Execution Started for Target[{target_date}]")

    all_fx =[]
    page = 1
    while True:
        params = {"include": "participants;scores;league", "per_page": 50, "page": page}
        resp = GET(f"/fixtures/date/{target_date}", params=params)
        data = resp.get("data",[])
        if not data: break
        all_fx.extend(data)
        if len(data) < 50: break
        page += 1
        time.sleep(REQ_DELAY)

    results =[]

    for i, fx in enumerate(all_fx):
        # FIX: one malformed fixture used to crash the whole run. Each fixture
        # is now isolated, and the error is logged.
        try:
            parts = fx.get("participants",[])
            if len(parts) < 2: continue

            fid = str(fx["id"])
            # FIX: home/away now taken from meta.location, not list order.
            home_p, away_p = _split_home_away(parts)
            h_id, h_name = str(home_p["id"]), home_p["name"]
            a_id, a_name = str(away_p["id"]), away_p["name"]

            # Metadata for Alert System
            league_name = (fx.get("league") or {}).get("name", "Unknown League")
            start_datetime = fx.get("starting_at", "")
            start_timestamp = 0
            
            if isinstance(start_datetime, str) and start_datetime:
                try:
                    dt_obj = datetime.strptime(start_datetime, "%Y-%m-%d %H:%M:%S")
                    start_timestamp = int(dt_obj.timestamp())
                except ValueError:
                    pass

            # 1. H2H
            h2h = check_h2h_strict(h_id, a_id)

            # 2. 2H Goals (Math Method)
            h_2h_activity, h_total, h_goals, h_sampled = check_recent_form_math(h_id, h_name)
            a_2h_activity, a_total, a_goals, a_sampled = check_recent_form_math(a_id, a_name)

            streaks =[]

            # FIX: needs MIN_FORM_GAMES finished matches with readable half-time
            # data on BOTH sides before the 100% label can fire.
            both_2h_goal = bool(
                h_2h_activity == 100 and a_2h_activity == 100
                and h_total >= MIN_FORM_GAMES and a_total >= MIN_FORM_GAMES
            )

            if both_2h_goal:
                streaks.append("🔥 BOTH 2H GOAL (100%)")

            if h2h:
                if h2h["h_win_100"]: streaks.append("💀 HOME H2H WINNER (100%)")
                if h2h["a_win_100"]: streaks.append("💀 AWAY H2H WINNER (100%)")
                if h2h["gg_100"]: streaks.append("⚽ H2H GG (100%)")
                if h2h["o25_100"]: streaks.append("⚽ H2H O2.5 (100%)")

            # Your original logic only exports matches that hit AT LEAST one streak
            if streaks:
                # Constructing the Machine-Readable Payload
                match_payload = {
                    "engine": "Second_Half_GG_Winner",
                    "fixture_id": fid,
                    "league": league_name,
                    "kickoff_timestamp": start_timestamp,
                    "kickoff_datetime": start_datetime,
                    "teams": {
                        "home": {"id": h_id, "name": h_name},
                        "away": {"id": a_id, "name": a_name}
                    },
                    "pick_labels": streaks,  
                    "flags": {
                        "both_2h_goal_100_percent": both_2h_goal,
                        "home_h2h_win_100": bool(h2h and h2h["h_win_100"]),
                        "away_h2h_win_100": bool(h2h and h2h["a_win_100"]),
                        "h2h_gg_100": bool(h2h and h2h["gg_100"]),
                        "h2h_o25_100": bool(h2h and h2h["o25_100"])
                    },
                    "metrics": {
                        "home_2h_rate": h_2h_activity,
                        "away_2h_rate": a_2h_activity,
                        "h2h_matches_analyzed": h2h["count"] if h2h else 0,
                        # (2026-10-04) ADDITIVE — consumed by the Over 1.5 VIP block
                        # to rank its survivors. Absent on every file written before
                        # this change, which is why the VIP tiers render as "—" on
                        # historical dates rather than guessing.
                        "home_goals_last_5": h_goals,
                        "away_goals_last_5": a_goals,
                        "home_games_sampled": h_sampled,
                        "away_games_sampled": a_sampled,
                    }
                }
                results.append(match_payload)

        except Exception as exc:
            fid_err = fx.get("id", "<unknown>") if isinstance(fx, dict) else "<unknown>"
            FIXTURE_ERRORS.append((fid_err, exc))
            if len(FIXTURE_ERRORS) <= 5:
                print(f"[SH GG Winner][ERROR] fixture {fid_err} skipped: "
                      f"{type(exc).__name__}: {exc}", flush=True)

    # FIX: report problems instead of hiding them
    if API_FAILURES:
        print(f"[SH GG Winner][WARN] {len(API_FAILURES)} API call(s) failed after retries. "
              f"Affected fixtures may show missing H2H/form data.", flush=True)
    if FIXTURE_ERRORS:
        print(f"[SH GG Winner][WARN] {len(FIXTURE_ERRORS)} fixture(s) skipped due to errors.", flush=True)

    # Save cleanly for the aggregator to pull/backup
    # (written to a temp file first, then swapped in, so a crash mid-write
    # can never leave a half-written JSON for the aggregator to read)
    tmp_file = OUTPUT_FILE + ".tmp"
    with open(tmp_file, "w") as f:
        json.dump(results, f, indent=4)
    os.replace(tmp_file, OUTPUT_FILE)
        
    print(f"[SH GG Winner] Exported {len(results)} payload objects to {OUTPUT_FILE}")

    # Return directly to memory so the Master API can use it instantly
    return results

# ==============================================================================
# IF RUN DIRECTLY (TESTING / CRON)
# ==============================================================================
# Usage:
#   python sh_gg_winner_engine_server.py                -> tomorrow (UTC)
#   python sh_gg_winner_engine_server.py 2026-10-12     -> that date
# No interactive prompt, so it is safe under cron / systemd / schedulers.
if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_date = sys.argv[1].strip()
        try:
            datetime.strptime(test_date, "%Y-%m-%d")
        except ValueError:
            raise SystemExit(f"Invalid date '{test_date}'. Use the format YYYY-MM-DD.")
    else:
        test_date = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    run_sh_gg_winner_engine(test_date)
