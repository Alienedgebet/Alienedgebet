"""
Phase 0 regression tests — Under 2.5 engine data integrity.

Guards the fixes made after the draw/under-2.5 investigation:
  1. c_p90 built from a real sample (no 1-minute cameo -> 270.00/90)
  2. a keeper with no usable data is NOT graded ELITE WALL
  3. a missing keeper grade can never earn the sig3 bonus
  4. the fatigue signal fires at a reachable threshold

Run:  ./venv/bin/python -m pytest tools/test_unders_phase0.py -v
  or:  ./venv/bin/python tools/test_unders_phase0.py
"""
import os
import sys

sys.path.insert(0, "/var/www/backend")

from Engine.unders_engine import (
    GK_ELITE_CPG,
    GK_AVERAGE_CPG,
    GK_MIN_APPS,
    GK_MIN_MINS,
    GK_CPG_SANITY_MAX,
    SIG5_FIRE_FATIGUE,
    GATE_MAX_GOALS_SCORED,
    GATE_MAX_GOALS_CONCEDED,
    GATE_H2H_MAX_TOTAL,
    GATE_FAIL_TIER_U25,
    GATE_FAIL_TIER_U35,
    GATE_PROFILES,
    LAMBDA_PRIOR_GOALS,
    LAMBDA_PRIOR_STRENGTH,
    build_lambdas,
    KING_BASE_POINTS,
    KING_MAX_POINTS,
    KING_SUPPORT_BONUS,
    KING_LAMBDA_MAX_U25,
    KING_LAMBDA_MAX_U35,
    calculate_king_signal,
    calculate_u25_score,
    calculate_u35_score,
    evaluate_unders_gates,
    get_u25_tier,
    get_u35_tier,
    king_sot_for_fixture,
)

_HOME_ID, _AWAY_ID = 101, 202


def _fx(team_id, team_goals, opp_goals):
    """A fixture in which team_id genuinely played, on its true venue."""
    if team_id == _HOME_ID:
        hg, ag = team_goals, opp_goals
    else:
        hg, ag = opp_goals, team_goals
    return {
        "scores": [
            {"participant": "home", "goals": hg},
            {"participant": "away", "goals": ag},
        ],
        "participants": [
            {"id": _HOME_ID, "meta": {"location": "home"}},
            {"id": _AWAY_ID, "meta": {"location": "away"}},
        ],
    }


def _series(team_id, rows):
    return [_fx(team_id, g, o) for g, o in rows]


def _quiet():
    """A window on both sides comfortably inside every gate.

    1 goal scored and 1 conceded across 4 matches gives totals of 4 and 4,
    which sit strictly below the 5-goal caps under every current setting, so a
    fixture built from these passes the gates for the right reason.
    """
    return _series(_HOME_ID, [(1, 1)] * 4), _series(_AWAY_ID, [(1, 1)] * 4)


def _lambda_inputs():
    """(lastN_home, home_id, lastN_away, away_id) for build_lambdas()."""
    home = _series(_HOME_ID, [(1, 1)] * 5)     # 1 scored, 1 conceded per match
    away = _series(_AWAY_ID, [(1, 1)] * 5)
    return home, _HOME_ID, away, _AWAY_ID


# ---------------------------------------------------------------- c_p90 math
def test_cpg_no_longer_explodes_on_tiny_sample():
    """The original bug: (conceded / max(1, mins)) * 90 with mins=1 -> 270.0."""
    conceded, mins = 3, 1
    naive = (conceded / max(1, mins)) * 90
    assert naive == 270.0, "sanity: reproduce the original defect"

    # A real sample is required, so this keeper is graded UNKNOWN (None).
    # None is not a number and must never satisfy an ELITE comparison.
    sample_ok = mins >= GK_MIN_MINS and conceded >= 0
    assert not sample_ok
    ungraded = None
    assert not (ungraded is not None and ungraded <= GK_ELITE_CPG)


def test_cpg_within_sanity_cap():
    """A genuine long sample that is still corrupt is clamped, not trusted."""
    conceded, mins = 40, 300
    c_p90 = (conceded / mins) * 90.0
    assert c_p90 > GK_CPG_SANITY_MAX
    clamped = min(c_p90, GK_CPG_SANITY_MAX)
    assert clamped == GK_CPG_SANITY_MAX
    # and a clamped value must never read as an ELITE wall
    assert not (clamped <= GK_ELITE_CPG)


def test_genuine_keeper_sample_is_graded():
    """A real ELITE sample is still rewarded — the fix is not over-blocking."""
    conceded, mins = 3, 900
    c_p90 = (conceded / mins) * 90.0
    assert mins >= GK_MIN_MINS
    assert c_p90 <= GK_ELITE_CPG


# ------------------------------------------------------------------ sig3 gate
def test_missing_keeper_grade_earns_nothing():
    """An ungraded keeper (None) must not produce an ELITE bonus."""
    score, fired, bd = calculate_u25_score(
        u25_prob=0.6, venue_u25_home=0.6, venue_u25_away=0.6,
        home_gk_cpg=None, away_gk_cpg=0.5,   # one unknown, one elite
        h2h_u25_rate=0.5, combined_lambda=2.7,
        fatigue_home=0.0, fatigue_away=0.0,
    )
    assert bd["sig3_gk_wall"] == 0.0
    assert score <= 30 + 25 + 0 + 15 + 0


def test_two_elite_keepers_still_score():
    """Guard against over-correction: real elite data still scores 20."""
    _, _, bd = calculate_u25_score(
        u25_prob=0.6, venue_u25_home=0.6, venue_u25_away=0.6,
        home_gk_cpg=0.8, away_gk_cpg=0.9,
        h2h_u25_rate=0.5, combined_lambda=2.7,
        fatigue_home=0.0, fatigue_away=0.0,
    )
    assert bd["sig3_gk_wall"] == 20.0


def test_u35_scorer_survives_none():
    """The U3.5 path must not raise on a None keeper grade."""
    score, bd = calculate_u35_score(
        u35_prob=0.7, combined_lambda=2.6, venue_u35_home=0.5,
        venue_u35_away=0.5, league_weight=0.2,
        fatigue_home=0.1, fatigue_away=0.1,
        home_gk_cpg=None, away_gk_cpg=None,
    )
    assert 0.0 <= score <= 100.0


# ------------------------------------------------------------------ sig5 gate
def test_fatigue_signal_fires_below_old_threshold():
    """
    2026-10-04 — REVERSED DELIBERATELY.

    The fatigue bonus was removed after measuring it on 1,393 settled U2.5 rows:
    fatigue avg >= 0.40 hit 41.9% against a 44.1% base, i.e. +0.0pp in-sample and
    +0.0pp out-of-sample. It added up to 10 points to u25_score for no measurable
    reason, diluting a score that IS predictive.

    sig5 is RETAINED as a signal so the documented 5-signal structure and the
    "signals_fired >= 4" Tier 1 rule are untouched; only its score contribution
    and its fired flag were switched off. This test now pins that contract, and
    will fail loudly if the bonus is ever reintroduced by accident.
    """
    assert SIG5_FIRE_FATIGUE < 0.60  # constant retained for a one-line restore
    _, fired, bd = calculate_u25_score(
        u25_prob=0.55, venue_u25_home=0.5, venue_u25_away=0.5,
        home_gk_cpg=2.5, away_gk_cpg=2.5,
        h2h_u25_rate=0.5, combined_lambda=2.7,
        fatigue_home=0.42, fatigue_away=0.42,
    )
    # sig5 must NOT fire and must NOT contribute, even at a high fatigue.
    assert bd["sig5_fatigue_boost"] == 0.0, "fatigue bonus must stay removed"
    # The other signals still count, so the 5-signal structure is intact.
    assert fired >= 1, "sig1-sig4 must still be able to fire"


def test_fatigue_no_longer_moves_the_score():
    """Max fatigue and zero fatigue must produce the SAME u25_score."""
    base = dict(u25_prob=0.55, venue_u25_home=0.5, venue_u25_away=0.5,
                home_gk_cpg=1.2, away_gk_cpg=1.3, h2h_u25_rate=0.5,
                combined_lambda=2.2)
    hot, _, _ = calculate_u25_score(fatigue_home=0.9, fatigue_away=0.9, **base)
    cold, _, _ = calculate_u25_score(fatigue_home=0.0, fatigue_away=0.0, **base)
    assert hot == cold, "fatigue must not influence the U2.5 score at all"


def test_king_is_a_signal_not_a_separate_tier():
    """
    2026-10-04 — REDESIGNED to match the requested architecture.

    KING is SIGNAL 6 inside calculate_u25_score()/calculate_u35_score(). It adds
    points to the score, and the existing tier thresholds read that score. There
    is deliberately no separate KING tier and no 4-of-6 vote.
    """
    pts, fired, det = calculate_king_signal(0.90, 0.90, combined_lambda=1.5,
                                           venue_rate=0.6, h2h_total=1, proj_sot=5.0)
    assert fired is True
    assert pts > 0.0, "a real GK wall must earn points"
    assert det["king_points"] == pts

    # the points genuinely lift the U2.5 score the tier reads
    base = dict(u25_prob=0.55, venue_u25_home=0.5, venue_u25_away=0.5,
                home_gk_cpg=0.90, away_gk_cpg=0.90, h2h_u25_rate=0.5,
                combined_lambda=2.2, fatigue_home=0.0, fatigue_away=0.0)
    without = calculate_u25_score(king_points=0.0, king_fired=False, **base)
    with_king = calculate_u25_score(king_points=pts, king_fired=True, **base)
    assert with_king[0] == without[0] + pts, "KING must add exactly its points"
    assert with_king[2]["sig6_king"] == pts


def test_king_needs_the_gk_wall_to_score():
    """Zero points unless the wall is there; the other inputs only add to it."""
    # no wall -> nothing, however supportive the rest is
    pts, fired, _ = calculate_king_signal(1.40, 1.60, combined_lambda=1.0,
                                          venue_rate=0.9, h2h_total=0, proj_sot=3.0)
    assert (pts, fired) == (0.0, False)
    # ungradeable keeper -> nothing, never a free pass
    pts, fired, det = calculate_king_signal(None, 0.5, combined_lambda=1.0,
                                            venue_rate=0.9, h2h_total=0, proj_sot=3.0)
    assert (pts, fired) == (0.0, False)
    assert det["king_ungradeable_keeper"] is True
    # wall alone still scores the base
    pts_wall_only, fired, _ = calculate_king_signal(0.90, 0.90)
    assert fired is True and pts_wall_only == KING_BASE_POINTS


def test_king_support_adds_but_never_blocks():
    """Support raises the points; a missing or high SOT never suppresses them."""
    wall = (0.90, 0.90)
    few, _, _ = calculate_king_signal(*wall, combined_lambda=9.0, venue_rate=0.0,
                                     h2h_total=9, proj_sot=99.0)
    many, _, _ = calculate_king_signal(*wall, combined_lambda=1.0, venue_rate=0.9,
                                       h2h_total=0, proj_sot=2.0)
    assert many > few, "supporting evidence must raise KING's value"
    assert few == KING_BASE_POINTS, "the wall alone is worth the base"
    assert many == KING_MAX_POINTS, "full support reaches the ceiling"
    # high SOT and unmeasured SOT both still yield the base wall score
    assert calculate_king_signal(*wall, proj_sot=99.0)[0] == KING_BASE_POINTS
    assert calculate_king_signal(*wall, proj_sot=None)[0] == KING_BASE_POINTS


def test_king_lambda_bound_differs_by_market():
    """U3.5 tolerates more lambda than U2.5, so its KING can fire where U2.5's cannot."""
    lam = 2.3
    assert calculate_king_signal(0.9, 0.9, combined_lambda=lam,
                                 lambda_max=KING_LAMBDA_MAX_U25)[0] == KING_BASE_POINTS
    pts35, fired35, det35 = calculate_king_signal(0.9, 0.9, combined_lambda=lam,
                                                  lambda_max=KING_LAMBDA_MAX_U35)
    assert fired35 is True and pts35 == KING_BASE_POINTS + KING_SUPPORT_BONUS
    assert det35["king_comp_low_lambda"] is True


def test_king_also_feeds_the_u35_score():
    """U3.5 receives KING too, so both markets promote from one shared signal."""
    base = dict(u35_prob=0.6, combined_lambda=2.4, venue_u35_home=0.6,
                venue_u35_away=0.6, league_weight=0.2, fatigue_home=0.0,
                fatigue_away=0.0, home_gk_cpg=0.90, away_gk_cpg=0.90)
    without, bd_w = calculate_u35_score(king_points=0.0, king_fired=False, **base)
    with_king, bd_k = calculate_u35_score(king_points=KING_BASE_POINTS,
                                           king_fired=True, **base)
    assert with_king == round(min(100.0, without + KING_BASE_POINTS), 1)
    assert bd_k["sig6_king"] == KING_BASE_POINTS
    assert bd_k["king_fired"] is True


def test_gate_profiles_share_the_original_caps():
    """
    2026-10-04 — the per-market caps were REVERTED. Both markets now use the
    original scored<=5 / conceded<=5, because the looser variants were measured
    and made the Under hit rate worse (gates PASS 44.3% vs gates FAIL 69.2%;
    9 of 13 rejected fixtures were hits).
    """
    assert GATE_PROFILES["u25"]["max_scored"] == 5
    assert GATE_PROFILES["u25"]["max_conceded"] == 5
    assert GATE_PROFILES["u35"]["max_scored"] == 5
    assert GATE_PROFILES["u35"]["max_conceded"] == 5
    home, away = _quiet()
    leaky7 = _series(_AWAY_ID, [(0, 3), (0, 2), (0, 2)])   # 7 conceded
    p25, r25, _ = evaluate_unders_gates(home, _HOME_ID, leaky7, _AWAY_ID,
                                         [_fx(_HOME_ID, 1, 1)], profile="u25")
    p35, _, _ = evaluate_unders_gates(home, _HOME_ID, leaky7, _AWAY_ID,
                                       [_fx(_HOME_ID, 1, 1)], profile="u35")
    assert p25 is False and p35 is False, "7 conceded fails both markets again"


def test_lambda_prior_strength_allows_recent_form_through():
    """
    2026-10-04 — LAMBDA_PRIOR_STRENGTH dropped 6.0 -> 2.5.

    At 6.0 pseudo-matches against a 5-match window the prior outweighed the
    evidence six to one, so a genuine 3.0 attack was flattened to 2.10 and a
    genuine 0.0 to 0.74. At 2.5 the same records survive far better.
    """
    assert LAMBDA_PRIOR_STRENGTH == 2.5
    prior = LAMBDA_PRIOR_GOALS
    def rate(g, n, strength):
        return (g * n + strength * prior) / (n + strength)
    # a real 3.0 goals/game attack over 5 matches stays recognisable
    assert rate(3.0, 5, 2.5) > 2.3, "a genuine attack must not be flattened"
    # ...and a genuine 0.0 stays genuinely low
    assert rate(0.0, 5, 2.5) < 0.5, "a genuine blank must not be inflated"
    # the old setting did much less of either
    assert rate(3.0, 5, 6.0) < rate(3.0, 5, 2.5)
    assert rate(0.0, 5, 6.0) > rate(0.0, 5, 2.5)


def test_lambda_uses_the_league_prior_when_measurable():
    """
    2026-10-04 — the flat 1.35 is now only a fallback. A league with a measured
    average supplies its own prior, measured directly from goals (no Poisson
    inversion, which is what previously produced an impossible 8.0).
    """
    league_cache = {7: {"avg_goals": {"avg_total": 3.2, "per_team": 1.6,
                                      "matches": 120}}}
    lh, la, detail = build_lambdas(*_lambda_inputs(), 7, league_cache)
    assert detail["lambda_base"] == 1.6, "the league prior must be used"
    assert detail["lambda_prior_source"] == "league"
    assert detail["lambda_league_avg_total"] == 3.2
    assert detail["lambda_league_n"] == 120
    # an unmeasurable league falls back rather than inventing a number
    _, _, d2 = build_lambdas(*_lambda_inputs(), 7, {7: {"avg_goals": None}})
    assert d2["lambda_base"] == LAMBDA_PRIOR_GOALS
    assert d2["lambda_prior_source"] == "fallback"


def test_lambda_shrinks_once_not_twice():
    """
    The prior must be applied ONCE. Shrinking attack and defence separately and
    averaging the two shrunk values applied the prior twice.
    """
    home = [_fx(_HOME_ID, 3, 0)] * 5      # home attack 3.0
    away = [_fx(_AWAY_ID, 0, 0)] * 5      # away attack 0.0
    lh, la, detail = build_lambdas(home, _HOME_ID, away, _AWAY_ID, None, None)
    prior, strength, n = LAMBDA_PRIOR_GOALS, LAMBDA_PRIOR_STRENGTH, 5
    # one shrinkage of a single blended observation of 1.50
    expected = (1.50 * n + strength * prior) / (n + strength)
    assert abs(lh - expected) < 1e-6, f"expected one shrinkage ({expected:.3f}), got {lh:.3f}"
    # the double-shrink answer must differ, proving the change took effect
    old = (((3.0 * 5 + 6.0 * prior) / 11.0) + ((0.0 * 5 + 6.0 * prior) / 11.0)) / 2.0
    assert abs(lh - old) > 1e-6, "the old double-shrink must no longer be produced"


def test_lambda_falls_back_to_prior_with_no_history():
    """No history at all: the prior IS the estimate, and it says so."""
    lh, la, detail = build_lambdas([], _HOME_ID, [], _AWAY_ID, None, None)
    assert lh == LAMBDA_PRIOR_GOALS and la == LAMBDA_PRIOR_GOALS
    assert detail["lambda_prior_source"] == "fallback"


def test_gate3_needs_two_h2h_before_it_can_gate():
    """
    2026-10-04 — Gate 3 no longer gates on a single meeting. One 3-1 twelve
    months ago is one observation, not evidence about the fixture being priced
    now, and gating on it discarded real Under fixtures.
    """
    home, away = _quiet()
    one_over = [_fx(_HOME_ID, 3, 1)]
    passed, reasons, detail = evaluate_unders_gates(home, _HOME_ID, away, _AWAY_ID,
                                                     one_over, profile="u25")
    assert passed is True, "a single h2h match must not be able to gate"
    assert "1 h2h match" in detail.get("gate_h2h_status", "")
    assert detail["gate_h2h"] == "3-1", "the latest is still reported"

    # with two meetings it may gate, and it does
    two = [_fx(_HOME_ID, 1, 1), _fx(_HOME_ID, 3, 1)]
    passed2, reasons2, detail2 = evaluate_unders_gates(home, _HOME_ID, away, _AWAY_ID,
                                                       two, profile="u25")
    assert detail2["gate_h2h_checked"] == 2
    assert not passed2, "two meetings including an over-2.5 must gate"
    assert any("h2h over 2.5" in r for r in reasons2)

    # two meetings, both quiet, still passes
    quiet = [_fx(_HOME_ID, 1, 1), _fx(_HOME_ID, 2, 0)]
    passed3, _, _ = evaluate_unders_gates(home, _HOME_ID, away, _AWAY_ID,
                                          quiet, profile="u25")
    assert passed3


def test_gate_caps_are_five():
    """The scored cap is back to 5, so 6 goals in the window now fails again."""
    home, _ = _quiet()
    six = _series(_AWAY_ID, [(2, 0), (2, 0), (2, 0)])
    passed, reasons, detail = evaluate_unders_gates(home, _HOME_ID, six, _AWAY_ID,
                                                     [_fx(_HOME_ID, 1, 1)], profile="u25")
    assert detail["gate_away_scored"] == 6.0
    assert not passed, "6 goals scored must fail under the restored cap of 5"
    assert any("away scored" in r for r in reasons)


def test_sot_missing_returns_none_not_zero():
    """Unmeasured SOT must be None, never 0.0 — a phantom value would fake a component."""
    proj, detail = king_sot_for_fixture({}, _HOME_ID, _AWAY_ID,
                                        _series(_HOME_ID, [(1, 0)] * 3),
                                        _series(_AWAY_ID, [(0, 1)] * 3))
    assert proj is None, "no statistics means unmeasured, not zero shots"
    assert detail["sot_home_att"] is None


def test_low_fatigue_scores_nothing():
    _, _, bd = calculate_u25_score(
        u25_prob=0.55, venue_u25_home=0.5, venue_u25_away=0.5,
        home_gk_cpg=2.5, away_gk_cpg=2.5,
        h2h_u25_rate=0.5, combined_lambda=2.7,
        fatigue_home=0.10, fatigue_away=0.10,
    )
    assert bd["sig5_fatigue_boost"] == 0.0


# ------------------------------------------------------------------- the gates
def test_gate1_blocks_prolific_scorer():
    home, _ = _quiet()
    # away scores more than the cap across the window
    hot_away = _series(_AWAY_ID, [(2, 1)] * 5)      # 10 goals in the window
    passed, reasons, detail = evaluate_unders_gates(
        home, _HOME_ID, hot_away, _AWAY_ID, [_fx(_HOME_ID, 1, 1)]
    )
    assert not passed
    assert detail["gate_away_scored"] == 10.0
    assert any("away scored" in r for r in reasons)


def test_gate1_boundary_is_inclusive_at_cap():
    """Exactly the cap passes; one goal more must fail."""
    home, _ = _quiet()
    cap = GATE_MAX_GOALS_SCORED

    def window(total):
        """A 5-match window scoring exactly `total` goals."""
        rows = []
        left = total
        for _ in range(5):
            take = min(2, left)
            rows.append((take, 0))
            left -= take
        assert left == 0, "window must hit the target exactly"
        return rows

    passed, _, detail = evaluate_unders_gates(
        home, _HOME_ID, _series(_AWAY_ID, window(cap)), _AWAY_ID, [_fx(_HOME_ID, 1, 1)]
    )
    assert detail["gate_away_scored"] == cap
    assert passed, "a window summing to exactly the cap must pass"

    passed_over, _, _ = evaluate_unders_gates(
        home, _HOME_ID, _series(_AWAY_ID, window(cap + 1)), _AWAY_ID, [_fx(_HOME_ID, 1, 1)]
    )
    assert not passed_over, "one goal over the cap must fail"


def test_gate2_blocks_leaky_defence():
    home, _ = _quiet()
    leaky = _series(_AWAY_ID, [(0, 3), (1, 3), (0, 2), (1, 3), (1, 2)])  # 13 conceded
    passed, reasons, detail = evaluate_unders_gates(
        home, _HOME_ID, leaky, _AWAY_ID, [_fx(_HOME_ID, 1, 1)]
    )
    assert not passed
    assert detail["gate_away_conceded"] == 13.0
    assert any("away conceded" in r for r in reasons)


def test_gate3_blocks_h2h_over_25():
    """
    2026-10-04 — now written against TWO h2h meetings, because Gate 3 refuses to
    gate on a single one. The boundary itself is unchanged: 2 total goals is
    under 2.5 and passes, 3+ is over 2.5 and gates.
    """
    home, away = _quiet()
    for hg, ag, should_pass in [(1, 1, True), (2, 0, True), (2, 1, False), (3, 0, False)]:
        # a quiet meeting first, so Gate 3 has the 2 meetings it now requires
        passed, _, detail = evaluate_unders_gates(
            home, _HOME_ID, away, _AWAY_ID, [_fx(_HOME_ID, 1, 1), _fx(_HOME_ID, hg, ag)]
        )
        assert detail["gate_h2h_checked"] == 2
        assert passed is should_pass, f"h2h {hg}-{ag} should pass={should_pass}"


def test_gate3_boundary_total_two_vs_three():
    """2 total goals is under 2.5 and passes; 3+ is over 2.5 and gates."""
    home, away = _quiet()
    passed, _, _ = evaluate_unders_gates(home, _HOME_ID, away, _AWAY_ID,
                                         [_fx(_HOME_ID, 1, 1), _fx(_HOME_ID, 2, 0)])
    assert passed, "2 total goals is under 2.5 and must pass"
    passed3, _, _ = evaluate_unders_gates(home, _HOME_ID, away, _AWAY_ID,
                                           [_fx(_HOME_ID, 1, 1), _fx(_HOME_ID, 1, 2)])
    assert not passed3, "3 total goals is over 2.5 and must fail"


def test_gate_reports_every_failure():
    home, _ = _quiet()
    hot = _series(_AWAY_ID, [(3, 3)] * 5)            # scored 15, conceded 15
    # two h2h meetings, both over 2.5, so all three gates have something to report
    passed, reasons, _ = evaluate_unders_gates(
        home, _HOME_ID, hot, _AWAY_ID, [_fx(_HOME_ID, 3, 3), _fx(_HOME_ID, 2, 2)]
    )
    assert not passed
    assert len(reasons) >= 3, f"all failures must be reported, got {reasons}"


def test_missing_h2h_passes_but_is_flagged():
    home, away = _quiet()
    passed, _, detail = evaluate_unders_gates(home, _HOME_ID, away, _AWAY_ID, [])
    assert passed
    assert "no h2h data" in detail.get("gate_h2h_status", "")


# ------------------------------------------------- gates override every tier
def test_high_score_cannot_bypass_gates_u25():
    assert get_u25_tier(96, 5, True) == "🛡️ U2.5 TIER 1 — LOCK"
    assert get_u25_tier(96, 5, False) == GATE_FAIL_TIER_U25


def test_high_score_cannot_bypass_gates_u35():
    assert get_u35_tier(99, True) == "🧱 U3.5 TIER 1 — LOCK"
    assert get_u35_tier(99, False) == GATE_FAIL_TIER_U35


def test_gates_block_every_tier_level():
    """No tier, at any score, survives a gate failure."""
    for score in (0, 39, 40, 55, 70, 100):
        assert get_u25_tier(score, 5, False) == GATE_FAIL_TIER_U25
        assert get_u35_tier(score, False) == GATE_FAIL_TIER_U35


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
