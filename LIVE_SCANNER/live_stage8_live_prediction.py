"""
STAGE 8 — live match prediction for users.

WHAT THIS IS FOR
----------------
A user types two team names into the search bar and gets, instantly and with no
API call, an honest read of the match as it stands: who is likely to win, who is
likely to draw, who is likely to score, and where the goal total is heading.

WHY IT IS NOT CODE 6's STORM
----------------------------
Code 6 fires on `structural_break`, which needs one squad rated twice as weak as
the other AND the stronger side controlling the match. Both halves of that are
either static (the squad rating never changes during a match) or need ~45
minutes for pressure to separate at all — so in the recorded history not one
alert fired before 45'. This engine instead reasons from MINUTES REMAINING and
live chance creation, which are meaningful from the first minute.

THE MODEL
---------
A live model has to be anchored somewhere honest, or it is inventing. The book
is the anchor:

  1. Over-2.5 price  ->  expected total goals for the full match (de-vigged,
     inverted through a Poisson CDF).
  2. 1X2 price       ->  how that total splits between the two sides.
  3. Live reality    ->  how much of that total is still unspent, and whether
     the match is running hotter or colder than the price implied.
  4. Structure      ->  a missing key player lowers that side's output; a
     liability keeper raises the opponent's.

Steps 1-3 are the same arithmetic on both sides, so they cannot favour anyone.
Step 4 is the only place the pre-match intelligence is allowed to speak, and it
is bounded and disclosed.

Every published number carries the trace of questions that produced it, and
five independent judges must clear it before it is shown.
"""
import json
import math
import os
import time

from .live_prediction_questions import build_trace, REQUIRED_QUESTION_IDS

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

BOARD_FILE = os.path.join(OUTPUT_DIR, "orchestrator_board.json")
DANGER_FILE = os.path.join(DATA_DIR, "danger_audit.json")
PREMATCH_FILE = os.path.join(DATA_DIR, "prematch_team_audit.json")
# DNA intelligence files — the rich pre-match layer Stage 8 was blind to.
DNA_PROFILES_FILE = os.path.join(DATA_DIR, "team_dna_v2_profiles.json")
STYLE_CLASHES_FILE = os.path.join(DATA_DIR, "fixture_style_clashes_v2.json")
# NOT "live_predictions.json" — that file belongs to Code 1
# (live_stage1_prematch.PREDICTIONS_FILE) and holds the daily picks feed. The
# first draft of this engine pointed here and overwrote Code 1's output on
# every cycle. Stage 1 rewrites it each run so it self-heals, but two engines
# sharing one filename means one silently destroys the other, and neither finds
# out. Namespaced to this stage instead.
OUTPUT_FILE = os.path.join(DATA_DIR, "stage8_live_prediction.json")

REGULATION_MINUTES = 90
# How far the structural layer is allowed to move the split. Bounded on
# purpose: an unbacktested adjustment must not be able to overturn the market.
# Keeper ±0.06, absences ±0.04, DNA pillars ±0.05 — the DNA signals have been
# measured against goals (r up to +0.47 for Box Dominance), so they get a
# larger voice than keeper/absence, but still never a veto.
MAX_STRUCTURAL_SHIFT = 0.15
KEEPER_SHIFT_WEIGHT = 0.06
ABSENCE_SHIFT_WEIGHT = 0.04
DNA_PILLAR_SHIFT_WEIGHT = 0.05

# ── A1 Live-state integration constants ──────────────────────────────────────
# Two independent, de-correlated live signals are blended WITH the market split
# (never instead of it) when a price exists:
#   * Intensity signal (total match goal propensity): total_xg + SOT -> tempo
#     factor on remaining_frac, capped and shrinkage-priored.
#   * Direction signal (which side more likely to score): h_xg/a_xg share and
#     h_pressure/a_pressure share, inverse-variance weighted, capped at a small
#     ceiling so correlated xG/pressure cannot double-count.
LIVE_DIRECTION_SHIFT_CAP = 0.08      # max share shift from live direction signal
LIVE_INTENSITY_MIN = 0.70            # tempo factor floor
LIVE_INTENSITY_MAX = 1.60            # tempo factor ceiling
LIVE_INTENSITY_PRIOR = 1.0           # shrinkage prior for intensity tempo
DA_CONFIRM_DISAGREE = 0.30           # DA/xG run-rate disagreement threshold

# Fallback anchor, used only when a fixture has NO prematch price.
#
# WHY THIS EXISTS: Code 1 admits a fixture to the prematch board only once the
# provider returns an official lineup. On the live board right now that is 1
# fixture in 5 — the rest are INSUFFICIENT purely because nobody priced them
# for us, which makes the engine useless exactly where a user is most likely to
# ask about it.
#
# So when there is no price, the anchor becomes the match's OWN observed chance
# creation, shrunk toward a league-average goal rate. It is a real estimate from
# real xG and shot counts, not a guess — but it is weaker than a price, so it is
# named in `model.anchor` and the market judge downgrades it to WARN rather
# than passing it as if a bookmaker had endorsed it.
FALLBACK_GOAL_RATE = 2.65      # league-average goals per match
FALLBACK_PRIOR_STRENGTH = 45.0  # pseudo-minutes of prior; higher = more shrink
# SOT converts at ~0.3 goals per shot on target (league-wide conversion).
# The old blend treated 1 SOT as 1 goal (0.3 weight on raw counts), inflating
# fallback anchors ~0.7 goals (0.9 xG + 3 SOT @30' read 3.4 not 2.7).
SHOT_TO_GOAL_WEIGHT = 0.30     # blend of converted-SOT alongside xG
SHOT_TO_GOAL_RATE = 0.30       # goals per shot on target
# Pace shrinkage: (observed+a)/(expected+a) — a lone 0.4 xG shot @10' no
# longer swings the whole match 33%.
PACE_PRIOR_STRENGTH = 1.2


def _live_anchor_goals(board, stats, played):
    """
    Estimate expected total goals from the match's own chance creation, shrunk
    toward the league average.

    Shrinkage is not decoration: a 20-minute sample of shots and xG extrapolated
    to 90 minutes is wildly unstable, so the observed rate is given weight
    (elapsed / (elapsed + prior)) and the rest comes from the base rate.
    """
    h_xg = float(board.get("h_xg") or 0.0)
    a_xg = float(board.get("a_xg") or 0.0)
    sot = 0.0
    for side in ("home", "away"):
        block = stats.get(side) or {}
        if isinstance(block, dict):
            sot += float(block.get("shots-on-target") or 0.0)
    sot_goals = sot * SHOT_TO_GOAL_RATE
    observed_equiv = (1.0 - SHOT_TO_GOAL_WEIGHT) * (h_xg + a_xg) \
        + SHOT_TO_GOAL_WEIGHT * sot_goals
    if observed_equiv <= 0:
        return None
    observed_rate = observed_equiv / played
    extrapolated = observed_rate * REGULATION_MINUTES
    weight = played / (played + FALLBACK_PRIOR_STRENGTH)
    return max(0.2, min(6.0,
                        weight * extrapolated
                        + (1.0 - weight) * FALLBACK_GOAL_RATE))


def _load(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback


def _as_rows(data):
    """Accept a list of records or a mapping keyed by id. Never guess further."""
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        out = []
        for key, value in data.items():
            if not isinstance(value, dict):
                continue
            row = dict(value)
            row.setdefault("fixture_id", key)
            out.append(row)
        return out
    return []


# ── Poisson helpers ────────────────────────────────────────────────────────
def poisson_pmf(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def poisson_at_least_one(lam):
    """P(X >= 1). Used for every to-score line."""
    return 1.0 - math.exp(-lam) if lam > 0 else 0.0


def poisson_between(lo, hi, lam):
    return sum(poisson_pmf(k, lam) for k in range(lo, hi + 1))


def implied_total_goals(odds_over25, min_goals=0.35, max_goals=6.0,
                      odds_under25=None):
    """
    Invert an over-2.5 price into the expected total goals it implies.

    Solves P(X > 2.5) = 1/price for lambda under a Poisson. Bisection, not a
    closed form: there isn't one, and a wrong lambda here silently shifts every
    goal market on the page.

    When the under-2.5 price from the SAME odds response is available, the
    target is de-vigged first: raw_over/(raw_over+raw_under) instead of raw
    1/over (which keeps the book's margin in the anchor). Single-sided prices
    keep the old raw behaviour.

    THE BOUNDARY CHECK WAS INVERTED IN AN EARLIER DRAFT. It asked whether
    P(0-2 goals) at the ceiling was still BELOW the target, which is true for
    almost every price, and so returned the ceiling 12.0 for every fixture
    instead of the answer. lambda 12 is twelve expected goals: it produced 100%
    "to score" and 98.9% over-2.5 on a match priced at 5.5. A comparison that
    cannot match, silently returning a boundary — the fifth of this family.

    Football totals live roughly between 0.35 and 6.0 expected goals. A price
    implying more than that is not a market view, so it is refused rather than
    clamped: a wrong anchor would corrupt every number downstream.
    """
    if not odds_over25 or float(odds_over25) <= 1.0:
        return None
    target = 1.0 / float(odds_over25)
    if odds_under25:
        try:
            up = float(odds_under25)
            if up > 1.0:
                raw_over, raw_under = 1.0 / float(odds_over25), 1.0 / up
                if raw_over + raw_under > 0:
                    target = raw_over / (raw_over + raw_under)
        except (TypeError, ValueError):
            pass
    lo, hi = 0.01, 20.0
    # Unreachable only if even the ceiling produces too FEW overs.
    if (1.0 - poisson_between(0, 2, hi)) < target:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if (1.0 - poisson_between(0, 2, mid)) < target:
            lo = mid
        else:
            hi = mid
    lam = (lo + hi) / 2.0
    if lam < min_goals or lam > max_goals:
        return None
    return lam


def devig_two_way(price_a, price_b):
    """Strip the bookmaker's overround from a two-way market."""
    if not price_a or not price_b:
        return None
    try:
        price_a, price_b = float(price_a), float(price_b)
    except (TypeError, ValueError):
        return None
    if price_a <= 1.0 or price_b <= 1.0:
        return None
    raw_a, raw_b = 1.0 / price_a, 1.0 / price_b
    total = raw_a + raw_b
    if total <= 0:
        return None
    return raw_a / total


def devig_three_way(price_home, price_draw, price_away):
    """De-vig a 1X2 into (home, draw, away) probabilities. None if unusable."""
    try:
        ph, pd, pa = float(price_home), float(price_draw), float(price_away)
    except (TypeError, ValueError):
        return None
    if min(ph, pd, pa) <= 1.0:
        return None
    raw_h, raw_d, raw_a = 1.0 / ph, 1.0 / pd, 1.0 / pa
    total = raw_h + raw_d + raw_a
    if total <= 0:
        return None
    return raw_h / total, raw_d / total, raw_a / total


def fit_goal_split_three_way(total_goals, p_home, p_draw, p_away):
    """Fit (home_share) so a Poisson (λh,λa) grid reproduces the 1X2.

    A two-way home/away share ignores the draw mass and overstates favourites.
    This searches share in [0.05, 0.95] for the split whose 9x9 scoreline grid
    best matches the de-vigged (home, draw, away) triple (least squares).
    Falls back to the two-way share when the triple is unusable.
    """
    best_share, best_err = None, None
    for step in range(5, 96):
        share = step / 100.0
        lam_h, lam_a = total_goals * share, total_goals * (1.0 - share)
        hw = dw = aw = 0.0
        for i in range(9):
            pi = poisson_pmf(i, lam_h)
            for j in range(9):
                pj = poisson_pmf(j, lam_a)
                if i > j:
                    hw += pi * pj
                elif i == j:
                    dw += pi * pj
                else:
                    aw += pi * pj
        s = hw + dw + aw
        if s <= 0:
            continue
        hw, dw, aw = hw / s, dw / s, aw / s
        err = (hw - p_home) ** 2 + (dw - p_draw) ** 2 + (aw - p_away) ** 2
        if best_err is None or err < best_err:
            best_err, best_share = err, share
    return best_share


def parse_minute(value):
    """Parse a board minute robustly — never raises.

    The provider sometimes sends stoppage as "45+2" / "90+4" strings.
    int("45+2") raises ValueError, which broke predict()'s "never raises"
    promise (caught upstream as ERROR/BLOCK). "45+2" -> 47, "90+4" -> 94.
    None / garbage -> 0.
    """
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        try:
            iv = int(value)
            return max(0, iv)
        except (TypeError, ValueError):
            return 0
    s = str(value).strip()
    if not s:
        return 0
    if "+" in s:
        parts = s.split("+")
        try:
            base = int(parts[0].strip() or 0)
            extra = int(parts[1].strip() or 0)
            return max(0, base + max(0, extra))
        except (TypeError, ValueError):
            pass
    try:
        return max(0, int(float(s)))
    except (TypeError, ValueError):
        return 0


# Empirical goal-timing CDF (fraction of regulation goals scored by minute).
# Sources: league-wide timing splits; ~55% of goals come after half-time, so a
# linear (90-played)/90 understates late remaining rates. Linear interpolation
# between knots; beyond 90 a small stoppage/ET residual decays, never zero
# while the match is still live (the old min(minute,90) clamp set the rate to
# exactly 0 at 90' — a 1-1 at 90' read as 100% draw with 4' left).
_GOAL_TIMING_KNOTS = (
    (0, 0.00), (15, 0.14), (30, 0.29), (45, 0.45),
    (60, 0.61), (75, 0.79), (90, 1.00), (95, 1.00),
)

# League-average first-half goal share (the 45-minute CDF knot).
# Used as the anchor when team-specific HT rates from DNA are unavailable.
LEAGUE_HT_GOAL_SHARE = 0.45


def _team_timing_factor(ctx):
    """Team-specific first-half goal share factor from DNA.

    Combines each team's historical Scored_At_HT_Rate and Conceded_At_HT_Rate
    to produce a single factor that shifts the league-wide timing knots.

    A factor > 1 means the match is expected to have MORE goals before halftime
    (teams that score early, or concede early). A factor < 1 means goals are
    expected later (teams that score/concede after the break).

    Bounded to [0.7, 1.4] — a team that puts 65% of its goals before halftime
    is a real signal, but an 80% shift would over-ride the market's own
    timing view entirely.

    Returns 1.0 (no adjustment) when DNA is unavailable or insufficient.
    """
    dna = ctx.get("dna") or {}
    if not dna.get("available"):
        return 1.0
    rates = []
    for _side in ("home", "away"):
        team = dna.get(_side) or {}
        if not team.get("available"):
            continue
        if team.get("insufficient_data"):
            continue
        gv = team.get("goal_volume") or {}
        sc = gv.get("scored_at_ht_rate")
        cc = gv.get("conceded_at_ht_rate")
        ht_cov = gv.get("ht_coverage") or 0
        # Require at least 70% HT coverage for the rate to be trusted
        if ht_cov < 0.7:
            continue
        if sc is not None:
            rates.append(sc)
        if cc is not None:
            rates.append(cc)
    if not rates:
        return 1.0
    avg_ht = sum(rates) / len(rates)
    factor = avg_ht / LEAGUE_HT_GOAL_SHARE
    # B2: archetype timing adjustment — bounded, disclosed, coverage-gated.
    # Two defensive sides → slightly fewer early goals; two attacking sides →
    # slightly more. Mixed → no change. Capped inside [0.9, 1.1] multiplier so
    # archetype can never overturn the timing view from data.
    arch_adj = 0.0
    home_arch = (dna.get("home") or {}).get("archetype") or ""
    away_arch = (dna.get("away") or {}).get("archetype") or ""
    home_cov = (dna.get("home") or {}).get("coverage_pct") or 0
    away_cov = (dna.get("away") or {}).get("coverage_pct") or 0
    if home_cov >= 0.7 and away_cov >= 0.7 and home_arch and away_arch:
        _defensive_kw = ("defensive", "low block", "deep", "compact",
                         "sit in", "park the bus", "counter-attack",
                         "counter attack")
        home_def = any(k in home_arch.lower() for k in _defensive_kw)
        away_def = any(k in away_arch.lower() for k in _defensive_kw)
        if home_def and away_def:
            arch_adj = -0.05
        elif not home_def and not away_def:
            arch_adj = +0.05
        factor = factor * (1.0 + arch_adj)
    return max(0.7, min(1.4, factor))


def time_remaining_share(played, timing_factor=1.0):
    """Share of the match's goal expectation still unspent at `played`.

    When *timing_factor* deviates from 1.0, the league-wide goal-timing knots
    are locally rescaled so that more (or fewer) goals fall before halftime,
    reflecting the teams' actual first-half scoring tendency from DNA.
    """
    played = max(0.0, float(played or 0))
    if played >= 120:
        return 0.0
    if played >= 75:
        # Late regulation blends into stoppage then ET on one decaying line:
        # 75' -> ~0.21, 90' -> ~0.08, 95' -> 0.08 (ET kickoff, continuous),
        # then decay to the 0.02 floor at 120'. No jumps, never zero live.
        if played < 90:
            frac = (played - 75) / 15.0
            return max(0.02, 0.21 - frac * (0.21 - 0.08))
        if played < 95:
            return 0.08
        return max(0.02, 0.08 * (120 - played) / 25.0)

    knots = _GOAL_TIMING_KNOTS
    if timing_factor != 1.0:
        # ht_share is the new 45-minute CDF value; ft_share is the remainder.
        ht_share = min(0.95, max(0.05, LEAGUE_HT_GOAL_SHARE * timing_factor))
        ft_share = 1.0 - ht_share
        sh_base = 1.0 - LEAGUE_HT_GOAL_SHARE  # original second-half share (0.55)
        sh_scale = ft_share / sh_base if sh_base > 0 else 1.0
        ht_scale = ht_share / LEAGUE_HT_GOAL_SHARE if LEAGUE_HT_GOAL_SHARE > 0 else 1.0
        knots = tuple(
            (m, min(1.0, c * ht_scale)) if c <= LEAGUE_HT_GOAL_SHARE
            else (m, ht_share + (c - LEAGUE_HT_GOAL_SHARE) * sh_scale)
            for m, c in _GOAL_TIMING_KNOTS
        )

    for i in range(1, len(knots)):
        m_prev, c_prev = knots[i - 1]
        m_cur, c_cur = knots[i]
        if played <= m_cur:
            span = max(1e-9, m_cur - m_prev)
            frac = (played - m_prev) / span
            cdf = c_prev + frac * (c_cur - c_prev)
            return max(0.0, min(1.0, 1.0 - cdf))
    return 0.0


def effective_minutes_left(played, is_finished=False):
    """Minutes left for display: regulation + average stoppage, ET-aware."""
    if is_finished:
        return 0
    played = max(0.0, float(played or 0))
    if played < 90:
        # Regulation left + pro-rata share of ~5' average stoppage.
        return int(round((90 - played) + 5.0 * (1.0 - played / 90.0)))
    if played < 95:
        return max(1, int(round(95 - played)))
    if played < 120:
        return max(1, int(round(120 - played)))
    return 0


def load_context(fixture_id, _board_cache=None, _danger_cache=None,
                 _prematch_cache=None, _dna_cache=None, _clash_cache=None):
    """
    Assemble the feeds for one fixture.

    Returns None only when the fixture is not on the live board at all. A
    fixture that IS live but has no pre-match intelligence still returns a
    context — it will be labelled LIVE_ONLY, which is very different from being
    silently absent.

    The optional *_cache args hold pre-parsed feeds for a whole cycle so
    predict-every-fixture does at most 6 parses per cycle (board, danger,
    prematch, DNA profiles, style clashes), not 6 per fixture.
    """
    if _board_cache is None:
        board_doc = _load(BOARD_FILE, {})
        _board_cache = _as_rows(board_doc.get("matches", [])
                                if isinstance(board_doc, dict) else board_doc)
    if _danger_cache is None:
        _danger_cache = _as_rows(_load(DANGER_FILE, []))
    if _prematch_cache is None:
        _prematch_cache = _as_rows(_load(PREMATCH_FILE, {}))
    if _dna_cache is None:
        _dna_cache = _load(DNA_PROFILES_FILE, {})
    if _clash_cache is None:
        _clash_cache = _as_rows(_load(STYLE_CLASHES_FILE, []))
    board = next((m for m in _board_cache
                  if str(m.get("id")) == str(fixture_id)), None)
    if board is None:
        return None

    danger_row = next((r for r in _danger_cache
                       if str(r.get("fixture_id")) == str(fixture_id)), None)

    pm = next((r for r in _prematch_cache
               if str(r.get("fixture_id")) == str(fixture_id)), None)

    danger = {
        "home_team": (danger_row or {}).get("home_team") or {},
        "away_team": (danger_row or {}).get("away_team") or {},
        "home_name": ((danger_row or {}).get("home_team") or {}).get(
            "team_name") or (pm or {}).get("home", {}).get("team_name"),
        "away_name": ((danger_row or {}).get("away_team") or {}).get(
            "team_name") or (pm or {}).get("away", {}).get("team_name"),
        "available": danger_row is not None,
    }
    # Fall back to the board's own name when no audit names the sides.
    if not danger["home_name"] or not danger["away_name"]:
        name = str(board.get("name") or "")
        for sep in (" vs ", " v ", " - "):
            if sep in name:
                home, _, away = name.partition(sep)
                danger["home_name"] = danger["home_name"] or home.strip()
                danger["away_name"] = danger["away_name"] or away.strip()
                break

    # ─────────────────────────────────────────────────────────────────────────
    # DNA INTELLIGENCE — team-specific tactical knowledge
    # ─────────────────────────────────────────────────────────────────────────
    # Each team's DNA profile carries its archetype, 5 market-power pillars,
    # tactical DNA (tempo, line height, risk appetite), and goal-volume facts
    # including halftime scoring rates. The style clash carries the fixture-level
    # structural matchup and market signals. Stage 8 was previously blind to all
    # of this; it only saw keeper leakage and absence count.
    def _team_dna_lookup(team_id):
        """Look up a team's DNA profile by team_id from the prematch audit."""
        if not team_id:
            return None
        tid = str(team_id)
        # danger_audit home_team.id and prematch home.team_id are both provider
        # team PKs that index into team_dna_v2_profiles.json.
        profile = _dna_cache.get(tid) or _dna_cache.get(int(team_id) if str(team_id).isdigit() else None)
        if isinstance(profile, dict):
            return profile
        return None

    h_id = ((danger_row or {}).get("home_team") or {}).get("id") or (pm or {}).get("home", {}).get("team_id")
    a_id = ((danger_row or {}).get("away_team") or {}).get("id") or (pm or {}).get("away", {}).get("team_id")

    # Style clash keyed by fixture_id
    clash_row = next((r for r in _clash_cache
                      if str(r.get("fixture_id")) == str(fixture_id)), None)

    home_dna = _team_dna_lookup(h_id)
    away_dna = _team_dna_lookup(a_id)

    def _dna_summary(profile):
        """Extract only the fields Stage 8 needs from a DNA profile.

        Returns None when the profile is absent or insufficient — never a
        fabricated zero. Consumers check `available` themselves.
        """
        if not profile or not isinstance(profile, dict):
            return None
        mps = profile.get("Market_Power_Scores") or {}
        tactical = profile.get("Tactical_DNA") or {}
        gv = (profile.get("Raw_Audit_Metrics") or {}).get("Goal_Volume") or {}
        return {
            "available": True,
            "archetype": profile.get("Archetype"),
            "pillars": {
                "Corner_Power": mps.get("Corner_Power"),
                "Goal_Intent": mps.get("Goal_Intent"),
                "BTTS_Friction": mps.get("BTTS_Friction"),
                "Win_Dominance": mps.get("Win_Dominance"),
                "Box_Dominance": mps.get("Box_Dominance"),
            },
            "tactical": {
                "tempo": tactical.get("Tempo"),
                "line_height": tactical.get("Line_Height"),
                "risk_appetite": tactical.get("Risk_Appetite"),
                "verticality": tactical.get("Verticality"),
                "shot_quality": tactical.get("Shot_Quality"),
                "transition_style": tactical.get("Transition_Style"),
                "transition_score": tactical.get("Transition_Score"),
            },
            "goal_volume": {
                "scored_avg": gv.get("Goals_Scored_Avg"),
                "conceded_avg": gv.get("Goals_Conceded_Avg"),
                "clean_sheet_rate": gv.get("Clean_Sheet_Rate"),
                "scored_at_ht_rate": gv.get("Scored_At_HT_Rate"),
                "conceded_at_ht_rate": gv.get("Conceded_At_HT_Rate"),
                "leading_at_ht_rate": gv.get("Leading_At_HT_Rate"),
                "ht_matches_known": gv.get("HT_Matches_Known"),
                "ht_coverage": gv.get("HT_Coverage"),
                "last_result": gv.get("Last_Result"),
                "scored_in_last2": gv.get("Scored_In_Last2"),
            },
            "coverage_pct": (profile.get("Data_Coverage") or {}).get("Stats_Coverage_Pct"),
            "insufficient_data": profile.get("insufficient_data", False),
        }

    def _clash_summary(clash):
        """Extract style clash intelligence for this fixture."""
        if not clash or not isinstance(clash, dict):
            return None
        pillar_clash = clash.get("pillar_clash") or {}
        edges = {}
        for pillar, data in pillar_clash.items():
            if isinstance(data, dict):
                edges[pillar] = {
                    "home": data.get("home_score"),
                    "away": data.get("away_score"),
                    "edge": data.get("edge"),
                    "margin": data.get("margin"),
                }
        return {
            "available": True,
            "edges": edges,
            "overall_edge": clash.get("overall_structural_edge"),
            "home_pillar_edges": clash.get("home_pillar_edges"),
            "away_pillar_edges": clash.get("away_pillar_edges"),
            "combined_box_dominance": clash.get("combined_box_dominance"),
            "combined_goal_intent": clash.get("combined_goal_intent"),
            "market_signals": clash.get("market_signals") or {},
        }

    home_dna_sum = _dna_summary(home_dna) if home_dna else None
    away_dna_sum = _dna_summary(away_dna) if away_dna else None
    clash = _clash_summary(clash_row) if clash_row else None

    dna = {
        "home": home_dna_sum,
        "away": away_dna_sum,
        "clash": clash,
        "available": home_dna_sum is not None or away_dna_sum is not None or clash is not None,
    }

    odds = {}
    if pm:
        odds = {"home": pm.get("odds_home_win"),
                "draw": pm.get("odds_draw"),
                "away": pm.get("odds_away_win"),
                "over25": pm.get("odds_o25"),
                "under25": pm.get("odds_u25")}

    stats = board.get("statistics") or {}
    h_goals = (stats.get("home") or {}).get("goals")
    a_goals = (stats.get("away") or {}).get("goals")

    return {
        "fixture_id": str(fixture_id),
        "board": board,
        "danger": danger,
        "prematch": pm or {},
        "odds": odds,
        "score": {"home": int(h_goals or 0), "away": int(a_goals or 0)},
        "mode": "FULL" if danger["available"] else "LIVE_ONLY",
        "dna": dna,
    }


# ── Team-name aliases for search (common short names -> provider names) ──────
_TEAM_ALIASES = {
    "man utd": "manchester united",
    "man united": "manchester united",
    "man city": "manchester city",
    "spurs": "tottenham",
    "psg": "paris saint germain",
    "paris sg": "paris saint germain",
    "bayern": "bayern munchen",
    "inter": "internazionale",
    "ac milan": "milan",
    "atletico": "atletico madrid",
    "atleti": "atletico madrid",
    "barca": "barcelona",
    "juve": "juventus",
    "sporting": "sporting cp",
    "dortmund": "borussia dortmund",
    "bvb": "borussia dortmund",
    "leverkusen": "bayer leverkusen",
    "leipzig": "rb leipzig",
    "newcastle": "newcastle united",
    "west ham": "west ham united",
    "wolves": "wolverhampton",
    "leeds": "leeds united",
    "leicester": "leicester city",
    "norwich": "norwich city",
    "sheffield utd": "sheffield united",
    "qpr": "queens park rangers",
}
# Characters NFKD does not decompose: map explicitly before tokenising.
# (ø/æ/ł/đ/ß survive NFKD, so "Bodø" never matched "bodo".)
_NON_DECOMPOSING = {
    "ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "œ": "oe", "Œ": "oe",
    "ł": "l", "Ł": "l", "đ": "d", "Đ": "d", "ð": "d", "Ð": "d",
    "þ": "th", "Þ": "th", "ß": "ss", "ẞ": "ss", "ŋ": "n", "Ŋ": "n",
}


def normalise(text):
    """Lowercase, strip punctuation and accents so a typed name still matches.

    Handles ø/æ/ł/đ/ß (survive NFKD) and '/' in names like "Bodø/Glimt".
    """
    import unicodedata
    if not text:
        return ""
    s = str(text)
    for src, dst in _NON_DECOMPOSING.items():
        s = s.replace(src, dst)
    cleaned = unicodedata.normalize("NFKD", s)
    cleaned = "".join(c for c in cleaned if not unicodedata.combining(c))
    cleaned = cleaned.lower()
    for ch in ".'’,-_()/":
        cleaned = cleaned.replace(ch, " ")
    return " ".join(cleaned.split())


def _expand_aliases(text):
    """Expand common short names before tokenising ("man utd" -> manchester...)."""
    s = " " + normalise(text) + " "
    for short, full in _TEAM_ALIASES.items():
        s = s.replace(" " + short + " ", " " + full + " ")
    return s.strip()


def _tokens(text):
    """Words worth matching on — drop the noise words that appear in no club."""
    noise = {"fc", "afc", "cf", "sc", "ac", "as", "ss", "us", "cd", "rc",
             "vs", "v", "de", "del", "la", "le", "1", "fk", "sk", "bk", "if",
             "utd", "rbl"}
    return {w for w in _expand_aliases(text).split() if w and w not in noise}


def find_fixtures(query):
    """
    Match a typed string against the live board.

    A user types two team names in any order and with any amount of slop
    ("denmark portugal", "Denmark vs Portugal", "DENMARK"). Matching is done on
    content words with a containment rule, because a strict equality test on a
    provider name like "Dunajská Streda" fails almost every real query.
    """
    wanted = _tokens(query)
    if not wanted:
        return []
    rows = _as_rows((_load(BOARD_FILE, {}) or {}).get("matches", [])
                    if isinstance(_load(BOARD_FILE, {}), dict) else [])
    hits = []
    for m in rows:
        name = normalise(m.get("name"))
        available = _tokens(name)
        if not available:
            continue
        matched = sum(1 for w in wanted if w in available)
        # Every typed word must land somewhere, and at least two distinct team
        # words must match, or "Denmark" alone would silently match Denmark v
        # Iceland and report the wrong match.
        if matched == len(wanted) and matched >= 2:
            hits.append((matched, m))
        elif matched == len(wanted) and matched == 1 and len(wanted) == 1:
            hits.append((matched, m))
    hits.sort(key=lambda t: -t[0])
    scored = []
    for matched, m in hits:
        avail_count = len(_tokens(normalise(m.get("name"))))
        # Coverage: how much of the fixture name the query explains.
        # "Denmark" (1/2 words) scores below "Denmark Iceland" (2/2),
        # so the exact fixture outranks a partial hit.
        coverage = matched / max(1, avail_count)
        scored.append((matched, coverage, m))
    scored.sort(key=lambda t: (-t[0], -t[1]))
    return [m for _, _, m in scored]


def _structural_shift(ctx, trace):
    """
    How far the pre-match intelligence is allowed to move the goal split.

    Bounded by MAX_STRUCTURAL_SHIFT on purpose. Signals like "liability keeper"
    and "key man out" have never been shown to beat the price on this feed, so
    they get a voice with a hard ceiling, never a veto and never an unbounded
    say. Returns (shift, supporting_question_ids).

    SIGN CONVENTION: `share` is the HOME share of goals. A liability HOME
    keeper raises the AWAY output, so it moves share DOWN (negative). A
    liability AWAY keeper moves share UP (positive). Both flagged = cancel.
    """
    shift = 0.0
    supporting = []
    home_gk_bad = any(q["id"] == "keeper_liability_home"
                      and q["direction"] == "for_away" for q in trace)
    away_gk_bad = any(q["id"] == "keeper_liability_away"
                      and q["direction"] == "for_home" for q in trace)

    # Both keepers flagged = no edge either way. Symmetry must cancel, or two
    # identical liabilities would manufacture a preference out of nothing.
    danger = ctx.get("danger") or {}
    if home_gk_bad and not away_gk_bad:
        # Home keeper is the liability -> away benefits -> home share DOWN.
        # C1: scale by vulnerability magnitude, not just binary DANGER.
        h_gk = danger.get("home_team") or {}
        if h_gk.get("gk_leak_available") is False:
            pass  # missing data: no shift, trace already records available=False
        else:
            vuln = float(h_gk.get("vulnerability_pct") or 0)
            magnitude = max(0.0, min(1.0, vuln / 100.0))
            shift -= KEEPER_SHIFT_WEIGHT * magnitude
            supporting.append("keeper_liability_home")
    elif away_gk_bad and not home_gk_bad:
        # Away keeper is the liability -> home benefits -> home share UP.
        a_gk = danger.get("away_team") or {}
        if a_gk.get("gk_leak_available") is False:
            pass  # missing data: no shift
        else:
            vuln = float(a_gk.get("vulnerability_pct") or 0)
            magnitude = max(0.0, min(1.0, vuln / 100.0))
            shift += KEEPER_SHIFT_WEIGHT * magnitude
            supporting.append("keeper_liability_away")

    # Absences: symmetric in the home-centred vocabulary. "for_home" always
    # helps home (home share UP), "against_home" always hurts home (DOWN),
    # regardless of which side's absence row produced it.
    # C2: scale with count and importance (sub-linear, diminishing returns)
    # instead of a fixed ±0.04 per side.
    for side in ("home", "away"):
        q = next((x for x in trace if x["id"] == f"absences_{side}"), None)
        if not (q and q["available"]):
            continue
        team = danger.get(f"{side}_team") or {}
        missing = team.get("missing_details") or []
        count = len(missing)
        if count == 0:
            continue
        # Sub-linear count scaling: sqrt(count)/sqrt(5) maxes at 1.0 for 5+
        count_factor = min((count ** 0.5) / 2.236, 1.0)
        # Importance from player worth; fall back to moderate weight if unknown
        worth_sum = sum(float(m.get("worth") or 0) for m in missing)
        if worth_sum > 0:
            worth_factor = min(worth_sum / 25.0, 1.0)
        else:
            worth_factor = 0.5  # unknown worth -> moderate weight
        magnitude = min(count_factor * worth_factor, 1.0)
        if q["direction"] == "for_home":
            shift += ABSENCE_SHIFT_WEIGHT * magnitude
            supporting.append(q["id"])
        elif q["direction"] == "against_home":
            shift -= ABSENCE_SHIFT_WEIGHT * magnitude
            supporting.append(q["id"])

    # ── DNA PILLAR EDGES ──────────────────────────────────────────────────
    # The style clash computes per-pillar edges between the two sides.
    # Box_Dominance (r=+0.475 with goals) and Goal_Intent (r=+0.472) are the
    # strongest correlates of which side scores more. We translate their
    # differential into a share shift, bounded by DNA_PILLAR_SHIFT_WEIGHT.
    dna = ctx.get("dna") or {}
    clash = dna.get("clash") if dna else None
    if clash and clash.get("available"):
        edges = clash.get("edges") or {}
        pillar_delta = 0.0
        for pillar in ("Box_Dominance", "Goal_Intent"):
            e = edges.get(pillar) or {}
            home_s = e.get("home")
            away_s = e.get("away")
            if home_s is None or away_s is None:
                continue
            diff = (home_s - away_s) / 100.0
            # B2: scale by clash margin/edge confidence rather than flat 0.30.
            # Clear margin = full weight; Tight = half; Neutral/none = none.
            margin = (e.get("margin") or "").title()
            edge = (e.get("edge") or "").title()
            if edge == "Neutral":
                confidence = 0.0
            elif margin == "Clear":
                confidence = 1.0
            elif margin == "Tight":
                confidence = 0.5
            else:
                confidence = 0.0
            contribution = diff * 0.30 * confidence
            pillar_delta += contribution
            if abs(contribution) > 0.001:
                supporting.append(f"dna_pillar_{pillar}")

        bf = edges.get("BTTS_Friction") or {}
        if bf.get("home") is not None and bf.get("away") is not None:
            bf_diff = (bf["home"] - bf["away"]) / 100.0
            bf_margin = (bf.get("margin") or "").title()
            bf_edge = (bf.get("edge") or "").title()
            if bf_edge == "Neutral":
                bf_confidence = 0.0
            elif bf_margin == "Clear":
                bf_confidence = 1.0
            elif bf_margin == "Tight":
                bf_confidence = 0.5
            else:
                bf_confidence = 0.0
            bf_contrib = bf_diff * 0.15 * bf_confidence
            pillar_delta += bf_contrib
            if abs(bf_contrib) > 0.001:
                supporting.append("dna_pillar_BTTS_Friction")

        dna_shift = max(-DNA_PILLAR_SHIFT_WEIGHT,
                        min(DNA_PILLAR_SHIFT_WEIGHT, pillar_delta))
        shift += dna_shift

    return (max(-MAX_STRUCTURAL_SHIFT, min(MAX_STRUCTURAL_SHIFT, shift)),
            supporting)


def predict(fixture_id, history=None, _board_cache=None, _danger_cache=None,
            _prematch_cache=None, _dna_cache=None, _clash_cache=None):
    """
    Produce the live prediction for one fixture.

    `history` is prior readings of this same fixture, used by the degeneracy
    judge to prove the probabilities actually respond to the clock.

    Never raises for a missing or malformed feed: an unusable fixture comes back
    as an explicit INSUFFICIENT result carrying the reason, because a confident
    number derived from nothing is worse than no number at all.
    """
    ctx = load_context(fixture_id, _board_cache, _danger_cache,
                       _prematch_cache, _dna_cache, _clash_cache)
    base = {"fixture_id": str(fixture_id)}
    if ctx is None:
        return {**base, "status": "NOT_LIVE",
                "error": "this fixture is not on the live board",
                "predictions": None, "trace": [], "judges": None,
                "verdict": "BLOCK"}

    board = ctx["board"]
    trace = build_trace(ctx)
    answered = {q["id"] for q in trace if q["available"]}
    missing = [q for q in REQUIRED_QUESTION_IDS if q not in answered]

    base = {"fixture_id": str(fixture_id), "fixture": board.get("name"),
            "minute": board.get("minute"),
            "score": f"{ctx['score']['home']}-{ctx['score']['away']}",
            "home_team": ctx["danger"]["home_name"],
            "away_team": ctx["danger"]["away_name"],
            "mode": ctx["mode"], "trace": trace}

    if missing:
        return {**base, "status": "INSUFFICIENT",
                "error": "no live data yet for: " + ", ".join(missing),
                "predictions": None, "judges": None, "verdict": "BLOCK"}

    played = parse_minute(board.get("minute"))
    is_finished = bool(board.get("is_finished"))
    if played <= 0 and not is_finished:
        # Minute missing on a live fixture: keep a minimal played=1 (old
        # behaviour) rather than INSUFFICIENT, clock questions already gated.
        played = 1
    timing_factor = _team_timing_factor(ctx)
    remaining_frac = time_remaining_share(played, timing_factor)
    if is_finished:
        remaining_frac = 0.0

    total_goals = implied_total_goals(ctx["odds"].get("over25"),
                                    odds_under25=ctx["odds"].get("under25"))
    anchor = "market_price"
    if ctx["odds"].get("over25") and ctx["odds"].get("under25"):
        anchor = "market_price_devigged"
    board_stats = board.get("statistics") or {}
    if total_goals is None:
        # No price. Fall back to the match's own chance creation rather than
        # refusing outright — but say so, loudly, in the model block.
        total_goals = _live_anchor_goals(board, board_stats, played)
        anchor = "live_observation"
    if total_goals is None:
        return {**base, "status": "INSUFFICIENT",
                "error": "no price and no chance-creation data to anchor on",
                "predictions": None, "judges": None, "verdict": "BLOCK"}

    # Goal split: prefer the three-way fit (home/draw/away -> share whose
    # Poisson grid reproduces the triple); two-way share ignores the draw mass
    # and overstates favourites. xG/pressure split only when no 1X2 at all.
    share = None
    split_method = "none"
    three = devig_three_way(ctx["odds"].get("home"), ctx["odds"].get("draw"),
                            ctx["odds"].get("away"))
    if three is not None:
        fitted = fit_goal_split_three_way(total_goals, *three)
        if fitted is not None:
            share, split_method = fitted, "three_way_fit"
    if share is None:
        share = devig_two_way(ctx["odds"].get("home"),
                              ctx["odds"].get("away"))
        if share is not None:
            split_method = "two_way"
    # A1: live direction signal blended WITH the market split (never instead
    # of it). Only when a price set the share; xG/pressure are de-correlated
    # via inverse-variance weighting and capped so correlated stats don't
    # double-count. If both signals are stale/missing, market share stands.
    if share is not None:
        h_xg = float(board.get("h_xg") or 0.0)
        a_xg = float(board.get("a_xg") or 0.0)
        h_press = float(board.get("h_pressure") or 0.0)
        a_press = float(board.get("a_pressure") or 0.0)
        live_share = None
        live_weight = 0.0
        # xG-share component (quality of chances created)
        total_xg = h_xg + a_xg
        if total_xg > 0.05:
            xg_share = h_xg / total_xg
            # weight by total xG volume (more chances = more reliable)
            live_share = xg_share
            live_weight = min(total_xg / 3.0, 0.5)
        # pressure-share component (territorial control)
        total_press = h_press + a_press
        if total_press > 0:
            press_share = h_press / total_press
            press_weight = min(total_press / 100.0, 0.5)
            if live_share is None:
                live_share = press_share
                live_weight = press_weight
            else:
                # blend two correlated signals; downweight pressure to avoid
                # double-counting with xG
                combined_w = min(live_weight + press_weight * 0.5, 0.5)
                live_share = (live_share * live_weight +
                              press_share * press_weight * 0.5) / combined_w
                live_weight = combined_w
        if live_share is not None and live_weight > 0:
            # apply only a fraction of the live signal, capped at cap
            shift_live = (live_share - share) * min(live_weight, 1.0)
            shift_live = max(-LIVE_DIRECTION_SHIFT_CAP,
                             min(LIVE_DIRECTION_SHIFT_CAP, shift_live))
            if abs(shift_live) > 0.001:
                share = max(0.05, min(0.95, share + shift_live))
                supporting.append("live_direction")
                if split_method in ("three_way_fit", "two_way"):
                    split_method = split_method + "+live"
    if share is None:
        # Without a 1X2 price the split comes from who is actually creating
        # chances, which is the best available evidence about the same question.
        total_xg = (float(board.get("h_xg") or 0.0)
                    + float(board.get("a_xg") or 0.0))
        if total_xg > 0.05:
            share = float(board.get("h_xg") or 0.0) / total_xg
            split_method = "live_xg"
        else:
            h_press = float(board.get("h_pressure") or 0.0)
            a_press = float(board.get("a_pressure") or 0.0)
            if (h_press + a_press) > 0:
                share = h_press / (h_press + a_press)
                split_method = "live_pressure"
            # else: leave share as None — no live statistics to split on
            # honestly; treating missing as zero would fabricate a 50/50 split.
        if share is not None:
            share = max(0.15, min(0.85, share))
    if share is None:
        # No price and no live statistics — cannot determine split honestly.
        # Return INSUFFICIENT rather than fabricating a number (A2).
        return {**base, "status": "INSUFFICIENT",
                "error": "no price and no live statistics to split goals on",
                "predictions": None, "judges": None, "verdict": "BLOCK"}
    shift, supporting = _structural_shift(ctx, trace)
    share = max(0.05, min(0.95, share + shift))

    # PACE: is the match running hotter than the price implied? Compare the
    # chance quality generated so far against what the anchor expected by this
    # point. This is what makes the engine react to the match rather than
    # replay the pre-match view.
    #
    # Two guards the old code lacked:
    #  1. In fallback mode the anchor IS the observation, so pace would divide
    #     the observation by itself (self-referential, hot-stays-hot). Pace is
    #     1.0 there — the observation was already used once.
    #  2. Gamma-Poisson shrinkage (observed+a)/(expected+a) per the PRIOR
    #     above, so a lone 0.4 xG shot @10' no longer swings the match 33%.
    if anchor == "live_observation":
        pace = 1.0
        pace_note = "fallback anchor already uses the observation — pace 1.0"
    else:
        observed = float(board.get("h_xg") or 0.0) \
            + float(board.get("a_xg") or 0.0)
        played_share = 1.0 - time_remaining_share(played, timing_factor)
        expected_so_far = total_goals * max(0.0, played_share)
        a = PACE_PRIOR_STRENGTH
        pace = ((observed + a) / (expected_so_far + a)
                if (expected_so_far + a) > 0 else 1.0)
        pace = max(0.55, min(2.4, pace))
        pace_note = (f"shrunk pace (obs {observed:.2f} vs exp "
                     f"{expected_so_far:.2f})")
        # A1: intensity tempo factor from total xG + SOT — separate from,
        # and additive to, pace. Adjusts how much goal expectation remains;
        # capped and shrinkage-priored so a single event can't swing the match.
        h_sot = float(board.get("h_sot") or 0.0)
        a_sot = float(board.get("a_sot") or 0.0)
        intensity_obs = observed + 0.1 * (h_sot + a_sot)  # SOT weighted lower
        tempo = ((intensity_obs + LIVE_INTENSITY_PRIOR) /
                 (expected_so_far + LIVE_INTENSITY_PRIOR)
                 if (expected_so_far + LIVE_INTENSITY_PRIOR) > 0 else 1.0)
        # A1: dangerous attacks as confirmatory cross-check only — if DA
        # run-rate strongly disagrees with xG/SOT intensity, pull tempo
        # toward neutral (reduce confidence). Never a direct probability input
        # (avoids double-counting with xG/SOT).
        h_da = float(board.get("h_dangerous_attacks") or 0.0)
        a_da = float(board.get("a_dangerous_attacks") or 0.0)
        total_da = h_da + a_da
        if total_da > 0 and intensity_obs > 0:
            da_per_xg = total_da / max(intensity_obs, 0.01)
            if da_per_xg < DA_CONFIRM_DISAGREE or da_per_xg > (1.0 / DA_CONFIRM_DISAGREE):
                tempo = 1.0 + (tempo - 1.0) * 0.5
                pace_note += "; DA/xG disagreement — confidence reduced"
        tempo = max(LIVE_INTENSITY_MIN, min(LIVE_INTENSITY_MAX, tempo))
        remaining_frac = remaining_frac * tempo
        pace_note = pace_note + f"; intensity tempo {tempo:.2f}"

    lam_home = total_goals * share * remaining_frac * pace
    lam_away = total_goals * (1.0 - share) * remaining_frac * pace
    current = ctx["score"]
    goals_already = current["home"] + current["away"]

    home_score_p = poisson_at_least_one(lam_home)
    away_score_p = poisson_at_least_one(lam_away)
    # To-score here means ONE MORE goal from now (remaining-goals Poisson),
    # not "scored in the match" (Stage 1/2 settlement semantics). Labelled
    # explicitly so a 1-0 leader showing 40% is read as "40% for a second",
    # not as doubting the goal already scored.
    lam_left = lam_home + lam_away
    over25_p = sum(poisson_pmf(k, lam_left) for k in range(26)
                   if goals_already + k > 2)
    under35_p = sum(poisson_pmf(k, lam_left) for k in range(26)
                    if goals_already + k <= 3)
    exactly3 = sum(poisson_pmf(k, lam_left) for k in range(26)
                   if goals_already + k == 3)

    home_w = draw_w = away_w = 0.0
    for i in range(9):
        pi = poisson_pmf(i, lam_home)
        for j in range(9):
            pj = poisson_pmf(j, lam_away)
            fh, fa = current["home"] + i, current["away"] + j
            if fh > fa:
                home_w += pi * pj
            elif fh == fa:
                draw_w += pi * pj
            else:
                away_w += pi * pj
    denom = home_w + draw_w + away_w
    if denom > 0:
        home_w, draw_w, away_w = home_w / denom, draw_w / denom, away_w / denom

    predictions = {
        "home_win": round(100 * home_w, 1),
        "draw": round(100 * draw_w, 1),
        "away_win": round(100 * away_w, 1),
        # One-more-goal semantics (see note above): keys renamed with the old
        # names kept alongside so the API + frontend keep working untouched.
        "home_to_score_next": {"team": ctx["danger"]["home_name"],
                               "pct": round(100 * home_score_p, 1)},
        "away_to_score_next": {"team": ctx["danger"]["away_name"],
                               "pct": round(100 * away_score_p, 1)},
        "home_to_score": {"team": ctx["danger"]["home_name"],
                          "pct": round(100 * home_score_p, 1)},
        "away_to_score": {"team": ctx["danger"]["away_name"],
                          "pct": round(100 * away_score_p, 1)},
        "over_2_5": round(100 * over25_p, 1),
        "under_3_5": round(100 * under35_p, 1),
        "exactly_3_goals": round(100 * exactly3, 1),
    }
    # The market judge needs the anchor the engine actually used, so it can
    # re-derive the same number independently and catch a wrong one.
    judge_payload = dict(predictions)
    judge_payload["_anchor"] = {"anchor_total_goals": round(total_goals, 4),
                                "anchor_source": anchor}
    judge_payload["_lambda"] = {"home": round(lam_home, 4),
                                "away": round(lam_away, 4),
                                "pace": round(pace, 3)}
    try:
        from .live_prediction_judges import run_judges
        panel = run_judges(ctx, judge_payload, trace, history)
    except Exception as exc:
        # A panel that cannot run is a BLOCK, not a PASS. Defaulting open here
        # would let any import error silently disable every judge.
        panel = {"verdict": "BLOCK", "judges": [],
                 "blocked_by": ["panel"],
                 "error": f"judge panel failed to run: {exc}"}

    return {**base, "status": "OK", "error": None,
            "predictions": predictions,
            "judges": panel["judges"], "verdict": panel["verdict"],
            "blocked_by": panel.get("blocked_by", []),
            "dna_available": (ctx.get("dna") or {}).get("available", False),
            "home_archetype": ((ctx.get("dna") or {}).get("home") or {}).get(
                "archetype"),
            "away_archetype": ((ctx.get("dna") or {}).get("away") or {}).get(
                "archetype"),
            "overall_structural_edge": ((ctx.get("dna", {}) or {}).get(
                "clash") or {}).get("overall_edge"),
            "market_signals": ((ctx.get("dna", {}) or {}).get(
                "clash") or {}).get("market_signals", {}),
            "model": {"anchor": anchor,
                      "lambda_home_remaining": round(lam_home, 3),
                      "lambda_away_remaining": round(lam_away, 3),
                      "anchor_total_goals": round(total_goals, 2),
                      "pace_multiplier": round(pace, 2),
                      "pace_note": pace_note,
                      "split_method": split_method,
                      "structural_shift": round(shift, 3),
                      "structural_signals": supporting,
                      "timing_factor": round(timing_factor, 3),
                      "played_minute": played,
                      "minutes_remaining": effective_minutes_left(
                          played, is_finished)}}


# ── Append-only prediction log (the validation upgrade) ─────────────────────
# Every OK reading appends one JSONL line:
#   (timestamp, fixture_id, minute, score, probabilities, anchor, lambdas)
# The snapshot file is still overwritten each cycle for the API; this log is
# never overwritten, so Brier / calibration-by-minute can be scored later
# against final results and the constants tuned walk-forward (Draw precedent).
PREDICTION_LOG_FILE = os.path.join(DATA_DIR, "stage8_prediction_log.jsonl")


def _append_prediction_log(entry):
    try:
        with open(PREDICTION_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def run_live_prediction_engine():
    """
    Predict every fixture on the live board and publish one file.

    The file is the engine's whole output; nothing here writes to any other
    engine's file or makes a network call.
    """
    board_doc = _load(BOARD_FILE, {})
    rows = _as_rows(board_doc.get("matches", [])
                    if isinstance(board_doc, dict) else board_doc)
    danger_rows = _as_rows(_load(DANGER_FILE, []))
    pm_rows = _as_rows(_load(PREMATCH_FILE, {}))
    # DNA caches parsed ONCE per cycle, shared across all fixtures.
    dna_cache = _load(DNA_PROFILES_FILE, {})
    clash_cache = _as_rows(_load(STYLE_CLASHES_FILE, []))
    out = {}
    for m in rows:
        fid = m.get("id")
        if fid is None:
            continue
        try:
            rec = predict(fid, _board_cache=rows, _danger_cache=danger_rows,
                          _prematch_cache=pm_rows, _dna_cache=dna_cache,
                          _clash_cache=clash_cache)
            out[str(fid)] = rec
            # Append-only log: every OK reading is history for Brier /
            # calibration scoring. Failures of the log never break the cycle.
            if rec.get("status") == "OK" and rec.get("predictions"):
                model = rec.get("model") or {}
                _append_prediction_log({
                    "ts": time.time(),
                    "fixture_id": str(fid),
                    "fixture": rec.get("fixture"),
                    "minute": rec.get("minute"),
                    "score": rec.get("score"),
                    "mode": rec.get("mode"),
                    "verdict": rec.get("verdict"),
                    "predictions": rec.get("predictions"),
                    "anchor": model.get("anchor"),
                    "anchor_total_goals": model.get("anchor_total_goals"),
                    "lambda_home_remaining": model.get(
                        "lambda_home_remaining"),
                    "lambda_away_remaining": model.get(
                        "lambda_away_remaining"),
                    "pace_multiplier": model.get("pace_multiplier"),
                    "structural_shift": model.get("structural_shift"),
                    "structural_signals": model.get("structural_signals"),
                    "timing_factor": model.get("timing_factor"),
                    # DNA-enhanced fields for training
                    "dna_available": rec.get("dna_available"),
                    "home_archetype": rec.get("home_archetype"),
                    "away_archetype": rec.get("away_archetype"),
                    "overall_structural_edge": rec.get(
                        "overall_structural_edge"),
                    "market_signals": rec.get("market_signals"),
                })
        except Exception as exc:
            out[str(fid)] = {"fixture_id": str(fid),
                             "status": "ERROR",
                             "error": f"prediction failed: {exc}",
                             "predictions": None, "trace": [],
                             "judges": None, "verdict": "BLOCK"}
    payload = {"generated_at": time.time(),
               "engines": len(rows), "predictions": out}
    tmp = OUTPUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
    os.replace(tmp, OUTPUT_FILE)
    return payload
