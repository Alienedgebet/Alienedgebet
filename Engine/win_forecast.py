import os
import sys
import json
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
# ADDED: this file previously had no DATA_DIR at all, so there was nowhere
# safe to persist the league goals-prior cache below. Every sibling engine
# (draw_engine.py, unders_engine.py, gg_precision_engine.py) already uses
# this exact BASE_DIR/"data" convention for small persistent caches.
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

API_TOKEN = os.getenv("SPORTMONKS_API_KEY")
BASE_URL = "https://api.sportmonks.com/v3/football"

# Market IDs for Accurate Odds Sniper
MARKET_1X2 = 1
MARKET_OU = 12
MARKET_GG = 9

REQUEST_DELAY = 0.2
MAX_RETRIES = 5

# ==============================================================================
# LAMBDA SHRINKAGE MODEL (same proven model now shared by Draw and Unders —
# see Engine/unders_engine.py Phase 2 and Engine/draw_engine.py for the full
# rationale). This engine's own lambda had TWO separate problems, not one:
#
#   1. NO SHRINKAGE — one-off results swung expected goals as hard as a full
#      sample, exactly like every other engine before this session's fixes.
#
#   2. DOUBLE-COUNTING — get_complex_metrics()'s old lambda was
#      `(ov_gs + v_gs) / 10`, treating "last 5 overall" and "last 5 at this
#      venue" as 10 INDEPENDENT matches. They are not disjoint: any match
#      that is both recent and at the right venue is counted in BOTH windows,
#      silently double-weighting it. Fixed below by de-duplicating on
#      fixture id before the goals are ever summed.
#
#   3. FIXED 50/50 H2H BLEND — `(own_lambda + h2h_rate) / 2` gave a single
#      historical H2H match the same statistical authority as a full 5-match
#      recent-form sample, regardless of how much H2H history actually
#      existed. Replaced below with shrinkage that blends by REAL sample
#      size: own-form goals and H2H goals are pooled and shrunk together,
#      so one H2H match barely moves the number and five genuinely do.
# ==============================================================================
LAMBDA_PRIOR_STRENGTH = 6.0     # pseudo-matches of prior weight
LAMBDA_PRIOR_FALLBACK = 1.35    # used ONLY if a league has no cached average yet
LAMBDA_MIN = 0.05
LAMBDA_MAX = 6.00
LAMBDA_CLAMP_ALERT = 4.50

LAMBDA_HEALTH_WARNINGS = []     # reset at the start of every run_win_forecast_engine() call


def compute_league_avg_goals(league_id, days_lookback=180):
    """
    Real per-team goals prior for a league, measured directly (total goals /
    2 / matches). Ported from draw_engine.py's compute_league_avg_goals(),
    same TTL-cached-to-disk pattern, own cache file so this engine's cache
    stays independent of Draw's.
    """
    cache_file = os.path.join(DATA_DIR, "win_league_avg_goals_cache.json")
    cache_data = {}
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                cache_data = json.load(f)
        except Exception:
            pass

    now_utc = datetime.now(timezone.utc)
    lid_str = str(league_id)

    if lid_str in cache_data:
        try:
            last_updated = datetime.fromisoformat(cache_data[lid_str]["last_updated"])
            if (now_utc - last_updated).days < 7:
                return cache_data[lid_str]["avg_goals_per_team"]
        except Exception:
            pass

    end_dt = now_utc.date() - timedelta(days=1)
    start_dt = end_dt - timedelta(days=min(days_lookback, 180))

    all_fx = []
    seen = set()
    page = 1
    while True:
        data = GET(f"/fixtures/between/{start_dt}/{end_dt}/{league_id}",
                   params={"include": "scores", "per_page": 50, "page": page})
        fx = data.get("data", [])
        if not fx:
            break
        added_new = False
        for f in fx:
            fid = f.get("id")
            if fid not in seen:
                seen.add(fid); all_fx.append(f); added_new = True
        if not added_new:
            break
        page += 1
        sleep_short()

    total_matches = 0
    total_goals = 0
    for fx in all_fx:
        hg, ag = extract_goals_v3(fx.get("scores", []))
        if hg is None or ag is None:
            continue
        total_matches += 1
        total_goals += (hg + ag)

    avg_goals_per_team = round((total_goals / total_matches) / 2.0, 4) if total_matches > 0 else LAMBDA_PRIOR_FALLBACK

    cache_data[lid_str] = {
        "avg_goals_per_team": avg_goals_per_team,
        "sample_matches": total_matches,
        "last_updated": now_utc.isoformat(),
    }
    try:
        with open(cache_file, "w") as f:
            json.dump(cache_data, f, indent=4)
    except Exception:
        pass

    return avg_goals_per_team


def shrunk_rate(goals, matches, prior_mean, prior_strength=LAMBDA_PRIOR_STRENGTH):
    """Empirical-Bayes shrinkage toward a prior mean. Ported verbatim from
    draw_engine.py / unders_engine.py."""
    try:
        goals = float(goals); matches = float(matches)
    except (TypeError, ValueError):
        return float(prior_mean)
    if matches <= 0:
        return float(prior_mean)
    if not math.isfinite(goals) or not math.isfinite(matches):
        return float(prior_mean)
    return (goals + prior_strength * prior_mean) / (matches + prior_strength)


def lambda_health_note(lh, la, base):
    """Telemetry for a degenerate base rate driving lambda to the clamp
    ceiling/floor. Ported verbatim from draw_engine.py / unders_engine.py."""
    notes = []
    for side, lam in (("home", lh), ("away", la)):
        if lam >= LAMBDA_CLAMP_ALERT:
            notes.append(f"{side} lambda {lam:.2f} at/over the clamp ceiling "
                         f"({LAMBDA_CLAMP_ALERT:.2f})")
        elif lam <= LAMBDA_MIN + 1e-9:
            notes.append(f"{side} lambda {lam:.2f} at the floor")
    if base is not None and (not math.isfinite(base) or base <= 0):
        notes.append(f"base rate invalid: {base!r}")
    return "; ".join(notes) if notes else None

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

class ForecastDataError(RuntimeError):
    """Raised when the provider response cannot produce a valid forecast."""


def _response_json(response, path):
    """Return a JSON object or raise a useful provider error.

    api_cache deliberately returns the original response for non-200 statuses.
    The old forecast loop assumed every response had ``.get()`` and hid the
    resulting AttributeError with ``except Exception: pass``.  Normalize that
    boundary here so one bad response is visible and cannot blank the artifact.
    """
    status = getattr(response, "status_code", 200)
    if status != 200:
        raise ForecastDataError(f"SportMonks GET {path} returned HTTP {status}")
    try:
        payload = response.json()
    except Exception as exc:
        raise ForecastDataError(f"SportMonks GET {path} returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ForecastDataError(
            f"SportMonks GET {path} returned {type(payload).__name__}, expected object"
        )
    return payload


# -------------------------
# HTTP & UNLIMITED PAGINATION (STRICT)
# -------------------------
def GET(path, params=None):
    if params is None:
        params = {}
    params.setdefault("api_token", API_TOKEN)
    url = f"{BASE_URL}{path}"
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, params=params, timeout=30)
            if getattr(response, "status_code", None) == 200:
                return _response_json(response, path)
            if getattr(response, "status_code", None) == 429:
                last_error = ForecastDataError(f"SportMonks GET {path} returned HTTP 429")
                if attempt + 1 < MAX_RETRIES:
                    time.sleep(2 ** attempt)
                    continue
            _response_json(response, path)
        except ForecastDataError:
            raise
        except Exception as exc:
            last_error = ForecastDataError(f"SportMonks GET {path} failed: {exc}")
            if attempt + 1 < MAX_RETRIES:
                time.sleep(1)
                continue
            raise last_error from exc

    raise last_error or ForecastDataError(f"SportMonks GET {path} failed")

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
    """Accurately parses nested goals for Sportmonks v3.

    FIXED: the previous version read whatever `goals` value it found with no
    check on what KIND of score entry it came from — on any match decided by
    a penalty shootout, this could silently read the SHOOTOUT score instead
    of the regulation result, flipping a drawn 90-minute match into a
    recorded W/L and corrupting every downstream stat built from it
    (last_5_wins, parity_score, the lambda itself). Every sibling engine in
    this codebase (draw_engine.py, unders_engine.py) already filters these
    out; this engine was the one exception.
    """
    home, away = None, None
    for entry in (scores or[]):
        if not isinstance(entry, dict): continue
        s_obj = entry.get("score") or entry
        desc = str(entry.get("description", s_obj.get("description", ""))).upper()
        if any(w in desc for w in ["PENALTY", "EXTRA", "AGG"]):
            continue
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

    # Fresh lambda-health report per run (see LAMBDA_HEALTH_WARNINGS above).
    LAMBDA_HEALTH_WARNINGS.clear()

    # 1. Fetch All Daily Matches
    fixtures = fetch_all_fixtures_for_date(target_date)
    if not fixtures:
        raise ForecastDataError(f"No fixtures found for {target_date}")

    # 2. Collect History
    team_ids = set()
    for fx in fixtures:
        for p in fx.get("participants",[]):
            if p.get('id'): team_ids.add(p['id'])

    team_histories = {}
    print(f"[INFO] Extracting history for {len(team_ids)} teams...")
    # The scheduled run targets tomorrow, so history must end relative to
    # target_date rather than the wall clock date on which the process runs.
    target_dt = datetime.strptime(target_date, "%Y-%m-%d")
    history_start = (target_dt - timedelta(days=365)).strftime("%Y-%m-%d")
    history_end = (target_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    for tid in team_ids:
        # Fetch 40 games to find enough Home/Away specific matches
        h_data = GET(f"/fixtures/between/{history_start}/{history_end}/{tid}",
                     params={"include":"scores;participants", "filters":"fixtureStates:5", "order":"desc", "per_page": 40})
        team_histories[tid] = h_data.get("data",[])
        sleep_short()

    # ── LEAGUE GOALS PRIOR CACHE (NEW — required by the shrinkage model) ───
    # One cached lookup per league represented today, same cost pattern as
    # every sibling engine's league_weight cache below.
    league_ids = {fx.get("league_id") for fx in fixtures if fx.get("league_id")}
    league_goals_cache = {}
    for lid in league_ids:
        try:
            league_goals_cache[lid] = compute_league_avg_goals(lid)
        except Exception:
            league_goals_cache[lid] = LAMBDA_PRIOR_FALLBACK
        sleep_short()

    raw_output = []
    fixture_errors = []
    valid_odds_rows = 0

    # 3. Analysis Layer
    print(f"[INFO] Running Analysis on {len(fixtures)} fixtures...")
    for fx in fixtures:
        fid = fx.get("id", "<unknown>") if isinstance(fx, dict) else "<unknown>"
        try:
            fid = fx['id']
            parts = fx.get("participants",[])
            if len(parts) < 2: continue

            h_p = next(p for p in parts if p.get("meta", {}).get("location") == "home")
            a_p = next(p for p in parts if p.get("meta", {}).get("location") == "away")
            hid, aid = int(h_p['id']), int(a_p['id'])
            league_id = fx.get("league_id")
            league_prior = league_goals_cache.get(league_id, LAMBDA_PRIOR_FALLBACK)

            odds = sniper_fetch_odds(fid)
            if odds.get("home") is not None or odds.get("away") is not None:
                valid_odds_rows += 1

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

                # RECTIFICATION 5 (NEW): de-duplicated sample for the lambda
                # base. ov_5 and v_5 are NOT disjoint — any match that is both
                # recent AND at the right venue was previously counted in
                # BOTH windows, so `(ov_gs + v_gs) / 10` silently treated it
                # as two independent matches. This builds the lambda input
                # from the UNION of both windows, keyed by fixture id, so
                # every match counts exactly once.
                dedup = {}
                for m in (ov_5 + v_5):
                    m_fid = m.get("id")
                    if m_fid is None or m_fid in dedup:
                        continue
                    st = get_match_stats(m, tid)
                    if st:
                        dedup[m_fid] = st["scored"]
                dedup_goals = sum(dedup.values())
                dedup_n = len(dedup)

                return {
                    "wins": ov_wins, "gs": ov_gs, "gc": ov_gc, "losses": ov_loss,
                    "cs_fail": ov_cs_fail, "even": ov_even, "no_draw_3": no_draw_3,
                    # Keep the venue goal fields in this metric contract: the
                    # emitted forecast rows consume both values below.
                    "v_wins": v_wins, "v_gs": v_gs, "v_gc": v_gc,
                    "v_parity": (v_gs + v_gc), "ov_parity": (ov_gs + ov_gc),
                    "dedup_goals": dedup_goals, "dedup_n": dedup_n,
                }

            h_m = get_complex_metrics(hid, team_histories.get(hid,[]), "home")
            a_m = get_complex_metrics(aid, team_histories.get(aid,[]), "away")

            # ── LAMBDA (FIXED): shrinkage toward the real per-league goals
            # prior, pooling each side's de-duplicated recent-form goals with
            # its H2H goals BEFORE shrinking — so the H2H sample's influence
            # scales with how many H2H matches actually exist, instead of
            # always counting as a flat 50% regardless of sample size. See
            # the LAMBDA SHRINKAGE MODEL block near the top of this file.
            h_final_lamb = shrunk_rate(
                h_m["dedup_goals"] + h2h_h_gs,
                h_m["dedup_n"] + len(h2h_matches),
                league_prior,
            )
            a_final_lamb = shrunk_rate(
                a_m["dedup_goals"] + h2h_a_gs,
                a_m["dedup_n"] + len(h2h_matches),
                league_prior,
            )
            h_final_lamb = max(LAMBDA_MIN, min(LAMBDA_MAX, h_final_lamb))
            a_final_lamb = max(LAMBDA_MIN, min(LAMBDA_MAX, a_final_lamb))

            _lam_note = lambda_health_note(h_final_lamb, a_final_lamb, league_prior)
            if _lam_note:
                LAMBDA_HEALTH_WARNINGS.append(
                    f"{h_p['name']} v {a_p['name']}: {_lam_note}")
                print(f"   [lambda-health] {_lam_note}")

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
                lam = h_final_lamb if side == "home" else a_final_lamb

                raw_output.append({
                    "fixture_id": fid,
                    "fixture": f"{h_p['name']} vs {a_p['name']}",
                    "side": side,
                    "team_name": h_p['name'] if side == "home" else a_p['name'],
                    "win_odds": w_odd,
                    "poisson_win_prob_num": prob, # Keep numeric for sorting
                    "poisson_win_prob": f"{prob}%",
                    "poisson_draw_prob": f"{p_draw}%",
                    "lambda": round(lam, 3),
                    "lambda_base": round(league_prior, 3),
                    "lambda_warning": _lam_note,
                    "last_5_wins_overall": t_m["wins"],
                    "last_5_wins_at_venue": t_m["v_wins"],
                    "last_5_venue_goals_scored": t_m["v_gs"],
                    "last_5_venue_goals_conceded": t_m["v_gc"],
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

        except Exception as exc:
            fixture_errors.append((fid, exc))
            if len(fixture_errors) <= 5:
                print(f"[ERROR] Win Forecast fixture {fid} skipped: "
                      f"{type(exc).__name__}: {exc}", flush=True)

    if fixture_errors:
        print(f"[WARN] Win Forecast skipped {len(fixture_errors)} fixture(s) due to errors.",
              flush=True)

    if LAMBDA_HEALTH_WARNINGS:
        print(f"\n[WARN] LAMBDA HEALTH: {len(LAMBDA_HEALTH_WARNINGS)} fixture(s) hit the "
              f"lambda clamp/floor.")
        for _w in LAMBDA_HEALTH_WARNINGS[:10]:
            print(f"    - {_w}")
        if len(LAMBDA_HEALTH_WARNINGS) > 10:
            print(f"    ... and {len(LAMBDA_HEALTH_WARNINGS) - 10} more")

    # 4. RANKING SYSTEM (Highest Poisson Win Prob to Lowest)
    if not raw_output:
        details = "; ".join(
            f"fixture {fid}: {type(exc).__name__}: {exc}"
            for fid, exc in fixture_errors[:3]
        ) or "no fixture-level error was reported"
        raise ForecastDataError(
            f"Win Forecast produced 0 rows for {target_date} "
            f"from {len(fixtures)} fixture(s): {details}"
        )

    df = pd.DataFrame(raw_output)
    df = df.sort_values(by="poisson_win_prob_num", ascending=False).reset_index(drop=True)
    # Drop the numeric helper column
    df = df.drop(columns=["poisson_win_prob_num"])

    # Never write a headerless/blank artifact.  A previous version wrote an
    # empty DataFrame here, which made every downstream reader fail with
    # "No columns to parse from file" and gave the second-chance pass no data
    # to recover.
    output_path = os.path.join(OUTPUT_DIR, f"ranked_win_forecast_{target_date}.csv")
    tmp_path = output_path + ".tmp"
    try:
        df.to_csv(tmp_path, index=False)
        os.replace(tmp_path, output_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    print(f"[INFO] Win Forecast valid odds fixtures: {valid_odds_rows}/{len(fixtures)}")
    print(f"\n[Done] Base Win Forecast saved to {output_path}")
    print(df.to_string(index=False))
    return df.to_dict(orient="records")

if __name__ == "__main__":
    run_win_forecast_engine()
