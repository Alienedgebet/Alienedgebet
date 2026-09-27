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

    def test_nan_and_infinity_are_missing_not_numbers(self):
        """NaN/inf must never be returned as a signal value.

        They are not "low" readings, they are absent data. Returning them
        silently breaks every mean/threshold downstream and, because
        json.dump writes a bare NaN, produces a ledger file that is not valid
        JSON at all.
        """
        self.assertIsNone(sl.as_float(float("nan")))
        self.assertIsNone(sl.as_float(float("inf")))
        self.assertIsNone(sl.as_float(float("-inf")))
        # Overflowing digit runs land on inf rather than raising.
        self.assertIsNone(sl.as_float("1" + "0" * 400))
        # And a NaN must never survive into the serialised entry.
        import json as _json
        entry = {"v": sl.as_float(float("nan"))}
        self.assertEqual(_json.loads(_json.dumps(entry)), {"v": None})


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


class VenueOrientationTests(unittest.TestCase):
    """The archiver and the engines do not always agree on which side is home.

    A prediction may read 'A vs B' while the archive row stores home='B',
    away='A'. Before the unordered join existed, every such row was counted as
    `unmatched` and silently shrank the sample — which is how o15 / shvi /
    fhvi joined ZERO rows while corners and sot looked healthy by luck.
    """

    @staticmethod
    def _actual(**overrides):
        row = {"fixture_id": "1", "home_team": "A", "away_team": "B",
               "h_ht": 1, "a_ht": 0, "h_ft": 2, "a_ft": 1, "ft_score": "2-1",
               "total_goals": 3, "sh_goals_home": 1, "sh_goals_away": 0,
               "sh_goals": 1, "h_corners": 6, "a_corners": 5, "total_corners": 11,
               "h_sot": 5, "a_sot": 4, "total_sot": 9, "has_started": True,
               "is_finished": True, "score_available": True, "minute": 90,
               "match_date": "2026-09-26"}
        row.update(overrides)
        return row

    def test_reversed_archive_orientation_still_joins(self):
        """Prediction says 'A vs B'; archive stored home='B', away='A'."""
        reversed_actual = self._actual(home_team="B", away_team="A")
        results = {(sl.norm_name("B"), sl.norm_name("A")): reversed_actual}
        row = {"Fixture": "A vs B", "Total_Exp": "11"}
        with mock.patch.object(sl, "load_predictions", lambda k, d: [row]), \
             mock.patch.object(sl, "load_results", lambda d: results):
            entries, stats = sl.build_entries("corners", "2026-09-26")
        self.assertEqual(stats["unmatched"], 0, "reversed orientation must not be dropped")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["verdict"], "WON")

    def test_orientation_cannot_change_the_verdict(self):
        """The settled totals are side-symmetric, so folding is verdict-safe."""
        forward = self._actual()
        flipped = self._actual(home_team="B", away_team="A")
        self.assertEqual(forward["total_corners"], flipped["total_corners"])

    def test_pair_key_is_orientation_free(self):
        self.assertEqual(sl.pair_key("A", "B"), sl.pair_key("B", "A"))

    def test_a_different_fixture_is_still_unmatched(self):
        """Folding must not turn every row into a match."""
        results = {(sl.norm_name("X"), sl.norm_name("Y")): self._actual(
            home_team="X", away_team="Y")}
        with mock.patch.object(sl, "load_predictions",
                               lambda k, d: [{"Fixture": "A vs B"}]), \
             mock.patch.object(sl, "load_results", lambda d: results):
            _entries, stats = sl.build_entries("corners", "2026-09-26")
        self.assertEqual(stats["unmatched"], 1)
        self.assertEqual(stats["joined"], 0)


class FixtureColumnAliasTests(unittest.TestCase):
    """Engines disagree on the fixture column name; the ledger must accept all.

    o15 ships 'Match' while corners/sot/gg/o25 ship 'Fixture' or 'fixture'.
    Reading only one name made o15 join ZERO rows for an entire sweep, which
    read as "this market has no data" instead of "wrong column".
    """

    def test_every_alias_resolves(self):
        for column in ("fixture", "Fixture", "Match", "match", "Teams"):
            row = {column: "Atlante vs Monterrey"}
            self.assertEqual(sl.row_fixture_name(row), "Atlante vs Monterrey",
                             column)
            self.assertEqual(sl.row_fixture_key(row),
                             (sl.norm_name("Atlante"), sl.norm_name("Monterrey")),
                             column)

    def test_precedence_prefers_the_real_fixture_column(self):
        row = {"Match": "Ignored vs Other", "fixture": "Atlante vs Monterrey"}
        self.assertEqual(sl.row_fixture_name(row), "Atlante vs Monterrey")

    def test_absent_column_is_empty_not_a_crash(self):
        self.assertEqual(sl.row_fixture_name({}), "")
        self.assertIsNone(sl.row_fixture_key({}))

    def test_o15_style_row_joins_through_build_entries(self):
        """The exact shape that produced 0 joined rows for o15."""
        row = {"Match": "A vs B", "Poisson%": "60", "Grade": "A"}
        actual = {"home_team": "A", "away_team": "B", "has_started": True,
                  "is_finished": True, "score_available": True, "minute": 90,
                  "h_ht": 1, "a_ht": 1, "h_ft": 2, "a_ft": 1, "ft_score": "2-1",
                  "total_goals": 3, "sh_goals": 0, "h_corners": 4, "a_corners": 4,
                  "total_corners": 8, "h_sot": 3, "a_sot": 3, "total_sot": 6,
                  "match_date": "2026-09-26"}
        results = {(sl.norm_name("A"), sl.norm_name("B")): actual}
        with mock.patch.object(sl, "load_predictions", lambda k, d: [row]), \
             mock.patch.object(sl, "load_results", lambda d: results):
            entries, stats = sl.build_entries("o15", "2026-09-26")
        self.assertEqual(stats["unmatched"], 0)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["verdict"], "WON")   # 3 goals >= 2
        self.assertEqual(entries[0]["Poisson"], 60.0)


class LeakageGuardTests(unittest.TestCase):
    """A candidate field must not encode the settled outcome."""

    def test_shvi_signal_fields_exclude_the_stored_score(self):
        """shvi rows carry ft_score/ht_score — that IS the result."""
        row = {"fixture": "A vs B", "ft_score": "1-1", "ht_score": "0-0",
               "shvi_score": 9, "sh_pressure": 250}
        fields = sl.row_signal_fields("shvi", row)
        self.assertNotIn("ft_score", fields)
        self.assertNotIn("ht_score", fields)
        self.assertEqual(fields["shvi_score"], 9.0)

    def test_actual_total_uses_the_right_metric_per_market(self):
        """corners is corners; a goals market must not log total_sot."""
        self.assertEqual(sl.ACTUAL_TOTAL_FIELD["corners"], "total_corners")
        self.assertEqual(sl.ACTUAL_TOTAL_FIELD["o25"], "total_goals")
        self.assertEqual(sl.ACTUAL_TOTAL_FIELD["o15"], "total_goals")


class CompositeBlockTests(unittest.TestCase):
    """Some engines write SEVERAL markets into one file as a list of lists.

    `unders` writes data = [u25_rows, u35_rows]. Reading that with
    load_predictions() returns [] for every date, which is why the whole Unders
    market previously looked like it had no settled history at all.
    """

    def test_list_of_lists_is_read_as_blocks(self):
        u25 = [{"fixture": "A vs B"}, {"fixture": "C vs D"}]
        u35 = [{"fixture": "E vs F"}]
        payload = {"data": [u25, u35]}
        with mock.patch.object(sl, "prediction_path", lambda k, d: __file__), \
             mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(payload))):
            blocks = sl.load_blocks("unders", "2026-01-01")
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0], u25)
        self.assertEqual(blocks[1], u35)

    def test_a_plain_list_of_rows_is_still_one_block(self):
        rows = [{"fixture": "A vs B"}, {"fixture": "C vs D"}]
        payload = {"data": rows}
        with mock.patch.object(sl, "prediction_path", lambda k, d: __file__), \
             mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(payload))):
            blocks = sl.load_blocks("gg_supreme", "2026-01-01")
        self.assertEqual(blocks, [rows])

    def test_malformed_payload_is_empty_not_an_exception(self):
        for bad in ({"data": []}, {"data": None}, {"data": "junk"}, {}):
            with mock.patch.object(sl, "prediction_path", lambda k, d: __file__), \
                 mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(bad))):
                self.assertEqual(sl.load_blocks("unders", "2026-01-01"), [], bad)

    def test_composite_markets_are_not_in_the_one_file_map(self):
        """They must not be registered twice, or the two entries can disagree."""
        for market in sl.BLOCK_INDEX:
            self.assertNotIn(market, sl.MARKETS, market)
        for market in sl.MARKETS:
            self.assertNotIn(market, sl.BLOCK_INDEX, market)
        self.assertEqual(set(sl.ALL_MARKETS), set(sl.MARKETS) | set(sl.BLOCK_INDEX))

    def test_unders_and_draw_blocks_are_registered(self):
        self.assertEqual(sl.BLOCK_INDEX["u25"], ("unders", 0))
        self.assertEqual(sl.BLOCK_INDEX["u35"], ("unders", 1))
        self.assertEqual(sl.BLOCK_INDEX["draw"], ("draw", 0))


class WinSignalTests(unittest.TestCase):
    """win is graded per-ROW against that row's own side, so it IS rankable."""

    def test_win_signals_are_logged(self):
        row = {"fixture": "A vs B", "poisson_win_prob": "71.36%",
               "win_odds": 1.39, "side": "home", "team_name": "A"}
        fields = sl.row_signal_fields("win", row)
        self.assertEqual(fields["poisson_win_prob"], 71.36)
        self.assertEqual(fields["win_odds"], 1.39)

    def test_unders_signals_are_prefixed_per_market(self):
        row = {"fixture": "A vs B", "u25_score": 72, "u35_score": 61,
               "combined_lambda": 1.5, "mc_u25_prob": 0.81}
        self.assertEqual(sl.row_signal_fields("u25", row)["u25_score"], 72.0)
        self.assertEqual(sl.row_signal_fields("u35", row)["u35_score"], 61.0)
        # The other market's score is not even a key in this market's
        # extract, so u35's own number can never be read as a u25 signal.
        self.assertNotIn("u35_score", sl.row_signal_fields("u25", row))
        self.assertNotIn("u25_score", sl.row_signal_fields("u35", row))


if __name__ == "__main__":
    unittest.main()
