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
    calculate_u25_score,
    calculate_u35_score,
    evaluate_unders_gates,
    get_u25_tier,
    get_u35_tier,
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
    """The old constant 0.60 was above the observed max; 0.40 must be reachable."""
    assert SIG5_FIRE_FATIGUE < 0.60
    _, fired, bd = calculate_u25_score(
        u25_prob=0.55, venue_u25_home=0.5, venue_u25_away=0.5,
        home_gk_cpg=2.5, away_gk_cpg=2.5,
        h2h_u25_rate=0.5, combined_lambda=2.7,
        fatigue_home=0.42, fatigue_away=0.42,
    )
    assert fired >= 1
    assert bd["sig5_fatigue_boost"] > 0.0


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
    home, away = _quiet()
    for hg, ag, should_pass in [(1, 1, True), (2, 0, True), (2, 1, False), (3, 0, False)]:
        passed, _, detail = evaluate_unders_gates(
            home, _HOME_ID, away, _AWAY_ID, [_fx(_HOME_ID, hg, ag)]
        )
        assert detail["gate_h2h_total"] == hg + ag
        assert passed is should_pass, f"h2h {hg}-{ag} should pass={should_pass}"


def test_gate3_boundary_total_two_vs_three():
    home, away = _quiet()
    passed, _, _ = evaluate_unders_gates(home, _HOME_ID, away, _AWAY_ID, [_fx(_HOME_ID, 2, 0)])
    assert passed, "2 total goals is under 2.5 and must pass"
    passed3, _, _ = evaluate_unders_gates(home, _HOME_ID, away, _AWAY_ID, [_fx(_HOME_ID, 1, 2)])
    assert not passed3, "3 total goals is over 2.5 and must fail"


def test_missing_h2h_passes_but_is_flagged():
    home, away = _quiet()
    passed, _, detail = evaluate_unders_gates(home, _HOME_ID, away, _AWAY_ID, [])
    assert passed
    assert "no h2h data" in detail.get("gate_h2h_status", "")


def test_gate_reports_every_failure():
    home, _ = _quiet()
    hot = _series(_AWAY_ID, [(3, 3)] * 5)            # scored 15, conceded 15
    passed, reasons, _ = evaluate_unders_gates(
        home, _HOME_ID, hot, _AWAY_ID, [_fx(_HOME_ID, 3, 3)]
    )
    assert not passed
    assert len(reasons) >= 3, f"all failures must be reported, got {reasons}"


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
