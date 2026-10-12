"""
AlienEdge Win Forecast v2 — EXPERIMENTAL, runs alongside win_forecast.py
=========================================================================
This is a SEPARATE engine. It does not replace, call, or modify
win_forecast.py, main.py, or output_store.py in any way. Run it on its own
(`python Engine/win_forecast_v2.py`) and compare its CSV output against the
production engine's — that comparison is the whole point of this file.

HONESTY LEDGER — what is real here and what is NOT, read this before trusting
any number this file produces:

  REAL / IMPLEMENTED:
    - Opponent-adjusted attack/defence strength (iterative Poisson fit)
    - Home/away split strength, shrunk toward overall strength
    - Recency-weighted history (exponential decay, not flat last-5)
    - Real per-league goals prior (reused pattern from draw_engine.py)
    - Dixon-Coles low-score correlation correction
    - Full 0-10 score matrix with tail-mass accounting (no silent goal loss)
    - Bookmaker overround removal / market-implied probability
    - Fair odds, edge, EV arithmetic
    - Evidence-based model_confidence (sample size, data completeness)

  NOT YET REAL — explicitly stubbed, flagged in both the code AND every
  output row, per the spec's own "no data-mining / don't fake success"
  rules (do not quietly trust these until they are actually built):
    - calibration_version = "none-identity-v0": calibrated_probability is
      currently IDENTICAL to raw_probability. No isotonic/Platt calibration
      has been fit, because that requires a real settled-fixture dataset
      with chronological train/calibrate/test splits, which does not exist
      yet for Win specifically (unlike Draw, which has one — see
      draw_engine.py's backtest comments).
    - RHO_DEFAULT below is a LITERATURE value, not fit on your data.
    - LOCK1/LOCK2 thresholds (CONFIDENCE_MIN, EDGE_MIN_PP, EV_MIN) are
      reasonable STARTING DEFAULTS, not validated thresholds. Do not treat
      "VALUE CONFIRMED" as a proven signal until these are backtested.
    - No ensemble, no walk-forward backtester, no ROI audit. Those need the
      real settled-outcome history this run is one step toward building.

  SCOPE LIMIT ON THE OPPONENT NETWORK: to stay API-cost-neutral (no new
  SportMonks calls beyond what win_forecast.py already makes), the strength
  fit only uses the opponent network found WITHIN each team's own fetched
  history window — not a full league-wide connected graph. This is a
  reasonable approximation, not the full hierarchical model Section 6 of
  the spec describes. Flagged here so it is a documented limitation, not a
  silent one.

  ADDITIONAL LIMITATIONS (integration review, 2026-10-12 — recorded when
  this engine was wired into the pipeline alongside the production engine):
    - No global home-advantage parameter: the entire home boost rides on
      the per-team venue multipliers, which shrink toward 1.0 on thin venue
      samples, so home edge can collapse toward neutral for low-sample teams.
    - The strength fit uses ONE league prior averaged across every league on
      the day's slate, so attack/defence ratings are not strictly comparable
      ACROSS leagues. (The per-league prior IS used for each lambda.)
    - Venue multipliers are not opponent-adjusted: a team that happened to
      face weak opposition at home gets a home-attack boost.
    - Market odds are the MEDIAN pre-match price across bookmakers
      (deterministic), not a single sharp book — edge/EV are measured
      against a consensus price. market_books in each row reports how many
      bookmakers backed each side.
    - Team history is capped at per_page=40 matches; older matches inside
      the 365-day window are silently unseen (mitigated by the ~115-day
      recency half-life).
    - Dixon-Coles tau is applied without renormalising the full matrix, so
      score_matrix_tail_mass conflates 0-10 truncation with tau distortion
      (negligible at RHO_DEFAULT = -0.08, but reported per row regardless).
"""

import os
import sys
import json
import math
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────────────────────────────────
# VERSIONING (spec Section 41) — every prediction carries these so a result
# can always be traced back to the exact model/calibration/strength logic
# that produced it.
# ──────────────────────────────────────────────────────────────────────────
MODEL_VERSION = "alienedge-win-v2.0-dixoncoles-experimental"
CALIBRATION_VERSION = "none-identity-v0"          # see HONESTY LEDGER above
STRENGTH_MODEL_VERSION = "iterative-poisson-v1"   # see HONESTY LEDGER above

# ──────────────────────────────────────────────────────────────────────────
# PATHS / CONFIG
# ──────────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

API_TOKEN = os.getenv("SPORTMONKS_API_KEY")
BASE_URL = "https://api.sportmonks.com/v3/football"

MARKET_1X2 = 1
REQUEST_DELAY = 0.2
MAX_RETRIES = 5
TEAM_LOOKBACK_DAYS = 365

# Recency decay — different components may reasonably decay at different
# speeds (spec Section 7). DECAY_STRENGTH drives the strength fit and the
# home/away split (slow, season-length signal). DECAY_FORM is reserved for
# a future separate short-term form layer and is NOT yet used by the model
# — listed here so the second decay speed is a documented, not hidden, gap.
DECAY_STRENGTH = 0.006   # ~115-day half-life
DECAY_FORM = 0.025       # ~28-day half-life (RESERVED, not yet wired in)

# Shrinkage (spec Sections 5, 8, 13)
PRIOR_STRENGTH_MATCHES = 8.0     # pseudo-matches pulling a thin sample to 1.0
VENUE_PRIOR_STRENGTH = 5.0       # pseudo-matches pulling home/away split to overall

# Dixon-Coles low-score correlation (spec Section 15). This is the standard
# published tau correction for (0,0),(0,1),(1,0),(1,1). RHO_DEFAULT is a
# commonly-cited literature value (Dixon & Coles 1997 reported roughly
# -0.1 to -0.2 depending on league/era) — NOT fit on AlienEdge's own data.
RHO_DEFAULT = -0.08

SCORE_MATRIX_MAX_GOALS = 10   # extended from a 6-goal cap (spec Section 16)

# Two-lock thresholds (spec Sections 22, 37) — UNVALIDATED STARTING DEFAULTS.
CONFIDENCE_MIN_FOR_LOCK1 = "MEDIUM"
EDGE_MIN_PP_FOR_LOCK2 = 5.0     # percentage points
EV_MIN_FOR_LOCK2 = 0.0

MIN_SAMPLE_FOR_HIGH_CONFIDENCE = 8   # effective (recency-weighted) matches, each side
MIN_SAMPLE_FOR_ANY_CONFIDENCE = 3

LAMBDA_MIN = 0.05
LAMBDA_MAX = 6.00


# ──────────────────────────────────────────────────────────────────────────
# HTTP / PAGINATION (same robustness pattern as the fixed win_forecast.py —
# explicit provider-error surfacing instead of a swallowing except/pass)
# ──────────────────────────────────────────────────────────────────────────
class ForecastDataError(RuntimeError):
    """Raised when the provider response cannot produce a valid forecast."""


def _response_json(response, path):
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
    all_fx = []
    page = 1
    while True:
        resp = GET(f"/fixtures/date/{date_str}",
                   params={"include": "participants;scores", "per_page": 50, "page": page})
        data = resp.get("data", [])
        if not data:
            break
        all_fx.extend(data)
        page += 1
        sleep_short()
    return all_fx


# ──────────────────────────────────────────────────────────────────────────
# SCORE EXTRACTION — penalty/aggregate filtered (the bug this session found
# missing in win_forecast.py's original extract_goals_v3)
# ──────────────────────────────────────────────────────────────────────────
def extract_goals(scores):
    home, away = None, None
    for entry in (scores or []):
        if not isinstance(entry, dict):
            continue
        s_obj = entry.get("score") or entry
        desc = str(entry.get("description", s_obj.get("description", ""))).upper()
        if any(w in desc for w in ["PENALTY", "EXTRA", "AGG"]):
            continue
        p = s_obj.get("participant") or entry.get("participant")
        g = s_obj.get("goals") if isinstance(s_obj, dict) else entry.get("goals")
        if g is not None:
            val = int(g)
            if p == "home":
                home = val if home is None else max(home, val)
            elif p == "away":
                away = val if away is None else max(away, val)
    return home, away


def is_team_home(fx, team_id):
    for p in fx.get("participants", []):
        pid = p.get("id")
        if pid is None:
            continue
        try:
            if int(pid) == int(team_id):
                loc = (p.get("meta") or {}).get("location")
                return loc == "home"
        except (TypeError, ValueError):
            continue
    return False


def match_date(fx):
    raw = fx.get("starting_at")
    if not raw:
        return None
    try:
        ss = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
        dt = datetime.fromisoformat(ss)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def recency_weight(fx_date, target_dt, decay):
    if fx_date is None:
        return 0.0
    age_days = max(0, (target_dt - fx_date).days)
    return math.exp(-decay * age_days)


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


# ──────────────────────────────────────────────────────────────────────────
# LEAGUE GOALS PRIOR — same direct-measurement pattern as draw_engine.py's
# compute_league_avg_goals(), own cache file.
#
# 2026-10-12 FIX — the cache is keyed by (league_id, target_date), NOT by
# league alone. The value is anchored to target_dt (fixtures strictly BEFORE
# the target date), so it is immutable per (league, date) and safe to cache
# forever — which is also what makes it correct for backtests: a historical
# run can never be handed a prior computed from matches that happened after
# its own target date. The old league-only key with a 7-day TTL did exactly
# that whenever a backtest date ran close behind a live run.
# ──────────────────────────────────────────────────────────────────────────
def compute_league_avg_goals(league_id, target_dt, days_lookback=180):
    cache_file = os.path.join(DATA_DIR, "win_v2_league_avg_goals_cache.json")
    cache_data = {}
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                cache_data = json.load(f)
        except Exception:
            pass

    target_date_str = target_dt.date().isoformat()
    cache_key = f"{league_id}__{target_date_str}"
    if cache_key in cache_data:
        try:
            return float(cache_data[cache_key]["avg_goals_per_team"])
        except (KeyError, TypeError, ValueError):
            pass

    end_dt = target_dt.date() - timedelta(days=1)
    start_dt = end_dt - timedelta(days=min(days_lookback, 180))

    all_fx, seen, page = [], set(), 1
    while True:
        data = GET(f"/fixtures/between/{start_dt}/{end_dt}/{league_id}",
                   params={"include": "scores", "per_page": 50, "page": page})
        fx = data.get("data", [])
        if not fx:
            break
        added = False
        for f in fx:
            fid = f.get("id")
            if fid not in seen:
                seen.add(fid); all_fx.append(f); added = True
        if not added:
            break
        page += 1
        sleep_short()

    total_matches, total_goals = 0, 0
    for fx in all_fx:
        hg, ag = extract_goals(fx.get("scores", []))
        if hg is None or ag is None:
            continue
        total_matches += 1
        total_goals += (hg + ag)

    avg_goals_per_team = round((total_goals / total_matches) / 2.0, 4) if total_matches > 0 else 1.35

    cache_data[cache_key] = {
        "avg_goals_per_team": avg_goals_per_team,
        "sample_matches": total_matches,
        "target_date": target_date_str,
    }
    try:
        with open(cache_file, "w") as f:
            json.dump(cache_data, f, indent=4)
    except Exception:
        pass
    return avg_goals_per_team


def fetch_team_history(team_id, target_dt):
    """Single fetch per team, reused for the strength fit and the venue
    split — same caching discipline as every sibling engine."""
    end_dt = (target_dt.date() - timedelta(days=1)).isoformat()
    start_dt = (target_dt.date() - timedelta(days=TEAM_LOOKBACK_DAYS)).isoformat()
    resp = GET(f"/fixtures/between/{start_dt}/{end_dt}/{team_id}",
              params={"include": "scores;participants", "filters": "fixtureStates:5",
                      "order": "desc", "per_page": 40})
    return resp.get("data", [])


def sniper_fetch_odds(fixture_id):
    """Pre-match 1X2 odds for one fixture.

    2026-10-12 FIX — deterministic bookmaker handling. The endpoint returns
    every bookmaker's price; the previous last-write-wins loop silently
    measured edge against whichever bookmaker happened to come last in the
    response (and could even mix books across home/draw/away in one row).
    Here every bookmaker's price is collected per outcome and the MEDIAN is
    used — deterministic, robust to one outlier book, and the same rule for
    all three outcomes. res["n_books"] reports how many bookmakers backed
    each side (0 when any side has no price).
    """
    data = GET(f"/odds/pre-match/fixtures/{fixture_id}")
    odds_list = data.get("data", [])
    prices = {"home": [], "draw": [], "away": []}
    for o in odds_list:
        if o.get("market_id") != MARKET_1X2:
            continue
        lbl = str(o.get("label", "")).lower()
        val = o.get("value")
        if val is None:
            continue
        try:
            val = float(val)
        except (TypeError, ValueError):
            continue
        if val <= 1.0:
            continue
        if "1" in lbl or "home" in lbl:
            prices["home"].append(val)
        elif "x" in lbl or "draw" in lbl:
            prices["draw"].append(val)
        elif "2" in lbl or "away" in lbl:
            prices["away"].append(val)

    def _median(vals):
        if not vals:
            return None
        s = sorted(vals)
        n = len(s)
        mid = n // 2
        return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0

    res = {k: _median(v) for k, v in prices.items()}
    res["n_books"] = (min(len(v) for v in prices.values())
                      if all(prices.values()) else 0)
    return res


# ══════════════════════════════════════════════════════════════════════════
# PHASE 3/4/5: OPPONENT-ADJUSTED ITERATIVE ATTACK/DEFENCE STRENGTH
# ══════════════════════════════════════════════════════════════════════════
def fit_team_strengths(team_histories, league_prior, target_dt,
                        decay=DECAY_STRENGTH, max_iter=20, tol=1e-4):
    """
    Lightweight iterative Poisson attack/defence fit — the classic
    alternating-scaling approach used in simplified public implementations
    of the Dixon-Coles model (avoids a full scipy MLE optimization while
    keeping the same multiplicative structure the spec's Section 11 asks
    for: expected_goals(i vs j) = league_prior * attack_i * defence_j).

    SCOPE LIMIT: the opponent network here is only the teams that appear
    as OPPONENTS inside each fetched team's own history window (see the
    HONESTY LEDGER at the top of this file) — not a full league-wide
    connected graph, to avoid any new SportMonks calls.

    Recency-weighted: each historical match contributes
    exp(-decay * age_days) instead of being counted flatly, so a stale
    result barely moves a team's rating (spec Section 7).

    Returns {team_id: {"attack": float, "defence": float, "n_eff": float}}
    where n_eff is the recency-weighted effective number of matches.
    """
    team_matches = defaultdict(list)
    all_team_ids = set(int(t) for t in team_histories.keys())

    for tid, history in team_histories.items():
        tid = int(tid)
        for fx in history:
            hg, ag = extract_goals(fx.get("scores", []))
            if hg is None or ag is None:
                continue
            parts = fx.get("participants", [])
            if len(parts) < 2:
                continue
            opp_id = None
            for p in parts:
                pid = p.get("id")
                if pid is not None and int(pid) != tid:
                    opp_id = int(pid)
            if opp_id is None:
                continue
            w = recency_weight(match_date(fx), target_dt, decay)
            if w <= 0:
                continue
            is_home = is_team_home(fx, tid)
            goals_for = hg if is_home else ag
            goals_against = ag if is_home else hg
            team_matches[tid].append({
                "opp": opp_id, "gf": goals_for, "ga": goals_against, "w": w,
            })
            all_team_ids.add(opp_id)

    attack = {tid: 1.0 for tid in all_team_ids}
    defence = {tid: 1.0 for tid in all_team_ids}

    for _ in range(max_iter):
        max_delta = 0.0
        new_attack = dict(attack)
        new_defence = dict(defence)

        for tid, matches in team_matches.items():
            if not matches:
                continue
            num_a = den_a = num_d = den_d = w_sum = 0.0
            for m in matches:
                opp_def = defence.get(m["opp"], 1.0)
                opp_att = attack.get(m["opp"], 1.0)
                w = m["w"]
                num_a += w * m["gf"]
                den_a += w * opp_def * league_prior
                num_d += w * m["ga"]
                den_d += w * opp_att * league_prior
                w_sum += w

            if w_sum <= 0:
                continue

            raw_att = (num_a / den_a) if den_a > 0 else 1.0
            raw_def = (num_d / den_d) if den_d > 0 else 1.0
            # Empirical-Bayes shrink toward 1.0 using the effective
            # (recency-weighted) sample size — a thin sample stays near
            # league-average instead of swinging on 1-2 results.
            shrink_att = (raw_att * w_sum + 1.0 * PRIOR_STRENGTH_MATCHES) / (w_sum + PRIOR_STRENGTH_MATCHES)
            shrink_def = (raw_def * w_sum + 1.0 * PRIOR_STRENGTH_MATCHES) / (w_sum + PRIOR_STRENGTH_MATCHES)

            new_attack[tid] = clamp(shrink_att, 0.15, 4.0)
            new_defence[tid] = clamp(shrink_def, 0.15, 4.0)

            max_delta = max(max_delta,
                            abs(new_attack[tid] - attack.get(tid, 1.0)),
                            abs(new_defence[tid] - defence.get(tid, 1.0)))

        # Re-normalize so the league-wide average stays exactly at 1.0 each
        # iteration (prevents the whole system drifting up or down together).
        if new_attack:
            mean_a = sum(new_attack.values()) / len(new_attack)
            mean_d = sum(new_defence.values()) / len(new_defence)
            if mean_a > 0:
                new_attack = {k: v / mean_a for k, v in new_attack.items()}
            if mean_d > 0:
                new_defence = {k: v / mean_d for k, v in new_defence.items()}

        attack, defence = new_attack, new_defence
        if max_delta < tol:
            break

    result = {}
    for tid in team_histories.keys():
        tid = int(tid)
        n_eff = sum(m["w"] for m in team_matches.get(tid, []))
        result[tid] = {
            "attack": round(attack.get(tid, 1.0), 4),
            "defence": round(defence.get(tid, 1.0), 4),
            "n_eff": round(n_eff, 2),
        }
    return result


def fit_home_away_split(history, team_id, target_dt, decay=DECAY_STRENGTH):
    """
    Venue-specific attack/defence multiplier RELATIVE to the team's own
    overall rate, shrunk toward 1.0 (i.e. toward "no venue effect") by
    effective sample size — implements the hierarchy spec Section 8 asks
    for: venue_strength -> shrunk toward -> overall_strength.

    Returns (home_att_mult, home_def_mult, away_att_mult, away_def_mult,
             home_n_eff, away_n_eff)
    """
    home_gf = home_ga = home_w = 0.0
    away_gf = away_ga = away_w = 0.0

    for fx in history:
        hg, ag = extract_goals(fx.get("scores", []))
        if hg is None or ag is None:
            continue
        w = recency_weight(match_date(fx), target_dt, decay)
        if w <= 0:
            continue
        if is_team_home(fx, team_id):
            home_gf += w * hg; home_ga += w * ag; home_w += w
        else:
            away_gf += w * ag; away_ga += w * hg; away_w += w

    total_w = home_w + away_w
    baseline_gf = ((home_gf + away_gf) / total_w) if total_w > 0 else 0.0
    baseline_ga = ((home_ga + away_ga) / total_w) if total_w > 0 else 0.0

    def venue_mult(gf, ga, w):
        # No data at this venue, or no usable baseline -> neutral (no venue
        # effect) rather than inventing one.
        if w <= 0 or baseline_gf <= 0 or baseline_ga <= 0:
            return 1.0, 1.0
        att_mult = (gf / w) / baseline_gf
        def_mult = (ga / w) / baseline_ga
        # shrink toward 1.0 (no venue effect) by effective sample size
        att_mult = (att_mult * w + 1.0 * VENUE_PRIOR_STRENGTH) / (w + VENUE_PRIOR_STRENGTH)
        def_mult = (def_mult * w + 1.0 * VENUE_PRIOR_STRENGTH) / (w + VENUE_PRIOR_STRENGTH)
        return clamp(att_mult, 0.3, 3.0), clamp(def_mult, 0.3, 3.0)

    h_att, h_def = venue_mult(home_gf, home_ga, home_w)
    a_att, a_def = venue_mult(away_gf, away_ga, away_w)

    return h_att, h_def, a_att, a_def, round(home_w, 2), round(away_w, 2)


# ══════════════════════════════════════════════════════════════════════════
# PHASE 9/15: INDEPENDENT POISSON + DIXON-COLES CORRECTION
# ══════════════════════════════════════════════════════════════════════════
def poisson_pmf(k, lam):
    if lam < 0:
        return 0.0
    try:
        return math.exp(-lam) * (lam ** k) / math.factorial(k)
    except Exception:
        return 0.0


def dixon_coles_tau(x, y, lam_home, lam_away, rho):
    """Standard Dixon & Coles (1997) low-score correlation correction,
    applied only to the four cells it's defined for."""
    if x == 0 and y == 0:
        return 1.0 - (lam_home * lam_away * rho)
    elif x == 0 and y == 1:
        return 1.0 + (lam_home * rho)
    elif x == 1 and y == 0:
        return 1.0 + (lam_away * rho)
    elif x == 1 and y == 1:
        return 1.0 - rho
    return 1.0


def build_score_matrix(lambda_home, lambda_away, rho=RHO_DEFAULT,
                       max_goals=SCORE_MATRIX_MAX_GOALS):
    """
    Full score matrix with Dixon-Coles correction, extended to
    SCORE_MATRIX_MAX_GOALS (not silently truncated at 6 — spec Section 16).
    Residual tail mass beyond the matrix is distributed proportionally into
    the outcome probabilities rather than discarded, so P(home)+P(draw)+
    P(away) always sums to exactly 1.0.
    """
    matrix = np.zeros((max_goals + 1, max_goals + 1))
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = poisson_pmf(h, lambda_home) * poisson_pmf(a, lambda_away)
            if h <= 1 and a <= 1:
                p *= dixon_coles_tau(h, a, lambda_home, lambda_away, rho)
            matrix[h, a] = max(0.0, p)

    captured_mass = matrix.sum()
    tail_mass = max(0.0, 1.0 - captured_mass)

    # rows = home goals, cols = away goals. Home win = home goals > away
    # goals = strictly LOWER triangle (row index > col index).
    p_home = float(np.sum(np.tril(matrix, -1)))
    p_draw = float(np.sum(np.diag(matrix)))
    p_away = float(np.sum(np.triu(matrix, 1)))

    total = p_home + p_draw + p_away
    if total > 0 and tail_mass > 0:
        p_home += tail_mass * (p_home / total)
        p_draw += tail_mass * (p_draw / total)
        p_away += tail_mass * (p_away / total)

    norm = p_home + p_draw + p_away
    if norm > 0:
        p_home, p_draw, p_away = p_home / norm, p_draw / norm, p_away / norm

    return matrix, p_home, p_draw, p_away, round(tail_mass, 5)


# ══════════════════════════════════════════════════════════════════════════
# PHASE 19: MARKET NORMALIZATION / FAIR ODDS / EDGE / EV
# ══════════════════════════════════════════════════════════════════════════
def normalize_market_odds(h_odd, d_odd, a_odd):
    if not all([h_odd, d_odd, a_odd]) or min(h_odd, d_odd, a_odd) <= 1.0:
        return None, None, None, None
    raw_h, raw_d, raw_a = 1.0 / h_odd, 1.0 / d_odd, 1.0 / a_odd
    overround = raw_h + raw_d + raw_a
    if overround <= 0:
        return None, None, None, None
    return raw_h / overround, raw_d / overround, raw_a / overround, round((overround - 1.0) * 100, 2)


def compute_value(model_prob, market_prob, bookmaker_odds):
    """Returns (fair_odds, edge_pp, ev). edge in percentage points, EV as a
    fraction (0.05 = +5%)."""
    if model_prob is None or model_prob <= 0:
        return None, None, None
    fair_odds = round(1.0 / model_prob, 3)
    edge_pp = round((model_prob - market_prob) * 100, 2) if market_prob is not None else None
    ev = round((model_prob * bookmaker_odds) - 1.0, 4) if bookmaker_odds else None
    return fair_odds, edge_pp, ev


# ══════════════════════════════════════════════════════════════════════════
# PHASE 23/35: EVIDENCE-BASED CONFIDENCE + DATA QUALITY
# ══════════════════════════════════════════════════════════════════════════
def compute_model_confidence(home_n_eff, away_n_eff, odds_available):
    min_n = min(home_n_eff, away_n_eff)
    if min_n < MIN_SAMPLE_FOR_ANY_CONFIDENCE:
        return "LOW", "insufficient recent-match sample for at least one side"
    if min_n < MIN_SAMPLE_FOR_HIGH_CONFIDENCE:
        return "MEDIUM", "moderate sample size"
    if not odds_available:
        return "MEDIUM", "strong sample but no market odds to cross-check"
    return "HIGH", "sufficient sample on both sides, odds available"


def compute_verdict(confidence, edge_pp, ev):
    conf_rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    lock1 = conf_rank.get(confidence, 0) >= conf_rank.get(CONFIDENCE_MIN_FOR_LOCK1, 1)
    lock2 = (edge_pp is not None and edge_pp >= EDGE_MIN_PP_FOR_LOCK2
             and ev is not None and ev >= EV_MIN_FOR_LOCK2)

    if lock1 and lock2:
        return "VALUE CONFIRMED", True, True
    if lock1 and not lock2:
        return "STRONG PREDICTION — NO VALUE", True, False
    if not lock1 and lock2:
        return "DO NOT AUTO-BET — LOW CONFIDENCE", False, True
    return "NO BET", False, False


# ══════════════════════════════════════════════════════════════════════════
# MAIN ENGINE
# ══════════════════════════════════════════════════════════════════════════
def run_win_forecast_v2_engine(target_date=None):
    if not API_TOKEN:
        raise ForecastDataError("CRITICAL: SPORTMONKS_API_KEY is missing")

    if not target_date:
        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    target_dt = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    print(f"[v2] Win Forecast v2 (EXPERIMENTAL) start: {target_date}")
    print(f"[v2] model_version={MODEL_VERSION} calibration={CALIBRATION_VERSION}")

    fixtures = fetch_all_fixtures_for_date(target_date)
    if not fixtures:
        raise ForecastDataError(f"No fixtures found for {target_date}")

    team_ids = set()
    for fx in fixtures:
        for p in fx.get("participants", []):
            if p.get("id"):
                team_ids.add(int(p["id"]))

    print(f"[v2] Fetching history for {len(team_ids)} teams...")
    team_histories = {}
    for tid in team_ids:
        team_histories[tid] = fetch_team_history(tid, target_dt)
        sleep_short()

    league_ids = {fx.get("league_id") for fx in fixtures if fx.get("league_id")}
    league_prior_cache = {}
    for lid in league_ids:
        try:
            league_prior_cache[lid] = compute_league_avg_goals(lid, target_dt)
        except Exception:
            league_prior_cache[lid] = 1.35
        sleep_short()

    # ONE strength fit covering every team playing today, run once — the
    # compute-efficiency rule from spec Section 38.
    overall_league_prior = (sum(league_prior_cache.values()) / len(league_prior_cache)
                            if league_prior_cache else 1.35)
    print(f"[v2] Fitting opponent-adjusted strengths for {len(team_histories)} teams "
          f"(league prior ~{overall_league_prior:.2f} goals/team)...")
    strengths = fit_team_strengths(team_histories, overall_league_prior, target_dt)

    rows = []
    errors = []

    for fx in fixtures:
        fid = fx.get("id", "<unknown>")
        try:
            parts = fx.get("participants", [])
            if len(parts) < 2:
                continue
            h_p = next(p for p in parts if (p.get("meta") or {}).get("location") == "home")
            a_p = next(p for p in parts if (p.get("meta") or {}).get("location") == "away")
            hid, aid = int(h_p["id"]), int(a_p["id"])
            league_id = fx.get("league_id")
            league_prior = league_prior_cache.get(league_id, overall_league_prior)

            h_str = strengths.get(hid, {"attack": 1.0, "defence": 1.0, "n_eff": 0.0})
            a_str = strengths.get(aid, {"attack": 1.0, "defence": 1.0, "n_eff": 0.0})

            h_hatt, h_hdef, _h_aatt, _h_adef, _h_home_n, _h_away_n = fit_home_away_split(
                team_histories.get(hid, []), hid, target_dt)
            _a_hatt, _a_hdef, a_aatt, a_adef, _a_home_n, _a_away_n = fit_home_away_split(
                team_histories.get(aid, []), aid, target_dt)

            # log-link multiplicative structure (spec Section 11):
            #   lambda_home = league_prior * home team's attack at HOME *
            #                  away team's defence AWAY
            #   lambda_away = league_prior * away team's attack AWAY *
            #                  home team's defence at HOME
            lambda_home = league_prior * h_str["attack"] * h_hatt * a_str["defence"] * a_adef
            lambda_away = league_prior * a_str["attack"] * a_aatt * h_str["defence"] * h_hdef
            lambda_home = clamp(lambda_home, LAMBDA_MIN, LAMBDA_MAX)
            lambda_away = clamp(lambda_away, LAMBDA_MIN, LAMBDA_MAX)

            _matrix, p_home, p_draw, p_away, tail_mass = build_score_matrix(
                lambda_home, lambda_away, RHO_DEFAULT)

            # CALIBRATION: identity for v0 — see HONESTY LEDGER at the top.
            cal_home, cal_draw, cal_away = p_home, p_draw, p_away

            odds = sniper_fetch_odds(fid)
            mkt_home, mkt_draw, mkt_away, overround_pct = normalize_market_odds(
                odds.get("home"), odds.get("draw"), odds.get("away"))

            fair_h, edge_h, ev_h = compute_value(cal_home, mkt_home, odds.get("home"))
            fair_d, edge_d, ev_d = compute_value(cal_draw, mkt_draw, odds.get("draw"))
            fair_a, edge_a, ev_a = compute_value(cal_away, mkt_away, odds.get("away"))

            home_n_eff = h_str["n_eff"]
            away_n_eff = a_str["n_eff"]
            odds_available = mkt_home is not None
            confidence, confidence_reason = compute_model_confidence(
                home_n_eff, away_n_eff, odds_available)

            # One concrete verdict per fixture, on the outcome the model
            # actually favours (highest calibrated probability).
            outcomes = [("home", cal_home, edge_h, ev_h),
                       ("draw", cal_draw, edge_d, ev_d),
                       ("away", cal_away, edge_a, ev_a)]
            fav_side, fav_prob, fav_edge, fav_ev = max(outcomes, key=lambda o: o[1])
            verdict, lock1, lock2 = compute_verdict(confidence, fav_edge, fav_ev)

            rows.append({
                "fixture_id": fid,
                "fixture": f"{h_p['name']} vs {a_p['name']}",
                "league_id": league_id,
                "target_date": target_date,
                "home_team": h_p["name"],
                "away_team": a_p["name"],

                "home_attack_strength": h_str["attack"],
                "home_defence_strength": h_str["defence"],
                "away_attack_strength": a_str["attack"],
                "away_defence_strength": a_str["defence"],
                "home_venue_attack_mult": round(h_hatt, 3),
                "home_venue_defence_mult": round(h_hdef, 3),
                "away_venue_attack_mult": round(a_aatt, 3),
                "away_venue_defence_mult": round(a_adef, 3),
                "home_n_eff": home_n_eff,
                "away_n_eff": away_n_eff,

                "lambda_home": round(lambda_home, 3),
                "lambda_away": round(lambda_away, 3),
                "league_goals_prior": round(league_prior, 3),
                "dixon_coles_rho": RHO_DEFAULT,
                "score_matrix_tail_mass": tail_mass,

                "raw_home_probability": round(p_home, 4),
                "raw_draw_probability": round(p_draw, 4),
                "raw_away_probability": round(p_away, 4),

                "calibrated_home_probability": round(cal_home, 4),
                "calibrated_draw_probability": round(cal_draw, 4),
                "calibrated_away_probability": round(cal_away, 4),

                "home_market_odds": odds.get("home"),
                "draw_market_odds": odds.get("draw"),
                "away_market_odds": odds.get("away"),
                "market_books": odds.get("n_books", 0),
                "home_market_probability": round(mkt_home, 4) if mkt_home is not None else None,
                "draw_market_probability": round(mkt_draw, 4) if mkt_draw is not None else None,
                "away_market_probability": round(mkt_away, 4) if mkt_away is not None else None,
                "bookmaker_overround_pct": overround_pct,

                "home_fair_odds": fair_h, "draw_fair_odds": fair_d, "away_fair_odds": fair_a,
                "home_edge_pp": edge_h, "draw_edge_pp": edge_d, "away_edge_pp": edge_a,
                "home_ev": ev_h, "draw_ev": ev_d, "away_ev": ev_a,

                "favoured_side": fav_side,
                "favoured_probability": round(fav_prob, 4),
                "favoured_edge_pp": fav_edge,
                "favoured_ev": fav_ev,

                "data_quality": ("OK" if (home_n_eff >= MIN_SAMPLE_FOR_ANY_CONFIDENCE
                                          and away_n_eff >= MIN_SAMPLE_FOR_ANY_CONFIDENCE)
                                 else "THIN_SAMPLE"),
                "model_confidence": confidence,
                "model_confidence_reason": confidence_reason,

                "lock1_prediction_quality": lock1,
                "lock2_market_value": lock2,
                "final_verdict": verdict,

                "model_version": MODEL_VERSION,
                "calibration_version": CALIBRATION_VERSION,
                "strength_model_version": STRENGTH_MODEL_VERSION,
            })

        except Exception as exc:
            errors.append((fid, exc))
            if len(errors) <= 5:
                print(f"[v2][ERROR] fixture {fid} skipped: {type(exc).__name__}: {exc}")

    if errors:
        print(f"[v2][WARN] {len(errors)} fixture(s) skipped due to errors.")

    if not rows:
        raise ForecastDataError(f"Win Forecast v2 produced 0 rows for {target_date}")

    df = pd.DataFrame(rows)
    df = df.sort_values(by="favoured_probability", ascending=False).reset_index(drop=True)

    # Lean primary CSV (comparable shape to the v1 ranked forecast) +
    # separate full audit CSV, per spec Section 42.
    main_cols = [
        "fixture_id", "fixture", "league_id", "home_team", "away_team",
        "calibrated_home_probability", "calibrated_draw_probability",
        "calibrated_away_probability", "favoured_side", "favoured_probability",
        "home_market_odds", "draw_market_odds", "away_market_odds",
        "favoured_edge_pp", "favoured_ev", "model_confidence", "final_verdict",
        "model_version",
    ]
    main_path = os.path.join(OUTPUT_DIR, f"ranked_win_forecast_v2_{target_date}.csv")
    audit_path = os.path.join(OUTPUT_DIR, f"win_model_audit_v2_{target_date}.csv")

    for path, cols in ((main_path, main_cols), (audit_path, None)):
        tmp = path + ".tmp"
        (df[cols] if cols else df).to_csv(tmp, index=False)
        os.replace(tmp, path)

    print(f"\n[v2][DONE] {len(df)} fixtures processed.")
    print(f"[v2] Lean forecast : {main_path}")
    print(f"[v2] Full audit    : {audit_path}")
    print(f"[v2] Confidence distribution:\n{df['model_confidence'].value_counts().to_string()}")
    print(f"[v2] Verdict distribution:\n{df['final_verdict'].value_counts().to_string()}")
    print("\n[v2] REMINDER: calibration_version is 'none-identity-v0' — "
          "raw_probability == calibrated_probability. Treat 'VALUE CONFIRMED' "
          "rows as UNVALIDATED until this is backtested against real settled "
          "fixtures (see HONESTY LEDGER at the top of this file).")

    return df.to_dict(orient="records")


if __name__ == "__main__":
    # Scheduler-safe (matches the sibling engines fixed on 2026-10-10):
    # an optional YYYY-MM-DD argv, defaulting to TOMORROW UTC — no
    # interactive prompt, so this is safe under cron / systemd / the
    # pipeline's own orchestrators.
    if len(sys.argv) > 1:
        _date = sys.argv[1].strip()
        try:
            datetime.strptime(_date, "%Y-%m-%d")
        except ValueError:
            raise SystemExit(f"Invalid date '{_date}'. Use the format YYYY-MM-DD.")
    else:
        _date = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    # When run manually, verbose output is the point.
    run_win_forecast_v2_engine(_date)
