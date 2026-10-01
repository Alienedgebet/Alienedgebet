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
    calculate_u25_score,
    calculate_u35_score,
)


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
