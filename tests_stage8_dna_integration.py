"""Focused regression tests for Stage 8 DNA intelligence integration.

Tests that the live prediction engine correctly:
  1. Loads DNA profiles + style clashes into the context.
  2. Computes team-specific goal-timing factors from HT scoring rates.
  3. Expands the structural shift with DNA pillar edges.
  4. Produces new trace questions for archetypes, HT habits, and clash edges.
  5. Includes DNA context in the prediction log and output.

These tests use synthetic boards + real data files (DNA profiles, style clashes,
danger audit, prematch audit).  No network, no live service.
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from LIVE_SCANNER import live_stage8_live_prediction as s8
from LIVE_SCANNER import live_prediction_questions as q
from LIVE_SCANNER.live_stage8_live_prediction import _as_rows


def _load_real(fpath, default=None):
    if not os.path.exists(fpath):
        return default
    with open(fpath, encoding="utf-8") as f:
        return json.load(f)


class TestTimingFactor(unittest.TestCase):
    """_team_timing_factor and time_remaining_share with DNA."""

    def test_no_dna_returns_one(self):
        ctx = {"dna": {"available": False}}
        self.assertEqual(s8._team_timing_factor(ctx), 1.0)

    def test_league_average_returns_one(self):
        gv = {"scored_at_ht_rate": 0.45, "conceded_at_ht_rate": 0.45,
              "ht_coverage": 1.0}
        ctx = {"dna": {"available": True,
                       "home": {"available": True, "insufficient_data": False,
                                "goal_volume": gv},
                       "away": {"available": True, "insufficient_data": False,
                                "goal_volume": gv}}}
        self.assertAlmostEqual(s8._team_timing_factor(ctx), 1.0, places=1)

    def test_high_ht_rate_increases_factor(self):
        gv = {"scored_at_ht_rate": 0.60, "conceded_at_ht_rate": 0.60,
              "ht_coverage": 1.0}
        ctx = {"dna": {"available": True,
                       "home": {"available": True, "insufficient_data": False,
                                "goal_volume": gv},
                       "away": {"available": True, "insufficient_data": False,
                                "goal_volume": gv}}}
        factor = s8._team_timing_factor(ctx)
        self.assertGreater(factor, 1.0)
        self.assertLessEqual(factor, 1.4)

    def test_low_ht_rate_decreases_factor(self):
        gv = {"scored_at_ht_rate": 0.20, "conceded_at_ht_rate": 0.20,
              "ht_coverage": 1.0}
        ctx = {"dna": {"available": True,
                       "home": {"available": True, "insufficient_data": False,
                                "goal_volume": gv},
                       "away": {"available": True, "insufficient_data": False,
                                "goal_volume": gv}}}
        factor = s8._team_timing_factor(ctx)
        self.assertLess(factor, 1.0)
        self.assertGreaterEqual(factor, 0.7)

    def test_low_coverage_skipped(self):
        gv = {"scored_at_ht_rate": 0.60, "conceded_at_ht_rate": 0.60,
              "ht_coverage": 0.5}
        ctx = {"dna": {"available": True,
                       "home": {"available": True, "insufficient_data": False,
                                "goal_volume": gv},
                       "away": {"available": True, "insufficient_data": False,
                                "goal_volume": gv}}}
        self.assertEqual(s8._team_timing_factor(ctx), 1.0)

    def test_timing_adjusts_remaining_share(self):
        share_normal = s8.time_remaining_share(45, 1.0)
        share_early = s8.time_remaining_share(45, 1.3)
        self.assertLess(share_early, share_normal)

    def test_timing_adjusts_later_minute(self):
        share_normal = s8.time_remaining_share(30, 1.0)
        share_late = s8.time_remaining_share(30, 0.7)
        self.assertGreater(share_late, share_normal)

    def test_timing_factor_one_preserves_league_knots(self):
        for minute in [0, 15, 30, 45, 60, 75]:
            self.assertAlmostEqual(
                s8.time_remaining_share(minute, 1.0),
                s8.time_remaining_share(minute),
                places=6,
            )


class TestStructuralShiftDNA(unittest.TestCase):
    """_structural_shift with DNA pillar edges."""

    def test_no_dna_no_extra_shift(self):
        ctx = {"dna": {"available": False}}
        shift, supporting = s8._structural_shift(ctx, [])
        self.assertEqual(shift, 0.0)
        self.assertEqual(supporting, [])

    def test_dna_pillar_home_dominance_positive_shift(self):
        clash = {"available": True, "edges": {
            "Box_Dominance": {"home": 90, "away": 50, "edge": "Home", "margin": "Clear"},
            "Goal_Intent": {"home": 85, "away": 45, "edge": "Home", "margin": "Clear"},
            "BTTS_Friction": {"home": 70, "away": 30, "edge": "Home", "margin": "Clear"},
        }}
        ctx = {"dna": {"available": True, "clash": clash}}
        shift, supporting = s8._structural_shift(ctx, [])
        self.assertGreater(shift, 0.0)
        self.assertLessEqual(shift, s8.MAX_STRUCTURAL_SHIFT)
        self.assertIn("dna_pillar_Box_Dominance", supporting)
        self.assertIn("dna_pillar_Goal_Intent", supporting)

    def test_dna_pillar_away_dominance_negative_shift(self):
        clash = {"available": True, "edges": {
            "Box_Dominance": {"home": 50, "away": 90, "edge": "Away", "margin": "Clear"},
            "Goal_Intent": {"home": 45, "away": 85, "edge": "Away", "margin": "Clear"},
            "BTTS_Friction": {"home": 30, "away": 70, "edge": "Away", "margin": "Clear"},
        }}
        ctx = {"dna": {"available": True, "clash": clash}}
        shift, supporting = s8._structural_shift(ctx, [])
        self.assertLess(shift, 0.0)
        self.assertGreaterEqual(shift, -s8.MAX_STRUCTURAL_SHIFT)

    def test_dna_pillar_capped(self):
        clash = {"available": True, "edges": {
            "Box_Dominance": {"home": 100, "away": 0, "edge": "Home", "margin": "Clear"},
            "Goal_Intent": {"home": 100, "away": 0, "edge": "Home", "margin": "Clear"},
            "BTTS_Friction": {"home": 100, "away": 0, "edge": "Home", "margin": "Clear"},
        }}
        ctx = {"dna": {"available": True, "clash": clash}}
        shift, supporting = s8._structural_shift(ctx, [])
        self.assertLessEqual(shift, s8.DNA_PILLAR_SHIFT_WEIGHT + 1e-9)
        self.assertGreater(shift, 0.0)

    def test_dna_neutral_pillars_no_shift(self):
        clash = {"available": True, "edges": {
            "Box_Dominance": {"home": 50, "away": 50, "edge": "Neutral"},
            "Goal_Intent": {"home": 50, "away": 50, "edge": "Neutral"},
        }}
        ctx = {"dna": {"available": True, "clash": clash}}
        shift, supporting = s8._structural_shift(ctx, [])
        self.assertEqual(shift, 0.0)


class TestTraceQuestions(unittest.TestCase):

    _CTX = {
        "board": {"id": 1, "name": "H vs A", "minute": "45", "score": "1-0",
                  "is_finished": False, "statistics": {
                      "home": {"goals": 1, "shots-on-target": 3,
                               "dangerous-attacks": 45, "xG": 1.2},
                      "away": {"goals": 0, "shots-on-target": 1,
                               "dangerous-attacks": 22, "xG": 0.5},
                  }, "h_xg": 1.2, "a_xg": 0.5, "h_pressure": 65, "a_pressure": 35},
        "danger": {"available": True, "home_name": "Home", "away_name": "Away",
                   "home_team": {}, "away_team": {}},
        "odds": {"home": 2.0, "draw": 3.4, "away": 3.8,
                 "over25": 2.0, "under25": 1.85},
        "score": {"home": 1, "away": 0},
        "mode": "FULL",
    }

    def test_new_question_ids_present(self):
        ctx = dict(self._CTX)
        ctx["dna"] = {"available": True,
                      "home": {"available": True, "archetype": "Test Archer",
                               "pillars": {"Box_Dominance": 70, "Goal_Intent": 60,
                                           "BTTS_Friction": 50, "Corner_Power": 40,
                                           "Win_Dominance": 80},
                               "goal_volume": {"scored_at_ht_rate": 0.5,
                                               "conceded_at_ht_rate": 0.4,
                                               "ht_coverage": 1.0}},
                      "away": {"available": True, "archetype": "Test Defender",
                               "pillars": {"Box_Dominance": 50, "Goal_Intent": 55,
                                           "BTTS_Friction": 60, "Corner_Power": 40,
                                           "Win_Dominance": 70},
                               "goal_volume": {"scored_at_ht_rate": 0.3,
                                               "conceded_at_ht_rate": 0.5,
                                               "ht_coverage": 1.0}},
                      "clash": {"available": True,
                                "overall_edge": "Home",
                                "edges": {"Box_Dominance": {"home": 70, "away": 50,
                                                            "edge": "Home"},
                                          "Goal_Intent": {"home": 60, "away": 55,
                                                          "edge": "Home"},
                                          "BTTS_Friction": {"home": 50, "away": 60,
                                                            "edge": "Away"}}}}
        trace = q.build_trace(ctx)
        qids = {x["id"] for x in trace}
        expected = {"dna_archetype_home", "dna_archetype_away",
                    "ht_scoring_habit_home", "ht_scoring_habit_away",
                    "style_clash_edge", "dna_pillar_edge"}
        missing = expected - qids
        self.assertEqual(missing, set(), f"Missing DNA questions: {missing}")

    def test_dna_archetype_question_values(self):
        ctx = dict(self._CTX)
        ctx["dna"] = {"available": True,
                      "home": {"available": True, "archetype": "High-Friction Chaos (GG/OVER)",
                               "pillars": {"Box_Dominance": 78, "Goal_Intent": 53,
                                           "BTTS_Friction": 72},
                               "goal_volume": {"scored_at_ht_rate": 0.25,
                                               "conceded_at_ht_rate": 0.375,
                                               "ht_coverage": 1.0}},
                      "away": {"available": True, "archetype": "Box Predator (OVER/GG)",
                               "pillars": {"Box_Dominance": 80, "Goal_Intent": 58,
                                           "BTTS_Friction": 51},
                               "goal_volume": {"scored_at_ht_rate": 0.38,
                                               "conceded_at_ht_rate": 0.38,
                                               "ht_coverage": 1.0}},
                      "clash": {"available": True,
                                "overall_edge": "Contested",
                                "edges": {"Box_Dominance": {"home": 80, "away": 82,
                                                            "edge": "Neutral"},
                                          "Goal_Intent": {"home": 58, "away": 55,
                                                          "edge": "Neutral"},
                                          "BTTS_Friction": {"home": 72, "away": 51,
                                                            "edge": "Home"}},
                                "market_signals": {"Over_Under": "STRONG OVER",
                                                   "GG_NoGG": "LEAN GG"}}}
        trace = q.build_trace(ctx)
        arche_q = next(x for x in trace if x["id"] == "dna_archetype_home")
        self.assertTrue(arche_q["available"])
        self.assertIn("High-Friction Chaos", arche_q["answer"])

        habit_q = next(x for x in trace if x["id"] == "ht_scoring_habit_home")
        self.assertTrue(habit_q["available"])
        self.assertIn("25%", habit_q["answer"])

        clash_q = next(x for x in trace if x["id"] == "style_clash_edge")
        self.assertTrue(clash_q["available"])
        self.assertIn("Contested", clash_q["answer"])
        self.assertIn("STRONG OVER", clash_q["answer"])

    def test_dna_questions_absent_when_no_dna(self):
        """When dna is not in ctx, questions should be unavailable not crash."""
        ctx = dict(self._CTX)
        trace = q.build_trace(ctx)
        qids = {x["id"] for x in trace}
        for qid in ("dna_archetype_home", "dna_archetype_away",
                    "ht_scoring_habit_home", "ht_scoring_habit_away",
                    "style_clash_edge", "dna_pillar_edge"):
            self.assertIn(qid, qids)
            quest = next(x for x in trace if x["id"] == qid)
            self.assertFalse(quest["available"],
                             f"{qid} should be unavailable when no DNA")


class TestDNALoadingRealData(unittest.TestCase):
    """load_context correctly loads DNA from real data files."""

    def test_dna_profile_loaded_from_danger_audit_ids(self):
        board = [{"id": 19872636, "fixture_id": 19872636,
                  "name": "LASK vs Liverpool", "minute": "45",
                  "is_finished": False, "statistics": {},
                  "h_xg": 1.2, "a_xg": 0.5, "h_pressure": 65, "a_pressure": 35}]
        danger_rows = _load_real(os.path.join(s8.DATA_DIR, "danger_audit.json"), [])
        pm_data = _load_real(s8.PREMATCH_FILE, {})
        pm_rows = _as_rows(pm_data) if isinstance(pm_data, dict) else pm_data
        dna_cache = _load_real(s8.DNA_PROFILES_FILE, {})
        clash_cache = _as_rows(_load_real(s8.STYLE_CLASHES_FILE, []))

        ctx = s8.load_context(19872636, board, _as_rows(danger_rows), pm_rows,
                              dna_cache, clash_cache)
        self.assertIsNotNone(ctx)
        self.assertTrue(ctx["dna"]["available"])
        home = ctx["dna"].get("home")
        self.assertIsNotNone(home)
        self.assertTrue(home["available"])
        self.assertEqual(home["archetype"], "Set-Piece Specialist (CORNERS)")
        gv = home["goal_volume"]
        self.assertIsNotNone(gv["scored_at_ht_rate"])
        self.assertIsNotNone(gv["conceded_at_ht_rate"])


class TestPredictionLogDNAFields(unittest.TestCase):
    """Prediction log includes DNA context fields."""

    def test_log_source_has_dna_fields(self):
        import inspect
        src = inspect.getsource(s8.run_live_prediction_engine)
        self.assertIn("dna_available", src)
        self.assertIn("home_archetype", src)
        self.assertIn("away_archetype", src)
        self.assertIn("timing_factor", src)
        self.assertIn("market_signals", src)

    def test_return_has_dna_fields(self):
        import inspect
        src = inspect.getsource(s8.predict)
        self.assertIn("dna_available", src)
        self.assertIn("home_archetype", src)
        self.assertIn("away_archetype", src)
        self.assertIn("overall_structural_edge", src)
        self.assertIn("market_signals", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)

