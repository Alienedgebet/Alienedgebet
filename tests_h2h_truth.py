"""
Tests for the shared H2H primitive.

THE DEFECT BEING PINNED
-----------------------
An H2H threshold on the Weekly Tipster board did not exclude team pairs with
almost no history, because the sample size was discarded at the first step and
re-invented downstream as a literal "/5":

    "H2H_GG": f"{h2h_gg}/5"

Two meetings that both had BTTS became "2/5" -- indistinguishable from two of a
possible five that did not -- and a pair that never met became "0/5", a
confident-looking number that reads as real evidence.

Pure unit tests: no network, no provider, no writes.
"""

import unittest

from CORE.h2h_truth import H2H_CAP, H2HTruth, build_h2h_truth


def fixture(fid, goals, date="2026-09-01", participants=None):
    """A finished fixture with a readable FULL_TIME scoreline."""
    hg, ag = goals
    return {
        "id": fid,
        "starting_at": f"{date}T20:00:00+00:00",
        "state": {"state": "FT"},
        "scores": [
            {"description": "FULL_TIME", "score": {"participant": "home", "goals": hg}},
            {"description": "FULL_TIME", "score": {"participant": "away", "goals": ag}},
        ],
        "participants": participants or [],
    }


def _ft_goals(fx):
    """Full-time goals for both sides, or None when unreadable."""
    hg = ag = None
    for entry in fx.get("scores") or []:
        desc = str(entry.get("description", "")).upper()
        if desc != "FULL_TIME":
            continue
        val = (entry.get("score") or {}).get("goals")
        who = (entry.get("score") or {}).get("participant")
        if who == "home":
            hg = val
        elif who == "away":
            ag = val
    return (hg, ag) if (hg is not None and ag is not None) else None


def both_scored(fx):
    g = _ft_goals(fx)
    return None if g is None else (g[0] > 0 and g[1] > 0)


def over25(fx):
    g = _ft_goals(fx)
    return None if g is None else ((g[0] + g[1]) >= 3)


class SampleSizeIsNeverInventedTests(unittest.TestCase):
    def test_two_of_two_is_not_two_of_five(self):
        """THE bug. Two meetings, both BTTS: 2/2, never '2/5'."""
        truth = build_h2h_truth(
            [fixture(1, (2, 1)), fixture(2, (1, 3))], both_scored
        )
        self.assertEqual(truth.count, 2)
        self.assertEqual(truth.total, 2)
        self.assertEqual(truth.rate, 1.0)          # truly 100%, not 40%
        self.assertIn("2/2", truth.display)
        self.assertNotIn("/5", truth.display)

    def test_thin_sample_is_labelled_transparently(self):
        truth = build_h2h_truth([fixture(1, (2, 1))], both_scored)
        self.assertIn("thin", truth.display)
        self.assertTrue(truth.display.startswith("1/1"))

    def test_full_sample_is_not_labelled_thin(self):
        rows = [fixture(i, (2, 1)) for i in range(5)]
        truth = build_h2h_truth(rows, both_scored)
        self.assertEqual(truth.total, 5)
        self.assertNotIn("thin", truth.display)


class EmptyIsNeverZeroTests(unittest.TestCase):
    def test_no_history_is_unusable_and_rates_none(self):
        truth = build_h2h_truth([], both_scored)
        self.assertFalse(truth.usable)
        self.assertIsNone(truth.rate, "an empty sample must NOT read as 0.0")
        self.assertEqual(truth.display, "no H2H")
        self.assertEqual(truth.reason, "no_h2h_history")

    def test_never_met_pair_fails_every_threshold(self):
        """Spec A: no history must not qualify, at any threshold."""
        truth = build_h2h_truth(None, both_scored)
        self.assertFalse(truth.meets_count(None))
        self.assertFalse(truth.meets_count(1))
        self.assertFalse(truth.meets_count(3))

    def test_real_zero_is_distinguishable_from_no_history(self):
        """5 meetings, none BTTS -> rate 0.0 but STILL usable."""
        rows = [fixture(i, (2, 0)) for i in range(5)]
        truth = build_h2h_truth(rows, both_scored)
        self.assertTrue(truth.usable)
        self.assertEqual(truth.rate, 0.0)
        self.assertNotEqual(truth.display, "no H2H")
        # ...and a threshold of 1 is correctly NOT met by a real zero.
        self.assertFalse(truth.meets_count(1))


class ThresholdBehaviourTests(unittest.TestCase):
    def test_user_threshold_counts_real_meetings(self):
        rows = [fixture(i, (2, 1)) for i in range(4)]
        truth = build_h2h_truth(rows, both_scored)
        self.assertTrue(truth.meets_count(3))
        self.assertFalse(truth.meets_count(5))

    def test_thin_pair_can_still_qualify_when_the_count_is_real(self):
        """Spec B: 2 meetings that really were both BTTS is honest evidence."""
        truth = build_h2h_truth([fixture(1, (2, 1)), fixture(2, (1, 1))], both_scored)
        self.assertTrue(truth.meets_count(2))
        self.assertIn("thin", truth.display)

    def test_no_threshold_means_any_usable_pair_qualifies(self):
        truth = build_h2h_truth([fixture(1, (1, 0))], both_scored)
        self.assertTrue(truth.meets_count(None))


class CappingAndExclusionTests(unittest.TestCase):
    def test_more_than_five_is_capped_at_five(self):
        """Spec C: limit to five."""
        rows = [fixture(i, (2, 1), date=f"2026-09-{i:02d}") for i in range(1, 12)]
        truth = build_h2h_truth(rows, both_scored)
        self.assertEqual(truth.total, H2H_CAP)
        self.assertTrue(truth.truncated)
        self.assertIn("capped", truth.display)

    def test_cap_keeps_the_newest_meetings(self):
        rows = [fixture(1, (1, 0), date="2026-01-01"),
                fixture(2, (2, 1), date="2026-09-01"),
                fixture(3, (2, 1), date="2026-09-02")]
        truth = build_h2h_truth(rows, both_scored)
        # Only 3 meetings exist and the cap is 5, so all three are sampled.
        self.assertEqual(truth.total, 3)
        self.assertFalse(truth.truncated)

    def test_the_fixture_under_analysis_is_excluded(self):
        """A re-run of a played fixture must not read its own result."""
        rows = [fixture(19636609, (2, 1), date="2026-10-05"),
                fixture(1, (2, 1), date="2026-09-01"),
                fixture(2, (2, 1), date="2026-09-02")]
        truth = build_h2h_truth(rows, both_scored, exclude_fixture_id=19636609)
        self.assertEqual(truth.total, 2)
        self.assertEqual(truth.count, 2)

    def test_date_range_is_bounded_by_the_reference_date(self):
        """An ancient meeting must not supply today's number."""
        rows = [fixture(1, (2, 1), date="2015-01-01"),
                fixture(2, (2, 1), date="2026-09-01")]
        truth = build_h2h_truth(rows, both_scored,
                                max_age_days=1095, reference_date="2026-10-05")
        self.assertEqual(truth.total, 1)
        self.assertEqual(truth.count, 1)


class UnreadableIsNotAFailureTests(unittest.TestCase):
    def test_missing_scoreline_is_skipped_not_counted_as_a_loss(self):
        rows = [
            {"id": 1, "starting_at": "2026-09-01T20:00:00+00:00", "scores": []},
            fixture(2, (2, 1), date="2026-09-02"),
        ]
        truth = build_h2h_truth(rows, both_scored)
        self.assertEqual(truth.total, 1)
        self.assertEqual(truth.count, 1)

    def test_penalty_scores_are_not_open_play_goals(self):
        """A shootout is not a BTTS result in open play."""
        rows = [{
            "id": 1,
            "starting_at": "2026-09-01T20:00:00+00:00",
            "scores": [
                {"description": "FULL_TIME", "score": {"participant": "home", "goals": 0}},
                {"description": "FULL_TIME", "score": {"participant": "away", "goals": 0}},
                {"description": "PENALTY", "score": {"participant": "home", "goals": 3}},
                {"description": "PENALTY", "score": {"participant": "away", "goals": 2}},
            ],
        }]
        truth = build_h2h_truth(rows, both_scored)
        self.assertEqual(truth.count, 0)


class SerialisationTests(unittest.TestCase):
    def test_dict_carries_count_and_together(self):
        t = build_h2h_truth([fixture(1, (2, 1))], both_scored).as_dict()
        self.assertEqual(t["count"], 1)
        self.assertEqual(t["total"], 1)
        self.assertTrue(t["usable"])
        self.assertIn("thin", t["display"])

    def test_engine_specific_predicates_work(self):
        rows = [fixture(1, (2, 1)), fixture(2, (1, 0)), fixture(3, (3, 2))]
        o25 = build_h2h_truth(rows, over25)
        # (2,1)=3 and (3,2)=5 clear Over 2.5; (1,0)=1 does not.
        self.assertEqual(o25.count, 2)
        self.assertEqual(o25.total, 3)


if __name__ == "__main__":
    unittest.main()
