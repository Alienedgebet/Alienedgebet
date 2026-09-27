"""
tests_signal_ledger.py — contract tests for the market-signal backtest tools.

These lock the three things that would silently corrupt the analysis if they
broke: name normalisation (a broken join shrinks the sample and manufactures
fake "no signal" results), numeric parsing (a field that silently becomes 0
turns a real edge into noise), and the rule that PENDING rows are never
recorded as losses.
"""

import json
import os

import unittest
from unittest import mock

import signal_ledger as sl


class NameNormalisationTests(unittest.TestCase):
    def test_accents_and_case_are_folded(self):
        self.assertEqual(sl.norm_name("São Paulo"), sl.norm_name("Sao Paulo"))
        self.assertEqual(sl.norm_name("Atlante"), "atlante")

    def test_fixture_key_splits_both_sides(self):
        self.assertEqual(sl.fixture_key("Atlante vs Monterrey"),
                         ("atlante", "monterrey"))
        self.assertEqual(sl.fixture_key("A vs. B"), ("a", "b"))
        self.assertEqual(sl.fixture_key("A against B"), ("a", "b"))

    def test_unsplittable_name_returns_none_not_a_guess(self):
        # Must be None so the caller counts it unmatched instead of joining
        # it to an arbitrary fixture.
        self.assertIsNone(sl.fixture_key(""))
        self.assertIsNone(sl.fixture_key("NoSeparatorHere"))


class NumericParsingTests(unittest.TestCase):
    def test_parses_engine_string_fields(self):
        self.assertEqual(sl.as_float("41%"), 41.0)
        self.assertEqual(sl.as_float("13.11"), 13.11)
        self.assertEqual(sl.as_float(7), 7.0)

    def test_missing_or_junk_is_none_never_zero(self):
        # A fabricated 0 would rank a "no data" row as the lowest signal and
        # quietly count it as a loser.
        for junk in (None, "", "N/A", "None", "nan", "-", "--", "abc"):
            self.assertIsNone(sl.as_float(junk), junk)

    def test_booleans_are_not_numbers(self):
        self.assertIsNone(sl.as_float(True))


class BuildEntriesTests(unittest.TestCase):
    """PENDING and unmatched rows are counted, never recorded as LOST."""

    def test_pending_rows_are_counted_not_logged(self):
        predictions = [{"Fixture": "A vs B", "Total_Exp": "10"}]
        results = {(sl.norm_name("A"), sl.norm_name("B")):
                   {"home_team": "A", "away_team": "B", "has_started": False,
                    "is_finished": False, "total_corners": 0, "total_sot": 0}}
        with mock.patch.object(sl, "load_predictions", lambda k, d: predictions), \
             mock.patch.object(sl, "load_results", lambda d: results):
            entries, stats = sl.build_entries("corners", "2026-09-26")
        self.assertEqual(entries, [])
        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["joined"], 0)
        self.assertEqual(stats["lost"], 0)

    def test_unmatched_row_is_counted_not_graded(self):
        with mock.patch.object(sl, "load_predictions",
                               lambda k, d: [{"Fixture": "A vs B", "Total_Exp": "10"}]), \
             mock.patch.object(sl, "load_results", lambda d: {}):
            entries, stats = sl.build_entries("corners", "2026-09-26")
        self.assertEqual(entries, [])
        self.assertEqual(stats["unmatched"], 1)
        self.assertEqual(stats["joined"], 0)


class GraderFidelityTests(unittest.TestCase):
    """The ledger must use the real grader, and only its terminal verdicts."""

    @staticmethod
    def _actual(**overrides):
        """A COMPLETE archive row — grade_row reads nearly every one of these,
        and a partial row raises (which is what `ungraded` counts)."""
        row = {"fixture_id": "1", "home_team": "A", "away_team": "B",
               "h_ht": 1, "a_ht": 0, "h_ft": 2, "a_ft": 1, "ft_score": "2-1",
               "total_goals": 3, "sh_goals_home": 1, "sh_goals_away": 0,
               "sh_goals": 1, "h_corners": 6, "a_corners": 5, "total_corners": 11,
               "h_sot": 5, "a_sot": 4, "total_sot": 9, "has_started": True,
               "is_finished": True, "score_available": True, "minute": 90,
               "match_date": "2026-09-26"}
        row.update(overrides)
        return row

    def test_terminal_verdict_is_recorded_with_its_signals(self):
        row = {"Fixture": "A vs B", "Total_Exp": "11", "Home_Exp": "7",
               "Master_Score": "80", "Chaos_Rating": "60"}
        with mock.patch.object(sl, "load_predictions", lambda k, d: [row]), \
             mock.patch.object(sl, "load_results",
                               lambda d: {(sl.norm_name("A"), sl.norm_name("B")): self._actual()}):
            entries, stats = sl.build_entries("corners", "2026-09-26")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["verdict"], "WON")
        self.assertEqual(entries[0]["Total_Exp"], 11.0)
        self.assertEqual(entries[0]["actual_total"], 11)
        self.assertEqual(stats["won"], 1)

    def test_below_threshold_is_recorded_as_lost(self):
        """A settled fixture that genuinely missed the line IS a real loss."""
        row = {"Fixture": "A vs B", "Total_Exp": "5"}
        with mock.patch.object(sl, "load_predictions", lambda k, d: [row]), \
             mock.patch.object(sl, "load_results",
                               lambda d: {(sl.norm_name("A"), sl.norm_name("B")):
                                          self._actual(h_corners=2, a_corners=2, total_corners=4)}):
            entries, stats = sl.build_entries("corners", "2026-09-26")
        self.assertEqual(entries[0]["verdict"], "LOST")
        self.assertEqual(stats["lost"], 1)

    def test_sot_uses_its_own_line(self):
        row = {"Fixture": "A vs B", "Proj_SOT": 9.0, "Consistency": "60"}
        with mock.patch.object(sl, "load_predictions", lambda k, d: [row]), \
             mock.patch.object(sl, "load_results",
                               lambda d: {(sl.norm_name("A"), sl.norm_name("B")):
                                          self._actual(h_sot=3, a_sot=4, total_sot=7)}):
            entries, _ = sl.build_entries("sot", "2026-09-26")
        self.assertEqual(entries[0]["verdict"], "WON")   # 7 > 6
        self.assertEqual(entries[0]["Consistency"], 60.0)
        self.assertEqual(entries[0]["actual_total"], 7)

    def test_malformed_archive_row_is_counted_ungraded_not_lost(self):
        """A grader blow-up must never be laundered into a LOST verdict."""
        row = {"Fixture": "A vs B", "Total_Exp": "11"}
        broken = self._actual()
        del broken["total_goals"]                 # grade_row raises KeyError
        with mock.patch.object(sl, "load_predictions", lambda k, d: [row]), \
             mock.patch.object(sl, "load_results",
                               lambda d: {(sl.norm_name("A"), sl.norm_name("B")): broken}):
            entries, stats = sl.build_entries("corners", "2026-09-26")
        self.assertEqual(entries, [])
        self.assertEqual(stats["ungraded"], 1)
        self.assertEqual(stats["lost"], 0)


if __name__ == "__main__":
    unittest.main()
