"""
The Weekly Tipster board must filter by ONLY what the user typed.

REPORTED AS (2026-10-05)
------------------------
The user cleared every box on the GG board, typed 5 into MIN H2H GG, and got 6
matches. Those 6 were not chosen by their own number: six other rules the board
never showed were still filtering.

THE DEFECT
----------
Two layers filled the blanks:

  api/weekly_filter_live._live_gg  merged GG_PRESETS on top of the user's boxes
                                    with setdefault, so a preset value landed in
                                    every box the user left empty.
  FILTER/gg_precision_filter        started from cfg = dict(USER_FILTER), so any
                                    gate the caller did not mention still had a
                                    number (probability 60, last-3 2-3, table
                                    distance 1-10, home/away side 3).

_live_gg never read params["mode"], so the PUBLIC preset's opinions were applied
to a board that is supposed to hold nothing but the user's own choices.

THE RULE, AS STATED BY THE USER
-------------------------------
  * every match on the board must meet EVERY number typed;
  * a box left empty must not filter anything;
  * typing a second number must not let the first one's matches slip through --
    a new match that does not meet 5 H2H must not appear even if it meets the
    newly typed rule.

Pure unit tests over a synthetic frame. No network, no provider, no artifacts.
"""

import unittest

import pandas as pd

from FILTER.gg_precision_filter import (
    USER_FILTER,
    apply_precision_filter,
    build_gate_config,
)


def tipster_board():
    """A cfg with EVERY gate unset -- what a cleared Tipster board means."""
    return {k: None for k in USER_FILTER}


def slate():
    """Five fixtures, each failing a different rule on purpose.

    columns: h2h, home_side, away_side, last3_home, last3_away, prob, hpos, apos
    """
    spec = [
        ("F0", 5, 3, 3, 2, 2, 70, 3, 5),    # meets everything
        ("F1", 5, 1, 1, 1, 1, 30, 3, 60),   # meets ONLY h2h>=5
        ("F2", 2, 3, 3, 2, 2, 70, 3, 5),    # meets the old preset, not h2h>=5
        ("F3", 5, 1, 1, 1, 1, 30, 3, 60),   # meets only h2h>=5
        ("F4", 5, 3, 3, 2, 2, 70, 1, 20),   # h2h>=5 but 19 places apart
    ]
    return pd.DataFrame([{
        "fixture_id": 100 + i,
        "fixture": name,
        "home_position": r[6], "away_position": r[7],
        "h2h_goal_parity": 1, "concede_parity": 1,
        "gg_prob_pct": r[5],
        "home_gg_last3": r[3], "away_gg_last3": r[4],
        "h2h_gg_count": r[0],
        "home_gg_count": r[1], "away_gg_count": r[2],
        "gg_odds": 2.0,
    } for i, (name, *r) in enumerate(spec)])


def kept(df, cfg, **kw):
    out = apply_precision_filter(df, cfg, strict_mode=kw.pop("strict_mode", True), **kw)
    return sorted(out["fixture"].tolist())


class ClearedBoardFiltersNothingTests(unittest.TestCase):
    def test_empty_board_returns_every_row(self):
        self.assertEqual(kept(slate(), tipster_board()), ["F0", "F1", "F2", "F3", "F4"])

    def test_preset_defaults_do_not_leak_into_a_tipster_board(self):
        """F2 passes the preset but has h2h=2; an empty board must still keep it."""
        cfg = tipster_board()
        for gate in ("min_probability", "last3_gg_min", "last3_gg_max",
                     "pos_diff_min", "pos_diff_max",
                     "home_gg_side_min", "away_gg_side_min"):
            self.assertIsNone(cfg[gate], f"{gate} must be unset on a cleared board")


class EveryTypedNumberMustBeMetTests(unittest.TestCase):
    def test_only_h2h_typed_keeps_exactly_the_h2h_matches(self):
        cfg = tipster_board()
        cfg["h2h_gg_min"] = 5
        self.assertEqual(kept(slate(), cfg), ["F0", "F1", "F3", "F4"])

    def test_a_match_below_the_typed_h2h_never_appears(self):
        cfg = tipster_board()
        cfg["h2h_gg_min"] = 5
        self.assertNotIn("F2", kept(slate(), cfg))

    def test_untyped_rules_do_not_filter(self):
        """F4 is 19 places apart. With no table rule typed it must survive."""
        cfg = tipster_board()
        cfg["h2h_gg_min"] = 5
        self.assertIn("F4", kept(slate(), cfg))

    def test_a_table_rule_typed_now_does_filter(self):
        cfg = tipster_board()
        cfg["h2h_gg_min"] = 5
        cfg["pos_diff_max"] = 10
        self.assertNotIn("F4", kept(slate(), cfg))


class TypedRulesCombineAsAndTests(unittest.TestCase):
    def test_second_rule_must_also_be_met(self):
        """The user's own words: a new type must still meet the H2H number."""
        cfg = tipster_board()
        cfg["h2h_gg_min"] = 5
        cfg["home_gg_side_min"] = 3
        self.assertEqual(kept(slate(), cfg), ["F0", "F4"])

    def test_adding_a_rule_never_widens_the_result(self):
        base = tipster_board(); base["h2h_gg_min"] = 5
        wider = dict(base, home_gg_side_min=3)
        self.assertLessEqual(len(kept(slate(), wider)), len(kept(slate(), base)))

    def test_probability_rule_typed_also_applies(self):
        cfg = tipster_board()
        cfg["min_probability"] = 60
        self.assertEqual(kept(slate(), cfg), ["F0", "F2", "F4"])


class PublicPresetIsUnchangedTests(unittest.TestCase):
    def test_public_preset_still_applies_its_own_rules(self):
        """Public is the shipped opinionated view. It must not be softened."""
        out = apply_precision_filter(slate(), dict(USER_FILTER), strict_mode=True)
        self.assertEqual(sorted(out["fixture"].tolist()), ["F0"])


class SoftModeWithOneTypedRuleTests(unittest.TestCase):
    def test_a_lone_typed_rule_is_absolute(self):
        """"Allow one failure" is meaningless with a single gate -- it would let
        through exactly what the user excluded."""
        cfg = tipster_board()
        cfg["h2h_gg_min"] = 5
        got = kept(slate(), cfg, strict_mode=False)
        self.assertNotIn("F2", got)

    def test_soft_mode_still_allows_one_failure_across_several_rules(self):
        cfg = tipster_board()
        cfg["h2h_gg_min"] = 5
        cfg["home_gg_side_min"] = 3
        cfg["min_probability"] = 60
        # F4 fails the table rule only... which is not typed here, so under the
        # preset-off board F4 meets h2h, home and prob and must be present.
        self.assertIn("F4", kept(slate(), cfg, strict_mode=False))


class EmptyBoardMustNotCrashTests(unittest.TestCase):
    def test_no_layers_combine_safely(self):
        """layers[0] would raise IndexError on a fully cleared board."""
        out = apply_precision_filter(slate(), tipster_board(), strict_mode=True)
        self.assertEqual(len(out), 5)

    def test_empty_board_soft_mode_also_safe(self):
        out = apply_precision_filter(slate(), tipster_board(), strict_mode=False)
        self.assertEqual(len(out), 5)


class ConfigOwnershipTests(unittest.TestCase):
    """THE layer that decides who owns the board.

    This is the exact code that leaked: `cfg = dict(USER_FILTER)` ran for every
    caller, so the public preset's numbers were present even when the Tipster
    board asked for none of them.
    """

    def test_tipster_config_holds_only_what_was_typed(self):
        cfg = build_gate_config({"h2h_gg_min": 5}, use_preset=False)
        active = {k for k, v in cfg.items() if v is not None}
        self.assertEqual(active, {"h2h_gg_min"})

    def test_tipster_config_does_not_carry_any_preset_rule(self):
        cfg = build_gate_config({"h2h_gg_min": 5}, use_preset=False)
        for gate in ("min_probability", "last3_gg_min", "last3_gg_max",
                     "pos_diff_min", "pos_diff_max",
                     "home_gg_side_min", "away_gg_side_min"):
            self.assertIsNone(cfg[gate],
                              f"{gate} leaked from the public preset")

    def test_cleared_tipster_board_has_no_active_gate_at_all(self):
        cfg = build_gate_config({}, use_preset=False)
        self.assertEqual({k for k, v in cfg.items() if v is not None}, set())

    def test_public_config_keeps_every_preset_rule(self):
        cfg = build_gate_config({}, use_preset=True)
        self.assertEqual(cfg, USER_FILTER)

    def test_public_config_still_accepts_a_user_override(self):
        cfg = build_gate_config({"h2h_gg_min": 5}, use_preset=True)
        self.assertEqual(cfg["h2h_gg_min"], 5)
        self.assertEqual(cfg["min_probability"], USER_FILTER["min_probability"])

    def test_none_override_never_overwrites(self):
        cfg = build_gate_config({"h2h_gg_min": None}, use_preset=True)
        self.assertEqual(cfg["h2h_gg_min"], USER_FILTER["h2h_gg_min"])

    def test_unknown_key_is_ignored(self):
        cfg = build_gate_config({"not_a_real_gate": 99}, use_preset=False)
        self.assertNotIn("not_a_real_gate", cfg)


if __name__ == "__main__":
    unittest.main()
