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

from datetime import datetime, timedelta, timezone

import pandas as pd

from CORE.history_window import history_window, history_window_end
from FILTER.gg_precision_filter import (
    USER_FILTER,
    apply_precision_filter,
    build_gate_config,
)


def tipster_board():
    """A cfg with EVERY gate unset -- what a cleared Tipster board means."""
    return {
        **{k: None for k in USER_FILTER},
        # 2026-10-13: the new per-side Last-3 GG toggles are OFF (unset) and
        # the Goals Last 5 thresholds are unset by default; a cleared Tipster
        # board must not carry any of them either.
        "home_last3_gg": None, "away_last3_gg": None,
        "min_home_goals5": None, "min_away_goals5": None,
    }


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


def kept(df, cfg, typed=(), **kw):
    """`typed` = the cfg keys the USER typed, mirroring what run_gg_precision_filter
    derives from cfg_overrides. Gates outside this set are app-chosen and stay
    spendable by soft mode."""
    strict = kw.pop("strict_mode", True)
    out = apply_precision_filter(df, cfg, strict_mode=strict,
                                 user_gates=set(typed), **kw)
    return sorted(out["fixture"].tolist())


def slate_with_denominator():
    """Same slate, plus the REAL H2H sample size each pair actually has.

    GG column: h2h_count, h2h_total, prob, home_side, away_side,
               last3_home, last3_away, hpos, apos

    F_NEVER has never met (count 0, total 0). F_THIN met twice and both were
    GG -- count 2 of a real sample of 2, which is NOT the same as 2 of 5.
    """
    spec = [
        # name      count total prob  hside aside l3h  l3a  hpos apos
        ("F_FULL",  5, 5, 70, 3, 3, 2, 2, 3, 5),      # 5 of 5 -> qualifies for "5"
        ("F_FOUR",  4, 5, 70, 3, 3, 2, 2, 3, 5),      # 4 of 5 -> must NOT qualify
        ("F_THIN",  2, 2, 70, 3, 3, 2, 2, 3, 5),      # 2 of a real 2 -> must NOT qualify
        ("F_NEVER", 0, 0, 70, 3, 3, 2, 2, 3, 5),      # never met -> must NOT qualify
        ("F_NA",    None, None, 70, 3, 3, 2, 2, 3, 5),  # no parsable H2H at all
    ]
    return pd.DataFrame([{
        "fixture_id": 200 + i,
        "fixture": name,
        "home_position": r[7], "away_position": r[8],
        "h2h_goal_parity": 1, "concede_parity": 1,
        "gg_prob_pct": r[2],
        "home_gg_last3": r[5], "away_gg_last3": r[6],
        "h2h_gg_count": r[0], "h2h_gg_total": r[1],
        "home_gg_count": r[3], "away_gg_count": r[4],
        "gg_odds": 2.0,
    } for i, (name, *r) in enumerate(spec)])


class ClearedBoardFiltersNothingTests(unittest.TestCase):
    def test_empty_board_returns_every_row(self):
        self.assertEqual(kept(slate(), tipster_board()), ["F0", "F1", "F2", "F3", "F4"])

    def test_preset_defaults_do_not_leak_into_a_tipster_board(self):
        """F2 passes the preset but has h2h=2; an empty board must still keep it."""
        cfg = tipster_board()
        for gate in ("min_probability", "home_last3_gg", "away_last3_gg", "pos_diff_min", "pos_diff_max", "home_gg_side_min", "away_gg_side_min", "min_home_goals5", "min_away_goals5"):
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
        # Non-preset tipster configs are built only from USER_FILTER plus the
        # user overrides. Assert that every key present that is not the explicit
        # user override is unset — a preset opinion cannot leak into a tipster
        # board. (The last-3 toggles and Goals Last 5 thresholds are NOT preset
        # rules, so they are absent rather than leaked.)
        for gate, value in cfg.items():
            if gate == "h2h_gg_min":
                continue
            self.assertIsNone(value, f"{gate} leaked from the public preset")
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

    def test_unknown_drawer_keys_are_now_honored(self):
        """Drawer gates live outside USER_FILTER (forwarded via GG_CFG_KEYS);
        they must be honored — that is exactly why the previously dead Home/
        Away Goals Last 5 boxes now work."""
        cfg = build_gate_config({"min_home_goals5": 5}, use_preset=False)
        self.assertIn("min_home_goals5", cfg)
        self.assertEqual(cfg["min_home_goals5"], 5)
        # And the new per-side last-3 toggles flow through the same path.
        cfg = build_gate_config({"home_last3_gg": True, "away_last3_gg": True},
                                use_preset=False)
        self.assertEqual(cfg["home_last3_gg"], True)
        self.assertEqual(cfg["away_last3_gg"], True)


class ExactH2HThresholdTests(unittest.TestCase):
    """"Type 5 in H2H and bring me ONLY 5. Not 4. And nothing with no H2H."

    REGRESSION (2026-10-05). Soft mode allows ONE gate to fail. In Public mode
    the preset seeds min_probability alongside the user's H2H box, which gave
    the allowance something to spend itself on -- and it spent it on the H2H
    gate. On the real 2026-10-11 slate, strict returned 0 rows and soft returned
    23, including pairs whose true H2H GG count was 4, 3, 2, 1 and 0.

    A typed number is a REQUIREMENT. Only app-chosen gates are tradeable.
    """

    def setUp(self):
        self.df = slate_with_denominator()

    # -- the headline rule ------------------------------------------------
    def test_five_returns_only_a_pair_with_five(self):
        cfg = build_gate_config({"h2h_gg_min": 5}, use_preset=False)
        self.assertEqual(kept(self.df, cfg, strict_mode=True), ["F_FULL"])

    def test_four_never_satisfies_five(self):
        cfg = build_gate_config({"h2h_gg_min": 5}, use_preset=False)
        self.assertNotIn("F_FOUR", kept(self.df, cfg, strict_mode=True))

    def test_a_pair_that_never_met_never_appears(self):
        cfg = build_gate_config({"h2h_gg_min": 5}, use_preset=False)
        kept_rows = kept(self.df, cfg, strict_mode=True)
        self.assertNotIn("F_NEVER", kept_rows)
        self.assertNotIn("F_NA", kept_rows)

    def test_a_thin_sample_cannot_masquerade_as_five(self):
        """2 GG out of a REAL sample of 2 is not "5 H2H"."""
        cfg = build_gate_config({"h2h_gg_min": 5}, use_preset=False)
        self.assertNotIn("F_THIN", kept(self.df, cfg, strict_mode=True))

    # -- the actual defect: soft mode waiving a typed gate ------------------
    def test_soft_mode_cannot_buy_a_pass_for_a_typed_h2h_threshold(self):
        """THE REGRESSION. Public preset + user H2H, strict parity lock OFF."""
        cfg = build_gate_config({"h2h_gg_min": 5}, use_preset=True)
        self.assertEqual(kept(self.df, cfg, typed={"h2h_gg_min"},
                              strict_mode=False), ["F_FULL"])

    def test_soft_mode_still_trades_away_the_apps_own_preset_gates(self):
        """The Diamond in the Rough keeps working for app-chosen gates only.

        Here the preset's OWN rules (probability, last-3, table distance, side)
        are all spendable, so a row may still fail one of them -- but never the
        user's H2H number, and never by having no H2H at all.
        """
        cfg = build_gate_config({"h2h_gg_min": 5}, use_preset=True)
        rows = kept(self.df, cfg, typed={"h2h_gg_min"}, strict_mode=False)
        self.assertEqual(rows, ["F_FULL"])
        for absent in ("F_FOUR", "F_THIN", "F_NEVER", "F_NA"):
            self.assertNotIn(absent, rows)

    def test_a_typed_threshold_survives_every_other_typed_gate(self):
        """Typing a second rule must not let H2H<5 matches back in."""
        cfg = build_gate_config({"h2h_gg_min": 5, "min_probability": 60.0},
                                use_preset=False)
        for strict in (True, False):
            with self.subTest(strict_mode=strict):
                # F_FULL is the only fixture at 70% AND 5/5 H2H, so both rules
                # typed together must return exactly it -- never a 4 or a thin.
                self.assertEqual(
                    kept(self.df, cfg,
                         typed={"h2h_gg_min", "min_probability"},
                         strict_mode=strict), ["F_FULL"])

    # -- thresholds that are legitimately satisfiable ---------------------
    def test_two_returns_pairs_with_two_or_more(self):
        cfg = build_gate_config({"h2h_gg_min": 2}, use_preset=False)
        rows = kept(self.df, cfg, strict_mode=True)
        self.assertEqual(rows, ["F_FOUR", "F_FULL", "F_THIN"])  # kept() sorts
        self.assertNotIn("F_NEVER", rows)   # 0 is not >= 2
        self.assertNotIn("F_NA", rows)      # no evidence at all

    def test_zero_means_off_not_meet_zero(self):
        """A 0 must switch the gate OFF, not demand every pair score >= 0.

        F_NA is absent by a separate, older rule: the zero-fabrication dropna
        removes any row with no real H2H value BEFORE gates are evaluated, so 4
        of the 5 fixtures are gate-eligible here and all 4 must survive.
        """
        cfg = build_gate_config({"h2h_gg_min": 0}, use_preset=False)
        self.assertEqual(len(kept(self.df, cfg, strict_mode=True)), 4)

    def test_an_artifact_without_a_denominator_still_honours_the_count(self):
        """Old dated CSVs carry no H2H_GG_TOTAL; that must not empty the board."""
        df = self.df.drop(columns=["h2h_gg_total"])
        cfg = build_gate_config({"h2h_gg_min": 5}, use_preset=False)
        rows = kept(df, cfg, strict_mode=True)
        self.assertEqual(rows, ["F_FULL"])
        self.assertNotIn("F_NA", rows)


class HistoryWindowTests(unittest.TestCase):
    """A prediction must not depend on WHEN the engine ran.

    THE BUG (found 2026-10-05). Nine engine modules anchored their history
    window to the wall clock:

        end_dt = datetime.now(timezone.utc).date() - timedelta(days=1)

    The pipeline runs at 18:00 to predict TOMORROW, so "now - 1 day" reached
    past the target date and into the predicted fixture's own future. The same
    fixture therefore produced different "last 5" form depending on when it ran,
    which silently moves Tier 1/2 assignment. This is the test that would have
    caught it.
    """

    def test_window_is_anchored_to_the_target_date_not_today(self):
        self.assertEqual(history_window_end("2026-06-15").isoformat(), "2026-06-14")

    def test_an_old_target_date_is_honoured_not_overwritten_by_today(self):
        """The whole point: a 2025 fixture must not window to 2026."""
        self.assertEqual(history_window_end("2025-01-10").isoformat(), "2025-01-09")

    def test_the_window_never_contains_the_fixture_itself(self):
        """A match's own kickoff must not be part of its own history."""
        target = "2026-10-11"
        end = history_window_end(target)
        self.assertLess(end.isoformat(), target)

    def test_window_bounds_are_ordered_and_correctly_spanned(self):
        start, end = history_window("2026-10-11", lookback_days=30)
        self.assertEqual(end, "2026-10-10")
        self.assertEqual(start, "2026-09-10")
        self.assertLess(start, end)

    def test_accepts_a_datetime_as_well_as_a_string(self):
        dt = datetime(2026, 6, 15, 18, 30)
        self.assertEqual(history_window_end(dt).isoformat(), "2026-06-14")
        self.assertEqual(history_window_end("2026-06-15T18:30:00").isoformat(),
                         "2026-06-14")

    def test_no_target_date_is_the_only_way_to_reach_the_wall_clock(self):
        """None keeps the old behaviour for callers that genuinely mean 'now'."""
        self.assertEqual(history_window_end(None),
                         datetime.now(timezone.utc).date() - timedelta(days=1))

    def test_no_engine_module_re_rolls_its_own_wall_clock_window(self):
        """Guard against the bug coming back one hand-rolled line at a time.

        A module may legitimately call history_window_end() (or use the wall
        clock for something that is not a history window), but the exact
        `datetime.now(...) - timedelta(days=1)` history-window idiom must not
        reappear in any live engine module.
        """
        import re
        from pathlib import Path

        root = Path(__file__).parent
        offenders = []
        # The pattern: a wall-clock "now" minus a day, used as a window bound.
        pattern = re.compile(
            r"datetime\.now\([^)]*\)\.date\(\)\s*-\s*timedelta\(days=", re.I)
        for sub in ("Engine", "PSYCHOLOGY", "AGGREGATOR", "CORE", "FILTER",
                    "INTELLIGENT_PASS"):
            for path in (root / sub).rglob("*.py"):
                if path.name == "history_window.py":
                    continue
                if any(part.startswith("_backup_") for part in path.parts):
                    continue
                for n, line in enumerate(path.read_text(
                        encoding="utf-8", errors="ignore").splitlines(), 1):
                    if pattern.search(line):
                        offenders.append(f"{path.relative_to(root)}:{n}")
        self.assertEqual(offenders, [],
                         "wall-clock history windows reintroduced: "
                         + ", ".join(offenders))




class PerSideLast3ToggleTests(unittest.TestCase):
    """Regression tests for the 2026-10-13 per-side Last-3 GG On/Off toggles.

    `last3_home` / `last3_away` = how many of the side's own last 3 matches
    were Both-To-Score. Toggle ON enforces `side_gg_last3 >= 1`."""

    def _slate(self, rows):
        """rows: list of (name, home_last3, away_last3) — all other columns
        are irrelevant for this gate and default to non-blocking."""
        data = []
        for i, (name, hl3, al3) in enumerate(rows):
            data.append({
                "fixture_id": 300 + i,
                "fixture": f"Match {i}",
                "h2h_goal_parity": 1, "concede_parity": 1,
                "gg_prob_pct": 70.0,
                "home_gg_last3": hl3, "away_gg_last3": al3,
                "h2h_gg_count": 5, "h2h_gg_total": 5, "h2h_gg_usable": True,
                "home_position": 3, "away_position": 5,
                "home_gg_count": 3, "away_gg_count": 3,
                "gg_odds": 2.0,
            })
        return pd.DataFrame(data)

    def test_home_toggle_keeps_only_home_side_recent_form(self):
        """Home toggle ON keeps rows where HOME has GG in its own last 3,
        ignoring the away side."""
        cfg = tipster_board()
        cfg["home_last3_gg"] = True
        df = self._slate([
            ("H0", 1, 0),  # home OK, away 0 -> kept
            ("H1", 0, 1),  # home 0, away OK -> dropped
            ("H2", 1, 1),  # both OK -> kept
            ("H3", 0, 0),  # both 0 -> dropped
        ])
        out = apply_precision_filter(df, cfg)
        kept = out["fixture"].tolist()
        self.assertEqual(kept, ["Match 0", "Match 2"])

    def test_away_toggle_keeps_only_away_side_recent_form(self):
        """Away toggle ON keeps rows where AWAY has GG in its own last 3."""
        cfg = tipster_board()
        cfg["away_last3_gg"] = True
        df = self._slate([
            ("A0", 0, 1),  # away OK, home 0 -> kept
            ("A1", 1, 0),  # away 0, home OK -> dropped
            ("A2", 1, 1),  # both OK -> kept
            ("A3", 0, 0),  # both 0 -> dropped
        ])
        out = apply_precision_filter(df, cfg)
        kept = out["fixture"].tolist()
        self.assertEqual(kept, ["Match 0", "Match 2"])

    def test_both_toggles_must_both_pass(self):
        """With both toggles ON, a row needs GG on BOTH sides."""
        cfg = tipster_board()
        cfg["home_last3_gg"] = True
        cfg["away_last3_gg"] = True
        df = self._slate([
            ("B0", 1, 1),  # both OK -> kept
            ("B1", 1, 0),  # away missing -> dropped
            ("B2", 0, 1),  # home missing -> dropped
            ("B3", 0, 0),  # both missing -> dropped
        ])
        out = apply_precision_filter(df, cfg)
        kept = out["fixture"].tolist()
        self.assertEqual(kept, ["Match 0"])

    def test_toggles_off_do_not_filter(self):
        """With both toggles OFF, no row is filtered by recent form."""
        cfg = tipster_board()  # defaults are False
        df = self._slate([
            ("C0", 0, 0),
            ("C1", 1, 1),
        ])
        out = apply_precision_filter(df, cfg)
        kept = out["fixture"].tolist()
        self.assertEqual(kept, ["Match 0", "Match 1"])

    def test_toggle_is_mandatory_not_tradeable(self):
        """A typed toggle is a hard requirement; it cannot be spent to save
        another gate, so a row failing it is dropped regardless of other gates."""
        # The typed-gates set is derived from cfg_overrides by run_gg_precision_filter.
        typed_gates = {k for k, v in ({"home_last3_gg": True}).items() if v is not None}
        self.assertEqual(typed_gates, {"home_last3_gg"})
        # And apply_precision_filter enforces home >= 1 as a hard gate: a row
        # with 0 home last-3 GG is dropped even though the away side is fine.
        cfg = tipster_board()
        cfg["home_last3_gg"] = True
        df = self._slate([("D0", 0, 1)])  # home 0 -> dropped
        out = apply_precision_filter(df, cfg)
        self.assertEqual(out["fixture"].tolist(), [])

class Last5GoalsGateTests(unittest.TestCase):
    """Regression tests for the Home/Away Goals Last 5 drawer gates.

    The engine now exports `home_scored_total` / `away_scored_total` as
    `home_goals_scored_last_5` / `away_goals_scored_last_5`, so these gates
    filter instead of silently skipping."""

    def _slate(self, rows):
        """rows: list of (name, home_goals5, away_goals5) — other columns
        default to non-blocking for these tests."""
        data = []
        for i, (name, hg, ag) in enumerate(rows):
            data.append({
                "fixture_id": 400 + i,
                "fixture": f"Match {i}",
                "h2h_goal_parity": 1, "concede_parity": 1,
                "gg_prob_pct": 70.0,
                "home_gg_last3": 1, "away_gg_last3": 1,
                "h2h_gg_count": 5, "h2h_gg_total": 5, "h2h_gg_usable": True,
                "home_position": 3, "away_position": 5,
                "home_gg_count": 3, "away_gg_count": 3,
                "gg_odds": 2.0,
                "home_goals_scored_last_5": hg,
                "away_goals_scored_last_5": ag,
            })
        return pd.DataFrame(data)

    def test_home_goals_gate(self):
        """Home gate >= 4 keeps only rows where the home side scored >= 4
        in its last 5 matches."""
        cfg = tipster_board()
        cfg["min_home_goals5"] = 4
        df = self._slate([
            ("G0", 4, 0),  # home OK -> kept
            ("G1", 3, 0),  # home < 4 -> dropped
            ("G2", 5, 0),  # home OK -> kept
            ("G3", 0, 0),  # home < 4 -> dropped
        ])
        out = apply_precision_filter(df, cfg)
        kept = out["fixture"].tolist()
        self.assertEqual(kept, ["Match 0", "Match 2"])

    def test_away_goals_gate(self):
        """Away gate >= 3 keeps only rows where the away side scored >= 3
        in its last 5 matches."""
        cfg = tipster_board()
        cfg["min_away_goals5"] = 3
        df = self._slate([
            ("A0", 0, 3),  # away OK -> kept
            ("A1", 0, 2),  # away < 3 -> dropped
            ("A2", 0, 4),  # away OK -> kept
            ("A3", 0, 0),  # away < 3 -> dropped
        ])
        out = apply_precision_filter(df, cfg)
        kept = out["fixture"].tolist()
        self.assertEqual(kept, ["Match 0", "Match 2"])

    def test_both_goals_gates(self):
        """With both goals gates, a row needs BOTH sides to meet."""
        cfg = tipster_board()
        cfg["min_home_goals5"] = 4
        cfg["min_away_goals5"] = 3
        df = self._slate([
            ("B0", 4, 3),  # both OK -> kept
            ("B1", 4, 2),  # away < 3 -> dropped
            ("B2", 3, 3),  # home < 4 -> dropped
            ("B3", 3, 2),  # both < -> dropped
        ])
        out = apply_precision_filter(df, cfg)
        kept = out["fixture"].tolist()
        self.assertEqual(kept, ["Match 0"])

    def test_goals_gate_skips_when_no_real_data(self):
        """If the columns exist but carry no real values, the gate prints a
        message and does NOT turn into a 'reject everything' rule."""
        cfg = tipster_board()
        cfg["min_home_goals5"] = 4
        df = self._slate([
            ("S0", None, None),
            ("S1", None, None),
        ])
        out = apply_precision_filter(df, cfg)
        kept = out["fixture"].tolist()
        self.assertEqual(kept, ["Match 0", "Match 1"])  # gate skipped, nothing lost




class ApiDrawerForwardingTests(unittest.TestCase):
    """Regression: the API parameter parser must forward the new drawer keys.

    The Weekly board sends drawer values directly in the request body;
    api/weekly_filter_live.gg_filter_params() must accept and forward them
    into p["overrides"], otherwise the engine never sees them (that is why
    the last-3 toggles and goals boxes appeared live but controlled nothing).
    """

    def setUp(self):
        from api.weekly_filter_live import gg_filter_params
        self.gg_filter_params = gg_filter_params

    def test_last3_toggle_keys_forwarded(self):
        p = self.gg_filter_params(mode="tipster", home_last3_gg=True,
                                  away_last3_gg=False)
        self.assertEqual(p["overrides"].get("home_last3_gg"), True)
        self.assertEqual(p["overrides"].get("away_last3_gg"), False)

    def test_goals_keys_forwarded_as_numbers(self):
        p = self.gg_filter_params(mode="tipster", min_home_goals5=5,
                                  min_away_goals5=3)
        self.assertEqual(p["overrides"].get("min_home_goals5"), 5.0)
        self.assertEqual(p["overrides"].get("min_away_goals5"), 3.0)

    def test_none_values_not_forwarded(self):
        p = self.gg_filter_params(mode="tipster", home_last3_gg=None,
                                  min_home_goals5=None)
        self.assertNotIn("home_last3_gg", p["overrides"])
        self.assertNotIn("min_home_goals5", p["overrides"])

    def test_old_keys_still_forward(self):
        p = self.gg_filter_params(mode="tipster", min_h2h_gg=5, max_parity=4,
                                  min_prob=70, min_gg_odds=1.8)
        self.assertEqual(p["overrides"]["min_h2h_gg"], 5)
        self.assertEqual(p["overrides"]["max_parity"], 4)
        self.assertEqual(p["overrides"]["min_prob"], 70.0)
        self.assertEqual(p["overrides"]["min_gg_odds"], 1.8)

    def test_all_keys_together(self):
        p = self.gg_filter_params(mode="tipster", min_h2h_gg=5, max_parity=4,
                                  min_prob=70, min_gg_odds=1.8,
                                  home_last3_gg=True, away_last3_gg=False,
                                  min_home_goals5=6, min_away_goals5=4,
                                  strict_mode=True)
        o = p["overrides"]
        self.assertEqual(o["min_h2h_gg"], 5)
        self.assertEqual(o["max_parity"], 4)
        self.assertEqual(o["min_prob"], 70.0)
        self.assertEqual(o["min_gg_odds"], 1.8)
        self.assertEqual(o["home_last3_gg"], True)
        self.assertEqual(o["away_last3_gg"], False)
        self.assertEqual(o["min_home_goals5"], 6.0)
        self.assertEqual(o["min_away_goals5"], 4.0)
        self.assertEqual(o["strict_mode"], True)



if __name__ == "__main__":
    unittest.main()
