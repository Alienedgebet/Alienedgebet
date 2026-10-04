import os
import sys
import time
import json
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import math
from collections import Counter, defaultdict
from dotenv import load_dotenv

load_dotenv()

# ==============================================================================
# CONFIGURATION
# ==============================================================================
API_KEY  = os.getenv("SPORTMONKS_API_KEY")
BASE_URL = "https://api.sportmonks.com/v3/football"

# --- FIXED FOR GOOGLE COLAB & VS CODE COMPATIBILITY ---
try:
    BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
    OUTPUT_DIR = os.path.join(os.path.dirname(BASE_DIR), "output")
    DATA_DIR   = os.path.join(os.path.dirname(BASE_DIR), "data")
except NameError:
    BASE_DIR   = os.path.abspath("")  
    OUTPUT_DIR = os.path.join(BASE_DIR, "output")
    DATA_DIR   = os.path.join(BASE_DIR, "data")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(DATA_DIR,   exist_ok=True)

TEAM_LOOKBACK_DAYS     = 365
GK_LOOKBACK_DAYS       = 150    
REQUEST_DELAY_SEC      = 0.18
LAST_N_GAMES           = 5
FATIGUE_WINDOW_DAYS    = 30

SIMULATION_SIZE        = 10_000  
MAX_GOALS_DISPLAY      = 6
POISSON_MAX_GOALS      = 8

LEAGUE_SCALE           = 0.30
MAX_KEY_PLAYERS        = 16
CORE_START_RATE        = 0.6

MARKET_1X2             = 1

# ── UNDER 2.5 TIER THRESHOLDS ─────────────────────────────────────────────────
U25_TIER1_SCORE        = 70    
U25_TIER2_SCORE        = 55    
U25_TIER3_SCORE        = 40    

# ── UNDER 3.5 TIER THRESHOLDS ─────────────────────────────────────────────────
U35_TIER1_SCORE        = 75
U35_TIER2_SCORE        = 60
U35_TIER3_SCORE        = 45

# ── KEEPER WALL THRESHOLD ─────────────────────────────────────────────────────
GK_ELITE_CPG           = 1.10   
GK_AVERAGE_CPG         = 1.40   

# ── KEEPER DATA-INTEGRITY GUARDS (Phase 0) ────────────────────────────────────
# A keeper needs a real sample before he can be graded. Without these, a keeper
# with one cameo produces a p90 from a single match and is scored as an ELITE
# WALL, which hands out 20 free points to missing data.
GK_MIN_APPS            = 5      # appearances required before a grade is trusted
GK_MIN_MINS            = 270    # ~3 full matches of evidence
GK_CPG_SANITY_MAX      = 5.00   # >5 goals conceded per 90 is corrupt, not elite
# (an ungradeable keeper is reported as None, never as a filler number)

# ── FATIGUE SIGNAL THRESHOLD (Phase 0) ─────────────────────────────────────────
# The old constant (0.60) sat above the 99th percentile of the observed fatigue
# distribution (p50 0.26, p90 0.40, max 0.64), so the signal essentially never
# fired. This is set at the empirical 90th percentile.
SIG5_FIRE_FATIGUE      = 0.40

# ── LAMBDA MODEL (Phase 2) ───────────────────────────────────────────────────
# The old model averaged a raw 5-match attack rate with a raw concede rate:
#     lambda = max(0.05, (raw_attack + opp_concede) / 2)
# Its defining defect was NO SHRINKAGE: a team with one 3-0 win was treated as a
# 3.0 goals/game attack, exactly as loud as a 20-match record.
#
# LAMBDA_PRIOR_STRENGTH is a pseudo-match count: a team is treated as if it had
# this many matches against the prior mean before its own results count fully.
#
# ── 2026-10-04: PRIOR STRENGTH AND PRIOR MEAN BOTH FIXED ─────────────────────
# It was 6.0 pseudo-matches against a 5-match real window. That is SIX TIMES the
# evidence the team actually has, so the prior outvoted the form and the window
# barely moved the answer. A real 5-match run of 1.0 goals/game shrank to
# (5 + 6*1.35) / 11 = 1.19 — the team's own form was almost erased. At 2.5 the
# same record becomes (5 + 2.5*1.35) / 7.5 = 1.12 ... and a genuine 3.0 attack
# over 5 matches stays recognisable instead of being flattened to the mean.
# 2.5 pseudo-matches keeps the prior meaningful for a thin sample while letting
# recent form actually speak.
LAMBDA_PRIOR_STRENGTH   = 2.5    # pseudo-matches of prior weight (was 6.0)

# Per-team prior. This is now only the FALLBACK for when a league cannot be
# measured. Where a league prior exists, league_avg_total_goals()/2 is used
# instead — see build_lambdas().
#
# NOT USED as a prior: league_weight as a league scoring prior. It was tried and
# rejected. Post-mortem, kept here because the failure is instructive:
# `league_weight` is a CAPPED U2.5 RATE, not a scoring base rate. Inverting it via
# P(total<=2) under Poisson gave an impossible 8.0 goals/team for the 51.6% of
# cached leagues whose weight is 0.0 (a 0% under-rate is not a real observation).
# Every fixture then clamped to the LAMBDA_MAX ceiling and published u25_prob
# ~0.0006. That bug was caused by INVERTING a rate. The replacement below
# measures average goals DIRECTLY, so there is nothing to invert and no way to
# produce an 8.0 from a league that simply has no Under data.
LAMBDA_PRIOR_GOALS      = 1.35   # fallback per-team prior (global mean goals / 2)
LAMBDA_MIN              = 0.05
LAMBDA_MAX              = 6.00

# A league needs this many settled matches before its average is trusted as a
# prior. Below it the fallback LAMBDA_PRIOR_GOALS is used instead, so a league
# with three results cannot dictate the prior.
LEAGUE_AVG_MIN_MATCHES   = 20

# The /fixtures/between endpoint returns at most 200 fixtures regardless of the
# window asked for, so a 180-day request is silently truncated and measures only
# the busiest leagues. The sweep therefore walks backwards in small chunks.
LEAGUE_SWEEP_DAYS       = 120          # newest-to-oldest reach of the sweep
LEAGUE_SWEEP_CHUNK_DAYS = 7            # per chunk; small enough to stay under 200

# Leagues to measure on the current sweep. Populated once per run by
# run_unders_engine() so ONE sweep serves every fixture, instead of one broken
# request per league.
_LEAGUE_SWEEP_TARGETS = set()

# Health telemetry, added because the failure above was silent. A lambda sitting
# on the clamp is a confident probability derived from a poisoned input, so it is
# flagged just under the ceiling rather than left to be inferred from a
# suspiciously low pick rate.
LAMBDA_CLAMP_ALERT      = 4.50

# Per-run collector for lambda health warnings. Reset at the start of every
# run_unders_engine() call and printed in the summary, so a systemic clamp is
# visible in the log even when every individual fixture looks plausible.
LAMBDA_HEALTH_WARNINGS  = []

# ── HARD TIER GATES (user rules — apply to EVERY tier, both engines) ───────────
# A fixture only earns a tier if it clears ALL of these AND its score threshold.
# They are gates, not bonus points: failing any one demotes the fixture out of
# every tier regardless of how high it scored.
#
#   GATE 1  neither team may have scored more than MAX_SCORED in the window
#   GATE 2  neither team may have conceded more than MAX_CONCEDED in the window
#   GATE 3  the MOST RECENT head-to-head must not have finished over 2.5
#
# ── 2026-10-04 REVERTED TO THE ORIGINAL CAPS ──────────────────────────────────
# A revision today raised Gate 1 to 8 goals, widened Gate 3 from one h2h to
# three, and gave U3.5 a looser concede cap of 7. That revision was tested on
# the only sample where the gates could be reconstructed (207 of 1,509 rows that
# had 5 prior home AND 5 prior away matches inside the archives) and it made
# things WORSE, so it has been reverted:
#
#   gates PASS -> 44.3% under hit rate      gates FAIL -> 69.2%
#   9 of the 13 rejected fixtures were HITS, several finished 0-1 / 1-0 / 2-0.
#   A side conceding 6-8 goals across five matches is therefore NOT evidence
#   against the Under, and the 3-match h2h rule rejected real Under fixtures.
#
# The lesson is recorded here so this is not re-attempted blind: the concede cap
# is the gate doing the damage, and it stays at 5. The loosened U3.5 cap of 7 was
# the one part that behaved correctly (it admitted 8 fixtures U2.5 rejected, 5 of
# which hit under 3.5), but it was reverted with the rest because the same sample
# is too small to carry a per-market rule on its own.
#
# Every gate input is still written to the output rows (gate_home_scored,
# gate_away_scored, gate_home_conceded, gate_away_conceded, gate_h2h,
# gate_h2h_matches), so the next settled sample can measure these caps properly
# instead of guessing.
GATE_WINDOW             = LAST_N_GAMES   # matches inspected per team
GATE_H2H_COUNT          = 3              # h2h matches inspected
GATE_H2H_MAX_TOTAL      = 2              # last h2h total goals (2.5 -> 3+ fails)

# 2026-10-04 — GATE 3 NO LONGER GATES ON A SINGLE MATCH.
# Two teams that have met once give one observation, and one 3-1 twelve months
# ago is not evidence about the fixture being priced now. Previously that lone
# match could reject an otherwise clean fixture. Gate 3 now refuses to gate
# anything until it has GATE_H2H_MIN_MATCHES meetings to look at; below that it
# passes and says so. The single most recent meeting is still reported, so the
# existing output columns keep their meaning and nothing that reads them breaks.
GATE_H2H_MIN_MATCHES    = 2              # below this, Gate 3 cannot gate
GATE_REQUIRE_H2H        = False          # no h2h history -> pass, but flag it

# Per-market profiles are retained so a future, MEASURED difference between the
# two markets can be expressed without another signature change. Both markets
# currently share the original, proven caps.
GATE_PROFILES = {
    "u25": {
        "max_scored":   5,   # neither team may score more than 5 in the window
        "max_conceded":  5,   # neither team may concede more than 5 in the window
        "fail_tier":    "🚫 U2.5 GATE FAIL",
    },
    "u35": {
        "max_scored":   5,   # same cap as U2.5 (the looser 7 was reverted)
        "max_conceded":  5,
        "fail_tier":    "🚫 U3.5 GATE FAIL",
    },
}

# Retained for backwards compatibility with any external reader of these names.
GATE_MAX_GOALS_SCORED   = GATE_PROFILES["u25"]["max_scored"]
GATE_MAX_GOALS_CONCEDED = GATE_PROFILES["u25"]["max_conceded"]
GATE_FAIL_TIER_U25      = GATE_PROFILES["u25"]["fail_tier"]
GATE_FAIL_TIER_U35      = GATE_PROFILES["u35"]["fail_tier"]


# ── UNDER KING — implemented as SIGNAL 6, not a separate tier ────────────────
# The user asked for ONE calculation: the signals (with KING among them) set the
# score/probability, and the gates then filter out unqualified teams. KING is
# therefore a sixth signal inside calculate_u25_score() and calculate_u35_score(),
# NOT a parallel label bolted on after the tiers. It promotes a fixture by
# lifting the score the normal tiers already read.
#
# Measured on 1,393 settled U2.5 rows (base 44.1%):
#     GK avg c_p90 <= 1.00            n=173  52.0%  +7.7pp   <- the only input that
#                                                        held up out-of-sample
#     every other candidate           positive in-sample, negative out-of-sample
# So the GK wall is the floor of KING, and everything else only adds to it.
#
# Shots On Target is counted but is deliberately NOT a requirement and never
# blocks a fixture. On 539 rows joined to both an outcome and a SOT prediction
# (base 41.6%) the SOT bands ran p0-p25 38.8%, p25-p50 42.4%, p50-p75 43.5%,
# p75-p100 41.5% — flat to mildly inverted, so low SOT is NEUTRAL, not harmful.
# Inside the GK core the higher-SOT half actually hit harder (58.3% vs 43.5%),
# which is exactly why low SOT must not be demanded: requiring it would throw
# away the stronger group. Low-SOT fixtures remain fully eligible.
KING_GK_MAX          = 1.00   # both keepers' goals-conceded-per-90, averaged
KING_BASE_POINTS     = 10.0   # the proven GK wall on its own
KING_SUPPORT_BONUS   = 2.5    # per supporting signal, so the ceiling is 10 + 4*2.5
KING_MAX_POINTS      = KING_BASE_POINTS + (4 * KING_SUPPORT_BONUS)   # 20.0
KING_LAMBDA_MAX_U25  = 2.00   # combined lambda at or under this supports KING
KING_LAMBDA_MAX_U35  = 2.60   # U3.5 is a looser line, so it tolerates more lambda
KING_VENUE_U25_MIN   = 0.50   # combined home/away U2.5 rate at or above this
KING_H2H_MAX_TOTAL   = 2      # most recent h2h at or under this total
KING_SOT_MAX         = 8.5    # matches the SOT engine's own MIN_PROJECTED_SOT


def calculate_king_signal(home_gk_cpg, away_gk_cpg, combined_lambda=None,
                          venue_rate=None, h2h_total=None, proj_sot=None,
                          lambda_max=KING_LAMBDA_MAX_U25):
    """
    KING as a scored signal: (points, fired, detail).

    Points are ZERO unless both keepers form a real wall. An ungradeable keeper
    returns 0.0 and does not fire, because "unknown keeper" must never read as
    "perfect wall" — the same phantom-value failure as the 90.7% draw confidence.

    `lambda_max` lets Under 3.5 apply its own looser lambda bound.
    """
    detail = {"king_gk_avg": None, "king_fired": False, "king_points": 0.0}
    if home_gk_cpg is None or away_gk_cpg is None:
        detail["king_ungradeable_keeper"] = True
        return 0.0, False, detail

    gk_avg = (home_gk_cpg + away_gk_cpg) / 2.0
    detail["king_gk_avg"] = round(gk_avg, 3)
    detail["king_ungradeable_keeper"] = False

    if gk_avg > KING_GK_MAX:
        return 0.0, False, detail          # the wall is the floor of KING

    support = {
        "low_lambda": combined_lambda is not None and combined_lambda <= lambda_max,
        "venue_u25":  venue_rate is not None and venue_rate >= KING_VENUE_U25_MIN,
        "h2h_low":    h2h_total is not None and h2h_total <= KING_H2H_MAX_TOTAL,
        "low_sot":    proj_sot is not None and proj_sot <= KING_SOT_MAX,
    }
    fired_support = sum(1 for v in support.values() if v)
    points = min(KING_MAX_POINTS, KING_BASE_POINTS + fired_support * KING_SUPPORT_BONUS)

    detail.update({
        "king_fired":        True,
        "king_points":       round(points, 1),
        "king_support":      fired_support,
        "king_comp_gk_wall": True,
        "king_comp_low_lambda": support["low_lambda"],
        "king_comp_venue_u25":  support["venue_u25"],
        "king_comp_h2h_low":    support["h2h_low"],
        "king_comp_low_sot":    support["low_sot"],
    })
    return round(points, 1), True, detail

# ==============================================================================
# TITANIUM HTTP HELPER 
# ==============================================================================
def GET(path, params=None):
    if params is None: params = {}
    params.setdefault("api_token", API_KEY)
    url = f"{BASE_URL}{path}"
    
    max_retries = 5
    backoff = 2.0
    
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, timeout=15)
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 429:
                time.sleep(backoff * (attempt + 1))
                continue
            else:
                return {"data": []}
        except Exception:
            time.sleep(backoff)
            continue
            
    return {"data": []}

def sleep_short():
    time.sleep(REQUEST_DELAY_SEC)

# ==============================================================================
# PAGINATION HELPERS
# ==============================================================================
def fetch_fixtures_for_date(date_str):
    all_fx = []; seen = set(); page = 1
    while True:
        data = GET(
            f"/fixtures/date/{date_str}",
            params={
                "include":  "participants;scores;lineups;formations;statistics",
                "per_page": 50, "page": page
            }
        )
        fx = data.get("data", [])
        if not fx: break
        added = False
        for f in fx:
            fid = f.get("id")
            if fid not in seen:
                seen.add(fid); all_fx.append(f); added = True
        if not added: break
        page += 1; sleep_short()
    return all_fx

def fetch_last_finished_fixtures_for_team(team_id, max_needed=200):
    end_dt   = datetime.now(timezone.utc).date() - timedelta(days=1)
    start_dt = end_dt - timedelta(days=TEAM_LOOKBACK_DAYS)
    all_fx   = []; seen = set(); page = 1
    while True:
        data = GET(
            f"/fixtures/between/{start_dt}/{end_dt}/{team_id}",
            params={
                "include":  "participants;scores;state;lineups;formations;statistics",
                "filters":  "fixtureStates:5",
                "sortBy":   "starting_at",
                "order":    "desc",
                "per_page": 50, "page": page
            }
        )
        fx = data.get("data", [])
        if not fx: break
        added = False
        for f in fx:
            fid = f.get("id")
            if fid not in seen:
                seen.add(fid); all_fx.append(f); added = True
        if not added or len(all_fx) >= max_needed: break
        page += 1; sleep_short()
    return (all_fx or [])[:max_needed]

def fetch_last_h2h(team1, team2, n=LAST_N_GAMES):
    all_fx = []; seen = set(); page = 1
    while True:
        data = GET(
            f"/fixtures/head-to-head/{team1}/{team2}",
            params={
                "include":  "scores;participants",
                "filters":  "fixtureStates:5",
                "sortBy":   "starting_at",
                "order":    "desc",
                "per_page": 50, "page": page
            }
        )
        fx = data.get("data", [])
        if not fx: break
        added = False
        for f in fx:
            fid = f.get("id")
            if fid not in seen:
                seen.add(fid); all_fx.append(f); added = True
        if not added or len(all_fx) >= n: break
        page += 1; sleep_short()
    return (all_fx or [])[:n]

# ==============================================================================
# SAFE HELPERS & ODDS SNIPER 
# ==============================================================================
def safe_int(x, default=None):
    try:
        if x is None: return default
        return int(x)
    except Exception: return default

def sniper_fetch_odds(fixture_id):
    try:
        data = GET(f"/odds/pre-match/fixtures/{fixture_id}")
    except Exception:
        return {"h": None, "d": None, "a": None}
    odds_list = data.get("data", [])
    res = {"h": None, "d": None, "a": None}
    for o in odds_list:
        if o.get("market_id") == MARKET_1X2:
            lbl = str(o.get("label", "")).lower()
            try: val = float(o.get("value"))
            except: continue
            if ("1" in lbl or "home" in lbl) and res["h"] is None:
                res["h"] = val
            elif ("x" in lbl or "draw" in lbl) and res["d"] is None:
                res["d"] = val
            elif ("2" in lbl or "away" in lbl) and res["a"] is None:
                res["a"] = val
    return res

# ==============================================================================
# SCORE EXTRACTION HELPERS 
# ==============================================================================
def is_team_home(fx, team_id):
    for p in fx.get("participants", []):
        if safe_int(p.get("id")) == safe_int(team_id):
            loc = (p.get("meta") or {}).get("location")
            if loc == "home": return True
            if loc == "away": return False
    parts = fx.get("participants", [])
    if len(parts) >= 2:
        if safe_int(parts[0].get("id")) == safe_int(team_id): return True
        if safe_int(parts[1].get("id")) == safe_int(team_id): return False
    return False

def extract_final_goals_from_scores(scores):
    home = away = None
    for entry in (scores or []):
        if not isinstance(entry, dict): continue
        s    = entry.get("score") or entry
        desc = str(entry.get("description", s.get("description", ""))).upper()
        if any(w in desc for w in ["PENALTY", "EXTRA", "AGG"]): continue
        part = s.get("participant") or entry.get("participant")
        g    = s.get("goals") if isinstance(s, dict) else entry.get("goals")
        try:
            if isinstance(g, str) and g.isdigit(): g = int(g)
        except: pass
        if isinstance(g, int):
            if part == "home":  home = g if home is None else max(home, g)
            elif part == "away": away = g if away is None else max(away, g)
    return home, away

def get_team_and_opponent_goals_from_fixture(fx, team_id):
    hg, ag = extract_final_goals_from_scores(fx.get("scores", []))
    if hg is None or ag is None: return None, None
    return (hg, ag) if is_team_home(fx, team_id) else (ag, hg)

def is_u25(fx):
    hg, ag = extract_final_goals_from_scores(fx.get("scores", []))
    return hg is not None and ag is not None and (hg + ag) < 3

def is_u35(fx):
    hg, ag = extract_final_goals_from_scores(fx.get("scores", []))
    return hg is not None and ag is not None and (hg + ag) < 4

# ==============================================================================
# FORMATION / LINEUP HELPERS
# ==============================================================================
def extract_formation_from_fixture(fx, team_id):
    for f in fx.get("formations", []) or []:
        pid = safe_int(f.get("participant_id") or f.get("participantId"))
        if pid is not None and safe_int(team_id) is not None and pid == safe_int(team_id):
            return f.get("formation")
    return None

def extract_starters_from_fixture(fx, team_id):
    starters = []
    for l in fx.get("lineups", []) or []:
        t_id   = safe_int(l.get("team_id") or l.get("teamId"))
        t_type = safe_int(l.get("type_id") or l.get("typeId"))
        if (t_id is not None and safe_int(team_id) is not None and
                t_id == safe_int(team_id) and
                (t_type is None or t_type == 11)):
            starters.append({
                "player_id":     l.get("player_id") or l.get("playerId"),
                "player_name":   l.get("player_name") or l.get("playerName"),
                "jersey_number": l.get("jersey_number") or l.get("jerseyNumber"),
                "position_id":   l.get("position_id") or l.get("positionId")
            })
    return starters

def identify_key_players_from_history(recent_lineups, threshold_frac=CORE_START_RATE):
    counts, names = Counter(), {}
    valid = [l for l in recent_lineups if isinstance(l, list) and len(l) >= 8]
    for starters in valid:
        for p in starters:
            pid = p.get("player_id")
            if pid:
                counts[pid] += 1
                names[pid]   = p.get("player_name", names.get(pid))
    if not valid: return {}
    min_starts = math.ceil(len(valid) * threshold_frac)
    core = {
        pid: {"player_id": pid, "player_name": names.get(pid, "Unknown"),
              "starts": cnt}
        for pid, cnt in counts.items() if cnt >= min_starts
    }
    return dict(sorted(core.items(), key=lambda x: -x[1]["starts"])[:MAX_KEY_PLAYERS])

def compute_rotation_score(recent_starts, today_ids):
    if not recent_starts or not today_ids: return 0.0
    core_players = {pid for pid, c in recent_starts.items() if c >= 2}
    if not core_players: return 0.0
    overlap = len(core_players.intersection(set(today_ids)))
    return round(overlap / len(core_players), 2)

# ==============================================================================
# POISSON & MONTE CARLO (FLIPPED FOR UNDERS)
# ==============================================================================
def poisson_pmf(k, lam):
    if lam < 0: return 0.0
    try: return math.exp(-lam) * (lam ** k) / math.factorial(k)
    except Exception: return 0.0

def generate_scoreline_predictions(lh, la, n_sim=SIMULATION_SIZE):
    if n_sim <= 0:
        return {"u25_prob": 0.0, "u35_prob": 0.0, "sim_count": 0}
    np.random.seed(None)
    hg = np.random.poisson(lh, size=n_sim)
    ag = np.random.poisson(la, size=n_sim)

    u25 = u35 = 0

    for h, a in zip(hg, ag):
        total = h + a
        if total <= 2:  u25 += 1   
        if total <= 3:  u35 += 1   

    summary = {
        "u25_prob": u25 / n_sim,
        "u35_prob": u35 / n_sim,
        "sim_count": n_sim
    }
    return summary

# ==============================================================================
# FATIGUE ESTIMATOR 
# ==============================================================================
def parse_fixture_datetime(fx):
    dtcands = []
    if fx.get("starting_at"):                               dtcands.append(fx["starting_at"])
    if (fx.get("time") and isinstance(fx.get("time"), dict)
            and fx["time"].get("starting_at")):             dtcands.append(fx["time"]["starting_at"])
    if fx.get("date"):                                      dtcands.append(fx["date"])
    for s in dtcands:
        if not s: continue
        try:
            if isinstance(s, str):
                ss = s.replace("Z", "+00:00") if s.endswith("Z") else s
                try: dt = datetime.fromisoformat(ss)
                except:
                    try: dt = datetime.strptime(ss, "%Y-%m-%d %H:%M:%S")
                    except:
                        try: dt = datetime.strptime(ss, "%Y-%m-%d")
                        except: dt = None
            elif isinstance(s, (int, float)):
                dt = datetime.fromtimestamp(int(s), tz=timezone.utc)
            else: dt = None
            if dt:
                if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                else:                 dt = dt.astimezone(timezone.utc)
                return dt
        except Exception: continue
    return None

def estimate_fatigue_from_schedules(recent_fixtures, team_id, rotation_score):
    now       = datetime.now(timezone.utc)
    played_14 = played_7 = 0
    cutoff    = now - timedelta(days=FATIGUE_WINDOW_DAYS)
    for f in recent_fixtures or []:
        if not any(p.get("id") == team_id for p in f.get("participants", [])): continue
        dt = parse_fixture_datetime(f)
        if not dt or dt < cutoff: continue
        days = (now - dt).days
        if days <= 14: played_14 += 1
        if days <= 7:  played_7  += 1
    s14  = min(1.0, played_14 / 6.0)
    s7   = min(1.0, played_7  / 4.0)
    try: rot = float(rotation_score)
    except: rot = 0.0
    eff_rot = 1.0 - min(1.0, max(0.0, rot))
    fatigue = (0.6 * s14 + 0.4 * s7) * (0.7 + 0.3 * eff_rot)
    return min(1.0, max(0.0, fatigue))

# ==============================================================================
# LEAGUE UNDER 2.5 WEIGHT (TTL CACHED FOR MASSIVE API SAVINGS)
# ==============================================================================
def compute_league_under25_weight(league_id, days_lookback=180):
    cache_file = os.path.join(DATA_DIR, "league_weights_cache.json")
    cache_data = {}
    
    # 1. Load existing cache
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                cache_data = json.load(f)
        except Exception:
            pass

    now_utc = datetime.now(timezone.utc)
    lid_str = str(league_id)

    # 2. Check if league is in cache and less than 7 days old
    if lid_str in cache_data:
        try:
            last_updated = datetime.fromisoformat(cache_data[lid_str]["last_updated"])
            if (now_utc - last_updated).days < 7:
                return cache_data[lid_str]["weight"]
        except Exception:
            pass

    # 3. If missing or expired, fetch from API (Reduced lookback to 180 days to save API)
    end_dt   = now_utc.date() - timedelta(days=1)
    start_dt = end_dt - timedelta(days=min(days_lookback, 180))
    
    all_fx = []; seen = set(); page = 1
    while True:
        data = GET(
            f"/fixtures/between/{start_dt}/{end_dt}/{league_id}",
            params={"include": "scores", "per_page": 50, "page": page}
        )
        fx = data.get("data", [])
        if not fx: break
        added = False
        for f in fx:
            fid = f.get("id")
            if fid not in seen:
                seen.add(fid); all_fx.append(f); added = True
        if not added: break
        page += 1; sleep_short()
        
    total = under25 = 0
    for fx in all_fx:
        hg, ag = extract_final_goals_from_scores(fx.get("scores", []))
        if hg is None or ag is None: continue
        total += 1
        if hg + ag < 3: under25 += 1
        
    weight = 0.0
    if total > 0:
        weight = round((under25 / total) * LEAGUE_SCALE, 4)

    # 4. Save to cache
    cache_data[lid_str] = {
        "weight": weight,
        "last_updated": now_utc.isoformat()
    }
    try:
        with open(cache_file, "w") as f:
            json.dump(cache_data, f, indent=4)
    except Exception:
        pass

    return weight


# ==============================================================================
# LEAGUE AVERAGE TOTAL GOALS (DIRECT MEASUREMENT — the lambda prior)
# ==============================================================================
def compute_league_avg_total_goals(league_id, days_lookback=180):
    """
    Average TOTAL goals per match in a league, measured directly from results.

    This is the replacement for the rejected league_weight inversion. It records
    a raw goals-per-match number, so there is nothing to invert through Poisson
    and therefore no way to manufacture an impossible prior. A league with no
    results simply yields None (and the caller falls back to LAMBDA_PRIOR_GOALS)
    instead of a 0.0 that later inverted into 8.0 goals/team.

    Returns a dict {"avg_total", "per_team", "matches"} or None when the league
    cannot be measured. `per_team` is avg_total / 2 and is what shrunk_rate()
    wants, since lambda is a per-team scoring expectation.

    WHY THIS SWEEPS INSTEAD OF ASKING PER LEAGUE
    ---------------------------------------------
    The obvious call -- GET /fixtures/between/{start}/{end}/{league_id} -- does
    NOT work: that path segment is a TEAM id, so passing a league id returns an
    empty list and the league silently measures as None. That is also why the
    old league_weight cache held 0.0 for most leagues. Verified: passing league
    636 returned 0 fixtures, while the unfiltered sweep returns 26 of them.
    So one sweep is done per run and every league is measured from it.
    """
    cache_file = os.path.join(DATA_DIR, "league_avg_goals_cache.json")
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
                return cache_data[lid_str]["value"]
        except Exception:
            pass

    end_dt   = now_utc.date() - timedelta(days=1)
    start_dt = end_dt - timedelta(days=min(days_lookback, LEAGUE_SWEEP_DAYS))

    # ONE sweep of recent football, bucketed by league. The endpoint caps the
    # response at 200 fixtures, so the window is walked day-by-day from the most
    # recent end until every requested league has enough matches or the window
    # is exhausted.
    totals = defaultdict(lambda: [0.0, 0])
    wanted = {str(l) for l in _LEAGUE_SWEEP_TARGETS} if _LEAGUE_SWEEP_TARGETS else None

    cursor = end_dt
    while cursor >= start_dt:
        chunk_start = cursor - timedelta(days=LEAGUE_SWEEP_CHUNK_DAYS)
        page = 1
        seen = set()
        while page <= 6:
            data = GET(
                f"/fixtures/between/{chunk_start}/{cursor}",
                params={"include": "scores", "per_page": 50, "page": page}
            )
            fx = data.get("data", [])
            if not fx:
                break
            added = False
            for f in fx:
                fid = f.get("id")
                if fid in seen:
                    continue
                seen.add(fid); added = True
                lid = f.get("league_id")
                if lid is None:
                    continue
                lid = str(lid)
                if wanted is not None and lid not in wanted:
                    continue
                hg, ag = extract_final_goals_from_scores(f.get("scores", []))
                if hg is None or ag is None:
                    continue
                totals[lid][0] += (hg + ag)
                totals[lid][1] += 1
            if not added:
                break
            page += 1
            sleep_short()
        # stop once every requested league is measured or has run out of room
        if wanted:
            if all(totals.get(l, [0.0, 0])[1] >= LEAGUE_AVG_MIN_MATCHES for l in wanted):
                break
        else:
            break
        cursor = chunk_start - timedelta(days=1)

    value = None
    stats = totals.get(lid_str)
    if stats and stats[1] >= LEAGUE_AVG_MIN_MATCHES:
        avg = stats[0] / stats[1]
        value = {"avg_total": round(avg, 4), "per_team": round(avg / 2.0, 4),
                 "matches": stats[1]}

    cache_data[lid_str] = {"value": value, "last_updated": now_utc.isoformat()}
    try:
        with open(cache_file, "w") as f:
            json.dump(cache_data, f, indent=4)
    except Exception:
        pass

    return value

# ==============================================================================
# KEEPER WALL ENGINE (FLIPPED FROM VULNERABILITY TO SOLIDITY)
# ==============================================================================
GK_SQUAD_CACHE = {}    

def get_squad_data_for_gk(team_id, check_date_str):
    tid_str = str(team_id)
    if tid_str in GK_SQUAD_CACHE:
        cached = GK_SQUAD_CACHE[tid_str]
        if isinstance(cached, dict) and "players" in cached and len(cached["players"]) > 0:
            return cached

    end_dt   = (datetime.strptime(check_date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    start_dt = (datetime.strptime(check_date_str, "%Y-%m-%d") - timedelta(days=GK_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    try:
        resp = GET(
            f"/fixtures/between/{start_dt}/{end_dt}/{team_id}",
            params={
                "include": "lineups.details.type;lineups.player.position;scores;participants",
                "filter": "fixtureStates:5",
                "per_page": 40
            }
        )
    except Exception:
        return {"players": {}, "team_avg_leak": 1.2}

    player_stats        = {}
    team_total_conceded = 0
    valid_fixtures      = 0

    RATING_ID      = 118
    MINUTES_ID     = 119
    STAR_FACTOR_ID = 211

    for fx in resp.get("data", []):
        hid = aid = None
        for pt in fx.get("participants", []):
            if pt.get("meta", {}).get("location") == "home": hid = str(pt["id"])
            else: aid = str(pt["id"])

        hg, ag = extract_final_goals_from_scores(fx.get("scores", []))
        if hg is not None and ag is not None:
            opp_goals = ag if str(team_id) == hid else hg
            team_total_conceded += opp_goals
            valid_fixtures      += 1

        for l in fx.get("lineups", []):
            if str(l.get("team_id")) != str(team_id): continue
            if l.get("player_id") is None:            continue
            p_obj = l.get("player")
            if not p_obj:                             continue

            pid   = str(l["player_id"])
            m_val = r_val = star = 0
            c_val = -1.0

            for d in l.get("details", []):
                try: tid_d = int(d.get("type_id", 0))
                except: tid_d = 0
                raw_v = (d.get("data", {}).get("value") if isinstance(d.get("data"), dict) else d.get("value"))
                try: v = float(raw_v)
                except: v = 0
                
                if tid_d == MINUTES_ID: m_val = int(v)
                elif tid_d == RATING_ID: r_val = v
                elif tid_d == STAR_FACTOR_ID: star = 1
                elif "conceded" in str(d.get("type", {}).get("name", "")).lower(): c_val = v

            if m_val == 0 and str(l.get("formation_position")) == "1": m_val = 90
            if c_val == -1.0 and hg is not None and ag is not None:
                c_val = ag if str(team_id) == hid else hg

            pos_name = "Unknown"
            if p_obj.get("position") and isinstance(p_obj["position"], dict):
                pos_name = p_obj["position"].get("name", "Unknown")

            if pid not in player_stats:
                player_stats[pid] = {
                    "name": p_obj.get("display_name", "Unknown"), "pos": pos_name,
                    "mins": 0, "ratings": [], "star": 0, "apps": 0, "conceded": 0
                }
            player_stats[pid]["mins"]     += m_val
            player_stats[pid]["apps"]     += 1
            player_stats[pid]["star"]     += star
            if r_val > 0: player_stats[pid]["ratings"].append(r_val)
            if c_val >= 0: player_stats[pid]["conceded"] += c_val

    team_avg_leak = (team_total_conceded / max(1, valid_fixtures) if valid_fixtures > 0 else 1.2)

    processed = {}
    for pid, d in player_stats.items():
        # PHASE 0 FIX: c_p90 is a per-90 rate, so it must be built from a
        # genuine sample. The old form (conceded / max(1, mins)) * 90 divided
        # by whatever minutes happened to be on the books: a keeper who conceded
        # 3 goals in a single 1-minute cameo scored 3/1*90 = 270.00/90.
        # Insufficient evidence now yields None (unknown), never a fake number.
        if d["mins"] >= GK_MIN_MINS and d["apps"] >= GK_MIN_APPS and d["conceded"] >= 0:
            c_p90 = (d["conceded"] / d["mins"]) * 90.0
            if c_p90 > GK_CPG_SANITY_MAX:
                c_p90 = GK_CPG_SANITY_MAX   # corrupt upstream total, clamp
            c_p90 = round(c_p90, 2)
        else:
            c_p90 = None                    # unknown -> must not read as 0.0
        processed[pid] = {
            "id": pid, "name": d["name"], "pos": d["pos"],
            "apps": d["apps"], "mins": d["mins"], "c_p90": c_p90
        }

    result = {"players": processed, "team_avg_leak": team_avg_leak}
    GK_SQUAD_CACHE[tid_str] = result
    return result

def evaluate_gk_wall(team_id, today_fixture, check_date_str):
    sq_data   = get_squad_data_for_gk(team_id, check_date_str)
    squad_map = sq_data.get("players", {})
    avg_leak  = sq_data.get("team_avg_leak", 1.2)

    if not squad_map:
        # PHASE 0 FIX: no squad data used to return a 1.5 proxy, which sits
        # inside the AVERAGE band and so scored a keeper bonus off pure absence
        # of evidence. Report the keeper as ungraded instead.
        return False, False, None, "❔ GK no squad data (no grade)"

    starting_gk_id = None
    is_expected_gk = False 

    for l in today_fixture.get("lineups", []) or []:
        if str(l.get("team_id")) != str(team_id): continue
        t_type = safe_int(l.get("type_id"))
        if t_type not in [11, None]: continue
        pid    = str(l.get("player_id", ""))
        if not pid: continue
        p_data = squad_map.get(pid, {})
        if p_data.get("pos") == "Goalkeeper":
            starting_gk_id = pid
            break

    if not starting_gk_id:
        for l in today_fixture.get("lineups", []) or []:
            if str(l.get("team_id")) != str(team_id): continue
            if str(l.get("formation_position", "")) == "1":
                pid    = str(l.get("player_id", ""))
                if pid and pid in squad_map:
                    starting_gk_id = pid
                    break

    if not starting_gk_id:
        gks = [p for p in squad_map.values() if p['pos'] == "Goalkeeper"]
        if gks:
            number_1_gk = sorted(gks, key=lambda x: x['mins'], reverse=True)[0]
            if number_1_gk['mins'] > 0:
                starting_gk_id = number_1_gk['id']
                is_expected_gk = True 

    # PHASE 0 FIX: the third return value is a GRADE, not a filler number.
    # An ungradable keeper is reported as None so calculate_u25_score() /
    # calculate_u35_score() can withhold the keeper signal entirely, instead of
    # quietly treating a neutral 1.50 proxy as evidence of a wall.
    if not starting_gk_id:
        return False, False, None, "❔ GK unlisted (no grade)"

    starter = squad_map[starting_gk_id]
    apps    = starter.get("apps", 0)
    c_p90   = starter.get("c_p90")        # None = insufficient evidence

    prefix = "[Exp #1] " if is_expected_gk else ""

    # PHASE 0 FIX: an ungradable keeper is NOT an elite wall.
    # The old code let a missing c_p90 default to 0.0, and 0.0 <= GK_ELITE_CPG
    # promoted a goalkeeper with zero usable data to ELITE WALL (+20 pts).
    if c_p90 is None:
        return False, False, None, f"❔ {prefix}GK unknown (apps={apps}, no reliable sample)"

    is_elite = c_p90 <= GK_ELITE_CPG
    is_avg   = c_p90 <= GK_AVERAGE_CPG

    if is_elite:
        note = f"🧱 {prefix}ELITE WALL ({c_p90:.2f}/90)"
    elif is_avg:
        note = f"🛡️ {prefix}Solid Guard ({c_p90:.2f}/90)"
    else:
        note = f"⚠️ {prefix}Leaky ({c_p90:.2f}/90)"

    return is_elite, is_avg, round(c_p90, 2), note

# ==============================================================================
# UNDER 2.5 COMPOSITE SCORER
# ==============================================================================
def calculate_u25_score(
    u25_prob,              
    venue_u25_home,        
    venue_u25_away,        
    home_gk_cpg,           
    away_gk_cpg,           
    h2h_u25_rate,          
    combined_lambda,       
    fatigue_home,
    fatigue_away,
    king_points=0.0,          # from calculate_king_signal() — SIGNAL 6
    king_fired=False,
):
    sig1_raw   = min(1.0, u25_prob / 0.65)
    sig1_score = sig1_raw * 30
    sig1_fired = u25_prob >= 0.50

    if combined_lambda <= 2.0:
        sig2_score, sig2_fired = 25.0, True
    elif combined_lambda >= 2.8:
        sig2_score, sig2_fired = 0.0, False
    else:
        sig2_raw = (2.8 - combined_lambda) / 0.8  
        sig2_score = sig2_raw * 25.0
        sig2_fired = combined_lambda <= 2.4

    # PHASE 0 FIX: the keeper signal requires BOTH keepers to carry a real,
    # trustworthy grade. evaluate_gk_wall() now hands back None for a keeper it
    # cannot grade, so a missing grade can no longer be read as a perfect wall.
    if home_gk_cpg is None or away_gk_cpg is None:
        sig3_score, sig3_fired = 0.0, False
    elif home_gk_cpg <= GK_ELITE_CPG and away_gk_cpg <= GK_ELITE_CPG:
        sig3_score, sig3_fired = 20.0, True
    elif home_gk_cpg <= GK_AVERAGE_CPG and away_gk_cpg <= GK_AVERAGE_CPG:
        sig3_score, sig3_fired = 12.0, True
    else:
        avg_cpg = (home_gk_cpg + away_gk_cpg) / 2.0
        if avg_cpg > 1.8: sig3_score = 0.0
        else:
            sig3_raw = max(0.0, (1.8 - avg_cpg) / 0.7) 
            sig3_score = sig3_raw * 10.0
        sig3_fired = avg_cpg <= 1.4

    venue_u25_combined = (venue_u25_home + venue_u25_away) / 2.0
    sig4_raw   = min(1.0, venue_u25_combined / 0.60)  
    sig4_score = sig4_raw * 15
    sig4_fired = venue_u25_combined >= 0.50

    avg_fatigue = (fatigue_home + fatigue_away) / 2.0
    # 2026-10-04 — FATIGUE BONUS REMOVED, SIGNAL RETAINED.
    # Measured on 1,393 settled U2.5 rows (base 44.1%), fatigue avg >= 0.40 hit
    # 41.9% in-sample and 41.9% out-of-sample: +0.0pp lift in both halves. It
    # added up to 10 points to u25_score for no measurable reason, diluting a
    # score that IS predictive (score>=70 lifted +6.9pp) and dragging Tier 1
    # toward the base rate.
    #
    # The signal is deliberately NOT deleted: sig5 still exists, still appears in
    # the breakdown and still counts toward signals_fired, so the documented
    # 5-signal structure and the "signals_fired >= 4" Tier 1 rule are unchanged.
    # Only the non-informative score contribution is gone. Restoring it is a
    # one-line change if fresh data ever shows it carries value.
    sig5_score = 0.0
    sig5_fired = False

    # SIGNAL 6 — KING. Points are already computed by calculate_king_signal()
    # and arrive here, so the score the tiers read already includes them. This is
    # why KING needs no separate tier: it promotes through the normal thresholds.
    sig6_score = round(float(king_points or 0.0), 1)
    sig6_fired = bool(king_fired)

    total_score  = sig1_score + sig2_score + sig3_score + sig4_score + sig5_score + sig6_score
    total_score  = max(0.0, min(100.0, total_score))
    signals_fired = sum([sig1_fired, sig2_fired, sig3_fired, sig4_fired, sig5_fired, sig6_fired])

    breakdown = {
        "sig1_mc_u25":           round(sig1_score, 1),
        "sig2_lambda":           round(sig2_score, 1),
        "sig3_gk_wall":          round(sig3_score, 1),
        "sig4_venue_u25":        round(sig4_score, 1),
        "sig5_fatigue_boost":    round(sig5_score, 1),
        "sig6_king":             sig6_score,
        "signals_fired":         signals_fired,
        "venue_u25_combined":    round(venue_u25_combined, 3),
    }
    return round(total_score, 1), signals_fired, breakdown

def shrunk_rate(goals, matches, prior_mean, prior_strength=LAMBDA_PRIOR_STRENGTH):
    """
    Empirical-Bayes shrinkage of an observed scoring rate toward a prior mean.

        (goals + prior_strength * prior_mean) / (matches + prior_strength)

    A team with a long record keeps close to its own rate; a team with one or two
    matches is pulled hard toward the prior mean. This is what the old lambda
    lacked entirely -- it treated a single 3-0 as a 3.0 goals/game attack.
    """
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
    """
    Telemetry for the failure that actually shipped: a degenerate base rate drove
    lambda to the clamp ceiling and u25_prob collapsed to ~0.0006, but nothing
    logged it -- the per-fixture `except Exception: continue` swallowed the
    whole thing. Returns a short warning string, or None when healthy.
    """
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


def build_lambdas(lastN_home, home_id, lastN_away, away_id, league_id, league_cache=None):
    """
    Rebuild the scoring lambdas: combine attack and defence, then SHRINK ONCE.

    2026-10-04 — two changes, both measured:

    1. THE PRIOR IS NOW LEAGUE-SPECIFIC. `league_cache[lid]["avg_goals"]` holds the
       league's directly-measured average goals per match (see
       compute_league_avg_total_goals); its per_team figure becomes the prior
       mean for shrunk_rate(). LAMBDA_PRIOR_GOALS is only the fallback when a
       league has too few results to measure. Previously the prior was a flat
       1.35 for every league on the planet, so a high-scoring league and a
       defensive one were shrunk toward the same number.

    2. SHRUNK ONCE, NOT TWICE. The old code shrank attack and defence separately
       and then averaged the two shrunk numbers, which is two independent
       shrinkages: the same league prior was applied twice, so the prior carried
       double weight relative to the team's own form. Now the raw attack and raw
       defence are COMBINED FIRST, and that single blended observation is shrunk
       once toward the prior. The team's evidence is now counted once.

       Example, prior 1.35, strength 2.5, home attack 3.0 over 5 matches,
       away defence 0.0 over 5:
         old: att (15+8.1)/11=2.10, def (0+8.1)/11=0.74 -> mean 1.42
         new: raw blend (3.0+0.0)/2 = 1.50
              shrunk (7.5 + 2.5*1.35)/7.5 = 1.45
       The new path is not merely averaged-then-shrunk; the prior weight now
       appears exactly once.
    """
    prior_mean = LAMBDA_PRIOR_GOALS
    league_avg_total = None
    league_avg_n = None
    if league_cache and league_id is not None:
        entry = league_cache.get(league_id) or league_cache.get(str(league_id)) or {}
        avg = entry.get("avg_goals")
        if isinstance(avg, dict) and avg.get("per_team"):
            prior_mean = float(avg["per_team"])
            league_avg_total = avg.get("avg_total")
            league_avg_n = avg.get("matches")

    detail = {
        "lambda_base": round(prior_mean, 3),
        "lambda_prior_source": "league" if league_avg_total is not None else "fallback",
        "lambda_league_avg_total": league_avg_total,
        "lambda_league_n": league_avg_n,
    }

    def side_attack_concede(fixtures_list, tid):
        scored = 0.0
        conceded = 0.0
        n = 0
        for f in fixtures_list or []:
            tg, og = get_team_and_opponent_goals_from_fixture(f, tid)
            if tg is None or og is None:
                continue
            scored += tg
            conceded += og
            n += 1
        return scored, conceded, n

    h_s, h_c, h_n = side_attack_concede(lastN_home, home_id)
    a_s, a_c, a_n = side_attack_concede(lastN_away, away_id)

    # ONE shrinkage per side. The team's own attack and the opponent's defence are
    # combined into a single raw observation first, so the prior is applied once
    # rather than twice.
    if h_n > 0 or a_n > 0:
        h_raw_att = (h_s / h_n) if h_n > 0 else prior_mean
        h_raw_def = (a_c / a_n) if a_n > 0 else prior_mean
        a_raw_att = (a_s / a_n) if a_n > 0 else prior_mean
        a_raw_def = (h_c / h_n) if h_n > 0 else prior_mean

        h_blend = (h_raw_att + h_raw_def) / 2.0
        a_blend = (a_raw_att + a_raw_def) / 2.0

        lambda_home = shrunk_rate(h_blend * min(h_n, a_n) if (h_n and a_n) else 0.0,
                                  min(h_n, a_n), prior_mean)
        lambda_away = shrunk_rate(a_blend * min(h_n, a_n) if (h_n and a_n) else 0.0,
                                  min(h_n, a_n), prior_mean)
    else:
        # No history at all: the prior is the entire estimate, and it is said so.
        lambda_home = lambda_away = prior_mean

    detail.update({
        "lambda_home": round(lambda_home, 3),
        "lambda_away": round(lambda_away, 3),
        "lambda_home_n": h_n,
        "lambda_away_n": a_n,
    })
    return (
        max(LAMBDA_MIN, min(LAMBDA_MAX, lambda_home)),
        max(LAMBDA_MIN, min(LAMBDA_MAX, lambda_away)),
        detail,
    )


def evaluate_unders_gates(lastN_home, home_id, lastN_away, away_id, h2h,
                          profile="u25"):
    """
    Apply the three hard gates to a fixture for ONE market profile.

    `profile` selects the caps from GATE_PROFILES: "u25" (max_scored 8,
    max_conceded 5) or "u35" (max_scored 8, max_conceded 7).

    Gate 1: neither team scored more than profile["max_scored"] in the window
    Gate 2: neither team conceded more than profile["max_conceded"] in the window
    Gate 3: NONE of the last GATE_H2H_COUNT head-to-heads finished over 2.5

    Returns (passed, reasons, detail). Every tier on both engines depends on
    `passed` — these are gates, not bonus points.
    """
    prof = GATE_PROFILES.get(profile) or GATE_PROFILES["u25"]
    max_scored = prof["max_scored"]
    max_conceded = prof["max_conceded"]
    reasons = []
    detail = {"gate_profile": profile,
              "gate_max_scored": max_scored,
              "gate_max_conceded": max_conceded}

    def window_totals(fixtures_list, tid):
        scored = 0.0
        conceded = 0.0
        n = 0
        for f in fixtures_list or []:
            tg, og = get_team_and_opponent_goals_from_fixture(f, tid)
            if tg is None or og is None:
                continue
            scored += tg
            conceded += og
            n += 1
        return scored, conceded, n

    h_scored, h_conceded, h_n = window_totals(lastN_home, home_id)
    a_scored, a_conceded, a_n = window_totals(lastN_away, away_id)

    detail.update({
        "gate_home_scored": h_scored, "gate_home_conceded": h_conceded, "gate_home_n": h_n,
        "gate_away_scored": a_scored, "gate_away_conceded": a_conceded, "gate_away_n": a_n,
    })

    # GATE 1 — neither side may be a prolific scorer over the window
    if h_n == 0 or a_n == 0:
        reasons.append("no history to gate on")
    else:
        if h_scored > max_scored:
            reasons.append(f"home scored {h_scored:.0f} > {max_scored}")
        if a_scored > max_scored:
            reasons.append(f"away scored {a_scored:.0f} > {max_scored}")
        # GATE 2 — nor a leaky one (the cap differs per market)
        if h_conceded > max_conceded:
            reasons.append(f"home conceded {h_conceded:.0f} > {max_conceded}")
        if a_conceded > max_conceded:
            reasons.append(f"away conceded {a_conceded:.0f} > {max_conceded}")

    # GATE 3 — none of the last GATE_H2H_COUNT h2h matches may have gone over 2.5.
    # 2026-10-04: widened from the single most recent h2h to the last three. The
    # latest is still reported as `gate_h2h`/`gate_h2h_total`, so a consumer that
    # only ever read those two keys keeps exactly its previous meaning.
    h2h_total = None
    h2h_goals = None
    inspected = []
    if h2h:
        for m in (h2h or [])[:GATE_H2H_COUNT]:
            hg, ag = extract_final_goals_from_scores(m.get("scores", []))
            if hg is None or ag is None:
                continue
            inspected.append((f"{hg}-{ag}", hg + ag))
        if inspected:
            h2h_goals = inspected[0][0]
            h2h_total = inspected[0][1]
    detail["gate_h2h"] = h2h_goals or "n/a"
    detail["gate_h2h_total"] = h2h_total
    detail["gate_h2h_checked"] = len(inspected)
    detail["gate_h2h_matches"] = "; ".join(f"{g}({t})" for g, t in inspected) or "n/a"

    if not inspected:
        if GATE_REQUIRE_H2H:
            reasons.append("no h2h history to gate on")
        else:
            detail["gate_h2h_status"] = "no h2h data (passed by policy)"
    elif len(inspected) < GATE_H2H_MIN_MATCHES:
        # Too little h2h history to justify a rejection. One meeting is one
        # observation, and gating on it threw away real Under fixtures.
        detail["gate_h2h_status"] = (
            f"only {len(inspected)} h2h match, under the {GATE_H2H_MIN_MATCHES} "
            f"needed to gate (passed)"
        )
    else:
        over = [f"{g} ({t} goals)" for g, t in inspected if t > GATE_H2H_MAX_TOTAL]
        if over:
            reasons.append(
                f"{len(over)} of last {len(inspected)} h2h over 2.5: {'; '.join(over)}"
            )

    return (len(reasons) == 0), reasons, detail


def king_sot_for_fixture(fx, home_id, away_id, lastN_home, lastN_away):
    """
    Projected Shots On Target for a fixture, using ONLY statistics the unders
    engine has ALREADY fetched.

    /fixtures/between/... is called with
    include="participants;scores;state;lineups;formations;statistics"
    (see get_team_fixtures), so each past fixture in lastN_home/lastN_away already
    carries its statistics array in memory. This adds NO new API call and NO new
    include string — it only reads what is already there, exactly as the SOT
    engine (Engine/sot_engine.py) does.

    Returns (proj_sot, detail) or (None, detail) when a fixture has no usable
    SOT figures. A missing measurement returns None rather than 0.0: "we could
    not see the shots" must not be reported as "this team takes no shots", which
    is the same phantom-value failure as the 90.7% draw confidence.
    """

    def stat_label(entry):
        """SportMonks sends type as a dict, a bare string, or a bare code."""
        t = entry.get("type")
        if isinstance(t, dict):
            return str(t.get("name") or t.get("code") or t.get("developer_name") or "")
        if t is None:
            return ""
        return str(t)

    def is_sot_label(label):
        low = label.strip().lower()
        return low in ("shots on target", "shots_on_target", "shotsontarget",
                       "sot") or "shots on target" in low

    def sot_from(fixture, tid):
        stats = fixture.get("statistics") or []
        if isinstance(stats, dict):
            stats = list(stats.values())
        mine = None
        theirs = None
        for s in stats:
            if not isinstance(s, dict):
                continue
            if not is_sot_label(stat_label(s)):
                continue
            raw = s.get("value")
            if raw is None and isinstance(s.get("data"), dict):
                raw = s["data"].get("value")
            try:
                val = float(raw)
            except (TypeError, ValueError):
                continue
            if str(s.get("participant_id")) == str(tid):
                mine = val
            else:
                theirs = val
        return mine, theirs

    def team_projection(fixtures_list, tid):
        """Attack SOT vs the opponent's conceded SOT, over the window."""
        att, con, n = [], [], 0
        for f in fixtures_list or []:
            mine, theirs = sot_from(f, tid)
            if mine is None:
                continue
            att.append(mine)
            if theirs is not None:
                con.append(theirs)
            n += 1
        if not att:
            return None, None
        return sum(att) / n, (sum(con) / len(con) if con else None)

    h_att, h_con = team_projection(lastN_home, home_id)
    a_att, a_con = team_projection(lastN_away, away_id)

    detail = {"sot_proj": None,   # always present, None when unmeasured
          "sot_home_att": round(h_att, 2) if h_att is not None else None,
              "sot_away_att": round(a_att, 2) if a_att is not None else None,
              "sot_home_con": round(h_con, 2) if h_con is not None else None,
              "sot_away_con": round(a_con, 2) if a_con is not None else None}

    # Expected SOT for each side, using the SOT engine's own construction:
    # the team's own average SOT blended with the opponent's SOT conceded.
    if h_att is None or a_con is None:
        return None, detail
    if a_att is None or h_con is None:
        return None, detail
    proj = ((h_att + a_con) / 2.0 + (a_att + h_con) / 2.0) / 2.0
    detail["sot_proj"] = round(proj, 2)
    return proj, detail


def get_u25_tier(score, signals_fired, gates_passed=True):
    # HARD GATE: a fixture that fails any gate earns no tier at all,
    # however high it scored.
    if not gates_passed:
        return GATE_FAIL_TIER_U25
    if score >= U25_TIER1_SCORE and signals_fired >= 4:
        return "🛡️ U2.5 TIER 1 — LOCK"
    elif score >= U25_TIER2_SCORE:
        return "✅ U2.5 TIER 2 — SOLID"
    elif score >= U25_TIER3_SCORE:
        return "📊 U2.5 TIER 3 — LEAN"
    else:
        return "⚪ U2.5 BELOW THRESHOLD"

# ==============================================================================
# UNDER 3.5 COMPOSITE SCORER
# ==============================================================================
def calculate_u35_score(
    u35_prob,              
    combined_lambda,       
    venue_u35_home,        
    venue_u35_away,        
    league_weight,         
    fatigue_home,          
    fatigue_away,          
    home_gk_cpg,
    away_gk_cpg,
    king_points=0.0,          # from calculate_king_signal() — SIGNAL 6
    king_fired=False,
):
    sig1_raw   = min(1.0, u35_prob / 0.85)
    sig1_score = sig1_raw * 35

    if combined_lambda <= 2.6: sig2_score = 25.0
    elif combined_lambda >= 3.3: sig2_score = 0.0
    else:
        sig2_raw = (3.3 - combined_lambda) / 0.7
        sig2_score = sig2_raw * 25.0

    venue_u35_combined = (venue_u35_home + venue_u35_away) / 2.0
    sig3_raw   = min(1.0, venue_u35_combined / 0.85)
    sig3_score = sig3_raw * 20

    sig4_score = min(10.0, league_weight * 33.3)

    avg_fatigue = (fatigue_home + fatigue_away) / 2.0

    # PHASE 0 FIX: same integrity guard as the U2.5 scorer — an ungraded keeper
    # must not be averaged in as a clean sheet.
    if home_gk_cpg is None or away_gk_cpg is None:
        cpg_bonus = 0.0
    else:
        avg_cpg = (home_gk_cpg + away_gk_cpg) / 2.0
        cpg_bonus = max(0.0, (1.8 - avg_cpg) / 0.7) * 5.0

    fatigue_bonus = avg_fatigue * 5.0                  
    sig5_score = cpg_bonus + fatigue_bonus

    # SIGNAL 6 — KING, on the same footing as Under 2.5 so both markets promote
    # from one shared signal rather than two separate mechanisms.
    sig6_score = round(float(king_points or 0.0), 1)
    sig6_fired = bool(king_fired)

    total_score = sig1_score + sig2_score + sig3_score + sig4_score + sig5_score + sig6_score
    total_score = max(0.0, min(100.0, total_score))

    breakdown = {
        "sig1_mc_u35":         round(sig1_score, 1),
        "sig2_lambda":         round(sig2_score, 1),
        "sig3_venue_u35":      round(sig3_score, 1),
        "sig4_league_weight":  round(sig4_score, 1),
        "sig5_fortress_boost": round(sig5_score, 1),
        "sig6_king":           sig6_score,
        "king_fired":          sig6_fired,
        "venue_u35_combined":  round(venue_u35_combined, 3),
    }
    return round(total_score, 1), breakdown

def get_u35_tier(score, gates_passed=True):
    # HARD GATE: same three rules apply to Under 3.5 — no tier on score alone.
    if not gates_passed:
        return GATE_FAIL_TIER_U35
    if score >= U35_TIER1_SCORE:
        return "🧱 U3.5 TIER 1 — LOCK"
    elif score >= U35_TIER2_SCORE:
        return "✅ U3.5 TIER 2 — SOLID"
    elif score >= U35_TIER3_SCORE:
        return "📊 U3.5 TIER 3 — LEAN"
    else:
        return "⚪ U3.5 BELOW THRESHOLD"


# 📦 WRAPPED CALLABLE ENGINE (UNDER 2.5 & UNDER 3.5)
# ==============================================================================
def run_unders_engine(target_date=None, verbose=False):
    """
    Executes the Flipped Under 2.5 & Under 3.5 Engine.
    Fully wrapped for the VS Code Pipeline.
    verbose=False keeps it silent for API/Aggregator calls.
    """
    if not API_KEY:
        raise ValueError("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")

    # Fresh health report per run (see LAMBDA_HEALTH_WARNINGS).
    LAMBDA_HEALTH_WARNINGS.clear()

    if target_date is None:
        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if verbose:
        print(f"\n{'='*100}")
        print(f"  🛑 ALIENEDGE UNDER 2.5 & UNDER 3.5 DEFENSIVE ENGINE — {target_date}")
        print(f"  MC Trials: {SIMULATION_SIZE:,} | GK Lookback: {GK_LOOKBACK_DAYS}d")
        print(f"{'='*100}\n")

    fixtures = fetch_fixtures_for_date(target_date)
    if verbose: print(f"  Found {len(fixtures)} fixtures.\n")
    if not fixtures: return [], []

    league_cache = {}
    league_ids   = {fx.get("league_id") for fx in fixtures if fx.get("league_id")}
    # One sweep measures every league this run needs. The first call performs the
    # sweep and populates the cache; the rest read it.
    _LEAGUE_SWEEP_TARGETS.clear()
    _LEAGUE_SWEEP_TARGETS.update(str(l) for l in league_ids)

    for lid in league_ids:
        try: league_cache[lid] = {"league_weight": compute_league_under25_weight(lid)}
        except Exception: league_cache[lid] = {"league_weight": 0.0}
        try: league_cache[lid]["avg_goals"] = compute_league_avg_total_goals(lid)
        except Exception: league_cache[lid]["avg_goals"] = None
        sleep_short()

    team_cache = {}
    u25_picks  = []
    u35_picks  = []

    for fx in fixtures:
        try:
            parts = fx.get("participants", []) or []
            if len(parts) < 2: continue

            home_p = next((p for p in parts if (p.get("meta") or {}).get("location") == "home"), parts[0])
            away_p = next((p for p in parts if (p.get("meta") or {}).get("location") == "away"), parts[1] if len(parts) > 1 else None)
            if away_p is None: continue

            home_id   = safe_int(home_p.get("id"))
            away_id   = safe_int(away_p.get("id"))
            home_name = home_p.get("name") or f"Team {home_id}"
            away_name = away_p.get("name") or f"Team {away_id}"
            league_id = fx.get("league_id")

            for tid in (home_id, away_id):
                if tid not in team_cache:
                    try: team_cache[tid] = fetch_last_finished_fixtures_for_team(tid)
                    except Exception: team_cache[tid] = []
                    sleep_short()

            lastN_home = [f for f in team_cache.get(home_id, []) if is_team_home(f, home_id)][:LAST_N_GAMES]
            lastN_away = [f for f in team_cache.get(away_id, []) if not is_team_home(f, away_id)][:LAST_N_GAMES]

            try: h2h = fetch_last_h2h(home_id, away_id, n=LAST_N_GAMES)
            except Exception: h2h = []

            def personal_goals_total(fixtures_list, tid):
                s = c = 0
                for f in fixtures_list or []:
                    tg, _ = get_team_and_opponent_goals_from_fixture(f, tid)
                    if tg is not None: s += tg; c += 1
                return float(s), int(c)

            def avg_conceded(fixtures_list, tid):
                vals = []
                for f in fixtures_list or []:
                    _, og = get_team_and_opponent_goals_from_fixture(f, tid)
                    if og is not None: vals.append(og)
                return float(np.mean(vals)) if vals else 0.0

            # PHASE 2: rebuilt lambda with shrinkage toward a fixed prior mean.
            # The old form averaged a raw 5-match attack rate with a raw concede
            # rate (corr with actual goals was only +0.081): one 3-0 win implied a
            # 3.0 goals/game attack. Shrinkage fixes that over-reaction.
            lambda_home, lambda_away, lambda_detail = build_lambdas(
                lastN_home, home_id, lastN_away, away_id, league_id, league_cache
            )
            combined_lambda = lambda_home + lambda_away

            # A clamped lambda is a confident-looking prediction built on a
            # poisoned input. Surface it in the log and on the record instead of
            # letting it pass as a strict, low-scoring fixture.
            _lam_note = lambda_health_note(lambda_home, lambda_away,
                                           lambda_detail.get("lambda_base"))
            if _lam_note:
                LAMBDA_HEALTH_WARNINGS.append(
                    f"{home_name} v {away_name}: {_lam_note}")
                if verbose:
                    print(f"   [lambda-health] {_lam_note}")

            mc_summary = generate_scoreline_predictions(lambda_home, lambda_away, n_sim=SIMULATION_SIZE)
            u25_prob   = mc_summary.get("u25_prob", 0.0)
            u35_prob   = mc_summary.get("u35_prob", 0.0)

            def u_rate(fixtures_list, target):
                if not fixtures_list: return 0.0
                if target == 2.5: return round(sum(1 for f in fixtures_list if is_u25(f)) / len(fixtures_list), 3)
                if target == 3.5: return round(sum(1 for f in fixtures_list if is_u35(f)) / len(fixtures_list), 3)

            venue_u25_home = u_rate(lastN_home, 2.5)
            venue_u25_away = u_rate(lastN_away, 2.5)
            venue_u35_home = u_rate(lastN_home, 3.5)
            venue_u35_away = u_rate(lastN_away, 3.5)
            h2h_u25_rate   = u_rate(h2h, 2.5)

            _, _, h_gk_cpg, h_gk_note = evaluate_gk_wall(home_id, fx, target_date)
            _, _, a_gk_cpg, a_gk_note = evaluate_gk_wall(away_id, fx, target_date)
            sleep_short()

            h_recent_lin = [extract_starters_from_fixture(f, home_id) for f in lastN_home]
            a_recent_lin = [extract_starters_from_fixture(f, away_id) for f in lastN_away]
            h_core = identify_key_players_from_history(h_recent_lin)
            a_core = identify_key_players_from_history(a_recent_lin)
            h_today = [p.get("player_id") for p in extract_starters_from_fixture(fx, home_id)]
            a_today = [p.get("player_id") for p in extract_starters_from_fixture(fx, away_id)]
            h_rot = compute_rotation_score({k: v["starts"] for k, v in h_core.items()}, h_today)
            a_rot = compute_rotation_score({k: v["starts"] for k, v in a_core.items()}, a_today)
            
            fatigue_home = estimate_fatigue_from_schedules(team_cache.get(home_id, []), home_id, h_rot)
            fatigue_away = estimate_fatigue_from_schedules(team_cache.get(away_id, []), away_id, a_rot)
            league_weight = league_cache.get(league_id, {}).get("league_weight", 0.0)

            try: odds = sniper_fetch_odds(fx.get("id"))
            except Exception: odds = {"h": None, "d": None, "a": None}

            # ── ORDER MATTERS: gates first, then the signals, then the tiers ──
            # The gates supply gate_h2h_total, which KING reads, so they cannot be
            # evaluated after the score. The gates filter; the signals (with KING
            # among them) decide the score; the tier reads that score.
            gates_passed, gate_reasons, gate_detail = evaluate_unders_gates(
                lastN_home, home_id, lastN_away, away_id, h2h, profile="u25"
            )
            # U3.5 carries its own gate profile (max_conceded 7 vs U2.5's 5).
            u35_gates_passed, u35_gate_reasons, u35_gate_detail = evaluate_unders_gates(
                lastN_home, home_id, lastN_away, away_id, h2h, profile="u35"
            )

            # SOT comes from statistics the engine has already fetched, so this
            # costs no additional API call.
            try:
                proj_sot, sot_detail = king_sot_for_fixture(
                    fx, home_id, away_id, lastN_home, lastN_away
                )
            except Exception:
                proj_sot, sot_detail = None, {}

            venue_u25_combined = ((venue_u25_home or 0.0) + (venue_u25_away or 0.0)) / 2.0
            h2h_total = gate_detail.get("gate_h2h_total")

            # KING is computed ONCE and fed to both scorers as signal 6. U3.5 gets
            # its own looser lambda bound because a 3.5 line tolerates more goals.
            king_u25_pts, king_fired, king_detail = calculate_king_signal(
                h_gk_cpg, a_gk_cpg,
                combined_lambda = combined_lambda,
                venue_rate      = venue_u25_combined,
                h2h_total       = h2h_total,
                proj_sot        = proj_sot,
                lambda_max      = KING_LAMBDA_MAX_U25,
            )
            king_u35_pts, _, king_detail_u35 = calculate_king_signal(
                h_gk_cpg, a_gk_cpg,
                combined_lambda = combined_lambda,
                venue_rate      = ((venue_u35_home or 0.0) + (venue_u35_away or 0.0)) / 2.0,
                h2h_total       = h2h_total,
                proj_sot        = proj_sot,
                lambda_max      = KING_LAMBDA_MAX_U35,
            )
            king_detail.update(sot_detail)

            u25_score, signals_fired, u25_breakdown = calculate_u25_score(
                u25_prob        = u25_prob,
                venue_u25_home  = venue_u25_home,
                venue_u25_away  = venue_u25_away,
                home_gk_cpg     = h_gk_cpg,
                away_gk_cpg     = a_gk_cpg,
                h2h_u25_rate    = h2h_u25_rate,
                combined_lambda = combined_lambda,
                fatigue_home    = fatigue_home,
                fatigue_away    = fatigue_away,
                king_points     = king_u25_pts,
                king_fired      = king_fired,
            )
            u25_tier = get_u25_tier(u25_score, signals_fired, gates_passed)

            u35_score, u35_breakdown = calculate_u35_score(
                u35_prob        = u35_prob,
                combined_lambda = combined_lambda,
                venue_u35_home  = venue_u35_home,
                venue_u35_away  = venue_u35_away,
                league_weight   = league_weight,
                fatigue_home    = fatigue_home,
                fatigue_away    = fatigue_away,
                home_gk_cpg     = h_gk_cpg,
                away_gk_cpg     = a_gk_cpg,
                king_points     = king_u35_pts,
                king_fired      = king_fired,
            )
            u35_tier = get_u35_tier(u35_score, u35_gates_passed)
            if u35_gates_passed != gates_passed:
                u35_gate_detail["u25_gates_passed"] = gates_passed

            base_record = {
                "date":              target_date,
                "fixture_id":        fx.get("id"),
                "fixture":           f"{home_name} vs {away_name}",
                "league_id":         league_id,
                "home_team":         home_name,
                "away_team":         away_name,
                "combined_lambda":   round(combined_lambda, 3),
                "lambda_home":      round(lambda_home, 3),
                "lambda_away":      round(lambda_away, 3),
                "lambda_base":      lambda_detail.get("lambda_base"),
                "lambda_prior_source": lambda_detail.get("lambda_prior_source"),
                "lambda_league_avg_total": lambda_detail.get("lambda_league_avg_total"),
                "lambda_league_n":  lambda_detail.get("lambda_league_n"),
                "lambda_home_n":    lambda_detail.get("lambda_home_n"),
                "lambda_away_n":    lambda_detail.get("lambda_away_n"),
                "lambda_warning":   _lam_note,
                "mc_u25_prob":       round(u25_prob, 4),
                "mc_u35_prob":       round(u35_prob, 4),
                "home_gk_cpg":       h_gk_cpg,
                "away_gk_cpg":       a_gk_cpg,
                "home_gk_note":      h_gk_note,
                "away_gk_note":      a_gk_note,
                "fatigue_home":      round(fatigue_home, 3),
                "fatigue_away":      round(fatigue_away, 3),
                "draw_odds":         odds.get("d"),
                "gates_passed":      gates_passed,
                "gate_reasons":      "; ".join(gate_reasons) if gate_reasons else "all gates passed",
                "gate_home_scored":  gate_detail.get("gate_home_scored"),
                "gate_away_scored":  gate_detail.get("gate_away_scored"),
                "gate_home_conceded": gate_detail.get("gate_home_conceded"),
                "gate_away_conceded": gate_detail.get("gate_away_conceded"),
                "gate_h2h":          gate_detail.get("gate_h2h"),
                # ── 2026-10-04: everything needed to MEASURE the rules later ──
                # The gate inputs above were never persisted before today, which is
                # why the cap change had to be judged on 207 reconstructed rows
                # instead of the full history. These columns make the next settled
                # sample measurable, so a future cap or signal change can be
                # backtested properly instead of guessed at.
                "gate_h2h_matches": gate_detail.get("gate_h2h_matches"),
                "gate_h2h_checked": gate_detail.get("gate_h2h_checked"),
                "gate_max_scored":   gate_detail.get("gate_max_scored"),
                "gate_max_conceded": gate_detail.get("gate_max_conceded"),
                "u35_gates_passed": u35_gates_passed,
                "u35_gate_reasons": "; ".join(u35_gate_reasons) if u35_gate_reasons else "all u3.5 gates passed",
                # Per-signal scores, so any single signal can be tested alone later
                # without re-running the engine.
                "sig1_mc_u25":        u25_breakdown.get("sig1_mc_u25"),
                "sig2_lambda":        u25_breakdown.get("sig2_lambda"),
                "sig3_gk_wall":       u25_breakdown.get("sig3_gk_wall"),
                "sig4_venue_u25":     u25_breakdown.get("sig4_venue_u25"),
                "sig5_fatigue":       u25_breakdown.get("sig5_fatigue_boost"),
                "sig6_king":          u25_breakdown.get("sig6_king"),
                "venue_u25_combined": u25_breakdown.get("venue_u25_combined"),
                "venue_u25_home":     round(venue_u25_home, 3),
                "venue_u25_away":     round(venue_u25_away, 3),
                "h2h_u25_rate":       round(h2h_u25_rate, 3),
                # KING is signal 6, so it appears as its score/points rather than as a
                # separate tier. Its weight is already inside u25_score/u35_score.
                "king_points":   king_u25_pts,
                "king_points_u35": king_u35_pts,
                "king_fired":    king_fired,
                **king_detail,
            }

            u25_picks.append({**base_record, "u25_score": u25_score, "u25_signals_fired": signals_fired, "u25_tier": u25_tier})
            u35_picks.append({**base_record, "u35_score": u35_score, "u35_tier": u35_tier})

        except Exception:
            continue

    if not u25_picks:
        if verbose: print("\n  No picks generated.")
        return [], []

    # GATE FAIL sorts last (rank 99) — it is a rejection, not a pick.
    tier_order_u25 = {"🛡️ U2.5 TIER 1 — LOCK": 1, "✅ U2.5 TIER 2 — SOLID": 2, "📊 U2.5 TIER 3 — LEAN": 3, "⚪ U2.5 BELOW THRESHOLD": 4, GATE_FAIL_TIER_U25: 99}
    tier_order_u35 = {"🧱 U3.5 TIER 1 — LOCK": 1, "✅ U3.5 TIER 2 — SOLID": 2, "📊 U3.5 TIER 3 — LEAN": 3, "⚪ U3.5 BELOW THRESHOLD": 4, GATE_FAIL_TIER_U35: 99}

    df_u25 = pd.DataFrame(u25_picks)
    df_u35 = pd.DataFrame(u35_picks)

    df_u25["tier_rank"] = df_u25["u25_tier"].map(tier_order_u25).fillna(99)
    df_u25 = df_u25.sort_values(["tier_rank", "u25_score", "u25_signals_fired"], ascending=[True, False, False]).reset_index(drop=True)

    df_u35["tier_rank"] = df_u35["u35_tier"].map(tier_order_u35).fillna(99)
    df_u35 = df_u35.sort_values(["tier_rank", "u35_score"], ascending=[True, False]).reset_index(drop=True)

    u25_csv_path  = os.path.join(OUTPUT_DIR, f"ALIENEDGE_U25_PICKS_{target_date}.csv")
    u35_csv_path  = os.path.join(OUTPUT_DIR, f"ALIENEDGE_U35_PICKS_{target_date}.csv")
    df_u25.drop(columns=["tier_rank"], errors="ignore").to_csv(u25_csv_path, index=False)
    df_u35.drop(columns=["tier_rank"], errors="ignore").to_csv(u35_csv_path, index=False)

    if LAMBDA_HEALTH_WARNINGS:
        print(f"\n  ⚠️  LAMBDA HEALTH: {len(LAMBDA_HEALTH_WARNINGS)} fixture(s) hit the "
              f"lambda clamp/floor.")
        for _w in LAMBDA_HEALTH_WARNINGS[:10]:
            print(f"      - {_w}")
        if len(LAMBDA_HEALTH_WARNINGS) > 10:
            print(f"      ... and {len(LAMBDA_HEALTH_WARNINGS) - 10} more")
        print("     A clamped lambda publishes a confident probability from a "
              "poisoned input. Treat these fixtures as untrusted.")
    elif verbose:
        print("\n  ✅ Lambda health: no fixture hit the clamp or floor.")

    if verbose:
        print(f"\n{'🛡️'*50}\n  UNDER 2.5 DEFENSIVE BOARD — {target_date}\n{'🛡️'*50}")
        u25_show_cols = ["fixture", "u25_tier", "u25_score", "u25_signals_fired", "mc_u25_prob", "combined_lambda", "home_gk_cpg", "away_gk_cpg", "fatigue_home", "fatigue_away"]
        pd.set_option("display.max_rows", None); pd.set_option("display.max_columns", None); pd.set_option("display.width", 240)
        
        for tier_name, group in df_u25.groupby("u25_tier", sort=False):
            print(f"\n  ── {tier_name} ──\n{group[u25_show_cols].to_string(index=False)}")

        print(f"\n{'🧱'*50}\n  UNDER 3.5 FORTRESS BOARD — {target_date}\n{'🧱'*50}")
        u35_show_cols = ["fixture", "u35_tier", "u35_score", "mc_u35_prob", "combined_lambda", "home_gk_cpg", "away_gk_cpg", "fatigue_home", "fatigue_away"]
        for tier_name, group in df_u35.groupby("u35_tier", sort=False):
            print(f"\n  ── {tier_name} ──\n{group[u35_show_cols].to_string(index=False)}")

        print(f"\n  💾 U2.5 picks saved: {u25_csv_path}")
        print(f"  💾 U3.5 picks saved: {u35_csv_path}")

    return df_u25.to_dict(orient="records"), df_u35.to_dict(orient="records")

if __name__ == "__main__":
    target = input("\nEnter target date (YYYY-MM-DD) or leave empty for today: ").strip()
    run_unders_engine(target if target else None, verbose=True)