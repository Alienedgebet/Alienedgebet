"""Offline regression tests for the live scanner stage contracts.

These tests use synthetic provider-shaped payloads and temporary files only. They
never call SportMonks, run a scanner cycle, write production artifacts, or
restart the live service.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import live_cache
import notifications as notify
from LIVE_SCANNER import live_stage2_verification as stage2


def _patch_notify_paths(tmp):
    """
    Redirect every notification file into a temp dir.

    Notification tests must never write to the live data/ or output/
    directories, or running the suite would create real subscriptions and
    events that the running scanner would then try to deliver.
    """
    notify.OUTPUT_DIR = tmp
    notify.DATA_DIR = tmp
    notify.EVENTS_FILE = os.path.join(tmp, "push_events.jsonl")
    notify.SUBS_FILE = os.path.join(tmp, "push_subscriptions.json")
    notify.SENT_FILE = os.path.join(tmp, "push_sent.json")
    notify.DELIVERED_FILE = os.path.join(tmp, "push_delivered.json")
from LIVE_SCANNER import live_stage4_danger as stage4
from LIVE_SCANNER import live_stage3_incoming as stage3
from LIVE_SCANNER import live_signed_impact as si
from LIVE_SCANNER import live_stage5_aggregator as stage5
from LIVE_SCANNER import live_stage6_alerts as stage6
from LIVE_SCANNER import user_rules_store as rules
from api import main as api_main
from LIVE_SCANNER import live_state_classifier as classifier

# Shared, minimal live payloads for the user-rule contracts. Enough for
# `analyze_match_state`-shaped intel to be read without raising; deliberately
# NOT a real cycle's output, because these tests assert gate logic, not engine
# output.
_INTEL = {
    "match": {
        "confidence_score": 80,
        "h_pressure_share": 60.0,
        "a_pressure_share": 40.0,
        "chaos_index": 12.0,
    },
    "home": {"live_xg": 1.2, "sot": 4, "corn": 3, "da": 30},
    "away": {"live_xg": 0.8, "sot": 2, "corn": 1, "da": 20},
}
_KEY_LOSS = {"h_lost": 0, "a_lost": 0}


class IncomingReasonContractTests(unittest.TestCase):
    """The reason text a user reads must agree with the number beside it."""

    def test_a_positive_net_is_described_as_quality_lost(self):
        """
        REGRESSION: one hardcoded literal for every rotation pick.

        The reason used to read "the players who left were no better than the
        ones now starting" regardless of sign. `live_signed_impact` defines
        net > 0 as quality LOST, so a +15.3 row was asserting a large loss in
        the same sentence that denied one.
        """
        text = stage3._describe_rotation(
            {"verdict": "DANGER", "net_impact": 15.3, "confidence": 0.80})
        self.assertIn("BETTER", text,
                      "a positive net means the players who left were better")
        self.assertNotIn("no better", text)
        self.assertIn("lost quality", text)

    def test_a_negative_net_is_described_as_an_upgrade(self):
        text = stage3._describe_rotation(
            {"verdict": "BLESSING", "net_impact": -8.6, "confidence": 0.65})
        self.assertIn("WORSE", text,
                      "a negative net means the players who left were worse")
        self.assertIn("upgraded", text)

    def test_thin_evidence_says_so_instead_of_claiming_a_direction(self):
        """
        Most rotation picks on the live board sit below the call floor, where
        the signed verdict itself declines to call a direction. The sentence
        must not assert a quality comparison the engine did not make.
        """
        text = stage3._describe_rotation(
            {"verdict": "ROTATION", "net_impact": 11.4, "confidence": 0.00})
        self.assertIn("too thin", text)
        self.assertNotIn("BETTER", text)
        self.assertNotIn("WORSE", text)

    def test_the_stated_number_and_confidence_match_the_side(self):
        for net, conf in ((15.3, 0.39), (-2.0, 0.68), (0.0, 0.50)):
            text = stage3._describe_rotation(
                {"verdict": "ROTATION", "net_impact": net,
                 "confidence": conf})
            self.assertIn(f"{net:+.1f}", text)
            self.assertIn(f"{conf:.2f}", text)

    def test_junk_inputs_never_raise(self):
        """A malformed side must still render a sentence, not crash the feed."""
        for side in ({"verdict": None, "net_impact": None, "confidence": None},
                     {"verdict": "ROTATION"},
                     {"verdict": "BLESSING", "net_impact": "x",
                      "confidence": "y"},
                     {"verdict": "ROTATION", "net_impact": float("nan"),
                      "confidence": 0.5}):
            with self.subTest(side=side):
                self.assertTrue(stage3._describe_rotation(side).strip())


class LiveScannerContractTests(unittest.TestCase):
    def test_stage4_uses_participant_location_not_array_order(self):
        parts = [
            {"id": 2, "name": "Away", "meta": {"location": "away"}},
            {"id": 1, "name": "Home", "meta": {"location": "home"}},
        ]
        home, away = stage4.resolve_participants(parts)
        self.assertEqual((home["id"], away["id"]), (1, 2))
        self.assertIsNone(stage4.resolve_participants([{"id": 1}])[0])

    def test_stage4_style_keeps_missing_da_unavailable(self):
        unavailable = stage4.compute_style_analysis([], 1)
        self.assertFalse(unavailable["available"])
        self.assertIsNone(unavailable["da"])

        history = [{
            "statistics": [{
                "participant_id": 1,
                "type": {"name": "Dangerous Attacks"},
                "data": {"value": 40},
            }]
        }]
        available = stage4.compute_style_analysis(history, 1)
        self.assertTrue(available["available"])
        self.assertEqual(available["da"], 40.0)
        self.assertEqual(available["label"], "Attacking")

    def test_stage4_history_request_includes_statistics(self):
        response = {"data": []}
        with patch.object(stage4, "GET", return_value=response) as get, \
             patch.object(stage4, "_history_cache", {}):
            stage4.get_key_players_forensics(1)
        include = get.call_args.kwargs["params"]["include"]
        self.assertIn("statistics", include)
        self.assertIn("statistics.type", include)

    def test_a_full_strength_xi_scores_zero_net_impact(self):
        """
        THE DEFINING PROPERTY OF THE SIGNED VERDICT.

        `net_impact` is documented as the damage done by ABSENCES. If nobody is
        absent, the damage is zero, so the number must be zero. It was not: the
        replacement group was built as the survivors (the key eleven minus the
        absentee), whose offset measures how good the whole starting XI is
        against the 6.8 baseline. On the 2026-09-29 board that made a
        zero-absence side score -9.43..+14.22 and drove corr(net, absentee) to
        -0.131, i.e. the metric was ranking squad quality and calling it
        rotation.
        """
        good_squad = [{"name": f"P{i}", "pos": "Midfielder",
                       "avg_rating": 7.1, "apps": 9, "mins": 800}
                      for i in range(10)]
        weak_squad = [{"name": f"W{i}", "pos": "Midfielder",
                       "avg_rating": 6.2, "apps": 9, "mins": 800}
                      for i in range(10)]

        for squad in (good_squad, weak_squad):
            with self.subTest(squad=squad[0]["avg_rating"]):
                result = si.assess_absence([], squad, regime="MID_FIELD")
                self.assertEqual(result["net_impact"], 0.0)
                self.assertEqual(result["verdict"], si.STATE_UNKNOWN)

    def test_the_replacement_group_is_not_the_survivors(self):
        """
        Losing one good player and replacing him with a worse one is DAMAGE.
        Scoring the survivors instead of the replacements made the sign depend
        on the quality of the remaining XI instead of the swap, which is how a
        strong squad was labelled BLESSING while Oyarzabal, Porro and Pedri
        were the absentees (Spain, 2026-09-29).
        """
        absent = [{"name": "Star", "pos": "Midfielder",
                   "avg_rating": 7.5, "apps": 9, "mins": 800}]
        survivors = [{"name": f"S{i}", "pos": "Midfielder",
                      "avg_rating": 6.8, "apps": 9, "mins": 800}
                     for i in range(10)]
        replacements = [{"name": "Academy", "pos": "Midfielder",
                         "avg_rating": 6.3, "apps": 9, "mins": 800}]

        honest = si.assess_absence(absent, replacements, regime="MID_FIELD")
        survivors_only = si.assess_absence(absent, survivors, regime="MID_FIELD")

        # A drop from 7.5 to 6.3 is real damage, so the sign must be positive
        # (DANGER side) under the honest comparison.
        self.assertGreater(honest["net_impact"], 0.0)
        # The survivor group dilutes it, and can even flip the sign.
        self.assertLess(survivors_only["net_impact"], honest["net_impact"])

    def test_an_unrated_replacement_contributes_nothing_rather_than_being_guessed(self):
        """
        Absence of evidence is not evidence of quality. A replacement with no
        observed rating must score zero, not a fabricated 6.0 that would read as
        exactly average and drag the verdict toward zero.
        """
        absent = [{"name": "Star", "pos": "Midfielder",
                   "avg_rating": 7.5, "apps": 9, "mins": 800}]
        unrated = [{"name": "New signing", "pos": "Midfielder",
                    "avg_rating": None, "apps": 0, "mins": 0}]

        result = si.assess_absence(absent, unrated, regime="MID_FIELD")
        self.assertEqual(result["replacement_credit"], 0.0)
        self.assertEqual(result["quality_lost"], result["net_impact"])

    def test_the_recall_window_can_actually_produce_a_qualified_player(self):
        """
        The window must be deep enough for `confidence()` to reach a verdict.

        `confidence()` needs FULL_CONFIDENCE_APPS = 8 appearances before a
        player's rating counts at full weight, and MIN_CONFIDENCE_FOR_CALL =
        0.45 gates the call. The window was 150 days, which is roughly a CLUB
        season, but this board is almost entirely international fixtures and
        those teams play 3-6 times in 150 days. Measured: team 18828 returned 2
        finished fixtures at 150d and 10 at 400d, and across 46 cached teams the
        median was 3 fixtures with 1,705 of 5,191 player records at zero
        appearances. A 3-match window cannot produce one qualified player, so
        the board could never call anything and read ROTATION everywhere.
        """
        self.assertGreaterEqual(
            stage4.HISTORICAL_RECALL_DAYS, 300,
            "150 days cannot yield 8 appearances for an international side",
        )
        # The schema marker is what forces the refetch of the stale 150d
        # windows; without the bump the board would keep reading 3-match
        # windows for up to HISTORY_TTL while claiming a deeper recall.
        self.assertEqual(stage4.HISTORY_CACHE_SCHEMA, 3)

    def test_a_confident_verdict_is_reachable_on_international_evidence(self):
        """
        With a realistic international sample the engine must be able to speak.

        This is the end-to-end consequence of the recall change: 8 observed
        appearances at 720 minutes has to clear MIN_CONFIDENCE_FOR_CALL and
        produce a DANGER, otherwise the threshold is unreachable no matter how
        much history is collected.
        """
        self.assertEqual(si.confidence(8, 720), 1.0)
        self.assertGreaterEqual(si.confidence(8, 720), si.MIN_CONFIDENCE_FOR_CALL)

        missing = [{"name": "Star", "pos": "Midfielder",
                    "avg_rating": 7.6, "apps": 8, "mins": 720}]
        # A real XI is 11, so replacing one absentee means 10 others stay on.
        # Scoring the swap against an empty bench would make the credit side
        # vanish and overstate the damage.
        replacements = [{"name": f"R{i}", "pos": "Midfielder",
                         "avg_rating": 6.4, "apps": 8, "mins": 720}
                        for i in range(10)]
        out = si.assess_absence(missing, replacements, regime="MID_FIELD")
        self.assertEqual(out["verdict"], si.STATE_DANGER)

    def test_the_replacement_pool_is_joined_by_id_not_by_record(self):
        """
        Regression: the replacement group came back EMPTY in production.

        `get_key_players_forensics()` returns the full player pool as a LIST of
        records. Joining that list with `pid in player_pool` is a membership test
        over whole dicts, which never matches an int id, so the replacement group
        silently came back empty for every side. The artifact was gone and the
        numbers looked plausible, but every fixture fell through to UNKNOWN with
        zero replacement credit — the engine had stopped measuring the swap
        entirely, which is a different lie rather than an honest one.

        The join must therefore be done on an id-indexed dict.
        """
        pool_list = [
            {"id": 10, "name": "Survivor", "pos": "Midfielder",
             "avg_rating": 6.8, "apps": 9, "mins": 800},
            {"id": 11, "name": "Replacement", "pos": "Midfielder",
             "avg_rating": 6.3, "apps": 9, "mins": 800},
        ]
        by_id = {int(p["id"]): p for p in pool_list
                 if isinstance(p, dict) and p.get("id") is not None}

        self.assertIn(11, by_id)
        self.assertNotIn(11, pool_list, "the raw list is what caused the bug")

        absent = [{"name": "Star", "pos": "Midfielder",
                   "avg_rating": 7.5, "apps": 9, "mins": 800}]
        replacements = [{**by_id[11], "id": 11}]
        result = si.assess_absence(absent, replacements, regime="MID_FIELD")
        self.assertNotEqual(result["replacement_credit"], 0.0)
        self.assertGreater(result["net_impact"], 0.0)

    def test_stage2_keeps_scheduled_fixtures_without_picks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            predictions = Path(temp_dir) / "live_predictions.json"
            incoming = Path(temp_dir) / "incoming_predictions.json"
            board_path = Path(temp_dir) / "validation_board.json"
            predictions.write_text("{}", encoding="utf-8")
            incoming.write_text("{}", encoding="utf-8")
            fixtures = [{
                "id": 501, "name": "Alpha vs Beta", "state": {"state": "NS"},
                "periods": [],
            }]
            with patch.object(stage2, "API_TOKEN", "test-token"), \
                 patch.object(stage2, "DATA_DIR", temp_dir), \
                 patch.object(stage2, "BOARD_FILE", str(board_path)), \
                 patch.object(stage2, "PREDICTIONS_FILE", str(predictions)), \
                 patch.object(stage2, "INCOMING_PREDICTIONS_FILE", str(incoming)), \
                 patch("live_cache.get_live_scores_cached", return_value=fixtures), \
                 patch.object(stage2, "load_memory"), \
                 patch.object(stage2, "save_memory"), \
                 patch("settlement_service.load_ft_snapshot", return_value={}):
                board = stage2.run_live_validator_once(7)
        self.assertEqual(board["total_live"], 1)
        self.assertEqual(board["matches"][0]["id"], "501")
        self.assertEqual(board["matches"][0]["status"], "SCHEDULED")

    def test_stage2_retains_finished_fixture_after_live_removal(self):
        snapshot = {
            "502": {
                "fixture_id": "502", "home_team": "Alpha", "away_team": "Beta",
                "ft_score": "2-1", "is_finished": True, "minute": 0,
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            predictions = Path(temp_dir) / "live_predictions.json"
            incoming = Path(temp_dir) / "incoming_predictions.json"
            board_path = Path(temp_dir) / "validation_board.json"
            predictions.write_text("{}", encoding="utf-8")
            incoming.write_text("{}", encoding="utf-8")
            with patch.object(stage2, "API_TOKEN", "test-token"), \
                 patch.object(stage2, "DATA_DIR", temp_dir), \
                 patch.object(stage2, "BOARD_FILE", str(board_path)), \
                 patch.object(stage2, "PREDICTIONS_FILE", str(predictions)), \
                 patch.object(stage2, "INCOMING_PREDICTIONS_FILE", str(incoming)), \
                 patch("live_cache.get_live_scores_cached", return_value=[]), \
                 patch.object(stage2, "load_memory"), \
                 patch.object(stage2, "save_memory"), \
                 patch("settlement_service.load_ft_snapshot", return_value=snapshot):
                board = stage2.run_live_validator_once(8)
        self.assertEqual(board["retained_finished"], 1)
        self.assertEqual(board["matches"][0]["id"], "502")
        self.assertEqual(board["matches"][0]["status"], "FINISHED")
        self.assertEqual(board["matches"][0]["minute"], 90)

    def test_stage2_period_minutes_and_unknown_event_identity(self):
        fixture = {
            "id": 42,
            "name": "Away vs Home",
            "participants": [
                {"id": 2, "name": "Away", "meta": {"location": "away"}},
                {"id": 1, "name": "Home", "meta": {"location": "home"}},
            ],
            "periods": [{"minutes": 37}],
            "scores": [
                {"description": "CURRENT", "score": {"participant": "home", "goals": 1}},
                {"description": "CURRENT", "score": {"participant": "away", "goals": 0}},
            ],
            "events": [
                {"type": {"code": "red-card"}, "participant_id": 1},
                {"type": {"code": "red-card"}, "participant_id": 999},
            ],
            "statistics": [],
        }
        with patch.object(stage2, "get_squad_data_standardized", return_value={}):
            context = stage2.extract_live_context(fixture)
        self.assertEqual(context["minute"], 37)
        self.assertEqual(context["home"]["goals"], 1)
        self.assertEqual(context["impact"]["home"]["reds"], 1)
        self.assertEqual(context["impact"]["away"]["reds"], 0)

    def test_stage2_compound_gg_over_requires_three_goals(self):
        base = {
            "home": {"goals": 1, "stats": {"corners": 0}},
            "away": {"goals": 1, "stats": {"corners": 0}},
        }
        pick = {"type": "GG_OVER_2.5"}
        # check_if_done now returns (done, note, outcome) so the caller can
        # record WON / LOST as well as the human-readable settlement text.
        self.assertEqual(stage2.check_if_done(base, pick), (False, "", ""))
        base["away"]["goals"] = 2
        done, note, outcome = stage2.check_if_done(base, pick)
        self.assertTrue(done)
        self.assertEqual(outcome, stage2.VERDICT_WON)

    # ── CODE 2 VALIDATION GATE ────────────────────────────────────────────
    # The forensic validator used to return True for "nothing bad happened"
    # (MAINTAINED / STABLE) and the statistical judge used `passed_count >= 1`,
    # so a single weak signal passed the whole validator (STATS_1/3).

    @staticmethod
    def _stage2_ctx(**overrides):
        blank = {
            "shots-on-target": 0, "dangerous-attacks": 0,
            "box": 0, "corners": 0, "ball-possession": 50,
        }
        ctx = {
            "id": "1", "name": "Home vs Away", "minute": 50,
            "home": {"goals": 0, "stats": dict(blank)},
            "away": {"goals": 0, "stats": dict(blank)},
            "impact": {
                "home": {"reds": 0, "gk_risk": False, "key_sub_off": 0},
                "away": {"reds": 0, "gk_risk": False, "key_sub_off": 0},
            },
            "events": [],
        }
        for key, value in overrides.items():
            if key in ("home", "away"):
                ctx[key]["stats"].update(value)
            elif key == "impact":
                for side, patch in value.items():
                    ctx["impact"][side].update(patch)
            else:
                ctx[key] = value
        return ctx

    def test_stage2_forensic_neutral_is_not_positive_evidence(self):
        quiet = self._stage2_ctx()
        state, note = stage2.new_engine_forensic_investigation(
            quiet, {"target_loc": "home"})
        self.assertEqual(state, stage2.V_NEUTRAL)
        self.assertIn("not evidence", note)

        managed = self._stage2_ctx(impact={"home": {"key_sub_off": 1}})
        state, note = stage2.new_engine_forensic_investigation(
            managed, {"target_loc": "home"})
        self.assertEqual(state, stage2.V_NEUTRAL)
        self.assertIn("not evidence", note)

    def test_stage2_forensic_supported_requires_real_exploitable_gap(self):
        exploited = self._stage2_ctx(
            impact={"home": {"gk_risk": True}},
            away={"shots-on-target": 2},
        )
        self.assertEqual(
            stage2.new_engine_forensic_investigation(
                exploited, {"target_loc": "home"})[0],
            stage2.V_SUPPORTED,
        )

        protected = self._stage2_ctx(impact={"home": {"gk_risk": True}})
        self.assertEqual(
            stage2.new_engine_forensic_investigation(
                protected, {"target_loc": "home"})[0],
            stage2.V_CONTRADICTED,
        )

    def test_stage2_single_engine_cannot_pass_the_gate(self):
        # Exactly one of three engines can pass: for a TO_SCORE home pick the
        # rule validator is satisfied (home SOT >= 1 and home DA ahead), while
        # structure (ratios/diffs) and momentum (recent events) both fail.
        weak = self._stage2_ctx(
            minute=20,
            home={"shots-on-target": 1, "dangerous-attacks": 6,
                  "box": 0, "corners": 0},
            away={"shots-on-target": 5, "dangerous-attacks": 4,
                  "box": 0, "corners": 0},
        )
        pick = {"type": "TO_SCORE", "target_loc": "home", "target_id": "1"}
        self.assertTrue(stage2.engine_1_rule_validator(weak, pick)[0])
        self.assertFalse(stage2.engine_2_structural_stacker(weak, "home")[0])
        # `weak` carries no event feed, so Engine 3 abstains rather than
        # recording a fail. Only two engines report, and one pass out of two is
        # still inconclusive — a single engine must never carry the gate.
        e3_pass, e3_note = stage2.engine_3_momentum_escalator(weak, "1")
        self.assertIsNone(e3_pass)
        self.assertIn("abstained", e3_note)

        state, label, _ = stage2.old_engine_statistical_judge(weak, pick)
        self.assertIn("abstained", label)
        self.assertEqual(state, stage2.V_INSUFFICIENT)
        self.assertNotEqual(state, stage2.V_SUPPORTED)

    def test_single_reporting_engine_never_passes_the_gate(self):
        # Even with Engine 3 abstaining, the bar must never drop below 2 real
        # engines. One engine voting yes is not agreement.
        ctx = self._stage2_ctx(
            minute=45,
            home={"shots-on-target": 1, "dangerous-attacks": 12,
                  "box": 0, "corners": 3},
            away={"shots-on-target": 0, "dangerous-attacks": 2,
                  "box": 0, "corners": 0},
        )
        ctx["events"] = []   # Engine 3 abstains
        pick = {"type": "TO_SCORE", "target_loc": "home", "target_id": "1"}
        e3_pass, _ = stage2.engine_3_momentum_escalator(ctx, "1")
        self.assertIsNone(e3_pass)
        state, label, detail = stage2.old_engine_statistical_judge(ctx, pick)
        # Whichever way Engines 1 and 2 land, two reporting engines with a
        # single pass must not reach SUPPORTED.
        self.assertIn("abstained", label)
        self.assertIn("need 2", detail)

    def test_stage2_strong_evidence_passes_the_gate(self):
        strong = self._stage2_ctx(
            home={"shots-on-target": 5, "dangerous-attacks": 40,
                  "box": 8, "corners": 5},
            away={"shots-on-target": 1, "dangerous-attacks": 10,
                  "box": 1, "corners": 1},
        )
        state, _, _ = stage2.old_engine_statistical_judge(
            strong, {"type": "TO_SCORE", "target_loc": "home",
                     "target_id": "1"})
        self.assertEqual(state, stage2.V_SUPPORTED)

    def test_stage2_combined_gate_needs_both_dimensions(self):
        self.assertEqual(
            stage2.combine_validation_states(
                stage2.V_SUPPORTED, stage2.V_SUPPORTED),
            stage2.V_SUPPORTED,
        )
        # Every other combination must not report a pass.
        for forensic in (stage2.V_SUPPORTED, stage2.V_NEUTRAL,
                         stage2.V_INSUFFICIENT, stage2.V_CONTRADICTED):
            for stats in (stage2.V_SUPPORTED, stage2.V_NEUTRAL,
                          stage2.V_INSUFFICIENT, stage2.V_CONTRADICTED):
                if forensic == stage2.V_SUPPORTED and stats == stage2.V_SUPPORTED:
                    continue
                self.assertNotEqual(
                    stage2.combine_validation_states(forensic, stats),
                    stage2.V_SUPPORTED,
                )

    def test_stage2_score_parts_tolerates_missing_score(self):
        self.assertEqual(
            stage2._score_parts("—"),
            {"home": 0, "away": 0, "display": "—"},
        )

    # ── BUG 2: ONE MARKET MUST BE TRACKED ONCE ────────────────────────────
    # Dedup keyed on the raw pick object (including free-text `reason`), so
    # "TO_SCORE/away" with two different justifications became two predictions,
    # and "O2.5" vs "OVER_2.5" were treated as different markets.

    def test_normalize_pick_collapses_market_aliases(self):
        key, pick = stage2.normalize_pick(
            {"type": "O2.5", "target_loc": None})
        self.assertEqual(key, "OVER_2.5:match")
        self.assertEqual(pick["market"], "OVER_2.5")

        key, pick = stage2.normalize_pick({"type": "OVER_2.5"})
        self.assertEqual(key, "OVER_2.5:match")

        key, _ = stage2.normalize_pick({"type": "U2.5"})
        self.assertEqual(key, "UNDER_2.5:match")

    def test_normalize_pick_keeps_targets_distinct(self):
        home, _ = stage2.normalize_pick(
            {"type": "TO_SCORE", "target_loc": "home"})
        away, _ = stage2.normalize_pick(
            {"type": "TO_SCORE", "target_loc": "away"})
        self.assertNotEqual(home, away)

    def test_pick_feed_dedup_ignores_reason_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feed.json"
            path.write_text(json.dumps({
                "1": [
                    {"type": "TO_SCORE", "target_loc": "away",
                     "reason": "Favorite defense collapsing"},
                    {"type": "TO_SCORE", "target_loc": "away",
                     "reason": "Home GK liability"},
                    {"type": "O2.5"},
                    {"type": "OVER_2.5"},
                ]
            }), encoding="utf-8")
            merged = {}
            for fid, picks in stage2._read_pick_feed(str(path)).items():
                existing = merged.setdefault(fid, [])
                seen = {p.get("canonical_key") for p in existing}
                for pick in picks:
                    key, normalized = stage2.normalize_pick(pick)
                    if normalized is None or key in seen:
                        continue
                    existing.append(normalized)
                    seen.add(key)
            # O2.5 and OVER_2.5 collapse; the two TO_SCORE rows collapse.
            self.assertEqual(len(merged["1"]), 2)
            self.assertEqual(
                {p["canonical_key"] for p in merged["1"]},
                {"OVER_2.5:match", "TO_SCORE:away"},
            )

    def test_stage2_state_key_is_stable_not_index_based(self):
        # Index-based keys reset history whenever the feed is reordered.
        key_a, _ = stage2.normalize_pick({"type": "TO_SCORE", "target_loc": "away"})
        key_b, _ = stage2.normalize_pick({"type": "TO_SCORE", "target_loc": "away"})
        self.assertEqual(key_a, key_b)
        self.assertNotIn("0_", key_a)

    # ── BUG 3/5: BOX ENTRIES WERE PERMANENTLY ZERO ─────────────────────────
    # The provider never emits the codes the engine read, so box was always 0
    # and "Box touch diff" could never pass.

    def test_stage2_box_stat_prefers_a_code_the_provider_actually_sends(self):
        # "shots-insidebox" is present in the live feed; the two box-touch codes
        # are not, which is why box was permanently 0.
        self.assertEqual(stage2.BOX_STAT_CODES[0], "shots-insidebox")
        self.assertIn("shots-insidebox", stage2.BOX_STAT_CODES)
        # NO shots-total fallback. Mapping shots-total into the box slot and
        # then comparing it against a box threshold is a unit error: combined
        # shots-total has a median of ~8 per match against a box bar of 3-4, so
        # the fallback could never pass and silently dragged Engine 2 down.
        self.assertIsNone(stage2.BOX_STAT_FALLBACK)

    def test_stage2_under_sot_threshold_is_derived_not_the_over_one(self):
        # The UNDER bar must be its own derived value, not the OVER constant
        # and not the unreachable hardcoded 1 that rejected ordinary 0-0 halves.
        self.assertEqual(stage2.UNDER_SOT_MAX_MEDIAN, 4)
        self.assertLess(stage2.UNDER_SOT_MAX_STRONG, stage2.UNDER_SOT_MAX_MEDIAN)
        self.assertNotEqual(stage2.UNDER_SOT_MAX_MEDIAN, stage2.ENGINE1_MIN_COMBINED_SOT)
        # A completely normal 45' first half (3 combined SOT) must pass.
        self.assertTrue(3 <= stage2.UNDER_SOT_MAX_MEDIAN)

    def test_stage2_under_engine_passes_a_normal_first_half(self):
        # The reported 84'-at-0-0 case had a combined SOT of 3-4. Engine 1
        # used to demand <= 1 and failed it.
        ctx = self._stage2_ctx()
        ctx["home"]["stats"].update({"shots-on-target": 2})
        ctx["away"]["stats"].update({"shots-on-target": 1})
        pick = {"type": "UNDER_2.5", "target_loc": "match"}
        passed, note = stage2.engine_1_rule_validator(ctx, pick)
        self.assertTrue(passed, note)
        self.assertIn(str(stage2.UNDER_SOT_MAX_MEDIAN), note)

    def test_stage2_engine3_runs_for_match_level_markets(self):
        # Engine 3 returned False unconditionally for match-level markets
        # because target_id is None, and its message blamed the minute even at
        # 72'. It must now actually evaluate both teams' recent events.
        ctx = self._stage2_ctx()
        ctx["minute"] = 45
        # A quiet match: a real event feed with no recent key events, so the
        # UNDER direction passes. The feed must contain at least one event —
        # an EMPTY feed is missing data, not a quiet match (see below).
        ctx["events"] = [{"participant_id": "1", "minute": 5,
                          "type": {"code": "goal"}}]
        passed, note = stage2.engine_3_momentum_escalator(
            ctx, None, stage2.DIRECTION_UNDER)
        self.assertTrue(passed, note)
        self.assertNotIn("too early", note)
        self.assertNotIn("abstained", note)
        # A busy match must fail the UNDER direction.
        ctx["events"] = [{"participant_id": "1", "minute": 40,
                          "type": {"code": "goal"}} for _ in range(6)]
        passed, note = stage2.engine_3_momentum_escalator(
            ctx, None, stage2.DIRECTION_UNDER)
        self.assertFalse(passed, note)
        # Still honest about a genuinely early match: it abstains rather than
        # recording a fail, because "too early" is not a judgement.
        ctx["minute"] = 5
        passed, note = stage2.engine_3_momentum_escalator(
            ctx, None, stage2.DIRECTION_UNDER)
        self.assertIsNone(passed)
        self.assertIn("too early", note)

    def test_engine3_abstains_when_the_event_feed_is_empty(self):
        # 2 of the 10 live fixtures carried NO events at all. Counting zero
        # events on an empty feed scored a free PASS, which inflated the tally
        # and could carry a verdict on no evidence. An absent feed must abstain.
        ctx = self._stage2_ctx()
        ctx["minute"] = 45
        ctx["events"] = []
        passed, note = stage2.engine_3_momentum_escalator(
            ctx, None, stage2.DIRECTION_UNDER)
        self.assertIsNone(passed)
        self.assertIn("abstained", note)
        # The judge must then express the tally against the engines that DID
        # report, and must not treat the abstention as a fail.
        pick = {"type": "UNDER 2.5", "market": "UNDER 2.5", "target_loc": "match"}
        state, label, detail = stage2.old_engine_statistical_judge(ctx, pick)
        self.assertIn("abstained", label)
        self.assertIn("⏸️", detail)

    def test_match_level_gate_does_not_require_a_forensic_signal(self):
        # THE ROOT CAUSE. The forensic engine asks "is a team weakened?", which
        # is NEUTRAL on a healthy match. Requiring forensic==SUPPORTED meant a
        # match-level UNDER could never open its gate — Code 2 never approved
        # anything in production. The engines must decide alone here.
        stats_ok = stage2.V_SUPPORTED
        # Under/Over: forensic is irrelevant, so SUPPORTED is reachable.
        self.assertEqual(
            stage2.combine_validation_states(
                stage2.V_NEUTRAL, stats_ok, stage2.DIRECTION_UNDER),
            stage2.V_SUPPORTED)
        self.assertEqual(
            stage2.combine_validation_states(
                stage2.V_NEUTRAL, stats_ok, stage2.DIRECTION_OVER),
            stage2.V_SUPPORTED)
        # Team-side markets keep the forensic requirement.
        self.assertNotEqual(
            stage2.combine_validation_states(
                stage2.V_NEUTRAL, stats_ok, stage2.DIRECTION_NEUTRAL),
            stage2.V_SUPPORTED)

    def test_stage2_box_none_is_unavailable_not_zero(self):
        self.assertIsNone(stage2._opt_box({"box": None}))
        self.assertEqual(stage2._opt_box({"box": 7}), 7)
        # A missing box must not be scored as zero pressure.
        ctx = self._stage2_ctx(
            home={"shots-insidebox": 9, "dangerous-attacks": 40, "corners": 6},
            away={"shots-insidebox": 1, "dangerous-attacks": 8, "corners": 1},
        )
        ctx["home"]["stats"]["box"] = 9
        ctx["away"]["stats"]["box"] = 1
        passed, note = stage2.engine_2_structural_stacker(ctx, "home")
        self.assertTrue(passed)
        self.assertIn("Box entry diff 8", note)

    def test_stage2_forensic_handles_missing_box_without_crashing(self):
        # box=None previously made `opp_box >= 3` raise TypeError in production.
        ctx = self._stage2_ctx(impact={"home": {"gk_risk": True}})
        ctx["away"]["stats"]["box"] = None
        state, note = stage2.new_engine_forensic_investigation(
            ctx, {"target_loc": "home"})
        self.assertIn(state, (stage2.V_SUPPORTED, stage2.V_CONTRADICTED))
        self.assertIn("PROTECTED", note)

    def test_stage2_board_reports_box_unavailable_flag(self):
        entry = stage2._summary_board_entry(
            {"id": 7, "name": "A vs B", "state": {"state": "LIVE"}})
        self.assertIn("box_available", entry["statistics"]["home"])
        self.assertIsNone(entry["statistics"]["home"]["box_entries"])

    # ── P5: RAISED THRESHOLDS ─────────────────────────────────────────────
    def test_stage2_engine1_requires_more_than_three_combined_sot(self):
        self.assertEqual(stage2.ENGINE1_MIN_COMBINED_SOT, 3)
        ctx = self._stage2_ctx(
            home={"shots-on-target": 2}, away={"shots-on-target": 1})
        ok, note = stage2.engine_1_rule_validator(ctx, {"type": "OVER_2.5"})
        self.assertFalse(ok)          # exactly 3 is NOT enough
        self.assertIn("> 3", note)

        ctx["away"]["stats"]["shots-on-target"] = 2   # combined 4
        ok, note = stage2.engine_1_rule_validator(ctx, {"type": "OVER_2.5"})
        self.assertTrue(ok)
        self.assertIn("SOT combined 4", note)

    def test_stage2_structure_ratios_are_sixty_percent(self):
        self.assertEqual(stage2.MIN_DA_RATIO, 0.60)
        self.assertEqual(stage2.MIN_SOT_RATIO, 0.60)
        self.assertEqual(stage2.MIN_BOX_TOUCH_DIFF, 4)
        self.assertEqual(stage2.MIN_RECENT_KEY_EVENTS, 4)

    def test_stage2_da_ratio_below_sixty_fails(self):
        ctx = self._stage2_ctx(
            home={"dangerous-attacks": 4, "corners": 0, "shots-on-target": 0},
            away={"dangerous-attacks": 6, "corners": 0, "shots-on-target": 0},
        )
        ctx["home"]["stats"]["box"] = 0
        ctx["away"]["stats"]["box"] = 0
        _passed, note = stage2.engine_2_structural_stacker(ctx, "home")
        # 4/10 = 40% is below the 60% bar.
        self.assertIn("DA ratio 40% ≥ 60%: ❌", note)

    def test_stage2_momentum_requires_four_key_events(self):
        ctx = self._stage2_ctx(minute=60)
        for i in range(3):
            ctx["events"].append({
                "participant_id": "7", "minute": 55 + i,
                "type": {"code": "shot-on-target"},
            })
        ok, note = stage2.engine_3_momentum_escalator(ctx, "7")
        self.assertFalse(ok)
        self.assertIn("3 ≥ 4", note)

        ctx["events"].append({
            "participant_id": "7", "minute": 59,
            "type": {"code": "goal"},
        })
        ok, _note = stage2.engine_3_momentum_escalator(ctx, "7")
        self.assertTrue(ok)

    # ── P4: SETTLED PREDICTIONS ARE NOT "UNKNOWN" ─────────────────────────
    def test_settled_prediction_reports_its_outcome_not_unknown(self):
        stage, note = stage2.prediction_lifecycle_step(
            {"type": "GG"}, "SETTLED", stage2.V_SETTLED, 90, True)
        self.assertEqual(stage, "SETTLED")
        self.assertIn("Outcome", note)

    def test_prediction_lifecycle_names_each_stage(self):
        pick = {"type": "GG"}
        self.assertEqual(
            stage2.prediction_lifecycle_step(
                pick, "TRIGGERED", stage2.V_SUPPORTED, 45, False)[0],
            "TRIGGERED")
        self.assertEqual(
            stage2.prediction_lifecycle_step(
                pick, "WAITING", stage2.V_SUPPORTED, 30, False)[0],
            "SUPPORTED")
        self.assertEqual(
            stage2.prediction_lifecycle_step(
                pick, "WAITING", stage2.V_CONTRADICTED, 30, False)[0],
            "UNLIKELY")
        self.assertEqual(
            stage2.prediction_lifecycle_step(
                pick, "WAITING", stage2.V_INSUFFICIENT, 30, False)[0],
            "MONITORING")
        self.assertEqual(
            stage2.prediction_lifecycle_step(
                pick, "WAITING", stage2.V_NEUTRAL, 30, False)[0],
            "MONITORING")

    # ── PUSH NOTIFICATIONS ─────────────────────────────────────────────────
    def test_only_irreversible_events_are_notifiable(self):
        """
        The contract is that REVERSIBLE states are never announced, not that
        the set is exactly two entries.

        SUPPORTED and its siblings read differently on consecutive cycles: a
        prediction can be SUPPORTED now and CONTRADICTED next. Announcing them
        pushes a signal that un-happens, which is the misleading behaviour the
        validator was rebuilt to eliminate.

        USER_ALERT joined the set deliberately. It is the user pressing their
        own rule and it cannot un-fire, so it is announcement-worthy — and it
        is the only event that is scoped to a single account rather than
        broadcast (see the audience tests below).
        """
        self.assertEqual(
            notify.ALLOWED_EVENTS, {"TRIGGERED", "SETTLED", "USER_ALERT"})
        with tempfile.TemporaryDirectory() as tmp:
            _patch_notify_paths(tmp)
            for event in ("SUPPORTED", "REJECTED", "NEUTRAL", "MONITORING", ""):
                self.assertIsNone(
                    notify.emit_event(event, "1", "A v B", "GG", "match"))

    def test_event_is_recorded_once_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            _patch_notify_paths(tmp)
            first = notify.emit_event("TRIGGERED", "1", "A v B", "GG", "match",
                                      minute=45)
            again = notify.emit_event("TRIGGERED", "1", "A v B", "GG", "match",
                                      minute=45)
            self.assertIsNotNone(first)
            self.assertIsNone(again, "same event must not be recorded twice")
            self.assertEqual(len(notify.read_events()), 1)

    def test_distinct_markets_are_separate_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            _patch_notify_paths(tmp)
            notify.emit_event("TRIGGERED", "1", "A v B", "TO_SCORE", "home")
            notify.emit_event("TRIGGERED", "1", "A v B", "TO_SCORE", "away")
            notify.emit_event("TRIGGERED", "1", "A v B", "GG", "match")
            self.assertEqual(len(notify.read_events()), 3)

    def test_events_are_not_resent_after_delivery(self):
        # The log is append-only history; without a delivered marker the
        # dispatcher would re-send the same events every cycle.
        with tempfile.TemporaryDirectory() as tmp:
            _patch_notify_paths(tmp)
            notify.emit_event("SETTLED", "1", "A v B", "GG", "match",
                              settlement="GG settled ✅")
            self.assertEqual(len(notify.pending_events()), 1)
            notify.mark_delivered([notify.read_events()[0]["key"]])
            self.assertEqual(notify.pending_events(), [])
            # History is still available for the in-app list.
            self.assertEqual(len(notify.read_events()), 1)

    def test_subscription_is_per_user_and_reversible(self):
        with tempfile.TemporaryDirectory() as tmp:
            _patch_notify_paths(tmp)
            keys = {"p256dh": "abc", "auth": "def"}
            notify.save_subscription("u1", "https://push/1", keys)
            notify.save_subscription("u2", "https://push/2", keys)
            self.assertEqual(len(notify.list_subscriptions()), 2)
            notify.update_prefs("u1", {"triggered": False})
            self.assertFalse(notify.get_prefs("u1")["triggered"])
            # One user's preference must not affect the other.
            self.assertTrue(notify.get_prefs("u2")["triggered"])
            self.assertTrue(notify.delete_subscription("u1"))
            self.assertFalse(notify.delete_subscription("u1"))
            self.assertIn("u2", notify.list_subscriptions())

    def test_prefs_respect_event_toggle_when_dispatching(self):
        with tempfile.TemporaryDirectory() as tmp:
            _patch_notify_paths(tmp)
            subs = {"u1": {"endpoint": "https://push/1",
                           "keys": {"p256dh": "a", "auth": "b"},
                           "prefs": {"triggered": False, "settled": True}}}
            event = {"event": "TRIGGERED", "key": "k", "market": "GG",
                     "target": "match", "fixture": "A v B"}
            sent = []
            original = notify._send_one
            notify._send_one = lambda *a, **k: (sent.append(1), "sent")[1]
            try:
                notify.dispatch([event], subs)
                self.assertEqual(len(sent), 0, "toggled-off event must be skipped")
                subs["u1"]["prefs"]["triggered"] = True
                notify.dispatch([event], subs)
                self.assertEqual(len(sent), 1)
            finally:
                notify._send_one = original

    def test_dead_endpoint_is_pruned(self):
        with tempfile.TemporaryDirectory() as tmp:
            _patch_notify_paths(tmp)
            notify.save_subscription("gone", "https://push/gone",
                                     {"p256dh": "a", "auth": "b"})
            notify.save_subscription("keep", "https://push/keep",
                                     {"p256dh": "a", "auth": "b"})
            original = notify._send_one
            notify._send_one = lambda sub, *a, **k: (
                "gone" if "gone" in sub["endpoint"] else "sent")
            try:
                notify.dispatch([{"event": "SETTLED", "key": "k",
                                  "market": "GG", "target": "match"}])
                self.assertNotIn("gone", notify.list_subscriptions())
                self.assertIn("keep", notify.list_subscriptions())
            finally:
                notify._send_one = original

    def test_dispatch_without_vapid_keys_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            _patch_notify_paths(tmp)
            subs = {"u1": {"endpoint": "https://push/1",
                           "keys": {"p256dh": "a", "auth": "b"}, "prefs": {}}}
            # Patch the resolver: _vapid_keys() intentionally re-reads .env,
            # so clearing os.environ alone would not remove the keys.
            with patch.object(notify, "_vapid_keys", lambda: (None, None)):
                summary = notify.dispatch(
                    [{"event": "TRIGGERED", "key": "k", "market": "GG",
                      "target": "match"}], subs)
            self.assertEqual(summary["sent"], 0)
            self.assertEqual(summary["skipped"], 1)

    def test_payload_text_reflects_the_outcome(self):
        won = notify.build_payload({
            "event": "SETTLED", "market": "TO_SCORE", "target": "away",
            "settlement": "Away scored ✅", "fixture": "A v B",
            "final_score": "2-1"})
        self.assertTrue(won["title"].startswith("✅"))
        lost = notify.build_payload({
            "event": "SETTLED", "market": "O2.5", "target": "match",
            "settlement": "Over 2.5 lost ❌", "fixture": "A v B"})
        self.assertTrue(lost["title"].startswith("❌"))
        armed = notify.build_payload({
            "event": "TRIGGERED", "market": "GG", "target": "match",
            "minute": 45, "score_at_trigger": "2-0", "fixture": "A v B"})
        self.assertIn("45'", armed["body"])
        self.assertIn("2-0", armed["body"])

    def test_emit_event_never_raises_on_bad_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            _patch_notify_paths(tmp)
            self.assertIsNone(notify.emit_event(
                "TRIGGERED", None, None, None, None, minute="not-an-int"))

    def test_stage2_notify_helpers_survive_notification_failure(self):
        # A broken notification must never abandon the remaining predictions.
        ctx = self._stage2_ctx()
        with patch.dict(sys.modules, {"notifications": None}):
            stage2._notify_triggered(ctx, "GG", "GG", "match", 45, "1-0")
            stage2._notify_settled(ctx, "GG", "GG", "match", "GG settled ✅")

    # ── P6: STAGE 1 MUST NOT EMIT BOTH O/U DIRECTIONS ────────────────────
    def test_stage1_high_rotation_does_not_emit_both_directions(self):
        source = Path(
            "LIVE_SCANNER/live_stage1_prematch.py").read_text(encoding="utf-8")
        rotation_block = source.split("match_picks =[]", 1)[1].split(
            "h_odd, o25, kp", 1)[0]
        # The market is now emitted under its canonical label "UNDER 2.5" so
        # Stage 2 can read the direction without substring guessing. The
        # invariant this test actually protects is unchanged: the single
        # high-rotation condition must still resolve to ONE direction.
        self.assertTrue(
            'match_picks.append({"type": "UNDER 2.5"' in rotation_block
            or 'match_picks.append({"type": "U2.5"})' in rotation_block,
            "high-rotation block must emit the UNDER market exactly once",
        )
        # The old line emitted both directions from one condition.
        self.assertNotIn('{"type": "O2.5"}', rotation_block)
        self.assertNotIn(
            'match_picks.extend([{"type": "U2.5"}, {"type": "O2.5"}])',
            rotation_block,
        )

    def test_stage2_board_entry_exposes_structured_contract(self):
        entry = stage2._summary_board_entry({
            "id": 42,
            "name": "Home vs Away",
            "state": {"state": "LIVE"},
            "scores": [
                {"description": "CURRENT",
                 "score": {"participant": "home", "goals": 2}},
                {"description": "CURRENT",
                 "score": {"participant": "away", "goals": 1}},
            ],
        })
        # The frontend renders these fields directly instead of parsing `lines`.
        for field in ("fixture_id", "score_parts", "period", "status",
                      "updated_at", "statistics", "predictions"):
            self.assertIn(field, entry)
        self.assertEqual(entry["score_parts"],
                         {"home": 2, "away": 1, "display": "2-1"})
        self.assertEqual(set(entry["statistics"]), {"home", "away"})
        for side in ("home", "away"):
            self.assertEqual(
                set(entry["statistics"][side]),
                {"possession", "shots_on_target", "dangerous_attacks",
                 "corners", "box_entries", "box_available"},
            )

    def test_stage5_preserves_team_ids_and_explicit_breach(self):
        danger = [{
            "fixture": "Home vs Away",
            "fixture_id": 100,
            "home_team": {
                "id": 11, "team_name": "Home", "breach": False,
                "missing_details": [], "formation": "4-3-3",
                "style": {"label": "Balanced"},
            },
            "away_team": {
                "id": 22, "team_name": "Away", "breach": True,
                "missing_details": [], "formation": "4-3-3",
                "style": {"label": "Attacking"},
            },
            "style_alignment": "🔥 OPEN",
        }]
        with tempfile.TemporaryDirectory() as temp_dir:
            incoming = {"100": [{"type": "OVER_2.5"}]}
            incoming_path = Path(temp_dir) / "incoming.json"
            danger_path = Path(temp_dir) / "danger.json"
            report_path = Path(temp_dir) / "report.json"
            incoming_path.write_text(json.dumps(incoming), encoding="utf-8")
            danger_path.write_text(json.dumps(danger), encoding="utf-8")
            with patch.object(stage5, "DATA_DIR", temp_dir), \
                 patch.object(stage5, "INCOMING_PREDICTIONS_FILE", str(incoming_path)), \
                 patch.object(stage5, "DANGER_AUDIT_FILE", str(danger_path)), \
                 patch.object(stage5, "AGGREGATOR_REPORT_FILE", str(report_path)):
                report = stage5.run_master_aggregator()
        self.assertEqual(report[0]["danger_report"]["home"]["id"], 11)
        self.assertEqual(report[0]["danger_report"]["away"]["id"], 22)
        self.assertTrue(report[0]["danger_report"]["away"]["breach"])

    def test_stage5_marks_unavailable_evidence_explicitly(self):
        danger = [{
            "fixture": "Home vs Away", "fixture_id": 101,
            "home_team": {"id": 1, "team_name": "Home", "breach": None,
                          "data_available": False, "missing_details": [],
                          "formation": "N/A", "style": {"label": "Unavailable"}},
            "away_team": {"id": 2, "team_name": "Away", "breach": False,
                          "data_available": True, "missing_details": [],
                          "formation": "N/A", "style": {"label": "Balanced"}},
            "style_alignment": "⚠️ UNAVAILABLE",
        }]
        with tempfile.TemporaryDirectory() as temp_dir:
            incoming_path = Path(temp_dir) / "incoming.json"
            danger_path = Path(temp_dir) / "danger.json"
            report_path = Path(temp_dir) / "report.json"
            incoming_path.write_text(json.dumps({"101": []}), encoding="utf-8")
            danger_path.write_text(json.dumps(danger), encoding="utf-8")
            with patch.object(stage5, "DATA_DIR", temp_dir), \
                 patch.object(stage5, "INCOMING_PREDICTIONS_FILE", str(incoming_path)), \
                 patch.object(stage5, "DANGER_AUDIT_FILE", str(danger_path)), \
                 patch.object(stage5, "AGGREGATOR_REPORT_FILE", str(report_path)):
                report = stage5.run_master_aggregator()
        self.assertEqual(report[0]["match_chemistry_list"]["Gg"], "Unavailable")
        self.assertIsNone(report[0]["danger_report"]["home"]["breach"])

    def test_stage6_period_minutes_and_level_only_session_alert_render(self):
        orchestrator = object.__new__(stage6.SupremeOrchestrator)
        orchestrator.cycle = 1
        self.assertEqual(orchestrator.extract_minute({"periods": [{"minutes": 63}]}), 63)
        old_alerts = stage6.SESSION_ALERTS[:]
        stage6.SESSION_ALERTS[:] = [{
            "level": "✅ STANDARD", "fixture": "Home vs Away", "minute": 45,
            "confidence": 35, "msg": "Verified",
        }]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                orchestrator.print_orchestrator_board([], 0, 0)
        finally:
            stage6.SESSION_ALERTS[:] = old_alerts

    def test_api_live_index_keeps_ft_snapshot_after_feed_removal(self):
        snapshot = {
            "503": {
                "fixture_id": "503", "home_team": "Alpha", "away_team": "Beta",
                "ft_score": "3-0", "is_finished": True, "minute": 90,
            }
        }
        with patch.object(api_main, "load_finished_archive", return_value={}), \
             patch.object(api_main, "load_ft_snapshot", return_value=snapshot), \
             patch.object(api_main, "get_live_scores_cached", return_value=[]):
            index = api_main._live_index()
        self.assertTrue(index["503"]["is_finished"])
        self.assertEqual(index["503"]["state"], "FT")
        self.assertEqual(index["503"]["score"], "3-0")

    def test_stage6_isolates_fixture_failure_and_persists_errors(self):
        orchestrator = object.__new__(stage6.SupremeOrchestrator)
        orchestrator.cycle = 0
        orchestrator.load_all_prematch_data = lambda: {}
        orchestrator.maintenance_thread = lambda db, live=None: None
        orchestrator.fetch_live_scores = lambda: [{"id": "bad"}, {"id": "good"}]
        orchestrator.cleanup_stale_memory = lambda live_ids: None

        def process(fx, db):
            if fx["id"] == "bad":
                raise ValueError("malformed fixture")
            return {"id": fx["id"], "name": "Good", "minute": 10,
                    "conf": 0, "h_pressure": 0, "a_pressure": 0,
                    "chaos": 0, "h_xg": 0, "a_xg": 0, "h_sot": 0,
                    "a_sot": 0, "structural": "OK",
                    "key_loss": {"h_lost": 0, "a_lost": 0},
                    "alerts": [], "in_db": False}
        orchestrator._process_live_fixture = process
        orchestrator.print_orchestrator_board = lambda *args: None
        saved = {}
        orchestrator.save_orchestrator_board = lambda *args: saved.update(
            board=args[3], matches=args[0], errors=args[3])
        orchestrator.save_live_dashboard = lambda *args: None
        orchestrator.run_single_cycle()
        self.assertEqual([m["id"] for m in saved["matches"]], ["good"])
        self.assertEqual(saved["errors"][0]["fixture_id"], "bad")

    def test_stage6_preserves_board_when_live_feed_is_empty(self):
        orchestrator = object.__new__(stage6.SupremeOrchestrator)
        orchestrator.cycle = 0
        orchestrator.load_all_prematch_data = lambda: {}
        orchestrator.maintenance_thread = lambda db, live=None: None
        orchestrator.fetch_live_scores = lambda: []
        orchestrator.cleanup_stale_memory = lambda live_ids: None
        called = []
        orchestrator.print_orchestrator_board = lambda *args: called.append("print")
        orchestrator.save_orchestrator_board = lambda *args: called.append("save")
        orchestrator.run_single_cycle()

# ═══════════════════════════════════════════════════════════════════════════

        self.assertEqual(called, [])

# VALIDATION LEDGER — the rules confirmed for this build
#   1. UNDER 2.5 gets a FINAL verdict at 45' and is never extended.
#   2. The 30' verdict is a PRE-verdict, tallied against the 45' main verdict.
#   3. Code 1 keeps an un-kicked fixture while it has lineup+formation and
#      never shows a finished one.
#   4. Finished rows keep real statistics and terminal verdicts.
#   5. Every pick settles WON or LOST — there is no third "vanishes" path.
# ═══════════════════════════════════════════════════════════════════════════
class LiveValidationLedgerTests(unittest.TestCase):
    """Contracts for the 30'/45' ledger, the 45' UNDER lock and settlement."""

    @staticmethod
    def _ctx(home=0, away=0, h_sot=0, a_sot=0, h_corn=0, a_corn=0,
             minute=45, finished=False):
        def stats(sot, corn):
            return {"shots-on-target": sot, "corners": corn,
                    "dangerous-attacks": 0, "box": None}
        return {
            "id": "1", "name": "Home vs Away", "minute": minute,
            "home": {"goals": home, "stats": stats(h_sot, h_corn)},
            "away": {"goals": away, "stats": stats(a_sot, a_corn)},
            "impact": {"home": {"reds": 0, "gk_risk": False, "key_sub_off": 0},
                       "away": {"reds": 0, "gk_risk": False, "key_sub_off": 0}},
            "events": [],
            "is_finished": finished,
        }

    # ── RULE 1: UNDER 2.5 locks at 45', and ALWAYS decides ───────────────
    def test_under_locks_likely_at_45(self):
        verdict, note = stage2.locked_verdict_at_45(stage2.V_SUPPORTED, self._ctx())
        self.assertEqual(verdict, stage2.VERDICT_LIKELY)
        self.assertIn("LIKELY", note)

    def test_under_never_says_rejected_at_45(self):
        # The user's objection: "rejected" asserts a certainty the engine does
        # not have, and it was being produced from a WEAK engine reading. No
        # engine state may produce a REJECTED-family verdict at 45' any more.
        for gate in (stage2.V_SUPPORTED, stage2.V_CONTRADICTED,
                     stage2.V_NEUTRAL, stage2.V_INSUFFICIENT):
            for goals in ((0, 0), (1, 0), (2, 0), (0, 1)):
                verdict, _ = stage2.locked_verdict_at_45(
                    gate, self._ctx(home=goals[0], away=goals[1]))
                self.assertNotEqual(verdict, stage2.VERDICT_FINAL_REJECTED)
                self.assertIn(verdict, (
                    stage2.VERDICT_LIKELY, stage2.VERDICT_UNLIKELY,
                    stage2.VERDICT_UNCERTAIN, stage2.VERDICT_VOID))

    def test_under_two_goals_under_pressure_is_unlikely_not_rejected(self):
        # 2 goals is on the line, but sustained engine pressure is real
        # evidence, so the honest word is UNLIKELY.
        verdict, note = stage2.locked_verdict_at_45(
            stage2.V_CONTRADICTED, self._ctx(home=2, away=0, h_sot=5, a_sot=4))
        self.assertEqual(verdict, stage2.VERDICT_UNLIKELY)
        self.assertIn("UNLIKELY", note)

    def test_under_goalless_45_follows_the_engines_not_the_scoreline(self):
        # THE USER'S RULE: the ENGINE decides; the scoreline only breaks ties.
        # A first pass returned LIKELY for 0 goals BEFORE consulting the
        # engines, so a goalless half under relentless pressure (engines 0 of 3)
        # still printed LIKELY. That made Code 2 ignore its own intelligence.
        # 0-0 must now track the engine verdict exactly.
        # 2 of 3 agreeing -> LIKELY.
        verdict, note = stage2.locked_verdict_at_45(
            stage2.V_SUPPORTED, self._ctx(home=0, away=0, h_sot=2, a_sot=1),
            stage2.V_SUPPORTED)
        self.assertEqual(verdict, stage2.VERDICT_LIKELY)
        self.assertIn("2 of 3", note)
        # 0 of 3 - the engines reading pressure AGAINST the under -> UNLIKELY,
        # even though nobody has scored. A goalless half under 20 shots is a
        # match running away from the under and the board must say so.
        verdict, note = stage2.locked_verdict_at_45(
            stage2.V_CONTRADICTED, self._ctx(home=0, away=0, h_sot=10, a_sot=10),
            stage2.V_CONTRADICTED)
        self.assertEqual(verdict, stage2.VERDICT_UNLIKELY)
        self.assertIn("0 of 3", note)
        # 1 of 3 - the engines are split, so the scoreline breaks the tie.
        verdict, note = stage2.locked_verdict_at_45(
            stage2.V_INSUFFICIENT, self._ctx(home=0, away=0, h_sot=2, a_sot=1),
            stage2.V_INSUFFICIENT)
        self.assertEqual(verdict, stage2.VERDICT_LIKELY)
        self.assertIn("1 of 3", note)

    def test_scoreline_never_overrides_a_clear_engine_verdict(self):
        # Exhaustively: whatever the goal count, an engine verdict wins. Only
        # a split engine (1 of 3) may consult the scoreline.
        for goals in (0, 1, 2):
            for gate, stats, expected in (
                (stage2.V_SUPPORTED, stage2.V_SUPPORTED, stage2.VERDICT_LIKELY),
                (stage2.V_CONTRADICTED, stage2.V_CONTRADICTED,
                 stage2.VERDICT_UNLIKELY),
            ):
                verdict, _ = stage2.locked_verdict_at_45(
                    gate, self._ctx(home=goals, away=0, h_sot=6, a_sot=6), stats)
                self.assertEqual(verdict, expected,
                                 f"{goals} goals, {stats} should be {expected}")

    def test_under_one_goal_at_45_is_likely(self):
        verdict, _ = stage2.locked_verdict_at_45(
            stage2.V_INSUFFICIENT, self._ctx(home=1, away=0, h_sot=3, a_sot=2))
        self.assertEqual(verdict, stage2.VERDICT_LIKELY)

    def test_under_is_likely_when_two_of_three_engines_agree(self):
        # The user's rule: the condition OR a 2-of-3 engine agreement.
        # With no goals the scoreline already reads LIKELY, so the engines
        # agreeing must not change it.
        verdict, _ = stage2.locked_verdict_at_45(
            stage2.V_SUPPORTED, self._ctx(home=0, away=0),
            stage2.V_SUPPORTED)
        self.assertEqual(verdict, stage2.VERDICT_LIKELY)
        # And with 2 goals, engine agreement is what lifts it off UNCLEAR.
        verdict, note = stage2.locked_verdict_at_45(
            stage2.V_INSUFFICIENT, self._ctx(home=2, away=0),
            stage2.V_SUPPORTED)
        self.assertEqual(verdict, stage2.VERDICT_LIKELY)
        self.assertIn("2 of 3", note)

    def test_under_two_goals_without_pressure_is_unclear(self):
        # On the line, no engine opinion: a genuine coin-toss, so UNCLEAR.
        verdict, note = stage2.locked_verdict_at_45(
            stage2.V_INSUFFICIENT, self._ctx(home=2, away=0))
        self.assertEqual(verdict, stage2.VERDICT_UNCERTAIN)
        self.assertIn("UNCLEAR", note)

    def test_under_returns_unclear_when_data_says_nothing(self):
        # Only reachable with no goals AND contradictory engine states, which
        # the scoreline resolves as LIKELY. UNCLEAR is still the honest answer
        # whenever the engine states disagree with each other.
        for gate in (stage2.V_NEUTRAL, stage2.V_INSUFFICIENT):
            verdict, note = stage2.locked_verdict_at_45(gate, self._ctx())
            self.assertIn(verdict, (stage2.VERDICT_LIKELY, stage2.VERDICT_UNCERTAIN))
        # An explicitly empty scoreline with no supporting evidence at all.
        verdict, note = stage2.locked_verdict_at_45(
            stage2.V_NEUTRAL, self._ctx(home=0, away=0, h_sot=0, a_sot=0))
        self.assertEqual(verdict, stage2.VERDICT_LIKELY)

    def test_under_is_void_when_three_goals_already_scored(self):
        # 3+ goals is ARITHMETIC, not a judgement. This is the one case that
        # legitimately ends the pick without an opinion.
        verdict, note = stage2.locked_verdict_at_45(
            stage2.V_NEUTRAL, self._ctx(home=1, away=2))
        self.assertEqual(verdict, stage2.VERDICT_VOID)
        self.assertIn("already lost", note)
        # Even when the engines fully support it, arithmetic wins.
        verdict, _ = stage2.locked_verdict_at_45(
            stage2.V_SUPPORTED, self._ctx(home=3, away=0),
            stage2.V_SUPPORTED)
        self.assertEqual(verdict, stage2.VERDICT_VOID)

    def test_under_is_the_only_locked_market(self):
        self.assertIn("UNDER_2.5", stage2.LOCKED_AT_45_MARKETS)
        for extendable in ("OVER_2.5", "GG", "GG_OVER_2.5", "TO_SCORE"):
            self.assertNotIn(extendable, stage2.LOCKED_AT_45_MARKETS)

    def test_locked_verdicts_are_terminal(self):
        self.assertIn(stage2.VERDICT_FINAL_APPROVED, stage2.TERMINAL_VERDICTS)
        self.assertIn(stage2.VERDICT_FINAL_REJECTED, stage2.TERMINAL_VERDICTS)
        self.assertIn(stage2.VERDICT_UNCERTAIN, stage2.TERMINAL_VERDICTS)

    def test_to_score_window_extends_to_ninety(self):
        # The old 60-70 cap made a 78' or 82' TO_SCORE structurally incapable
        # of triggering.
        self.assertEqual(stage2.TO_SCORE_OPEN_MINUTE, 30)
        self.assertEqual(stage2.TO_SCORE_CLOSE_MINUTE, 90)
        self.assertGreater(stage2.TO_SCORE_CLOSE_MINUTE, 82)

    # ── RULE 2: 30' pre-verdict tallied against the 45' main verdict ─────
    def test_pre_and_main_agreeing_is_not_overruled(self):
        verdict, overruled, note = stage2.reconcile_pre_and_main(
            stage2.VERDICT_PRE_APPROVED, stage2.VERDICT_FINAL_APPROVED)
        self.assertEqual(verdict, stage2.VERDICT_FINAL_APPROVED)
        self.assertFalse(overruled)
        self.assertIn("agree", note)

    def test_45_overrules_a_different_30_pre_verdict(self):
        verdict, overruled, note = stage2.reconcile_pre_and_main(
            stage2.VERDICT_PRE_APPROVED, stage2.VERDICT_FINAL_REJECTED)
        self.assertEqual(verdict, stage2.VERDICT_FINAL_REJECTED)
        self.assertTrue(overruled)
        self.assertIn("overrules", note)

    def test_missing_pre_verdict_does_not_block_the_main_verdict(self):
        # A fixture first seen at 45' or later must still receive its 45' verdict.
        verdict, overruled, note = stage2.reconcile_pre_and_main(
            None, stage2.VERDICT_FINAL_APPROVED)
        self.assertEqual(verdict, stage2.VERDICT_FINAL_APPROVED)
        self.assertFalse(overruled)
        self.assertIn("No 30'", note)

    # ── RULE 5: every pick settles, win AND loss ────────────────────────
    def test_under_settles_lost_at_three_goals(self):
        done, note, outcome = stage2.check_if_done(
            self._ctx(home=1, away=2), {"type": "UNDER_2.5"})
        self.assertTrue(done)
        self.assertEqual(outcome, stage2.VERDICT_LOST)

    def test_under_settles_won_at_full_time(self):
        done, _, outcome = stage2.check_if_done(
            self._ctx(home=1, away=1, finished=True), {"type": "UNDER_2.5"},
            is_finished=True)
        self.assertTrue(done)
        self.assertEqual(outcome, stage2.VERDICT_WON)

    def test_gg_settles_lost_when_a_side_never_scores(self):
        done, _, outcome = stage2.check_if_done(
            self._ctx(home=0, away=1, finished=True), {"type": "GG"},
            is_finished=True)
        self.assertTrue(done)
        self.assertEqual(outcome, stage2.VERDICT_LOST)

    def test_to_score_settles_lost_at_full_time(self):
        done, _, outcome = stage2.check_if_done(
            self._ctx(home=0, away=2, finished=True),
            {"type": "TO_SCORE", "target_loc": "home"}, is_finished=True)
        self.assertTrue(done)
        self.assertEqual(outcome, stage2.VERDICT_LOST)

    def test_over_settles_lost_at_full_time(self):
        done, _, outcome = stage2.check_if_done(
            self._ctx(home=1, away=1, finished=True), {"type": "OVER_2.5"},
            is_finished=True)
        self.assertTrue(done)
        self.assertEqual(outcome, stage2.VERDICT_LOST)

    def test_open_pick_does_not_settle_before_it_can(self):
        done, _, outcome = stage2.check_if_done(
            self._ctx(home=0, away=0), {"type": "UNDER_2.5"})
        self.assertFalse(done)
        self.assertEqual(outcome, "")

    def test_legacy_u25_alias_still_settles(self):
        done, _, outcome = stage2.check_if_done(
            self._ctx(home=1, away=2), {"type": "U2.5"})
        self.assertTrue(done)
        self.assertEqual(outcome, stage2.VERDICT_LOST)

    # ── Market direction: an UNDER gate cannot open on OVER evidence ─────
    def test_market_direction_is_never_none(self):
        self.assertEqual(stage2.market_direction("UNDER_2.5"), stage2.DIRECTION_UNDER)
        self.assertEqual(stage2.market_direction("OVER_2.5"), stage2.DIRECTION_OVER)
        self.assertEqual(stage2.market_direction("GG"), stage2.DIRECTION_NEUTRAL)
        self.assertIsNotNone(stage2.market_direction("anything-else"))
        self.assertIsNotNone(stage2.market_direction(None))

    def test_engine2_inverts_its_polarity_for_under(self):
        # Heavy pressure: OVER must pass, UNDER must fail. Before the fix the
        # same evidence passed both directions, which is how one fixture was
        # handed UNDER 2.5 and OVER 2.5 at once.
        data = self._ctx(h_sot=6, a_sot=5)
        over_pass, _ = stage2.engine_2_structural_stacker(
            data, "match", stage2.DIRECTION_OVER)
        under_pass, _ = stage2.engine_2_structural_stacker(
            data, "match", stage2.DIRECTION_UNDER)
        self.assertTrue(over_pass)
        self.assertFalse(under_pass)

    def test_engine3_inverts_its_polarity_for_under(self):
        data = self._ctx(minute=60)
        data["events"] = [
            {"participant_id": 1, "minute": 55, "type": {"code": "shot-on-target"}},
            {"participant_id": 1, "minute": 56, "type": {"code": "corner"}},
            {"participant_id": 1, "minute": 57, "type": {"code": "goal"}},
            {"participant_id": 1, "minute": 58, "type": {"code": "corner"}},
            {"participant_id": 1, "minute": 59, "type": {"code": "goal"}},
        ]
        over_pass, _ = stage2.engine_3_momentum_escalator(
            data, 1, stage2.DIRECTION_OVER)
        under_pass, _ = stage2.engine_3_momentum_escalator(
            data, 1, stage2.DIRECTION_UNDER)
        self.assertTrue(over_pass)
        self.assertFalse(under_pass)

# ═══════════════════════════════════════════════════════════════════════════
# CODE 1 ADMISSION + SHARED STATE CLASSIFIER
# ═══════════════════════════════════════════════════════════════════════════
class PrematchAdmissionTests(unittest.TestCase):
    NOW = datetime(2026, 9, 26, 14, 0, tzinfo=timezone.utc)

    @classmethod
    def _fx(cls, state_id=1, starting_at="2026-09-26T15:00:00", lineups=True,
            formations=True, state=None):
        fx = {
            "id": 9, "starting_at": starting_at, "state_id": state_id,
            "name": "Alpha vs Beta",
            "participants": [{"id": 10, "meta": {"location": "home"}},
                             {"id": 20, "meta": {"location": "away"}}],
            "lineups": ([{"type_id": 11, "player_id": 1, "team_id": 10}]
                        if lineups else []),
            "formations": ([{"participant_id": 10, "formation": "4-3-3"},
                            {"participant_id": 20, "formation": "4-4-2"}]
                           if formations else []),
        }
        if state:
            fx["state"] = {"name": state}
        return fx

    def test_finished_states_are_never_live(self):
        # 6 = after extra time, 7 = after penalties. Both used to sit INSIDE the
        # "live" list, which kept a completed match on the board as LIVE.
        for sid in (5, 6, 7, 19):
            info = classifier.classify_fixture(self._fx(state_id=sid))
            self.assertTrue(info["is_finished"], f"state_id {sid} should be finished")
            self.assertFalse(info["is_live"], f"state_id {sid} must not be live")

    def test_real_live_states_are_still_live(self):
        for sid in (2, 3, 4, 12, 13, 21, 22):
            self.assertTrue(classifier.classify_fixture(
                self._fx(state_id=sid))["is_live"], f"state_id {sid}")

    def test_inplay_state_string_wins_over_state_id(self):
        self.assertTrue(classifier.classify_fixture(
            self._fx(state_id=2, state="FT"))["is_finished"])
        self.assertTrue(classifier.classify_fixture(
            self._fx(state_id=2, state="INPLAY_2ND_HALF"))["is_live"])

    def test_naive_kickoff_is_utc_not_machine_local(self):
        # On this UTC+1 host the old .astimezone() call shifted every kickoff
        # back an hour.
        parsed = classifier.parse_kickoff_utc("2026-09-26T11:30:00")
        self.assertEqual(parsed.hour, 11)
        self.assertEqual(parsed.utcoffset().total_seconds(), 0)

    def test_unstarted_fixture_admitted_with_lineup_and_formation(self):
        info = classifier.admit_to_prematch_board(self._fx(state_id=1), now=self.NOW)
        self.assertTrue(info["admitted"])
        self.assertIn("lineups + formation confirmed", info["admit_reason"])

    def test_unstarted_fixture_withheld_until_formation_arrives(self):
        info = classifier.admit_to_prematch_board(
            self._fx(state_id=1, formations=False), now=self.NOW)
        self.assertFalse(info["admitted"])
        self.assertIn("awaiting", info["admit_reason"])

    def test_one_sided_formation_is_not_enough(self):
        fx = self._fx(state_id=1)
        fx["formations"] = [{"participant_id": 10, "formation": "4-3-3"}]
        self.assertFalse(classifier.admit_to_prematch_board(fx, now=self.NOW)["admitted"])

    def test_upcoming_fixture_has_no_time_cap(self):
        # The user requires an un-kicked fixture to stay "for as long as it
        # takes". The old 65-minute cap dropped it while still waiting.
        far = self._fx(state_id=1, starting_at="2026-09-27T18:00:00")
        info = classifier.admit_to_prematch_board(far, now=self.NOW)
        self.assertTrue(info["is_upcoming"])
        self.assertTrue(info["admitted"])

    def test_finished_fixture_is_never_admitted(self):
        for sid in (5, 6, 7):
            self.assertFalse(classifier.admit_to_prematch_board(
                self._fx(state_id=sid), now=self.NOW)["admitted"], f"state_id {sid}")

    def test_abandoned_fixture_is_culled_by_the_clock(self):
        fx = self._fx(state_id=1, starting_at="2020-01-01T10:00:00")
        self.assertTrue(classifier.classify_fixture(fx, now=self.NOW)["is_stale"])
        self.assertFalse(classifier.admit_to_prematch_board(fx, now=self.NOW)["admitted"])

    def test_live_fixture_needs_official_lineup_only(self):
        info = classifier.admit_to_prematch_board(
            self._fx(state_id=2, formations=False), now=self.NOW)
        self.assertTrue(info["admitted"])
        self.assertIn("LIVE", info["admit_reason"])


# ═══════════════════════════════════════════════════════════════════════════
# FINISHED ROWS KEEP THEIR REAL STATISTICS AND VERDICTS
# ═══════════════════════════════════════════════════════════════════════════
class FinishedRowRetentionTests(unittest.TestCase):
    def test_finished_snapshot_carries_real_statistics(self):
        std = {"fixture_id": "42", "home_team": "A", "away_team": "B",
               "ft_score": "2-1", "h_sot": 4, "a_sot": 4,
               "h_corners": 8, "a_corners": 1}
        entry = stage2._finished_snapshot_board_entry(std)
        # The old code returned _empty_statistics() here, which is what
        # produced "No live statistics for this fixture yet".
        self.assertEqual(entry["statistics"]["home"]["shots_on_target"], 4)
        self.assertEqual(entry["statistics"]["away"]["shots_on_target"], 4)
        self.assertEqual(entry["statistics"]["home"]["corners"], 8)
        self.assertEqual(entry["statistics"]["away"]["corners"], 1)

    def test_finished_snapshot_resolves_sides_by_participant_meta(self):
        # participant_id is numeric; matching it against "home" always yielded 0.
        fixture = {
            "id": 7, "name": "X vs Y", "state": {"state": "FT"},
            "participants": [{"id": 101, "meta": {"location": "home"}},
                             {"id": 202, "meta": {"location": "away"}}],
            "statistics": [
                {"participant_id": 101, "type": {"code": "shots-on-target"},
                 "data": {"value": 5}},
                {"participant_id": 202, "type": {"code": "shots-on-target"},
                 "data": {"value": 3}},
                {"participant_id": 101, "type": {"code": "corners"},
                 "data": {"value": 7}},
            ],
        }
        entry = stage2._summary_board_entry(fixture)
        self.assertTrue(entry["is_finished"])
        self.assertEqual(entry["statistics"]["home"]["shots_on_target"], 5)
        self.assertEqual(entry["statistics"]["away"]["shots_on_target"], 3)
        self.assertEqual(entry["statistics"]["home"]["corners"], 7)

    def test_finished_snapshot_keeps_terminal_verdicts(self):
        fid = "777"
        saved = dict(stage2.MATCH_VALIDATION_STATE)
        try:
            stage2.MATCH_VALIDATION_STATE[fid] = {
                "UNDER_2.5:match": {
                    "verdict_30": stage2.VERDICT_PRE_APPROVED,
                    "verdict_45": stage2.VERDICT_FINAL_REJECTED,
                    "verdict_45_minute": 45, "final": True, "locked": True,
                    "overruled": True,
                },
            }
            entry = stage2._finished_snapshot_board_entry(
                {"fixture_id": fid, "ft_score": "1-2"})
            self.assertEqual(len(entry["predictions"]), 1)
            self.assertEqual(entry["predictions"][0]["verdict"],
                             stage2.VERDICT_FINAL_REJECTED)
            self.assertTrue(entry["predictions"][0]["final"])
        finally:
            stage2.MATCH_VALIDATION_STATE.clear()
            stage2.MATCH_VALIDATION_STATE.update(saved)

    def test_scheduled_rows_are_still_retained_for_bookkeeping(self):
        # Pinned by the original suite: the board keeps SCHEDULED/FINISHED rows
        # even after Code 1 stops showing them.
        fixture = {"id": 8, "name": "P vs Q", "state": {"state": "NS"},
                   "participants": [], "statistics": []}
        entry = stage2._summary_board_entry(fixture)
        self.assertEqual(entry["status"], "SCHEDULED")
        self.assertIn("predictions", entry)

# ═══════════════════════════════════════════════════════════════════════════
# CODE 3C — ALERT PRUNING (stale + legacy rows must stop being shown)
# ═══════════════════════════════════════════════════════════════════════════
class AlertPruningTests(unittest.TestCase):
    def _alert(self, fixture_id, when, **extra):
        row = {"fixture_id": fixture_id, "match_name": f"M{fixture_id}",
               "prediction_type": "GG", "target": "match",
               "combined_state": "SUPPORTED", "timestamp": when}
        row.update(extra)
        return row

    def test_recent_alert_survives_pruning(self):
        now = datetime.now(timezone.utc).isoformat()
        kept = api_main._prune_validated_alerts([self._alert("1", now)])
        self.assertEqual(len(kept), 1)

    def test_alert_older_than_24h_is_dropped(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=40)).isoformat()
        kept = api_main._prune_validated_alerts([self._alert("2", old)])
        self.assertEqual(kept, [])

    def test_legacy_row_without_combined_state_is_dropped(self):
        # The STATS_1/3 rows written by the old single-engine gate.
        now = datetime.now(timezone.utc).isoformat()
        legacy = {"fixture_id": "3", "match_name": "L", "stats_note": "STATS_1/3",
                  "timestamp": now}
        self.assertEqual(api_main._prune_validated_alerts([legacy]), [])

    def test_alert_gains_team_verdict_and_final_result(self):
        now = datetime.now(timezone.utc).isoformat()
        kept = api_main._prune_validated_alerts(
            [self._alert("4", now, home_team="Alpha", away_team="Beta")])
        self.assertEqual(len(kept), 1)
        self.assertIn("Alpha", kept[0]["team"])
        self.assertTrue(kept[0]["verdict"])
        self.assertEqual(kept[0]["final_result"], "PENDING")

    def test_pruning_is_capped_and_newest_first(self):
        now = datetime.now(timezone.utc)
        rows = [
            self._alert(str(i), (now - timedelta(minutes=i)).isoformat())
            for i in range(250)
        ]
        kept = api_main._prune_validated_alerts(rows)
        self.assertLessEqual(len(kept), 200)
        stamps = [r["timestamp"] for r in kept]
        self.assertEqual(stamps, sorted(stamps, reverse=True))

    def test_pruning_never_mutates_the_source_rows(self):
        now = datetime.now(timezone.utc).isoformat()
        original = self._alert("5", now)
        snapshot = json.loads(json.dumps(original))
        api_main._prune_validated_alerts([original])
        self.assertEqual(original, snapshot)

    def test_non_list_input_is_safe(self):
        self.assertEqual(api_main._prune_validated_alerts(None), [])


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 1 — CODE 2 ACTS AS A VALIDATOR, NOT A SETTLEMENT RECORDER
#   1. The 45' verdict is ALWAYS delivered, even if the window was missed.
#   2. 60' delivers a FINAL validation for every Code 1 market.
#   3. After 60' a market may only TRIGGER, never be re-verdicted.
#   4. Missed checkpoints are backfilled and flagged.
#   5. Under 2.5 is NOT re-decided at 60' — a 45' lock must stay locked.
# ═══════════════════════════════════════════════════════════════════════════
class Code2ValidatorPhase1Tests(unittest.TestCase):
    """Code 2 must VALIDATE every pick it carries, not merely settle it."""

    @staticmethod
    def _ctx(home=0, away=0, h_sot=0, a_sot=0, minute=60, finished=False):
        def stats(sot):
            return {"shots-on-target": sot, "corners": 2,
                    "dangerous-attacks": 0, "box": None}
        return {
            "id": "1", "name": "Home vs Away", "minute": minute,
            "home": {"goals": home, "stats": stats(h_sot)},
            "away": {"goals": away, "stats": stats(a_sot)},
            "impact": {"home": {"reds": 0, "gk_risk": False, "key_sub_off": 0},
                       "away": {"reds": 0, "gk_risk": False, "key_sub_off": 0}},
            "events": [],
            "is_finished": finished,
        }

    # ── ITEM 2: 60' final validation for every Code 1 market ────────────
    def test_every_code1_market_is_locked_at_60(self):
        # Before Phase 1 only UNDER_2.5 was locked. Every other Code 1 pick
        # could sit unresolved all match and settle at FT with no validation.
        for market in ("TO_SCORE", "GG", "OVER_2.5", "GG_OVER_2.5"):
            self.assertIn(market, stage2.LOCKED_AT_60_MARKETS,
                          f"{market} must receive a 60' final validation")
        self.assertIn("UNDER_2.5", stage2.LOCKED_AT_60_MARKETS)
        self.assertEqual(stage2.CHECKPOINT_FINAL_MINUTE, 60)

    def test_60_validation_engines_decide_not_the_scoreline(self):
        # Same rule as 45': the engine decides, the scoreline only breaks ties.
        verdict, note = stage2.final_verdict_at_60(
            stage2.V_SUPPORTED, self._ctx(h_sot=2, a_sot=1),
            "TO_SCORE", stage2.V_SUPPORTED)
        self.assertEqual(verdict, stage2.VERDICT_LIKELY)
        self.assertIn("2 of 3", note)
        # 0 of 3 beats a flattering goal count.
        verdict, note = stage2.final_verdict_at_60(
            stage2.V_CONTRADICTED, self._ctx(h_sot=10, a_sot=10, home=0),
            "TO_SCORE", stage2.V_CONTRADICTED)
        self.assertEqual(verdict, stage2.VERDICT_UNLIKELY)
        self.assertIn("0 of 3", note)

    def test_60_validation_never_says_rejected(self):
        for gate in (stage2.V_SUPPORTED, stage2.V_CONTRADICTED,
                     stage2.V_NEUTRAL, stage2.V_INSUFFICIENT):
            for market in ("TO_SCORE", "GG", "OVER_2.5", "UNDER_2.5"):
                for goals in (0, 1, 2, 3, 5):
                    verdict, _ = stage2.final_verdict_at_60(
                        gate, self._ctx(home=goals), market, gate)
                    self.assertNotEqual(verdict, stage2.VERDICT_FINAL_REJECTED)
                    self.assertIn(verdict, (
                        stage2.VERDICT_LIKELY, stage2.VERDICT_UNLIKELY,
                        stage2.VERDICT_UNCERTAIN, stage2.VERDICT_VOID))

    def test_60_arithmetic_voids_a_dead_market(self):
        # 3+ goals kills the under; 4+ kills the over. Arithmetic, not opinion.
        verdict, note = stage2.final_verdict_at_60(
            stage2.V_SUPPORTED, self._ctx(home=3, away=0),
            "UNDER_2.5", stage2.V_SUPPORTED)
        self.assertEqual(verdict, stage2.VERDICT_VOID)
        self.assertIn("dead", note)
        verdict, _ = stage2.final_verdict_at_60(
            stage2.V_CONTRADICTED, self._ctx(home=2, away=2),
            "OVER_2.5", stage2.V_CONTRADICTED)
        self.assertEqual(verdict, stage2.VERDICT_VOID)

    # ── ITEM 3: after 60' it may only TRIGGER ───────────────────────────
    def test_after_60_market_is_trigger_only(self):
        self.assertEqual(stage2.TRIGGER_ONLY_AFTER_MINUTE, 60)
        self.assertEqual(stage2.FINAL_STRIKE_OPEN, 60)

    # ── ITEM 5: the 45' lock is never overwritten at 60' ────────────────
    def test_under_45_lock_is_not_redecided_at_60(self):
        # A 45' lock that can be overwritten at 60' is not a lock. The main
        # loop gates the 60' checkpoint on `not is_locked_market`, so Under
        # never reaches final_verdict_at_60.
        self.assertIn("UNDER_2.5", stage2.LOCKED_AT_45_MARKETS)
        # Even if called directly, the under's own arithmetic keeps it honest.
        verdict, _ = stage2.final_verdict_at_60(
            stage2.V_SUPPORTED, self._ctx(h_sot=1, a_sot=1, home=0),
            "UNDER_2.5", stage2.V_SUPPORTED)
        self.assertEqual(verdict, stage2.VERDICT_LIKELY)

    # ── ITEMS 1 & 4: guaranteed delivery and honest backfill ────────────
    def test_45_verdict_is_delivered_on_first_cycle_at_or_past_45(self):
        # The condition the main loop uses. Whatever the minute, once at/past
        # 45' with no 45' verdict yet, the verdict is written.
        for minute in (45, 46, 61, 75, 90):
            self.assertTrue(minute >= stage2.CHECKPOINT_MAIN_MINUTE)
        # A pick first seen at 90' still gets a verdict, flagged as late.
        verdict, _ = stage2.locked_verdict_at_45(
            stage2.V_SUPPORTED, self._ctx(minute=90), stage2.V_SUPPORTED)
        self.assertEqual(verdict, stage2.VERDICT_LIKELY)

    def test_settled_rows_surface_the_60_verdict(self):
        # The finished-fixture board path previously read only verdict_45 and
        # verdict_30, so a properly validated pick appeared as never judged.
        board = stage2._finished_snapshot_board_entry
        self.assertTrue(callable(board))
        stage2.MATCH_VALIDATION_STATE.clear()
        stage2.MATCH_VALIDATION_STATE["42"] = {
            "GG:match": {
                "verdict_45": "LIKELY", "verdict_45_minute": 45,
                "verdict_60": "UNLIKELY", "verdict_60_minute": 60,
                "final_60": True,
                "verdict_60_note": "engines turned at 60'",
                "locked": False,
            },
        }
        row = board({
            "fixture_id": 42, "name": "A vs B", "minute": 90,
            "ft_score": "1-1", "home": {"goals": 1}, "away": {"goals": 1},
            "home_stats": {}, "away_stats": {},
        })
        preds = row.get("predictions") or []
        self.assertEqual(len(preds), 1)
        # The 60' final validation supersedes the 45' read.
        self.assertEqual(preds[0]["verdict_60"], "UNLIKELY")
        self.assertEqual(preds[0]["verdict"], "UNLIKELY")
        self.assertTrue(preds[0]["final"])
        stage2.MATCH_VALIDATION_STATE.clear()

    def test_under_locked_row_keeps_its_45_verdict(self):
        # Precedence rule: for a 45'-locked market the 45' verdict stands and
        # must not be replaced by a 60' read.
        stage2.MATCH_VALIDATION_STATE.clear()
        stage2.MATCH_VALIDATION_STATE["43"] = {
            "UNDER_2.5:match": {
                "verdict_45": "LIKELY", "verdict_45_minute": 45,
                "verdict_60": "UNLIKELY", "verdict_60_minute": 60,
                "locked": True, "final": True,
            },
        }
        row = stage2._finished_snapshot_board_entry({
            "fixture_id": 43, "name": "C vs D", "minute": 90,
            "ft_score": "1-0", "home": {"goals": 1}, "away": {"goals": 0},
            "home_stats": {}, "away_stats": {},
        })
        preds = row.get("predictions") or []
        self.assertEqual(preds[0]["verdict"], "LIKELY")
        # The 60' value is still on record for the audit trail.
        self.assertEqual(preds[0]["verdict_60"], "UNLIKELY")
        stage2.MATCH_VALIDATION_STATE.clear()


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 2 — CODE 2 VALIDATES EVERY LIVE MATCH
#   6. A match Code 1 did not pick is still read from its live statistics.
#   7. The read is an OBSERVATION: own vocabulary, never a verdict, never a bet.
# ═══════════════════════════════════════════════════════════════════════════
class Code2ValidatesEveryMatchTests(unittest.TestCase):
    """Code 2 must read every live match, not only the ones Code 1 picked."""

    @staticmethod
    def _ctx(home=0, away=0, h_sot=0, a_sot=0, minute=50, events=None):
        def stats(sot):
            return {"shots-on-target": sot, "corners": 2,
                    "dangerous-attacks": 2, "box": None}
        return {
            "id": "1", "name": "A vs B", "minute": minute,
            "home": {"goals": home, "stats": stats(h_sot)},
            "away": {"goals": away, "stats": stats(a_sot)},
            "impact": {"home": {"reds": 0, "gk_risk": False, "key_sub_off": 0},
                       "away": {"reds": 0, "gk_risk": False, "key_sub_off": 0}},
            "events": events or [],
            "is_finished": False,
        }

    def test_read_is_skipped_before_30_minutes(self):
        # Too little of the match to read anything.
        self.assertIsNone(stage2.live_only_read(self._ctx(minute=10)))
        self.assertIsNotNone(stage2.live_only_read(self._ctx(minute=31)))

    def test_read_uses_only_its_own_vocabulary(self):
        # A read must NEVER borrow the verdict words. Those belong to a
        # validated Code 1 pick, and reusing them would make an observation
        # indistinguishable from a real verdict.
        for gate in (stage2.V_SUPPORTED, stage2.V_CONTRADICTED,
                     stage2.V_NEUTRAL, stage2.V_INSUFFICIENT):
            for goals in (0, 1, 2, 3, 6):
                read = stage2.live_only_read(self._ctx(home=goals))
                self.assertIsNotNone(read)
                state, note = read
                self.assertIn(state, (stage2.READ_ON_TRACK, stage2.READ_AT_RISK,
                                      stage2.READ_DEAD, stage2.READ_UNCLEAR))
                self.assertNotIn(state, (stage2.VERDICT_LIKELY,
                                         stage2.VERDICT_UNLIKELY,
                                         stage2.VERDICT_FINAL_REJECTED,
                                         stage2.VERDICT_VOID))
                self.assertIn("No prematch pick", note)

    def test_three_goals_makes_the_read_dead(self):
        state, note = stage2.live_only_read(self._ctx(home=3, away=0))
        self.assertEqual(state, stage2.READ_DEAD)
        self.assertIn("dead", note)

    def test_read_never_writes_a_prediction(self):
        # The read must not be capable of becoming a bet. There is no function
        # that appends a live read to a prematch feed, and the read itself
        # carries no verdict and no pick identity.
        self.assertEqual(stage2.LIVE_ONLY_MARKET, "LIVE_READ")
        self.assertEqual(stage2.LIVE_ONLY_MARKETS, ("UNDER_2.5",))
        source = open(stage2.__file__).read()
        # _load_pick_feeds is the ONLY reader of the prematch feeds; a live read
        # must never be written into either of them.
        for feed_const in ("PREDICTIONS_FILE", "INCOMING_PREDICTIONS_FILE"):
            for line in source.splitlines():
                if feed_const in line and "json.dump" in line:
                    self.fail(f"live read must not be written to {feed_const}")

    def test_read_maps_to_a_gate_colour_but_not_a_verdict(self):
        self.assertEqual(stage2.combined_read_state(stage2.READ_ON_TRACK),
                         stage2.V_SUPPORTED)
        self.assertEqual(stage2.combined_read_state(stage2.READ_AT_RISK),
                         stage2.V_CONTRADICTED)
        self.assertEqual(stage2.combined_read_state(stage2.READ_DEAD),
                         stage2.V_SETTLED)
        self.assertEqual(stage2.combined_read_state(stage2.READ_UNCLEAR),
                         stage2.V_INSUFFICIENT)


# ═══════════════════════════════════════════════════════════════════════════
# THE MATCH MINUTE — the number every checkpoint depends on
# ═══════════════════════════════════════════════════════════════════════════
class MatchMinuteResolutionTests(unittest.TestCase):
    """
    Every 30'/45'/60' checkpoint is gated on `minute`. If the minute is wrong,
    the wrong verdicts fire — which is exactly how "APPROVED" appeared on a
    16th-minute match.
    """

    @staticmethod
    def _fx(periods, events=None, state=None):
        return {"id": "1", "name": "A vs B", "periods": periods,
                "events": events or [], "state": state or {},
                "participants": []}

    def test_ticking_period_is_cumulative_match_time(self):
        # Verified against the live feed: Peñarol 1st=46 (ended), 2nd=56
        # (ticking) means the match is at 56', NOT 56+45=101 and NOT max()=56
        # only by luck. A 2nd-half `minutes` value is the match minute.
        fx = self._fx([
            {"description": "1st-half", "minutes": 46, "sort_order": 1,
             "ended": 1790461100, "ticking": False},
            {"description": "2nd-half", "minutes": 56, "sort_order": 2,
             "ended": None, "ticking": True},
        ])
        self.assertEqual(stage2._resolve_match_minute(fx), 56)

    def test_a_late_event_must_not_push_the_minute_forward(self):
        # THE BUG. Trinidense had events at minute 24 and a 1st-half period at
        # 45, so max() reported 45 and the board fired the 45' verdict against
        # a match that had not reached it. The ticking period must win, and an
        # event must never outrank it.
        fx = self._fx(
            [{"description": "1st-half", "minutes": 24, "sort_order": 1,
              "ended": None, "ticking": True}],
            events=[{"minute": 24}, {"minute": 24}])
        self.assertEqual(stage2._resolve_match_minute(fx), 24)

    def test_second_half_running_reads_as_match_minute(self):
        fx = self._fx([
            {"description": "1st-half", "minutes": 47, "sort_order": 1,
             "ended": 1, "ticking": False},
            {"description": "2nd-half", "minutes": 85, "sort_order": 2,
             "ended": None, "ticking": True},
        ])
        self.assertEqual(stage2._resolve_match_minute(fx), 85)

    def test_finished_match_with_no_ticking_period(self):
        fx = self._fx([
            {"description": "1st-half", "minutes": 46, "sort_order": 1,
             "ended": 1, "ticking": False},
            {"description": "2nd-half", "minutes": 94, "sort_order": 2,
             "ended": 2, "ticking": False},
        ], state={"state": "FT"})
        self.assertEqual(stage2._resolve_match_minute(fx), 94)

    def test_board_and_engine_resolve_the_same_minute(self):
        # The board and the engine must never disagree about the minute.
        fx = self._fx([
            {"description": "1st-half", "minutes": 40, "sort_order": 1,
             "ended": None, "ticking": True},
        ])
        self.assertEqual(stage2._resolve_match_minute(fx),
                         stage2._fixture_minute_for_board(fx))


class NoVerdictBeforeCheckpointTests(unittest.TestCase):
    """An open gate is an internal signal, never a verdict."""

    def test_gate_alone_never_produces_approved(self):
        # The board once showed "APPROVED" at 16' purely because the gate was
        # open. Before 30' nothing has been judged, so nothing may be claimed.
        self.assertEqual(stage2.CHECKPOINT_PRE_MINUTE, 30)

    def test_verdict_vocabulary_has_no_approved_watch_at_runtime(self):
        # APPROVED_WATCH still exists as a legacy constant for old boards, but
        # the live path must never emit it.
        self.assertTrue(hasattr(stage2, "VERDICT_APPROVED_WATCH"))
        source = open(stage2.__file__).read()
        # It may only appear in its definition and the legacy family mapper.
        occurrences = [ln.strip() for ln in source.splitlines()
                       if "VERDICT_APPROVED_WATCH" in ln]
        self.assertLessEqual(len(occurrences), 3,
                             "APPROVED_WATCH must not be emitted by the live path")


class Comparison30To45Tests(unittest.TestCase):
    """The function that compares what happened at 30' to what happened at 45'."""

    @staticmethod
    def _s(goals, sot, engines, verdict=None):
        return {"goals": goals, "sot": sot, "engines_passed": engines,
                "verdict": verdict}

    def test_engines_strengthened(self):
        cmp_, note = stage2.compare_observation_to_verdict(
            self._s(0, 2, 1), self._s(0, 4, 2, "LIKELY"))
        self.assertEqual(cmp_, stage2.COMPARE_STRENGTHENED)
        self.assertIn("2/3", note)

    def test_engines_weakened(self):
        cmp_, note = stage2.compare_observation_to_verdict(
            self._s(0, 2, 2), self._s(1, 5, 1, "UNLIKELY"))
        self.assertEqual(cmp_, stage2.COMPARE_WEAKENED)

    def test_engines_held_while_the_match_moved(self):
        cmp_, note = stage2.compare_observation_to_verdict(
            self._s(0, 2, 2), self._s(1, 6, 2, "LIKELY"))
        self.assertEqual(cmp_, stage2.COMPARE_HELD)
        self.assertIn("moved", note)

    def test_market_collapse(self):
        cmp_, note = stage2.compare_observation_to_verdict(
            self._s(0, 1, 2), self._s(2, 8, 0, "VOID"))
        self.assertEqual(cmp_, stage2.COMPARE_COLLAPSED)

    def test_no_baseline_is_honest(self):
        cmp_, note = stage2.compare_observation_to_verdict(
            None, self._s(0, 3, 2, "LIKELY"))
        self.assertEqual(cmp_, stage2.COMPARE_NO_BASELINE)
        self.assertIn("No 30'", note)

    def test_snapshot_reads_the_board_label(self):
        ctx = {
            "home": {"goals": 0, "stats": {"shots-on-target": 2}},
            "away": {"goals": 0, "stats": {"shots-on-target": 1}},
        }
        snap = stage2._live_snapshot(ctx, "STATS_2/3", "LIKELY")
        self.assertEqual(snap["goals"], 0)
        self.assertEqual(snap["sot"], 3)
        self.assertEqual(snap["engines_passed"], 2)


class SettledPredictionKeepsItsTrailTests(unittest.TestCase):
    """
    A settled prediction must still show the work Code 2 did.

    The settlement branch used to append a bare dict and `continue`, which
    discarded the whole validation history. The 30' observation, 45' verdict,
    60' final validation and 30'->45' comparison lived only in the ledger, so a
    settled prediction reached the board as a bare "SETTLED" with no evidence
    of any validation — and the per-match monitor list looked empty.
    """

    def test_settled_row_is_built_from_the_ledger_entry(self):
        source = open(stage2.__file__).read()
        # Both settlement branches must read the ledger entry.
        self.assertIn('settled_entry = MATCH_VALIDATION_STATE[f_id].get(p_key)',
                      source)
        self.assertIn('done_entry = MATCH_VALIDATION_STATE[f_id].get(p_key)',
                      source)
        # And each must carry the three checkpoints onto the row.
        self.assertGreaterEqual(source.count('"verdict_30":  settled_entry'), 1)
        self.assertGreaterEqual(source.count('"verdict_45":  settled_entry'), 1)
        self.assertGreaterEqual(source.count('"verdict_60":  settled_entry'), 1)
        self.assertGreaterEqual(source.count('"comparison_30_45": settled_entry'), 1)
        # The previously-settled branch must do the same.
        self.assertGreaterEqual(source.count('"verdict_45":  done_entry'), 1)

    def test_finished_snapshot_row_keeps_the_trail(self):
        stage2.MATCH_VALIDATION_STATE.clear()
        stage2.MATCH_VALIDATION_STATE["77"] = {
            "GG:match": {
                "verdict_30": "SUPPORTING", "verdict_30_minute": 32,
                "verdict_45": "LIKELY", "verdict_45_minute": 49,
                "verdict_60": "UNLIKELY", "verdict_60_minute": 60,
                "comparison_30_45": "HELD",
                "late_45": True,
            },
        }
        row = stage2._finished_snapshot_board_entry({
            "fixture_id": 77, "name": "X vs Y", "minute": 90,
            "ft_score": "2-2", "home": {"goals": 2}, "away": {"goals": 2},
            "home_stats": {}, "away_stats": {},
        })
        p = (row.get("predictions") or [])[0]
        self.assertEqual(p["verdict_30"], "SUPPORTING")
        self.assertEqual(p["verdict_45"], "LIKELY")
        self.assertEqual(p["verdict_60"], "UNLIKELY")
        self.assertEqual(p["comparison_30_45"], "HELD")
        self.assertTrue(p["late_45"])
        stage2.MATCH_VALIDATION_STATE.clear()

    # ── ONE DIRECTION PER FIXTURE ────────────────────────────────────────
    def test_under_fixture_suppresses_over_markets(self):
        """Code 1 said UNDER_2.5 while the incoming feed also carried two OVER
        markets for the same fixture. Both fired Supreme Alerts at 45', so the
        board contradicted itself. The OVER side must be suppressed and must
        never be alertable; it stays visible with a reason."""
        picks = [
            stage2.normalize_pick({"type": "UNDER 2.5", "target_loc": "match"})[1],
            stage2.normalize_pick({"type": "OVER 2.5", "target_loc": "match"})[1],
            stage2.normalize_pick({"type": "GG_OVER_2.5", "target_loc": "match"})[1],
        ]
        stage2.suppress_contradictory_markets(picks)
        by_key = {p["canonical_key"]: p for p in picks}
        self.assertFalse(by_key["UNDER_2.5:match"].get("suppressed"))
        self.assertTrue(by_key["OVER_2.5:match"].get("suppressed"))
        self.assertTrue(by_key["GG_OVER_2.5:match"].get("suppressed"))
        self.assertIn(
            "contradictory market",
            by_key["OVER_2.5:match"]["suppressed_reason"],
        )

    def test_direction_suppression_leaves_coherent_fixtures_alone(self):
        """Suppression must only fire when BOTH directions are present."""
        under_only = [
            stage2.normalize_pick({"type": "UNDER 2.5", "target_loc": "match"})[1],
            stage2.normalize_pick({"type": "TO_SCORE", "target_loc": "home"})[1],
        ]
        stage2.suppress_contradictory_markets(under_only)
        self.assertFalse(any(p.get("suppressed") for p in under_only))

        neutral = [
            stage2.normalize_pick({"type": "GG", "target_loc": "match"})[1],
            stage2.normalize_pick({"type": "TO_SCORE", "target_loc": "away"})[1],
        ]
        stage2.suppress_contradictory_markets(neutral)
        self.assertFalse(any(p.get("suppressed") for p in neutral))

        # GG is direction-neutral, so a GG + OVER pair on its own is NOT a
        # contradiction — there is no UNDER to contradict. Suppression is
        # specifically "an OVER market on a fixture already tracked UNDER".
        gg_and_over = [
            stage2.normalize_pick({"type": "GG", "target_loc": "match"})[1],
            stage2.normalize_pick({"type": "OVER 2.5", "target_loc": "match"})[1],
        ]
        stage2.suppress_contradictory_markets(gg_and_over)
        self.assertFalse(any(p.get("suppressed") for p in gg_and_over))

        # Add the UNDER back and the OVER side must be suppressed.
        gg_under_over = gg_and_over + [
            stage2.normalize_pick({"type": "UNDER 2.5", "target_loc": "match"})[1]
        ]
        stage2.suppress_contradictory_markets(gg_under_over)
        by_key = {p["canonical_key"]: p for p in gg_under_over}
        self.assertFalse(by_key["GG:match"].get("suppressed"))
        self.assertFalse(by_key["UNDER_2.5:match"].get("suppressed"))
        self.assertTrue(by_key["OVER_2.5:match"].get("suppressed"))

    def test_suppressed_pick_never_fires_an_alert(self):
        """The point of suppression is that the dropped market can never alert
        again. This drives a full cycle with an open gate and asserts no alert
        is recorded."""
        stage2.MATCH_VALIDATION_STATE.clear()
        stage2.ALERT_HISTORY_CACHE = set()
        stage2.VALIDATED_ALERTS = {}
        ctx = {
            "id": 9001, "name": "X vs Y", "minute": 50, "is_finished": False,
            "home": {"goals": 1, "stats": {"shots-on-target": 5,
                                           "dangerous-attacks": 30,
                                           "corners": 6, "box": 5}},
            "away": {"goals": 1, "stats": {"shots-on-target": 2,
                                           "dangerous-attacks": 12,
                                           "corners": 2, "box": 1}},
            "impact": {
                "home": {"reds": 0, "gk_risk": False, "key_sub_off": 0},
                "away": {"reds": 0, "gk_risk": False, "key_sub_off": 0},
            },
            "events": [{"minute": m, "type": t, "participant_id": 1}
                       for m, t in [(48, "corner"), (49, "shot-on-target"),
                                    (49, "goal"), (50, "corner")]],
        }
        pick = stage2.normalize_pick({"type": "OVER 2.5", "target_loc": "match"})[1]
        pick["suppressed"] = True
        pick["suppressed_reason"] = stage2.SUPPRESSED_REASON
        cycle_log = []
        stage2.process_triple_phase_audit(ctx, [pick], cycle_log)
        self.assertEqual(stage2.VALIDATED_ALERTS, {})
        row = (cycle_log[0].get("predictions") or [{}])[0]
        self.assertTrue(row.get("suppressed"))
        self.assertIn("contradictory market", row.get("suppressed_reason") or "")
        self.assertTrue(
            any("contradictory market" in ln for ln in cycle_log[0]["lines"])
        )
        stage2.MATCH_VALIDATION_STATE.clear()

    # ── ORPHAN CARRY-FORWARD ─────────────────────────────────────────────
    def test_alerted_pick_is_carried_forward_when_its_feed_row_disappears(self):
        """A market that alerted and then dropped out of the pick feed used to
        vanish from the tracked set while remaining stranded in Code 3C with no
        way to be validated or settled. It must be carried forward instead."""
        stage2.MATCH_VALIDATION_STATE.clear()
        stage2.MATCH_VALIDATION_STATE["555"] = {
            "UNDER_2.5:match": {"verdict_45": "LIKELY", "verdict_45_minute": 45},
            "OVER_2.5:match": {"verdict_45": "LIKELY", "verdict_45_minute": 45,
                               "alerted": True},
        }
        feed = {}
        stage2.carry_forward_orphans(feed)
        carried = {p["canonical_key"]: p for p in feed.get("555", [])}
        # The alerted OVER is recovered even though no feed row remains for it.
        self.assertIn("OVER_2.5:match", carried)
        self.assertTrue(carried["OVER_2.5:match"]["orphaned"])
        self.assertTrue(carried["OVER_2.5:match"]["suppressed"])
        self.assertIn("OVER_2.5:match", stage2.MATCH_VALIDATION_STATE["555"])
        stage2.MATCH_VALIDATION_STATE.clear()

    def test_carry_forward_keeps_a_pick_the_feed_still_carries(self):
        """A pick still present in the live feed must not be duplicated, and a
        state entry that was never judged must not be resurrected."""
        stage2.MATCH_VALIDATION_STATE.clear()
        stage2.MATCH_VALIDATION_STATE["556"] = {
            "UNDER_2.5:match": {"verdict_45": "LIKELY"},
            "TO_SCORE:home": {},
        }
        live = [stage2.normalize_pick({"type": "UNDER 2.5",
                                      "target_loc": "match"})[1]]
        feed = {"556": live}
        stage2.carry_forward_orphans(feed)
        self.assertEqual(len(feed["556"]), 1)
        self.assertEqual(feed["556"][0]["canonical_key"], "UNDER_2.5:match")
        stage2.MATCH_VALIDATION_STATE.clear()

    def test_canonical_key_round_trips_into_a_pick(self):
        pick = stage2._pick_from_canonical_key("GG_OVER_2.5:match")
        self.assertIsNotNone(pick)
        self.assertEqual(pick["market"], "GG_OVER_2.5")
        self.assertEqual(pick["target_loc"], "match")
        self.assertIsNone(stage2._pick_from_canonical_key("no-separator"))

    # ── ENGINE LABEL ─────────────────────────────────────────────────────
    def test_engine_label_has_two_numbers_not_three(self):
        """The label used to be STATS_1/3/3, which read as three separate
        quantities and was the single most confusing thing on the board."""
        ctx = {
            "minute": 40, "home": {"stats": {"shots-on-target": 3}},
            "away": {"stats": {"shots-on-target": 1}},
        }
        pick = {"type": "UNDER 2.5", "market": "UNDER 2.5",
                "target_loc": "match", "target_id": None}
        _state, label, detail = stage2.old_engine_statistical_judge(ctx, pick)
        self.assertRegex(label, r"^STATS_\d+/(2|3)")
        self.assertNotIn("/3/", label)
        # The judge reasoning must be carried so the UI can show it.
        self.assertIn("Engine 1 (Rule)", detail)
        self.assertIn("Engine 2 (Structure)", detail)
        self.assertIn("Engine 3 (Momentum)", detail)

    def test_engine_abstention_reports_two_of_three(self):
        """Engine 3 abstains with no event feed. The label must then read
        STATS_x/2 and say so, not STATS_x/3/3."""
        ctx = {
            "minute": 40, "home": {"stats": {"shots-on-target": 3}},
            "away": {"stats": {"shots-on-target": 1}}, "events": [],
        }
        pick = {"type": "UNDER 2.5", "market": "UNDER_2.5",
                "target_loc": "match", "target_id": None}
        _state, label, _detail = stage2.old_engine_statistical_judge(ctx, pick)
        self.assertIn("STATS_", label)
        self.assertIn("/2", label)
        self.assertIn("abstained", label)

    # (seeded "can still score" rules were removed: live_xg is cumulative,
    # so a fixed bar fired on every candidate past 45'. See the xg condition
    # in user_rules_store for the full reasoning.)
    # ──────────────────────────────────


    def _storm_ctx(self, a_press=60.0, h_press=40.0):
        # h_triple means the HOME squad is the structurally broken one, so it
        # is the AWAY side that dominates: a_pressure_share must exceed 50 for
        # the handshake condition to hold.
        return {
            "match": {"confidence_score": 70.0, "chaos_index": 12.0,
                      "a_pressure_share": a_press,
                      "h_pressure_share": h_press},
            "home": {"live_xg": 5.0}, "away": {"live_xg": 3.0},
        }

    def test_storm_gate_windows_do_not_overlap_and_cover_the_match(self):
        """The three gates must tile the second half exactly once each, so a
        fixture can never sit in two windows at the same cycle."""
        wins = sorted((g[1], g[2]) for g in stage6.STORM_GATES)
        self.assertEqual(wins, [(30, 45), (45, 60), (60, 75)])
        for (_, prev_end), (next_start, _) in zip(wins, wins[1:]):
            self.assertEqual(prev_end, next_start)

    def test_storm_bar_rises_with_the_window(self):
        """A later call must be a stronger one. This is what stops the wider
        window from diluting precision."""
        by_key = {g[0]: g for g in stage6.STORM_GATES}
        self.assertEqual(by_key["SUPREME_45"][3],
                         stage6.CONFIDENCE_STANDARD_THRESHOLD)
        self.assertEqual(by_key["SUPREME_75"][3],
                         stage6.CONFIDENCE_PREMIUM_THRESHOLD)
        self.assertGreater(by_key["SUPREME_75"][3], by_key["SUPREME_60"][3])

    def test_storm_gates_capture_the_score_at_trigger(self):
        """Each gate must anchor its alert to the scoreline at that instant."""
        orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
        fired = []
        orch.fire_alert = lambda *a, **k: fired.append((a, k))
        stage6.ALERT_HISTORY.clear()
        stage6.VALIDATION_STATE.clear()
        # No handshake at all, minute 50, strong structural break.
        orch.process_ai_gates("F1", "A vs B", 50, self._storm_ctx(),
                              {"h_triple": True, "a_triple": False},
                              {}, score=(2, 1))
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0][1]["storm_stage"], "sustained")
        self.assertEqual(fired[0][1]["score"], (2, 1))
        stage6.ALERT_HISTORY.clear()
        stage6.VALIDATION_STATE.clear()

    def test_each_storm_gate_fires_at_most_once(self):
        """Repeated cycles inside the same window must not re-alert."""
        orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
        fired = []
        orch.fire_alert = lambda *a, **k: fired.append(k)
        stage6.ALERT_HISTORY.clear()
        stage6.VALIDATION_STATE.clear()
        struct = {"h_triple": True, "a_triple": False}
        for minute in (46, 48, 50, 55, 59):
            orch.process_ai_gates("F2", "A vs B", minute, self._storm_ctx(),
                                  struct, {}, score=(0, 0))
        self.assertEqual(len(fired), 1, "the 45-60 gate must fire once only")
        stage6.ALERT_HISTORY.clear()
        stage6.VALIDATION_STATE.clear()

    def test_original_45_gate_is_unchanged(self):
        """Gate 1 must still require the 30-45 handshake. The storm track is
        additive; it must not have quietly relaxed the original rule."""
        orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
        fired = []
        orch.fire_alert = lambda *a, **k: fired.append(k)
        stage6.ALERT_HISTORY.clear()
        stage6.VALIDATION_STATE.clear()
        struct = {"h_triple": True, "a_triple": False}
        # Minute 50 with NO handshake: gate 1 must NOT fire on its own.
        orch.process_ai_gates("F3", "A vs B", 50, self._storm_ctx(),
                              struct, {}, score=(0, 0))
        stages = {f.get("storm_stage") for f in fired}
        self.assertNotIn("developing", stages)
        # Now with the handshake set, gate 1 fires.
        stage6.VALIDATION_STATE["F3"] = "VALID_30"
        fired.clear()
        orch.process_ai_gates("F3", "A vs B", 80, self._storm_ctx(),
                              struct, {}, score=(0, 0))
        self.assertIn("developing", {f.get("storm_stage") for f in fired})
        stage6.ALERT_HISTORY.clear()
        stage6.VALIDATION_STATE.clear()

    def test_storm_gates_do_not_fire_without_a_structural_break(self):
        """The 2x doom test is the whole bar. No break, no alert — widening the
        window must not weaken the condition."""
        orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
        fired = []
        orch.fire_alert = lambda *a, **k: fired.append(k)
        stage6.ALERT_HISTORY.clear()
        stage6.VALIDATION_STATE.clear()
        struct = {"h_triple": False, "a_triple": False}
        for minute in (35, 50, 65):
            orch.process_ai_gates("F4", "A vs B", minute, self._storm_ctx(),
                                  struct, {}, score=(0, 0))
        self.assertEqual(fired, [])
        stage6.ALERT_HISTORY.clear()
        stage6.VALIDATION_STATE.clear()

    def test_storm_tracker_never_alerts(self):
        """The tracker exists so the UI can show a storm building. It must be
        structurally incapable of raising an alert."""
        stage6.STORM_STATE.clear()
        orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
        fired = []
        orch.fire_alert = lambda *a, **k: fired.append(k)
        stage6.ALERT_HISTORY.clear()
        stage6.VALIDATION_STATE.clear()
        struct = {"h_triple": True, "a_triple": False}
        for minute in (33, 47, 63):
            orch.update_storm_state("F5", minute, self._storm_ctx(), struct)
        self.assertEqual(fired, [], "update_storm_state must never alert")
        self.assertEqual(stage6.STORM_STATE["F5"]["stage"], "peaking")
        stage6.STORM_STATE.clear()
        stage6.ALERT_HISTORY.clear()
        stage6.VALIDATION_STATE.clear()

    # ── SCORE AT TRIGGER + OUTCOME RESOLUTION ───────────────────────────
    def test_score_is_captured_when_an_alert_fires(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "ready_to_push.json")
            with patch.object(stage6, "OUTPUT_ALERTS_FILE", out), \
                 patch.object(stage6, "SESSION_LOG_FILE",
                              os.path.join(tmp, "s.json")):
                orch = stage6.SupremeOrchestrator.__new__(
                    stage6.SupremeOrchestrator)
                stage6.SESSION_ALERTS.clear()
                orch.fire_alert("F6", "A vs B", "🔥 PREMIUM", "m", 80.0, 47,
                                storm_stage="sustained", score=(2, 1))
                rec = stage6.SESSION_ALERTS[-1]
                self.assertEqual(rec["score_at_trigger"], "2-1")
                self.assertEqual(rec["score_home_trigger"], 2)
                self.assertEqual(rec["score_away_trigger"], 1)
                self.assertEqual(rec["outcome"], "pending")
                self.assertIsNone(rec["final_score"])
        stage6.SESSION_ALERTS.clear()

    def test_a_missing_trigger_score_is_never_invented(self):
        """No scoreline at fire time must record `None`, not a fabricated 0-0."""
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "ready_to_push.json")
            with patch.object(stage6, "OUTPUT_ALERTS_FILE", out), \
                 patch.object(stage6, "SESSION_LOG_FILE",
                              os.path.join(tmp, "s.json")):
                orch = stage6.SupremeOrchestrator.__new__(
                    stage6.SupremeOrchestrator)
                stage6.SESSION_ALERTS.clear()
                orch.fire_alert("F7", "A vs B", "✅ STANDARD", "m", 40.0, 50)
                self.assertIsNone(stage6.SESSION_ALERTS[-1]["score_at_trigger"])
        stage6.SESSION_ALERTS.clear()

    def test_goals_after_counts_goals_scored_after_the_trigger(self):
        """The verification question is whether anything followed the alert."""
        orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
        finished_fx = {
            "id": 42, "state": {"name": "FT"},
            "scores": [{"score": {"description": "FULLTIME",
                                  "participant": "home", "goals": 3}},
                       {"score": {"description": "FULLTIME",
                                  "participant": "away", "goals": 2}}],
        }
        base = {"f_id": "42", "outcome": "pending",
                "score_home_trigger": 1, "score_away_trigger": 1}
        self.assertTrue(orch.fixture_is_finished(finished_fx))
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "a.json")
            with patch.object(stage6, "OUTPUT_ALERTS_FILE", out):
                import json as _json
                with open(out, "w") as f:
                    f.write(_json.dumps(base) + "\n")
                settled = orch.resolve_alert_results({"42": finished_fx})
                self.assertEqual(settled, 1)
                rec = _json.loads(open(out).read().strip())
        self.assertEqual(rec["final_score"], "3-2")
        self.assertEqual(rec["goals_after"], 3)      # 5 total - 2 at trigger
        self.assertEqual(rec["outcome"], "goal_followed")

    def test_no_further_goal_is_reported_honestly(self):
        """A storm that produced nothing must say so, not be quietly dropped."""
        orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
        finished_fx = {
            "id": 43, "state": {"name": "FT"},
            "scores": [{"score": {"description": "FULLTIME",
                                  "participant": "home", "goals": 1}},
                       {"score": {"description": "FULLTIME",
                                  "participant": "away", "goals": 1}}],
        }
        base = {"f_id": "43", "outcome": "pending",
                "score_home_trigger": 1, "score_away_trigger": 1}
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "a.json")
            with patch.object(stage6, "OUTPUT_ALERTS_FILE", out):
                import json as _json
                with open(out, "w") as f:
                    f.write(_json.dumps(base) + "\n")
                orch.resolve_alert_results({"43": finished_fx})
                rec = _json.loads(open(out).read().strip())
        self.assertEqual(rec["goals_after"], 0)
        self.assertEqual(rec["outcome"], "no_further_goal")

    def test_unresolvable_alert_is_marked_unverifiable(self):
        """An older record with no trigger score must be labelled, not guessed."""
        orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
        finished_fx = {
            "id": 44, "state": {"name": "FT"},
            "scores": [{"score": {"description": "FULLTIME",
                                  "participant": "home", "goals": 2}},
                       {"score": {"description": "FULLTIME",
                                  "participant": "away", "goals": 0}}],
        }
        base = {"f_id": "44", "outcome": "pending",
                "score_home_trigger": None, "score_away_trigger": None}
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "a.json")
            with patch.object(stage6, "OUTPUT_ALERTS_FILE", out):
                import json as _json
                with open(out, "w") as f:
                    f.write(_json.dumps(base) + "\n")
                orch.resolve_alert_results({"44": finished_fx})
                rec = _json.loads(open(out).read().strip())
        self.assertEqual(rec["outcome"], "unverifiable")
        self.assertIsNone(rec["goals_after"])
        self.assertEqual(rec["final_score"], "2-0")

    def test_a_live_match_is_never_settled(self):
        orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
        live_fx = {"id": 45, "state": {"name": "INPLAY_2ND_HALF"},
                   "scores": [{"score": {"description": "CURRENT",
                                         "participant": "home", "goals": 9}}]}
        base = {"f_id": "45", "outcome": "pending",
                "score_home_trigger": 0, "score_away_trigger": 0}
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "a.json")
            with patch.object(stage6, "OUTPUT_ALERTS_FILE", out):
                import json as _json
                with open(out, "w") as f:
                    f.write(_json.dumps(base) + "\n")
                self.assertEqual(orch.resolve_alert_results({"45": live_fx}), 0)

    def test_settled_alert_is_never_rewritten(self):
        """Resolution only fills pending fields, so a settled alert is stable."""
        orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
        done = {"f_id": "46", "outcome": "goal_followed", "goals_after": 2,
                "final_score": "2-1"}
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "a.json")
            with patch.object(stage6, "OUTPUT_ALERTS_FILE", out):
                import json as _json
                with open(out, "w") as f:
                    f.write(_json.dumps(done) + "\n")
                self.assertEqual(orch.resolve_alert_results({}), 0)
                rec = _json.loads(open(out).read().strip())
        self.assertEqual(rec, done)

    def test_alerts_api_filters_by_date(self):
        """The day strip was decorative: the endpoint took no date and every
        tab returned the whole log."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ready_to_push.json")
            with open(path, "w") as f:
                f.write(json.dumps({"f_id": "1", "user_id": None,
                                    "time": "2026-09-26T10:00:00"}) + "\n")
                f.write(json.dumps({"f_id": "2", "user_id": None,
                                    "time": "2026-09-27T10:00:00"}) + "\n")

            class _Req:
                class state:
                    user = {"user_id": "me"}

            with patch.object(api_main.os.path, "exists", lambda p: True), \
                 patch.object(api_main, "OUTPUT_DIR", tmp):
                got = api_main.get_live_alerts(_Req(), date="2026-09-27")
                self.assertEqual([r["f_id"] for r in got], ["2"])
                # No date -> the whole log, as before.
                every = api_main.get_live_alerts(_Req())
                self.assertEqual(len(every), 2)
                # A day with nothing on it must be empty, not "everything".
                self.assertEqual(
                    api_main.get_live_alerts(_Req(), date="2020-01-01"), [])


    def test_squads_are_requested_for_live_fixtures_not_in_prematch(self):
        """
        THE REAL REASON CODE 6 BARELY ALERTED.

        maintenance_thread used to iterate the PREMATCH database only. A match
        that was live but absent from the prematch report — most youth,
        women's and lower-league fixtures, exactly the ones that produce
        alerts — never had its squads requested. investigate() then returned
        INSUFFICIENT_SQUAD_DATA, h_triple/a_triple were never computed, and
        the storm gates could not fire regardless of pressure or confidence.
        Widening the time window cannot help a match whose squad data was
        never fetched.
        """
        orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
        requested = []
        class _Ex:
            # submit(fn, tid) -> the id is the first vararg, not a[0] (that's
            # the callable).
            def submit(self, fn, *a):
                requested.extend(a)
        orch.executor = _Ex()
        orch._fetch_and_store_squad = lambda tid: None
        old_vault = dict(stage6.SQUAD_VAULT)
        old_fetching = set(stage6.FETCHING_TEAMS)
        stage6.SQUAD_VAULT.clear()
        stage6.FETCHING_TEAMS.clear()
        try:
            live = [{"id": "L1", "participants": [
                {"id": 111, "meta": {"location": "home"}},
                {"id": 222, "meta": {"location": "away"}},
            ]}]
            orch.maintenance_thread({}, live)
            self.assertIn(111, requested)
            self.assertIn(222, requested)
            # An empty players dict is a failed fetch, not a cached squad, so
            # it must be re-requested rather than treated as covered. Team 222
            # is marked as a SUCCESSFUL fetch and must be left alone.
            # FETCHING_TEAMS must be cleared first: it deliberately survives
            # across calls so a squad already being fetched is not requested
            # twice, which is correct in production.
            stage6.FETCHING_TEAMS.clear()
            stage6.SQUAD_VAULT["111"] = {"players": {}}          # failed fetch
            stage6.SQUAD_VAULT["222"] = {"players": {"p": {"doom": 1}}}
            requested.clear()
            orch.maintenance_thread({}, live)
            self.assertIn(111, requested, "a failed fetch must be retried")
            self.assertNotIn(222, requested, "a populated squad is not refetched")
            # A team already in flight must NOT be requested again.
            stage6.FETCHING_TEAMS.clear()
            stage6.SQUAD_VAULT["111"] = {"players": {"q": {"doom": 1}}}
            stage6.FETCHING_TEAMS.add(111)
            requested.clear()
            orch.maintenance_thread({}, live)
            self.assertNotIn(111, requested, "in-flight team not re-requested")
            self.assertNotIn(222, requested, "cached team not refetched")
        finally:
            stage6.SQUAD_VAULT.clear()
            stage6.SQUAD_VAULT.update(old_vault)
            stage6.FETCHING_TEAMS.clear()
            stage6.FETCHING_TEAMS.update(old_fetching)


    def test_coverage_reports_what_could_not_be_evaluated(self):
        """
        Option A: the strict 2x bar is kept and the unevaluable remainder is
        REPORTED. Silence must not be ambiguous — a match with no squad is
        BLIND, not QUIET, and the board has to say which.
        """
        import tempfile as _t
        with _t.TemporaryDirectory() as tmp:
            board_file = os.path.join(tmp, "ob.json")
            orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
            orch.cycle = 7
            with patch.object(stage6, "ORCHESTRATOR_BOARD_FILE", board_file):
                matches = [
                    {"id": "1", "structural": "OK"},
                    {"id": "2", "structural": "INSUFFICIENT_SQUAD_DATA"},
                    {"id": "3", "structural": "INSUFFICIENT_SQUAD_DATA"},
                    {"id": "4", "structural": "STALE_CACHE_FORMAT"},
                ]
                orch.save_orchestrator_board(matches, 4, 0)
                board = json.load(open(board_file))
        cov = board["coverage"]
        self.assertEqual(cov["total"], 4)
        # Only the single "OK" row is evaluable. INSUFFICIENT_SQUAD_DATA and
        # STALE_CACHE_FORMAT both mean the 2x bar was never tested.
        self.assertEqual(cov["evaluated"], 1)
        self.assertEqual(cov["unevaluated"], 3)
        self.assertEqual(cov["pct"], 25)
        # A row the structural detector could not read must be labelled, with a
        # reason a user could read.
        self.assertEqual(matches[0]["evaluation"], "evaluated")
        self.assertIsNone(matches[0]["evaluation_note"])
        self.assertEqual(matches[1]["evaluation"], "not_evaluated")
        self.assertIn("squad", matches[1]["evaluation_note"].lower())
        # A stale-cache row is equally unusable, so it must not be counted as
        # evaluable just because its status is not the exact insufficient code.
        self.assertEqual(matches[3]["evaluation"], "not_evaluated")
        self.assertTrue(cov["reason"])


    def test_coverage_is_marked_provisional_while_squads_load(self):
        """
        A cold vault must not be published as a real 0%. Observed live: 0/13 on
        the first cycle after a restart, then 8/13 two cycles later with no
        other change. Reporting the first figure as fact reads as "the engine
        is blind" when the truth is "it has not finished looking".
        """
        import tempfile as _t
        with _t.TemporaryDirectory() as tmp:
            board_file = os.path.join(tmp, "ob.json")
            orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
            orch.cycle = 1
            old_fetching = set(stage6.FETCHING_TEAMS)
            stage6.FETCHING_TEAMS.clear()
            try:
                # Cold: fetches still in flight, nothing evaluable yet.
                stage6.FETCHING_TEAMS.update({11, 22})
                with patch.object(stage6, "ORCHESTRATOR_BOARD_FILE", board_file):
                    orch.save_orchestrator_board(
                        [{"id": "1", "structural": "INSUFFICIENT_SQUAD_DATA"},
                         {"id": "2", "structural": "INSUFFICIENT_SQUAD_DATA"}],
                        2, 0)
                    cold = json.load(open(board_file))["coverage"]
                self.assertTrue(cold["warming_up"])
                self.assertTrue(cold["provisional"])
                self.assertEqual(cold["pending_fetches"], 2)
                self.assertEqual(cold["evaluated"], 0)

                # Warm: queue drained, the same 0% is now a real statement.
                stage6.FETCHING_TEAMS.clear()
                with patch.object(stage6, "ORCHESTRATOR_BOARD_FILE", board_file):
                    orch.save_orchestrator_board(
                        [{"id": "1", "structural": "OK"},
                         {"id": "2", "structural": "OK"}], 2, 0)
                    warm = json.load(open(board_file))["coverage"]
                self.assertFalse(warm["warming_up"])
                self.assertFalse(warm["provisional"])
                self.assertEqual(warm["evaluated"], 2)
            finally:
                stage6.FETCHING_TEAMS.clear()
                stage6.FETCHING_TEAMS.update(old_fetching)


    # ── FULL-TIME SCORE: THE FABRICATED 0-0 REGRESSION ───────────────────
    def _finished_fx(self, fid, period="FULLTIME", h=1, a=2):
        """A realistically finished fixture. Note there is NO `CURRENT`
        period: SportMonks drops it at the whistle, which is precisely why
        the old resolver returned 0-0 for every completed match."""
        return {
            "id": fid, "state": {"name": "FT"},
            "scores": [
                {"score": {"description": "1ST_HALF", "participant": "home",
                           "goals": 0}},
                {"score": {"description": period, "participant": "home",
                           "goals": h}},
                {"score": {"description": period, "participant": "away",
                           "goals": a}},
            ],
        }

    def test_score_is_read_correctly_without_a_current_period(self):
        """
        THE BUG, and it was NOT full-time only.

        `score_from_fixture` read only the CURRENT period and defaulted to 0.
        The provider frequently publishes no CURRENT period at all — a fixture
        LIVE at 43' was found carrying only 1ST_HALF and 2ND_HALF — so the
        read returned 0-0 for a match that was really 1-0, silently writing a
        wrong score onto the alert.

        The reader now falls back to the settlement standardiser and then to
        the most recent (cumulative) period, and returns None rather than a
        fabricated 0-0 when nothing can be read.
        """
        fx = self._finished_fx(42, period="FULLTIME", h=1, a=2)
        orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
        # No CURRENT entry anywhere, yet the score must still be right.
        self.assertEqual(orch.score_from_fixture(fx), (1, 2))
        self.assertIsNone(orch.score_period(fx, "CURRENT"))
        # An unreadable fixture yields None, never a fabricated 0-0.
        self.assertIsNone(orch.score_from_fixture({"scores": []}))

    def test_latest_cumulative_period_is_the_running_score(self):
        """With no CURRENT period, the newest period IS the running total:
        period entries are cumulative, not per-period goals."""
        fx = {"id": 1, "scores": [
            {"type_id": 1, "score": {"participant": "home", "goals": 1},
             "description": "1ST_HALF"},
            {"type_id": 1, "score": {"participant": "away", "goals": 0},
             "description": "1ST_HALF"},
            {"type_id": 2, "score": {"participant": "home", "goals": 1},
             "description": "2ND_HALF"},
            {"type_id": 2, "score": {"participant": "away", "goals": 0},
             "description": "2ND_HALF"},
        ]}
        orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
        self.assertEqual(orch.score_from_fixture(fx), (1, 0))

    def test_final_score_falls_back_to_the_fulltime_period(self):
        """With no FT snapshot available the FULLTIME period is used."""
        orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
        with patch.object(stage6.SupremeOrchestrator, "_ft_snapshot_scores",
                          staticmethod(lambda fid: None)):
            self.assertEqual(orch.score_at_ft(42, self._finished_fx(42)), (1, 2))

    def test_unreadable_final_score_is_never_invented(self):
        """A finished match whose score cannot be read must resolve to
        `unverifiable` with a null final_score — never a fabricated 0-0 that
        produces a confident "no further goal"."""
        orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
        with patch.object(stage6.SupremeOrchestrator, "_ft_snapshot_scores",
                          staticmethod(lambda fid: None)):
            self.assertIsNone(orch.score_at_ft(
                43, {"id": 43, "state": {"name": "FT"}, "scores": []}))
        import tempfile as _t
        with _t.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "a.json")
            rec = {"f_id": "43", "outcome": "pending",
                   "score_home_trigger": 0, "score_away_trigger": 0}
            with patch.object(stage6, "OUTPUT_ALERTS_FILE", out):
                with open(out, "w") as f:
                    f.write(json.dumps(rec) + "\n")
                with patch.object(
                        stage6.SupremeOrchestrator, "_ft_snapshot_scores",
                        staticmethod(lambda fid: None)):
                    orch.resolve_alert_results(
                        {"43": {"id": 43, "state": {"name": "FT"},
                                "scores": []}})
                got = json.loads(open(out).read().strip())
        self.assertIsNone(got["final_score"])
        self.assertIsNone(got["goals_after"])
        self.assertEqual(got["outcome"], "unverifiable")

    def test_final_score_prefers_the_settlement_snapshot(self):
        """The snapshot is the authority — it is how Serbia vs Netherlands is
        known to have finished 1-2 while the live read said 0-0."""
        orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
        with patch.object(
                stage6.SupremeOrchestrator, "_ft_snapshot_scores",
                staticmethod(lambda fid: (1, 2))):
            # Even with a misleading FULLTIME period, the snapshot wins.
            self.assertEqual(
                orch.score_at_ft(19676687, self._finished_fx(19676687, h=0, a=0)),
                (1, 2))

    # ── STORM GATES ARE A TRACK, NOT A DOUBLE COUNT ─────────────────────
    def test_each_window_alerts_independently(self):
        """
        EACH WINDOW IS ITS OWN QUESTION. A storm still present at 60' is NEW
        information — persistence — and must produce a second alert. Suppressing
        a gate because the previous one fired (an earlier version of this code)
        hid exactly that. Silence must mean "no storm in that window", never
        "already reported".
        """
        orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
        fired = []
        orch.fire_alert = lambda *a, **k: fired.append(
            (k.get("storm_stage"), a[5]))
        stage6.ALERT_HISTORY.clear()
        stage6.VALIDATION_STATE.clear()
        struct = {"h_triple": True, "a_triple": False}
        ctx = self._storm_ctx()
        # 46' with the handshake: developing fires.
        stage6.VALIDATION_STATE["FW1"] = "VALID_30"
        orch.process_ai_gates("FW1", "A vs B", 46, ctx, struct, {}, score=(0, 0))
        self.assertIn(("developing", 46), fired)
        # 46' falls inside BOTH the >=45 and the 45-60 windows, so both gates
        # legitimately fire on the same check — each window independently asks
        # "is there a storm NOW?". That is the intended behaviour, not a
        # double count: one question per window, one answer each.
        self.assertIn(("sustained", 46), fired)
        # A later cycle inside the same window must not re-fire: each gate
        # reports a window once, not every cycle within it.
        fired.clear()
        orch.process_ai_gates("FW1", "A vs B", 52, ctx, struct, {}, score=(0, 0))
        self.assertEqual(fired, [])
        # Outside every window -> silence.
        fired.clear()
        orch.process_ai_gates("FW1", "A vs B", 80, ctx, struct, {}, score=(0, 0))
        self.assertEqual(fired, [])
        stage6.ALERT_HISTORY.clear()
        stage6.VALIDATION_STATE.clear()

    def test_no_storm_in_a_window_means_silence(self):
        """The other half of independence: with no structural break, a window
        must stay silent even if an earlier one fired."""
        orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
        fired = []
        orch.fire_alert = lambda *a, **k: fired.append(k.get("storm_stage"))
        stage6.ALERT_HISTORY.clear()
        stage6.VALIDATION_STATE.clear()
        ctx = self._storm_ctx()
        no_break = {"h_triple": False, "a_triple": False}
        # Nothing structural in the 45-60 window -> only gate 1's own path is
        # available, and with no handshake it cannot fire either.
        for minute in (46, 48, 55, 65, 72):
            orch.process_ai_gates("FW2", "A vs B", minute, ctx, no_break, {},
                                  score=(0, 0))
        self.assertEqual(fired, [])
        stage6.ALERT_HISTORY.clear()
        stage6.VALIDATION_STATE.clear()

    def test_a_late_starting_storm_still_reports_its_first_stage(self):
        """The escalation guard must not silence a storm that genuinely only
        appears later — that is the whole point of widening the window."""
        orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
        fired = []
        orch.fire_alert = lambda *a, **k: fired.append(k.get("storm_stage"))
        stage6.ALERT_HISTORY.clear()
        stage6.VALIDATION_STATE.clear()
        struct = {"h_triple": True, "a_triple": False}
        ctx = self._storm_ctx()
        # No handshake at all, first structural sighting at 52'.
        orch.process_ai_gates("FG2", "A vs B", 52, ctx, struct, {}, score=(0, 0))
        self.assertIn("sustained", fired)
        stage6.ALERT_HISTORY.clear()
        stage6.VALIDATION_STATE.clear()


    # ── FINISHED MATCHES MUST NOT BE LOST ───────────────────────────────
    def test_a_fixture_that_left_the_live_feed_is_still_resolved(self):
        """
        A finished fixture LEAVES the in-play feed, usually in the same cycle.
        The old guard required it to still be in the live feed AND marked
        finished, so the verification silently lost those matches and their
        cards sat on "Match in progress" forever. The FT snapshot persists
        finished results independently, so it must be consulted even when the
        live feed has no row at all.
        """
        orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
        rec = {"f_id": "555", "outcome": "pending", "time":
               __import__("datetime").datetime.now().isoformat(),
               "score_home_trigger": 0, "score_away_trigger": 0}
        import tempfile as _t
        with _t.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "a.json")
            with patch.object(stage6, "OUTPUT_ALERTS_FILE", out):
                with open(out, "w") as f:
                    f.write(json.dumps(rec) + "\n")
                # live_by_id is EMPTY: the fixture is gone from the feed.
                with patch.object(
                        stage6.SupremeOrchestrator, "_ft_snapshot_scores",
                        staticmethod(lambda fid: (2, 1))):
                    settled = orch.resolve_alert_results({})
                self.assertEqual(settled, 1)
                got = json.loads(open(out).read().strip())
        self.assertEqual(got["final_score"], "2-1")
        self.assertEqual(got["outcome"], "goal_followed")

    def test_stale_pending_ages_out_instead_of_claiming_in_progress(self):
        """A match finished days ago whose score is in no retained source must
        read 'cannot verify', never 'match in progress'."""
        import tempfile as _t
        from datetime import datetime, timedelta
        orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
        old = (datetime.now() - timedelta(hours=stage6.STALE_PENDING_AFTER_S
                                         / 3600 + 6)).isoformat()
        rec = {"f_id": "556", "outcome": "pending", "time": old,
               "score_home_trigger": 0, "score_away_trigger": 0}
        with _t.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "a.json")
            with patch.object(stage6, "OUTPUT_ALERTS_FILE", out):
                with open(out, "w") as f:
                    f.write(json.dumps(rec) + "\n")
                live_fx = {"id": 556, "state": {"name": "INPLAY_2ND_HALF"},
                           "scores": [{"score": {"description": "CURRENT",
                                                 "participant": "home",
                                                 "goals": 0}}]}
                with patch.object(
                        stage6.SupremeOrchestrator, "_ft_snapshot_scores",
                        staticmethod(lambda fid: None)):
                    orch.resolve_alert_results({"556": live_fx})
                got = json.loads(open(out).read().strip())
        self.assertEqual(got["outcome"], "unverifiable")
        self.assertIsNone(got["final_score"])
        self.assertIn("no longer retained", got["unverifiable_reason"])

    def test_a_recent_pending_alert_is_left_alone(self):
        """The age-out must not touch a match that is simply still running."""
        import tempfile as _t
        from datetime import datetime
        orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
        rec = {"f_id": "557", "outcome": "pending",
               "time": datetime.now().isoformat(),
               "score_home_trigger": 0, "score_away_trigger": 0}
        with _t.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "a.json")
            with patch.object(stage6, "OUTPUT_ALERTS_FILE", out):
                with open(out, "w") as f:
                    f.write(json.dumps(rec) + "\n")
                live_fx = {"id": 557, "state": {"name": "INPLAY_2ND_HALF"},
                           "scores": [{"score": {"description": "CURRENT",
                                                 "participant": "home",
                                                 "goals": 0}}]}
                with patch.object(
                        stage6.SupremeOrchestrator, "_ft_snapshot_scores",
                        staticmethod(lambda fid: None)):
                    self.assertEqual(
                        orch.resolve_alert_results({"557": live_fx}), 0)
                got = json.loads(open(out).read().strip())
        self.assertEqual(got["outcome"], "pending")
        self.assertNotIn("unverifiable_reason", got)



















# The runner block must be LAST in this file. It used to sit at line 1394,
# mid-module, where unittest.main() called sys.exit() at import time and every
# test class declared after it was silently never defined or run. The suite
# reported "OK" while roughly half the contracts were dead code.
class ScorelineGateContractTests(unittest.TestCase):
    """
    THE USER'S SCORELINE LIMITATION.

    "I set up a prematch condition of SH over 2.5 — I should be able to set its
    live condition to under 2.5, or set the goal I want."

    These pin the three properties that make that honest:
      * under and over are NOT the same test (the asymmetry is the feature),
      * an unreadable scoreline never satisfies the gate (fails closed),
      * a rule with no watchlist behaves exactly as it did before.
    """

    @staticmethod
    def _rule(live, **extra):
        rule = {
            "rule_id": "r_test",
            "user_id": "u_test",
            "label": "Test",
            "prematch": {"type": "none"},
            "live": live,
            "active": True,
        }
        rule.update(extra)
        return rule

    # ── the under/over asymmetry ───────────────────────────────────────────
    def test_under_gate_fires_while_the_line_is_still_alive(self):
        """UNDER 2.5 is useful BEFORE the line is crossed — that is the point."""
        rule = self._rule({"type": "goals", "direction": "under", "line": 2.5})
        for score in [(0, 0), (1, 0), (1, 1), (2, 0), (0, 2)]:
            self.assertIsNotNone(
                rules.evaluate_rule_for_match(
                    rule, _INTEL, {}, 40, _KEY_LOSS, score=score
                ),
                f"under 2.5 should still fire at {score}",
            )

    def test_under_gate_goes_silent_once_the_line_is_gone(self):
        """At 2-1 the over-2.5 market is already lost; the alert must not fire."""
        rule = self._rule({"type": "goals", "direction": "under", "line": 2.5})
        for score in [(2, 1), (3, 0), (1, 2), (4, 4)]:
            self.assertIsNone(
                rules.evaluate_rule_for_match(
                    rule, _INTEL, {}, 40, _KEY_LOSS, score=score
                ),
                f"under 2.5 must NOT fire at {score}",
            )

    def test_over_gate_is_the_mirror_of_under(self):
        """OVER 2.5 is useful only AFTER the line is beaten."""
        under = self._rule({"type": "goals", "direction": "under", "line": 2.5})
        over = self._rule({"type": "goals", "direction": "over", "line": 2.5})
        # Below the line: UNDER is useful (the price still exists), OVER is not.
        for score in [(0, 0), (1, 1), (2, 0)]:
            self.assertIsNotNone(
                rules.evaluate_rule_for_match(under, _INTEL, {}, 40, _KEY_LOSS, score=score),
                f"under 2.5 should fire at {score}",
            )
            self.assertIsNone(
                rules.evaluate_rule_for_match(over, _INTEL, {}, 40, _KEY_LOSS, score=score),
                f"over 2.5 must not fire at {score}",
            )
        # Past the line: the exact mirror image.
        for score in [(2, 1), (3, 0), (1, 2)]:
            self.assertIsNone(
                rules.evaluate_rule_for_match(under, _INTEL, {}, 40, _KEY_LOSS, score=score)
            )
            self.assertIsNotNone(
                rules.evaluate_rule_for_match(over, _INTEL, {}, 40, _KEY_LOSS, score=score),
                f"over 2.5 should fire at {score}",
            )

    def test_whole_line_is_a_push_not_a_win(self):
        """over 3.0 needs 4 goals, and under 3.0 is still alive at 3."""
        over3 = self._rule({"type": "goals", "direction": "over", "line": 3})
        under3 = self._rule({"type": "goals", "direction": "under", "line": 3})
        self.assertIsNone(
            rules.evaluate_rule_for_match(over3, _INTEL, {}, 40, _KEY_LOSS, score=(2, 1))
        )
        self.assertIsNotNone(
            rules.evaluate_rule_for_match(under3, _INTEL, {}, 40, _KEY_LOSS, score=(2, 1))
        )
        self.assertIsNotNone(
            rules.evaluate_rule_for_match(over3, _INTEL, {}, 40, _KEY_LOSS, score=(2, 2))
        )

    def test_exact_gate_fires_on_one_total_only(self):
        rule = self._rule({"type": "goals", "direction": "exact", "line": 3})
        for score, expected in [((1, 1), False), ((2, 0), False), ((2, 1), True),
                                ((1, 2), True), ((3, 0), True), ((2, 2), False)]:
            hit = rules.evaluate_rule_for_match(
                rule, _INTEL, {}, 40, _KEY_LOSS, score=score
            )
            self.assertEqual(hit is not None, expected, f"exact 3 at {score}")

    # ── fails closed ───────────────────────────────────────────────────────
    def test_unreadable_scoreline_never_satisfies_the_gate(self):
        """
        None means "the provider published nothing", NOT 0-0. A gate whose whole
        job is to know the scoreline must not pass on a scoreline it lacks —
        otherwise a 0-0-looking read would fire the under gate for a match that
        may already be 3-0.
        """
        for bad in (None, (), ("x", None), (None, None)):
            rule = self._rule({"type": "goals", "direction": "under", "line": 2.5})
            self.assertIsNone(
                rules.evaluate_rule_for_match(
                    rule, _INTEL, {}, 40, _KEY_LOSS, score=bad
                ),
                f"unreadable score {bad!r} must not satisfy the gate",
            )

    def test_failing_closed_is_not_silently_swallowed(self):
        """The rule must be silent, but the reason must still be reportable."""
        met, note = rules._scoreline_condition_met(
            {"direction": "under", "line": 2.5}, None
        )
        self.assertFalse(met)
        self.assertIn("unavailable", note)
        self.assertIn("not alerting", note)

    # ── the gate must not be vetoed by the live-stat path ─────────────────
    def test_passing_gate_is_not_vetoed_by_the_live_condition_check(self):
        """
        Regression guard, twice over.

        The gate was originally decided OUTSIDE _live_condition_met, which had
        no branch for it, so a passing gate fell through to the "Unknown live
        condition" default and was vetoed — the rule could never fire. The gate
        is now a peer condition inside the group, and this pins that a genuine
        pass survives the plumbing.

        The second assertion is the opposite case: with no readable scoreline
        the gate must refuse, even though every other condition is fine.
        """
        gate = {"type": "goals", "direction": "under", "line": 2.5}
        met, note = rules._live_condition_met(gate, _INTEL, _KEY_LOSS, score=(1, 0))
        self.assertTrue(met, note)
        # Unreadable scoreline still fails closed through this same path.
        met_none, note_none = rules._live_condition_met(gate, _INTEL, _KEY_LOSS)
        self.assertFalse(met_none)
        self.assertIn("not alerting", note_none)

    # ── validation ─────────────────────────────────────────────────────────
    def test_goal_gate_rejects_a_bad_direction(self):
        with self.assertRaises(rules.RuleValidationError):
            rules.validate_rule_payload({
                "user_id": "u", "prematch": {"type": "none"},
                "live": {"type": "goals", "direction": "sideways", "line": 2.5},
            })

    def test_goal_gate_rejects_a_fractional_exact_line(self):
        with self.assertRaises(rules.RuleValidationError):
            rules.validate_rule_payload({
                "user_id": "u", "prematch": {"type": "none"},
                "live": {"type": "goals", "direction": "exact", "line": 2.5},
            })

    def test_goal_gate_rejects_an_out_of_range_line(self):
        for line in (-1, 99):
            with self.assertRaises(rules.RuleValidationError):
                rules.validate_rule_payload({
                    "user_id": "u", "prematch": {"type": "none"},
                    "live": {"type": "goals", "direction": "under", "line": line},
                })

    def test_goal_gate_requires_a_line(self):
        with self.assertRaises(rules.RuleValidationError):
            rules.validate_rule_payload({
                "user_id": "u", "prematch": {"type": "none"},
                "live": {"type": "goals", "direction": "under"},
            })

    def test_valid_goal_gate_round_trips(self):
        out = rules.validate_rule_payload({
            "user_id": "u", "prematch": {"type": "none"},
            "live": {"type": "goals", "direction": "under", "line": 2.5},
        })
        # A single condition is normalised into a one-condition group, so the
        # evaluator has exactly one code path and the old saved rules behave
        # identically to how they did before.
        self.assertEqual(out["live"], {
            "conditions": [{"type": "goals", "direction": "under", "line": 2.5}],
            "mode": "all",
            "threshold": 1,
        })

    # ── the window and the prematch filter still run first ─────────────────
    def test_gate_does_not_bypass_the_minute_window(self):
        rule = self._rule(
            {"type": "goals", "direction": "under", "line": 2.5},
            minute_window={"start": 30, "end": 50},
        )
        self.assertIsNone(
            rules.evaluate_rule_for_match(rule, _INTEL, {}, 10, _KEY_LOSS, score=(0, 0))
        )
        self.assertIsNotNone(
            rules.evaluate_rule_for_match(rule, _INTEL, {}, 40, _KEY_LOSS, score=(0, 0))
        )

    def test_gate_does_not_bypass_the_prematch_filter(self):
        rule = self._rule({"type": "goals", "direction": "under", "line": 2.5})
        rule["prematch"] = {"type": "key_missing", "side": "any", "min_count": 5}
        # No team_audit at all -> the prematch condition cannot be met.
        self.assertIsNone(
            rules.evaluate_rule_for_match(rule, _INTEL, {}, 40, _KEY_LOSS, score=(0, 0))
        )

    # ── backward compatibility ─────────────────────────────────────────────
    def test_a_rule_without_a_watchlist_still_fires_everywhere(self):
        """
        The three pre-existing rules in data/user_rules.json have no watchlist.
        A missing one must mean "no preference", never "match nothing".
        """
        rule = self._rule({"type": "goals", "direction": "under", "line": 2.5})
        self.assertNotIn("watchlist", rule)
        hit = rules.evaluate_rule_for_match(
            rule, _INTEL, {}, 40, _KEY_LOSS, score=(1, 1), fixture_id="999"
        )
        self.assertIsNotNone(hit)
        self.assertFalse(hit["watchlisted"])


class WatchlistContractTests(unittest.TestCase):
    """Accepted matches are a SOFT preference — recorded, never enforced."""

    @staticmethod
    def _rule(watchlist):
        return {
            "rule_id": "r_w",
            "user_id": "u_w",
            "label": "W",
            "prematch": {"type": "none"},
            "live": {"type": "goals", "direction": "under", "line": 2.5},
            "watchlist": watchlist,
            "active": True,
        }

    def test_a_watchlisted_match_is_flagged(self):
        hit = rules.evaluate_rule_for_match(
            self._rule(["111"]), _INTEL, {}, 40, _KEY_LOSS,
            score=(0, 0), fixture_id="111",
        )
        self.assertTrue(hit["watchlisted"])

    def test_a_non_watchlisted_match_still_fires(self):
        """
        THE DEFINING PROPERTY OF "SOFT". A match the user never clicked still
        raises the alert; it is simply not flagged. If this ever returns None,
        the watchlist has silently become a hard filter.
        """
        hit = rules.evaluate_rule_for_match(
            self._rule(["111"]), _INTEL, {}, 40, _KEY_LOSS,
            score=(0, 0), fixture_id="222",
        )
        self.assertIsNotNone(hit)
        self.assertFalse(hit["watchlisted"])

    def test_watchlist_ids_are_string_normalised_and_deduped(self):
        out = rules.validate_rule_payload({
            "user_id": "u", "prematch": {"type": "none"},
            "live": {"type": "goals", "direction": "under", "line": 2.5},
            "watchlist": [111, "111", " 222 ", "", "   "],
        })
        self.assertEqual(out["watchlist"], ["111", "222"])

    def test_watchlist_defaults_to_empty_not_none(self):
        out = rules.validate_rule_payload({
            "user_id": "u", "prematch": {"type": "none"},
            "live": {"type": "goals", "direction": "under", "line": 2.5},
        })
        self.assertEqual(out["watchlist"], [])

    def test_watchlist_must_be_a_list(self):
        with self.assertRaises(rules.RuleValidationError):
            rules.validate_rule_payload({
                "user_id": "u", "prematch": {"type": "none"},
                "live": {"type": "goals", "direction": "over", "line": 2.5},
                "watchlist": "111,222",
            })

    def test_the_scoreline_travels_with_the_alert(self):
        hit = rules.evaluate_rule_for_match(
            self._rule([]), _INTEL, {}, 40, _KEY_LOSS,
            score=(2, 0), fixture_id="111",
        )
        self.assertEqual(hit["score"], [2, 0])


class CandidateBoardContractTests(unittest.TestCase):
    """
    "Can Step 1 show all the matches that fall under any condition, and let me
    click accept?"

    The board is only trustworthy if it scores matches with the SAME predicate
    the live cycle uses, so these compare the two directly rather than pinning
    hard-coded counts that would drift every morning.
    """

    @staticmethod
    def _db():
        return {
            "1": {  # 3 key players missing, GK down
                "fixture": "A vs B",
                "team_audit": {
                    "home": {"missing_count": 3, "gk_out": True},
                    "away": {"missing_count": 0, "gk_out": False},
                    "has_lineup": True, "has_formation": True,
                    "formations": {"10": "4-3-3"},
                },
            },
            "2": {  # nothing wrong
                "fixture": "C vs D",
                "team_audit": {
                    "home": {"missing_count": 0, "gk_out": False},
                    "away": {"missing_count": 0, "gk_out": False},
                },
            },
            "3": {  # in the feeds, but stage 1 published NO audit for it
                "fixture": "E vs F",
            },
        }

    def test_board_reports_every_fixture_not_only_the_matches(self):
        """The user asked to see ALL matches, then pick. Hiding the misses
        would make the board a filter instead of a chooser."""
        cond = {"type": "key_missing", "side": "any", "min_count": 2}
        rows = rules.find_candidates(cond, self._db())
        self.assertEqual(len(rows), 3)
        # The misses are PRESENT, not filtered out — the user asked to see every
        # match and choose, not to be handed a pre-filtered list.
        self.assertEqual(sum(1 for r in rows if r["met"]), 1)
        self.assertEqual(sum(1 for r in rows if not r["met"]), 2)

    def test_matching_rows_sort_above_non_matching(self):
        rows = rules.find_candidates(
            {"type": "key_missing", "side": "any", "min_count": 2}, self._db()
        )
        self.assertTrue(rows[0]["met"])
        self.assertEqual(rows[0]["fixture_id"], "1")
        self.assertFalse(rows[1]["met"])

    def test_board_agrees_with_the_live_predicate(self):
        """
        The board and the cycle must never disagree. Scored here with the exact
        condition the live evaluator would use for this fixture.
        """
        cond = {"type": "key_missing", "side": "any", "min_count": 2}
        rows = rules.find_candidates(cond, self._db())
        for r in rows:
            live_met, _ = rules._prematch_condition_met(cond, self._db()[r["fixture_id"]])
            self.assertEqual(r["met"], live_met, r["fixture_id"])

    def test_evidence_comes_from_the_audit_and_nothing_is_invented(self):
        rows = rules.find_candidates({"type": "none"}, self._db())
        hit = next(r for r in rows if r["fixture_id"] == "1")
        self.assertTrue(hit["evidence"]["has_formation"])
        self.assertEqual(hit["evidence"]["home_missing"], 3)
        self.assertTrue(hit["evidence"]["home_gk_out"])
        # A real count of zero is shown as zero...
        clean = next(r for r in rows if r["fixture_id"] == "2")
        self.assertEqual(clean["evidence"]["home_missing"], 0)
        # ...but a fixture with NO audit at all is null, never coerced to 0.
        # "0 key players missing" and "we have no squad data" are opposite
        # facts and only one of them is a reason to act.
        blind = next(r for r in rows if r["fixture_id"] == "3")
        self.assertIsNone(blind["evidence"]["home_missing"])
        self.assertFalse(blind["evidence"]["has_lineup"])

    def test_a_fixture_that_is_not_live_carries_no_score(self):
        """Never a fabricated 0-0 for a match that has not kicked off."""
        rows = rules.find_candidates({"type": "none"}, self._db())
        self.assertIsNone(next(r for r in rows if r["fixture_id"] == "1")["live_score"])

    def test_a_live_fixture_carries_its_real_score(self):
        rows = rules.find_candidates(
            {"type": "none"}, self._db(), {"1": (2, 0)}
        )
        self.assertEqual(next(r for r in rows if r["fixture_id"] == "1")["live_score"], [2, 0])

    def test_the_board_validates_with_the_save_validator(self):
        """A condition the save would 422 must not be offered by the board."""
        with self.assertRaises(rules.RuleValidationError):
            rules.find_candidates(
                {"type": "key_missing", "side": "nowhere", "min_count": 2}, self._db()
            )

    def test_board_survives_a_malformed_source_row(self):
        db = {"1": {"fixture": "A vs B"}, "2": "not-a-dict", "3": {}}
        rows = rules.find_candidates({"type": "none"}, db)
        ids = {r["fixture_id"] for r in rows}
        self.assertIn("1", ids)
        self.assertNotIn("2", ids)   # skipped, not crashed on

    def test_board_never_returns_a_blank_name(self):
        rows = rules.find_candidates({"type": "none"}, {"9": {}})
        self.assertTrue(rows[0]["name"].strip())


class CandidatesEndpointContractTests(unittest.TestCase):
    """
    Regression guard for a bug that made the whole match board dead.

    The handler passed `payload.model_dump()` — which is the WRAPPER,
    {"prematch": {...}} — straight into find_candidates(), which expects the
    condition itself. Every condition therefore arrived with no "type" key and
    was rejected as invalid, so the board returned 422 for all of them.

    The unit tests on find_candidates() could not catch this: they call it
    correctly by definition. Only the wiring can break, so it is pinned here.
    """

    def _call(self, cond):
        from unittest.mock import MagicMock
        from api import user_rules_router as router

        req = MagicMock()
        req.state.user = {"user_id": "verify_probe"}
        req.client.host = "127.0.0.1"
        return router.post_user_rule_candidates(
            router.CandidateRequest(prematch=cond), req
        )

    def test_a_valid_condition_is_not_treated_as_a_wrapper(self):
        """Must return rows, not 422. This is the exact failure being pinned."""
        rows = self._call({"type": "none"})
        self.assertIsInstance(rows, list)
        self.assertGreater(len(rows), 0)

    def test_the_specific_parametrised_conditions_all_work(self):
        for cond in (
            {"type": "key_missing", "side": "any", "min_count": 2},
            {"type": "gk_liability", "side": "any"},
            {"type": "aggregator_breach", "side": "any"},
            {"type": "flag", "flag": "h2h_o25_100"},
        ):
            rows = self._call(cond)
            self.assertIsInstance(rows, list, f"{cond} returned {type(rows)}")
            for r in rows:
                self.assertIn("met", r)
                self.assertIn("reason", r)

    def test_an_invalid_condition_is_still_a_422(self):
        """The fix must not have turned the 422 path into a 500 or a pass."""
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            self._call({"type": "key_missing", "side": "nowhere", "min_count": 2})
        self.assertEqual(ctx.exception.status_code, 422)

    def test_an_unauthenticated_call_is_refused(self):
        from unittest.mock import MagicMock
        from fastapi import HTTPException
        from api import user_rules_router as router

        req = MagicMock()
        req.state.user = None
        with self.assertRaises(HTTPException) as ctx:
            router.post_user_rule_candidates(
                router.CandidateRequest(prematch={"type": "none"}), req
            )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_the_live_score_index_never_invents_a_goalless_draw(self):
        """A live fixture with no readable goals block is omitted, not zeroed."""
        from api import user_rules_router as router

        index = router._live_score_index()
        for fid, score in index.items():
            self.assertIsInstance(score, tuple)
            self.assertEqual(len(score), 2)
            self.assertTrue(all(isinstance(g, int) and g >= 0 for g in score), f"{fid}: {score}")


class UserAlertPushContractTests(unittest.TestCase):
    """
    "Where will they receive it? Will they have to come to the app?"

    A "Setup my alert" rule could fire perfectly, be written correctly to
    ready_to_push.json, and STILL never reach the user — which is exactly
    what was happening: the whole push pipeline existed but its only caller
    was the Code 2 validator, which had been removed.

    These pin the three properties that make delivery real and safe:
      * a user's alert reaches THEIR devices and nobody else's,
      * every one of their devices is covered, and a dead one is pruned
        without unsubscribing the rest,
      * nothing here can break a live cycle.
    """

    def test_user_alert_is_recorded_with_its_audience(self):
        with tempfile.TemporaryDirectory() as tmp:
            _patch_notify_paths(tmp)
            key = notify.emit_event(
                "USER_ALERT", "19715226", "Necaxa v America", "ALERT", None,
                audience_user_id="uA", rule_id="r1", rule_label="Under 2.5",
                minute=38, score_at_trigger="2-0", gate="under 2.5")
            self.assertIsNotNone(key)
            rec = notify.read_events()[-1]
            self.assertEqual(rec["event"], "USER_ALERT")
            self.assertEqual(rec["audience_user_id"], "uA")
            self.assertEqual(rec["gate"], "under 2.5")
            self.assertEqual(rec["score_at_trigger"], "2-0")

    def test_a_private_alert_never_reaches_another_user(self):
        """
        THE isolation contract. dispatch() is a broadcast for system events, so
        without audience scoping one user's private alert would be pushed to
        every account on the system.
        """
        with tempfile.TemporaryDirectory() as tmp:
            _patch_notify_paths(tmp)
            notify.save_subscription(
                "uA", "https://push/A", {"p256dh": "k", "auth": "a"})
            notify.save_subscription(
                "uB", "https://push/B", {"p256dh": "k", "auth": "a"})

            sent_to = []

            def fake_send(sub, payload, priv, pub):
                sent_to.append(sub["endpoint"])
                return "sent"

            event = {"event": "USER_ALERT", "key": "k1",
                     "audience_user_id": "uA"}
            with patch.object(notify, "_vapid_keys",
                              return_value=("priv", "pub")), \
                 patch.object(notify, "_send_one", fake_send):
                notify.dispatch([event])

            self.assertEqual(sent_to, ["https://push/A"],
                             "user B must never receive user A's alert")

    def test_a_system_event_is_still_broadcast(self):
        """Audience scoping must not silence the system events."""
        with tempfile.TemporaryDirectory() as tmp:
            _patch_notify_paths(tmp)
            notify.save_subscription(
                "uA", "https://push/A", {"p256dh": "k", "auth": "a"})
            notify.save_subscription(
                "uB", "https://push/B", {"p256dh": "k", "auth": "a"})
            sent_to = []
            with patch.object(notify, "_vapid_keys",
                              return_value=("priv", "pub")), \
                 patch.object(notify, "_send_one",
                              lambda s, p, a, b: (sent_to.append(s["endpoint"]), "sent")[1]):
                notify.dispatch([{"event": "TRIGGERED", "key": "k1",
                                  "market": "GG", "fixture": "A v B"}])
            self.assertEqual(sorted(sent_to), ["https://push/A", "https://push/B"])

    def test_every_device_of_the_owner_is_notified(self):
        """A phone and a laptop must BOTH be covered."""
        with tempfile.TemporaryDirectory() as tmp:
            _patch_notify_paths(tmp)
            notify.save_subscription(
                "uA", "https://push/phone", {"p256dh": "k", "auth": "a"})
            notify.save_subscription(
                "uA", "https://push/laptop", {"p256dh": "k", "auth": "a"})
            sent_to = []
            with patch.object(notify, "_vapid_keys",
                              return_value=("priv", "pub")), \
                 patch.object(notify, "_send_one",
                              lambda s, p, a, b: (sent_to.append(s["endpoint"]), "sent")[1]):
                notify.dispatch([{"event": "USER_ALERT", "key": "k1",
                                  "audience_user_id": "uA"}])
            self.assertEqual(sorted(sent_to),
                             ["https://push/laptop", "https://push/phone"])

    def test_a_second_device_does_not_evict_the_first(self):
        """
        The old store was keyed by user_id alone, so subscribing on a laptop
        silently REPLACED the phone. The user would believe both were covered
        and miss every alert on one of them.
        """
        with tempfile.TemporaryDirectory() as tmp:
            _patch_notify_paths(tmp)
            notify.save_subscription(
                "uA", "https://push/phone", {"p256dh": "k", "auth": "a"})
            notify.save_subscription(
                "uA", "https://push/laptop", {"p256dh": "k", "auth": "a"})
            prefs = notify.get_prefs("uA")
            self.assertTrue(prefs["subscribed"])
            self.assertEqual(prefs["devices"], 2)

    def test_a_legacy_single_endpoint_record_still_works(self):
        """
        The old flat shape {user_id: {endpoint, keys, prefs}} must keep
        working, or the first read after deploy would silently unsubscribe
        everyone already using the app.
        """
        with tempfile.TemporaryDirectory() as tmp:
            _patch_notify_paths(tmp)
            legacy = {"uA": {"endpoint": "https://push/old", "keys": {},
                             "prefs": {"triggered": True, "settled": True},
                             "created_at": "2026-01-01T00:00:00+00:00",
                             "updated_at": "2026-01-01T00:00:00+00:00"}}
            with open(notify.SUBS_FILE, "w", encoding="utf-8") as f:
                json.dump(legacy, f)
            prefs = notify.get_prefs("uA")
            self.assertTrue(prefs["subscribed"])
            self.assertEqual(prefs["devices"], 1)
            sent_to = []
            with patch.object(notify, "_vapid_keys",
                              return_value=("priv", "pub")), \
                 patch.object(notify, "_send_one",
                              lambda s, p, a, b: (sent_to.append(s["endpoint"]), "sent")[1]):
                notify.dispatch([{"event": "USER_ALERT", "key": "k1",
                                  "audience_user_id": "uA"}])
            self.assertEqual(sent_to, ["https://push/old"])

    def test_a_dead_device_is_pruned_without_losing_the_account(self):
        """A 410 on the laptop must not unsubscribe the phone."""
        with tempfile.TemporaryDirectory() as tmp:
            _patch_notify_paths(tmp)
            notify.save_subscription(
                "uA", "https://push/phone", {"p256dh": "k", "auth": "a"})
            notify.save_subscription(
                "uA", "https://push/laptop", {"p256dh": "k", "auth": "a"})

            def send(sub, payload, priv, pub):
                return "gone" if sub["endpoint"] == "https://push/laptop" else "sent"

            with patch.object(notify, "_vapid_keys",
                              return_value=("priv", "pub")), \
                 patch.object(notify, "_send_one", send):
                notify.dispatch([{"event": "USER_ALERT", "key": "k1",
                                  "audience_user_id": "uA"}])
            prefs = notify.get_prefs("uA")
            self.assertTrue(prefs["subscribed"], "the phone must survive")
            self.assertEqual(prefs["devices"], 1)

    def test_switching_user_alert_off_actually_suppresses_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            _patch_notify_paths(tmp)
            notify.save_subscription(
                "uA", "https://push/A", {"p256dh": "k", "auth": "a"})
            notify.update_prefs("uA", {"user_alert": False})
            self.assertFalse(notify.get_prefs("uA")["user_alert"])
            sent_to = []
            with patch.object(notify, "_vapid_keys",
                              return_value=("priv", "pub")), \
                 patch.object(notify, "_send_one",
                              lambda s, p, a, b: (sent_to.append(s["endpoint"]), "sent")[1]):
                notify.dispatch([{"event": "USER_ALERT", "key": "k1",
                                  "audience_user_id": "uA"}])
            self.assertEqual(sent_to, [], "opted-out alert must not be pushed")

    def test_prefs_apply_to_every_device(self):
        with tempfile.TemporaryDirectory() as tmp:
            _patch_notify_paths(tmp)
            notify.save_subscription(
                "uA", "https://push/phone", {"p256dh": "k", "auth": "a"})
            notify.save_subscription(
                "uA", "https://push/laptop", {"p256dh": "k", "auth": "a"})
            notify.update_prefs("uA", {"user_alert": False})
            for sub in notify._user_devices(notify.list_subscriptions(), "uA"):
                self.assertFalse(sub["prefs"]["user_alert"])

    def test_the_lockscreen_carries_the_scoreline(self):
        """'under 2.5' is not actionable without knowing the match is inside it."""
        payload = notify.build_payload({
            "event": "USER_ALERT", "fixture": "Necaxa v America",
            "rule_label": "Under 2.5 after danger breach",
            "minute": 38, "score_at_trigger": "2-0", "gate": "under 2.5",
            "fixture_id": "19715226",
        })
        self.assertIn("under 2.5", payload["body"])
        self.assertIn("2-0", payload["body"])
        self.assertIn("38'", payload["body"])
        self.assertEqual(payload["data"]["url"],
                         "/live/edges?fixture=19715226")

    def test_a_failed_push_never_escapes_into_the_scanner(self):
        """notifications.py's standing contract, enforced at the entry point."""
        with tempfile.TemporaryDirectory() as tmp:
            _patch_notify_paths(tmp)
            # A real pending event, so dispatch() is actually reached. Without
            # one the no-op path returns early and the guard is never tested.
            notify.emit_event("USER_ALERT", "1", "A v B", "ALERT", None,
                              audience_user_id="uA")
            self.assertEqual(len(notify.pending_events()), 1)
            with patch.object(notify, "dispatch",
                              side_effect=RuntimeError("push service on fire")):
                summary = notify.dispatch_pending(limit=10)
            self.assertTrue(summary.get("error"))
            self.assertEqual(summary.get("sent"), 0)

    def test_dispatch_pending_is_a_noop_with_nothing_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            _patch_notify_paths(tmp)
            summary = notify.dispatch_pending(limit=10)
            self.assertEqual(summary.get("pending"), 0)
            self.assertEqual(summary.get("sent"), 0)

    def test_the_goal_gate_is_described_in_words(self):
        from LIVE_SCANNER.user_rules_store import describe_goal_gate

        def group(*conds):
            return {"conditions": list(conds), "mode": "all",
                    "threshold": len(conds)}

        under = {"type": "goals", "direction": "under", "line": 2.5}
        self.assertEqual(describe_goal_gate(group(under)), "under 2.5")
        self.assertEqual(
            describe_goal_gate(group({"type": "goals", "direction": "over", "line": 3})),
            "over 3")
        self.assertEqual(
            describe_goal_gate(group({"type": "goals", "direction": "exact", "line": 3})),
            "exactly 3 goals")
        # The gate is found among siblings, not only when it is alone.
        self.assertEqual(
            describe_goal_gate(group(
                {"type": "sot", "side": "home", "min_value": 4}, under)),
            "under 2.5")
        # A group with no gate at all.
        self.assertIsNone(
            describe_goal_gate(group({"type": "sot", "side": "home", "min_value": 4})))
        self.assertIsNone(describe_goal_gate({"conditions": []}))
        # A legacy single-condition dict is still a dict, so it must be wrapped
        # rather than read as an (empty) group.
        self.assertEqual(describe_goal_gate(under), "under 2.5")
        self.assertIsNone(describe_goal_gate({}))

    def test_the_rule_alert_carries_its_gate_to_the_evaluator(self):
        from LIVE_SCANNER import user_rules_store as rules
        rule = {"rule_id": "r", "user_id": "u", "label": "L",
                "prematch": {"type": "none"},
                "live": {"type": "goals", "direction": "under", "line": 2.5},
                "active": True}
        hit = rules.evaluate_rule_for_match(
            rule, _INTEL, {}, 40, _KEY_LOSS, score=(1, 0), fixture_id="1")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["gate"], "under 2.5")

    def test_a_rule_with_no_gate_reports_none(self):
        from LIVE_SCANNER import user_rules_store as rules
        rule = {"rule_id": "r", "user_id": "u", "label": "L",
                "prematch": {"type": "none"},
                "live": {"type": "pressure_share", "side": "home", "min_value": 50},
                "active": True}
        hit = rules.evaluate_rule_for_match(
            rule, _INTEL, {}, 40, _KEY_LOSS, score=(1, 0), fixture_id="1")
        self.assertIsNotNone(hit)
        self.assertIsNone(hit["gate"])


class LiveConditionGroupContractTests(unittest.TestCase):
    """
    "The live condition should be flexible — I should be able to select all
    the conditions I want, not be limited to only one."

    A group is {conditions: [...], mode: "all" | "at_least", threshold: N}.
    Prematch stays single-select by design; only the live half is a group.
    """

    @staticmethod
    def _rule(conditions, mode="all", threshold=None, **extra):
        live = {"conditions": conditions, "mode": mode}
        if threshold is not None:
            live["threshold"] = threshold
        rule = {"rule_id": "r", "user_id": "u", "label": "L",
                "prematch": {"type": "none"}, "live": live, "active": True}
        rule.update(extra)
        return rule

    # Under 2.5 AND home pressure >= 55. _INTEL has h_pressure_share = 60.
    GATE = {"type": "goals", "direction": "under", "line": 2.5}
    PRESSURE = {"type": "pressure_share", "side": "home", "min_value": 55}
    # SOT is 4 for home, so min 4 passes and min 9 fails.
    SOT_PASS = {"type": "sot", "side": "home", "min_value": 4}
    SOT_FAIL = {"type": "sot", "side": "home", "min_value": 9}

    # ── the headline case: scoreline composes with another condition ───────
    def test_the_gate_combines_with_another_live_condition(self):
        """"under 2.5 AND home pressure > 60" was inexpressible before."""
        rule = self._rule([self.GATE, self.PRESSURE])
        # 1-0, pressure 60 -> both hold.
        self.assertIsNotNone(rules.evaluate_rule_for_match(
            rule, _INTEL, {}, 40, _KEY_LOSS, score=(1, 0)))
        # 2-1 -> three goals, the scoreline is gone, so the whole rule stays
        # silent even though the pressure condition still holds.
        self.assertIsNone(rules.evaluate_rule_for_match(
            rule, _INTEL, {}, 40, _KEY_LOSS, score=(2, 1)))
        # 3-0: three goals, so under 2.5 is gone again. The gate holds the
        # line from BOTH directions, and the pressure condition is irrelevant
        # to that decision.
        self.assertIsNone(rules.evaluate_rule_for_match(
            rule, _INTEL, {}, 40, _KEY_LOSS, score=(3, 0)))
        # 0-0 stays inside the limit at any scoreline the user allows.
        self.assertIsNotNone(rules.evaluate_rule_for_match(
            rule, _INTEL, {}, 40, _KEY_LOSS, score=(0, 0)))

    def test_a_failing_sibling_still_blocks_in_all_mode(self):
        rule = self._rule([self.GATE, self.SOT_FAIL])
        self.assertIsNone(rules.evaluate_rule_for_match(
            rule, _INTEL, {}, 40, _KEY_LOSS, score=(1, 0)))

    # ── at_least N of K ────────────────────────────────────────────────────
    def test_at_least_two_of_three_fires_when_two_hold(self):
        rule = self._rule([self.GATE, self.SOT_PASS, self.SOT_FAIL],
                          mode="at_least", threshold=2)
        self.assertIsNotNone(rules.evaluate_rule_for_match(
            rule, _INTEL, {}, 40, _KEY_LOSS, score=(1, 0)))

    def test_at_least_two_of_three_is_silent_when_only_one_holds(self):
        rule = self._rule([self.GATE, self.SOT_FAIL, self.SOT_FAIL],
                          mode="at_least", threshold=2)
        self.assertIsNone(rules.evaluate_rule_for_match(
            rule, _INTEL, {}, 40, _KEY_LOSS, score=(1, 0)))

    def test_at_least_one_of_two_is_equivalent_to_or(self):
        rule = self._rule([self.GATE, self.SOT_FAIL],
                          mode="at_least", threshold=1)
        # The gate holds, the SOT condition does not — OR still fires.
        self.assertIsNotNone(rules.evaluate_rule_for_match(
            rule, _INTEL, {}, 40, _KEY_LOSS, score=(1, 0)))
        # Gate gone at 2-1, SOT still failing — now nothing holds.
        self.assertIsNone(rules.evaluate_rule_for_match(
            rule, _INTEL, {}, 40, _KEY_LOSS, score=(2, 1)))

    def test_all_mode_is_the_default(self):
        rule = self._rule([self.GATE, self.SOT_PASS])
        self.assertIsNotNone(rules.evaluate_rule_for_match(
            rule, _INTEL, {}, 40, _KEY_LOSS, score=(1, 0)))

    # ── backward compatibility ─────────────────────────────────────────────
    def test_a_legacy_single_condition_rule_still_works(self):
        """Every alert saved before multi-select must keep behaving the same."""
        legacy = {"rule_id": "r", "user_id": "u", "label": "L",
                  "prematch": {"type": "none"},
                  "live": {"type": "goals", "direction": "under", "line": 2.5},
                  "active": True}
        self.assertIsNotNone(rules.evaluate_rule_for_match(
            legacy, _INTEL, {}, 40, _KEY_LOSS, score=(1, 0)))
        self.assertIsNone(rules.evaluate_rule_for_match(
            legacy, _INTEL, {}, 40, _KEY_LOSS, score=(2, 1)))

    def test_a_legacy_rule_still_reports_its_gate(self):
        legacy = {"rule_id": "r", "user_id": "u", "label": "L",
                  "prematch": {"type": "none"},
                  "live": {"type": "goals", "direction": "under", "line": 2.5},
                  "active": True}
        hit = rules.evaluate_rule_for_match(
            legacy, _INTEL, {}, 40, _KEY_LOSS, score=(1, 0))
        self.assertEqual(hit["gate"], "under 2.5")

    # ── validation ─────────────────────────────────────────────────────────
    def test_an_empty_group_is_rejected(self):
        with self.assertRaises(rules.RuleValidationError):
            rules.validate_rule_payload({
                "user_id": "u", "prematch": {"type": "none"},
                "live": {"conditions": [], "mode": "all"}})

    def test_an_unknown_mode_is_rejected(self):
        with self.assertRaises(rules.RuleValidationError):
            rules.validate_rule_payload({
                "user_id": "u", "prematch": {"type": "none"},
                "live": {"conditions": [self.GATE], "mode": "sideways"}})

    def test_a_threshold_above_the_condition_count_is_rejected(self):
        with self.assertRaises(rules.RuleValidationError):
            rules.validate_rule_payload({
                "user_id": "u", "prematch": {"type": "none"},
                "live": {"conditions": [self.GATE], "mode": "at_least",
                         "threshold": 3}})

    def test_a_zero_threshold_is_rejected(self):
        with self.assertRaises(rules.RuleValidationError):
            rules.validate_rule_payload({
                "user_id": "u", "prematch": {"type": "none"},
                "live": {"conditions": [self.GATE], "mode": "at_least",
                         "threshold": 0}})

    def test_a_bad_condition_inside_a_group_is_still_rejected(self):
        with self.assertRaises(rules.RuleValidationError):
            rules.validate_rule_payload({
                "user_id": "u", "prematch": {"type": "none"},
                "live": {"conditions": [self.GATE,
                                        {"type": "goals", "direction": "sideways",
                                         "line": 2}]}})

    def test_too_many_conditions_are_rejected(self):
        many = [{"type": "sot", "side": "home", "min_value": 1} for _ in range(9)]
        with self.assertRaises(rules.RuleValidationError):
            rules.validate_rule_payload({
                "user_id": "u", "prematch": {"type": "none"},
                "live": {"conditions": many, "mode": "all"}})

    def test_threshold_defaults_to_all_when_omitted(self):
        out = rules.validate_rule_payload({
            "user_id": "u", "prematch": {"type": "none"},
            "live": {"conditions": [self.GATE, self.SOT_PASS]}})
        self.assertEqual(out["live"]["mode"], "all")
        self.assertEqual(out["live"]["threshold"], 2)

    # ── the note must explain a silent rule ───────────────────────────────
    def test_the_note_names_every_condition(self):
        """A rule that never fires must say WHY, not just go quiet."""
        met, note = rules._live_conditions_met(
            {"conditions": [self.GATE, self.SOT_FAIL], "mode": "all",
             "threshold": 2}, _INTEL, _KEY_LOSS, score=(1, 0))
        self.assertFalse(met)
        self.assertIn("1/2", note)          # how many held
        self.assertIn("under 2.5", note)     # the gate, by name
        self.assertIn("SOT", note)           # the blocker, by name
        self.assertIn("9", note)             # and its real numbers

    def test_the_note_states_the_threshold_in_at_least_mode(self):
        met, note = rules._live_conditions_met(
            {"conditions": [self.GATE, self.SOT_FAIL, self.SOT_FAIL],
             "mode": "at_least", "threshold": 2},
            _INTEL, _KEY_LOSS, score=(1, 0))
        self.assertFalse(met)
        self.assertIn("need 2", note)

    def test_one_broken_condition_does_not_take_down_the_group(self):
        """
        An unreadable condition must be reported as UNMET, never raised, and
        must not stop its siblings from being evaluated. If this ever raised,
        one bad condition in a group would take down the whole live cycle.
        """
        met, note = rules._live_conditions_met(
            {"conditions": [{"type": "not_a_real_type"}, self.GATE],
             "mode": "all", "threshold": 2},
            _INTEL, _KEY_LOSS, score=(1, 0))
        self.assertFalse(met)
        self.assertIn("Unknown live condition", note)
        # The good sibling was still evaluated and still passed.
        self.assertIn("1/2", note)
        self.assertIn("under 2.5", note)

    def test_prematch_remains_single_select(self):
        """
        Prematch is deliberately NOT a group. A second prematch condition must
        be rejected rather than silently ignored, so a user never believes
        they narrowed the board when they did not.
        """
        with self.assertRaises(rules.RuleValidationError):
            rules.validate_rule_payload({
                "user_id": "u",
                "prematch": {"conditions": [
                    {"type": "flag", "flag": "h2h_o25_100"},
                    {"type": "key_missing", "side": "any", "min_count": 2}],
                },
                "live": {"type": "goals", "direction": "under", "line": 2.5}})


class ServiceWorkerReachabilityContractTests(unittest.TestCase):
    """
    Web Push cannot work if the browser cannot fetch /sw.js.

    The service worker script was NOT in the auth middleware's public
    allowlist, so it answered 307 (redirect to /login) for any request without
    a session cookie. A service worker registration is entitled to fetch that
    script at moments when a redirect is fatal, and a redirect is never a valid
    service worker response — so registration can fail in ways that look like
    "push is unsupported" and send the user chasing the wrong fix.

    These are static checks against the source, because the failure is a
    routing decision, not runtime state.
    """

    @staticmethod
    def _middleware() -> str:
        from pathlib import Path
        return (Path(__file__).parent / "alienedge-frontend" / "middleware.ts").read_text(
            encoding="utf-8"
        )

    @staticmethod
    def _sw() -> str:
        from pathlib import Path
        return (Path(__file__).parent / "alienedge-frontend" / "public" / "sw.js").read_text(
            encoding="utf-8"
        )

    def test_sw_js_is_publicly_servable(self):
        self.assertIn('pathname === "/sw.js"', self._middleware())

    def test_the_manifest_is_publicly_servable(self):
        self.assertIn('pathname === "/manifest.webmanifest"', self._middleware())

    def test_the_icons_are_publicly_servable(self):
        self.assertIn('pathname.startsWith("/icons/")', self._middleware())
        self.assertIn('pathname === "/apple-touch-icon.png"', self._middleware())

    def test_the_sw_only_references_icons_that_exist(self):
        """
        A notification whose icon 404s still appears, but with a broken-image
        placeholder, which on iOS can suppress the alert entirely. The worker
        referenced /icon-192.png and /badge-72.png, neither of which existed.
        """
        sw = self._sw()
        referenced = [
            line.split('"')[1]
            for line in sw.splitlines()
            if 'icon:' in line or 'badge:' in line
        ]
        self.assertTrue(referenced, "expected the worker to set an icon")
        for url in referenced:
            path = (Path(__file__).parent / "alienedge-frontend" / "public" / url.lstrip("/"))
            self.assertTrue(path.exists(), f"sw.js references missing icon: {url}")

    def test_a_push_cannot_redirect_the_user_off_origin(self):
        """
        The push payload is remote input. Following a URL from it unchecked
        would let a compromised or malformed push bounce a user anywhere.
        """
        sw = self._sw()
        self.assertIn("self.location.origin", sw)

    def test_the_manifest_points_at_real_icons(self):
        import json
        from pathlib import Path
        root = Path(__file__).parent / "alienedge-frontend" / "public"
        manifest = json.loads((root / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertTrue(manifest["icons"], "manifest declares no icons")
        for icon in manifest["icons"]:
            self.assertTrue((root / icon["src"].lstrip("/")).exists(),
                            f"missing manifest icon: {icon['src']}")
        # Standalone display is what makes an installed app feel like an app.
        self.assertEqual(manifest["display"], "standalone")

    def test_the_layout_links_the_manifest(self):
        from pathlib import Path
        layout = (Path(__file__).parent / "alienedge-frontend" / "app" / "layout.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn('manifest: "/manifest.webmanifest"', layout)
        self.assertIn("appleWebApp", layout)


class AlertStatusContractTests(unittest.TestCase):
    """
    "Can it show three states — waiting, alerted, failed?"

    An alert that has never fired is indistinguishable from one that can never
    fire, because a log only records what HAPPENED and never what is about to.
    The status has to combine the live board with the fire history, and it must
    never dress up a guess as a fact.
    """

    def _call(self, rules, board, alerts, push_subscribed=True):
        from unittest.mock import MagicMock, patch
        import tempfile, os
        from api import user_rules_router as router

        tmp = tempfile.mkdtemp()
        board_file = os.path.join(tmp, "board.json")
        alerts_file = os.path.join(tmp, "alerts.jsonl")
        with open(board_file, "w", encoding="utf-8") as f:
            json.dump(board, f)
        with open(alerts_file, "w", encoding="utf-8") as f:
            for a in alerts:
                f.write(json.dumps(a) + "\n")

        req = MagicMock()
        req.state.user = {"user_id": "u1"}
        with patch.object(router, "READY_TO_PUSH_FILE", alerts_file), \
             patch.object(router, "ORCHESTRATOR_BOARD_FILE", board_file), \
             patch.object(router, "list_rules", return_value=rules), \
             patch("notifications.get_prefs", return_value={"subscribed": push_subscribed}):
            return {r["rule_id"]: r for r in router.get_user_rule_status(req)}

    # Computed, not hard-coded: `board_stale` compares the board's age against
    # the wall clock, so a fixed timestamp would make "fresh" true or false
    # depending on when the suite happens to run.
    @property
    def NOW(self):
        from datetime import datetime as _dt, timezone as _tz
        return _dt.now(_tz.utc).isoformat()

    def _board(self, live=True):
        return {
            "generated_at": self.NOW,
            "rule_live": {
                "r_live": [{"fixture_id": "1", "name": "A v B", "minute": 38,
                            "score": "1-0", "gate": "under 2.5"}],
            } if live else {},
        }

    # ── the three states the user asked for ────────────────────────────────
    def test_waiting_when_nothing_matches_and_nothing_fired(self):
        out = self._call(
            [{"rule_id": "r_wait", "label": "W", "active": True}],
            self._board(live=False), [])
        self.assertEqual(out["r_wait"]["status"], "waiting")
        self.assertEqual(out["r_wait"]["fired_count"], 0)
        self.assertIsNone(out["r_wait"]["last_fired"])

    def test_live_when_a_match_qualifies_right_now(self):
        out = self._call(
            [{"rule_id": "r_live", "label": "L", "active": True}],
            self._board(), [])
        r = out["r_live"]
        self.assertEqual(r["status"], "live")
        self.assertEqual(r["live_count"], 1)
        self.assertEqual(r["live_matches"][0]["name"], "A v B")
        self.assertEqual(r["live_matches"][0]["score"], "1-0")
        # The gate travels with it, so the UI can show why it qualifies.
        self.assertEqual(r["live_matches"][0]["gate"], "under 2.5")

    def test_fired_when_the_log_has_an_entry(self):
        out = self._call(
            [{"rule_id": "r_fired", "label": "F", "active": True}],
            self._board(live=False),
            [{"user_id": "u1", "rule_id": "r_fired", "f_id": "9",
              "fixture": "C v D", "minute": 55, "score_at_trigger": "2-0",
              "time": self.NOW}])
        r = out["r_fired"]
        self.assertEqual(r["status"], "fired")
        self.assertEqual(r["fired_count"], 1)
        self.assertEqual(r["last_fired"]["fixture"], "C v D")

    def test_live_outranks_fired(self):
        """A rule can have fired yesterday AND be qualifying again now."""
        out = self._call(
            [{"rule_id": "r_live", "label": "L", "active": True}],
            self._board(),
            [{"user_id": "u1", "rule_id": "r_live", "f_id": "8",
              "fixture": "E v F", "time": self.NOW}])
        # "Qualifying now" is the more useful and more current fact.
        self.assertEqual(out["r_live"]["status"], "live")

    def test_paused_when_the_user_turned_it_off(self):
        out = self._call(
            [{"rule_id": "r_p", "label": "P", "active": False}],
            self._board(), [])
        self.assertEqual(out["r_p"]["status"], "paused")

    # ── per-user isolation ─────────────────────────────────────────────────
    def test_another_users_alerts_are_never_counted(self):
        out = self._call(
            [{"rule_id": "r_fired", "label": "F", "active": True}],
            self._board(live=False),
            [{"user_id": "SOMEONE_ELSE", "rule_id": "r_fired", "f_id": "9",
              "fixture": "Not mine", "time": self.NOW}])
        self.assertEqual(out["r_fired"]["status"], "waiting")
        self.assertEqual(out["r_fired"]["fired_count"], 0)

    # ── needs push ─────────────────────────────────────────────────────────
    def test_qualifying_but_unsubscribed_raises_needs_push(self):
        """The one combination that otherwise looks like silence."""
        out = self._call(
            [{"rule_id": "r_live", "label": "L", "active": True}],
            self._board(), [], push_subscribed=False)
        self.assertTrue(out["r_live"]["needs_push"])

    def test_qualifying_and_subscribed_does_not_raise_needs_push(self):
        out = self._call(
            [{"rule_id": "r_live", "label": "L", "active": True}],
            self._board(), [], push_subscribed=True)
        self.assertFalse(out["r_live"]["needs_push"])

    def test_needs_push_only_while_something_qualifies(self):
        """A dormant rule must not nag about push it has not earned yet."""
        out = self._call(
            [{"rule_id": "r_wait", "label": "W", "active": True}],
            self._board(live=False), [], push_subscribed=False)
        self.assertFalse(out["r_wait"]["needs_push"])

    # ── honesty about an unknown state ─────────────────────────────────────
    def test_a_stale_board_never_claims_nothing_is_live(self):
        """An old board means "unknown", not "nothing"."""
        stale = {"generated_at": "2020-01-01T00:00:00+00:00", "rule_live": {}}
        out = self._call([{"rule_id": "r_w", "label": "W", "active": True}], stale, [])
        self.assertTrue(out["r_w"]["board_stale"])

    def test_a_fresh_board_is_not_stale(self):
        out = self._call([{"rule_id": "r_w", "label": "W", "active": True}],
                         self._board(live=False), [])
        self.assertFalse(out["r_w"]["board_stale"])

    def test_old_alerts_outside_the_window_are_ignored(self):
        out = self._call(
            [{"rule_id": "r_f", "label": "F", "active": True}],
            self._board(live=False),
            [{"user_id": "u1", "rule_id": "r_f", "f_id": "1",
              "time": "2020-01-01T00:00:00+00:00"}])
        self.assertEqual(out["r_f"]["fired_count"], 0)
        self.assertEqual(out["r_f"]["status"], "waiting")

    def test_malformed_log_lines_are_skipped_not_fatal(self):
        out = self._call([{"rule_id": "r_f", "label": "F", "active": True}],
                         self._board(live=False), [])
        self.assertEqual(out["r_f"]["status"], "waiting")

    # ── the board must actually publish rule_live ─────────────────────────
    def test_the_cycle_publishes_rule_live_on_the_board(self):
        """
        Without this the status endpoint can only ever report "waiting", and
        the whole feature silently does nothing.
        """
        import inspect
        from LIVE_SCANNER import live_stage6_alerts as stage6
        src = inspect.getsource(stage6.SupremeOrchestrator.save_orchestrator_board)
        self.assertIn('"rule_live"', src)
        # And it must be rebuilt per cycle, never accumulated.
        self.assertIn("self._rule_live = {}", inspect.getsource(
            stage6.SupremeOrchestrator.run_single_cycle))

    # ── regression: the timestamp shape the log ACTUALLY writes ───────────
    def test_naive_log_timestamps_do_not_crash_the_endpoint(self):
        """
        fire_alert() writes `datetime.now().isoformat()` — no offset, no Z.
        Comparing that against the aware staleness cutoff raised TypeError and
        took the whole endpoint down on every real call, while every test that
        used an offset-aware fixture passed. Use the real shape here.
        """
        from datetime import datetime as _dt
        naive = _dt.now().isoformat()  # exactly what the scanner writes
        out = self._call(
            [{"rule_id": "r_n", "label": "N", "active": True}],
            self._board(live=False),
            [{"user_id": "u1", "rule_id": "r_n", "f_id": "7",
              "fixture": "G v H", "time": naive}])
        self.assertEqual(out["r_n"]["status"], "fired")
        self.assertEqual(out["r_n"]["fired_count"], 1)

    def test_naive_board_timestamp_does_not_crash_the_endpoint(self):
        """The board must not raise either when it carries a naive stamp."""
        from datetime import datetime as _dt
        board = {"generated_at": _dt.now().isoformat(), "rule_live": {}}
        out = self._call([{"rule_id": "r_n", "label": "N", "active": True}], board, [])
        self.assertFalse(out["r_n"]["board_stale"])

    def test_unparseable_timestamp_still_reports_the_alert_and_does_not_crash(self):
        """
        A record whose timestamp cannot be read has still HAPPENED, so it is
        still shown. Dropping it would hide a real alert because of a cosmetic
        data fault — the opposite of what the user wants. It simply cannot be
        age-filtered, so it is kept without one.
        """
        out = self._call(
            [{"rule_id": "r_n", "label": "N", "active": True}],
            self._board(live=False),
            [{"user_id": "u1", "rule_id": "r_n", "f_id": "7", "time": "not-a-date"}])
        self.assertEqual(out["r_n"]["status"], "fired")
        self.assertEqual(out["r_n"]["fired_count"], 1)




# ══════════════════════════════════════════════════════════════════════
# SIGNED IMPACT (2026-09-28)
# ══════════════════════════════════════════════════════════════════════
# The audit found Stage 4 deciding DANGER/SAFE from a headcount
# (`len(missing) >= 4 or gk_hole`) while DISPLAYING a `vulnerability_pct`
# that never influenced the verdict — and structurally unable to report
# that a rotation had UPGRADED a side. These pin the signed replacement.
#
# The motivating evidence, measured on the live board: 10 of 22 sides were
# labelled DANGER while the players who left were, on average, WORSE than
# the players who started. Northern Ireland vs Hungary was the clearest —
# 8 missing (the heaviest damage on the board) with the eight out averaging
# 6.83 against 7.41 for the eleven in.


def _player(name, pos, rating, apps, mins):
    return {"name": name, "pos": pos, "avg_rating": rating,
            "apps": apps, "mins": mins}


def _xi(rating, apps=20, mins=1800):
    """A realistic key eleven at one given quality level.

    Two players cannot exercise this metric: the weights are positional
    (GK 50, DEF 9, MID 4.5, ATT 1.5) and the DANGER bar was calibrated on the
    live board's real distribution, so a two-man sample lands under it and the
    verdict stays ROTATION. Building a full XI is what actually answers the
    question "is losing this side of its squad damage or an upgrade?".
    """
    return ([_player("GK", "Goalkeeper", rating, apps, mins)]
            + [_player(f"D{i}", "Defender", rating, apps, mins) for i in range(4)]
            + [_player(f"M{i}", "Midfielder", rating, apps, mins) for i in range(3)]
            + [_player(f"A{i}", "Attacker", rating, apps, mins) for i in range(3)])


# A proven, above-average XI (7.20) and a genuinely poor one (6.30), with
# thin-sample replacements that must not be able to cancel a real difference.
_PROVEN = _xi(7.20)
_WEAK = _xi(6.30)
_REPLACEMENTS = _xi(6.90, apps=1, mins=90)


class SignedImpactContractTests(unittest.TestCase):
    """The sign convention, the confidence shrink, and the keeper rule."""

    def test_confidence_is_full_only_for_a_well_evidenced_player(self):
        self.assertEqual(si.confidence(30, 2700), 1.0)
        # 2 apps / 126 min is the median "missing key player" on the live
        # board. It must earn almost no say in the verdict.
        self.assertLess(si.confidence(2, 126), 0.25)

    def test_confidence_never_raises_and_survives_junk(self):
        for bad in (None, -5, "x", float("nan")):
            c = si.confidence(bad, bad)
            self.assertGreaterEqual(c, 0.0)
            self.assertLessEqual(c, 1.0)

    def test_losing_your_best_players_is_damage(self):
        out = si.assess_absence(_PROVEN, _REPLACEMENTS, regime="MID_FIELD")
        self.assertGreater(out["net_impact"], 0,
                           "better players leaving must read as a LOSS")
        self.assertEqual(out["verdict"], si.STATE_DANGER)

    def test_losing_your_worst_players_is_an_upgrade(self):
        """The case the headcount could never express."""
        out = si.assess_absence(_WEAK, _REPLACEMENTS, regime="MID_FIELD")
        self.assertLess(out["net_impact"], 0,
                        "worse players leaving must read as a GAIN")
        self.assertEqual(out["verdict"], si.STATE_BLESSING)

    def test_thin_evidence_is_rotation_even_against_a_strong_favourite(self):
        """A 2-app sample must not be able to outvote a favourite's price."""
        thin = [_player("X", "Attacker", 7.40, 2, 126)]
        out = si.assess_absence(thin, _REPLACEMENTS, regime="STRONG_FAVOURITE")
        self.assertEqual(out["verdict"], si.STATE_ROTATION)
        self.assertEqual(out["rotation_uplift"], si.ROTATION_ATTACK_UPLIFT)

    def test_no_replacement_group_means_no_verdict(self):
        """The upgrade claim is meaningless without a comparison group."""
        out = si.assess_absence(_PROVEN, [], regime="MID_FIELD")
        self.assertEqual(out["verdict"], si.STATE_UNKNOWN)

    def test_both_sides_of_the_comparison_are_measured_on_one_ruler(self):
        """Regression: the replacement group was originally NOT shrunk.

        A one-appearance replacement with a 6.90 rating contributed a full
        0.15 of credit and cancelled real quality loss, turning a clear
        DANGER into ROTATION. Both sides must carry the same shrink.
        """
        out = si.assess_absence(_PROVEN, _REPLACEMENTS, regime="MID_FIELD")
        self.assertEqual(out["verdict"], si.STATE_DANGER,
                         "a noisy replacement must not cancel proven loss")

    def test_the_regime_gate_orders_the_bars_correctly(self):
        """The regime gate is what the user's odd/even insight became.

        A strong favourite's XI IS the product, so it must take a BIGGER hit
        before the engine calls it damage; a big dog's XI is already written
        off, so a SMALLER one suffices. The ordering is the meaning; the exact
        numbers are calibration and are deliberately not pinned here.
        """
        self.assertGreater(si._DANGER_BAR["STRONG_FAVOURITE"],
                           si._DANGER_BAR["MID_FIELD"],
                           "a favourite must be harder to call damaged")
        self.assertLess(si._DANGER_BAR["BIG_DOG"],
                        si._DANGER_BAR["MID_FIELD"],
                        "a big dog must be easier to call damaged")
        self.assertGreater(si._DANGER_BAR["BIG_DOG"], 0.0,
                           "the bar must stay positive, or every "
                           "fixture is 'damaged'")

    def test_unknown_keeper_is_unknown_not_guilty(self):
        """A debutant is unproven, not proven poor.

        The old code returned (85.0, True, "DEBUT/UNKNOWN GK (Max Risk)")
        purely because it could not find a starting keeper, and 26% of
        cached keepers have under three appearances.
        """
        out = si.assess_goalkeeper(None, None, regime="MID_FIELD")
        self.assertEqual(out["label"], si.STATE_UNKNOWN)
        self.assertFalse(out["liability"])

    def test_an_unnamed_keeper_still_matters_to_a_strong_favourite(self):
        out = si.assess_goalkeeper(None, None, regime="STRONG_FAVOURITE")
        self.assertEqual(out["label"], si.STATE_DANGER)
        self.assertTrue(out["liability"])

    def test_a_debutant_keeper_is_unknown_even_with_a_proven_benchmark(self):
        out = si.assess_goalkeeper(
            {"apps": 1, "avg_rating": 6.5, "mins": 90},
            {"apps": 20, "avg_rating": 7.2}, regime="MID_FIELD")
        self.assertEqual(out["label"], si.STATE_UNKNOWN)

    def test_a_proven_keeper_downgrade_is_damage(self):
        out = si.assess_goalkeeper(
            {"apps": 20, "avg_rating": 6.4, "mins": 1800},
            {"apps": 22, "avg_rating": 7.3}, regime="MID_FIELD")
        self.assertEqual(out["label"], si.STATE_DANGER)
        self.assertTrue(out["liability"])

    def test_regime_needs_odds_and_degrades_to_mid_field_without_them(self):
        self.assertEqual(si.regime_for_odds(1.25), "STRONG_FAVOURITE")
        self.assertEqual(si.regime_for_odds(3.10), "BIG_DOG")
        for missing in (None, 0, -1, "x"):
            self.assertEqual(si.regime_for_odds(missing), "MID_FIELD")


# ══════════════════════════════════════════════════════════════════════
# CODE 5 COHERENCE (2026-09-28)
# ══════════════════════════════════════════════════════════════════════
# Seven independent if/elif ladders asserted impossible combinations in
# the same row: `Over2.5 = Weak` beside `Over1.5 = Excellent` in 8 of 12
# live rows. These pin the single-scale + coherence-pass replacement.


def _chem_fixture(chem):
    """Minimal danger card for the aggregator."""
    def side(net, verdict="ROTATION"):
        return {"id": 1, "team_name": "T", "status": "OK",
                "data_available": True, "breach": False,
                "style": {"label": "Attacking", "score": 4.0, "da": 40.0,
                          "available": True},
                "formation": "4-3-3", "net_impact": net, "verdict": verdict}
    return {"fixture": "A vs B", "fixture_id": "1",
            "style_alignment": "🔥 OPEN",
            "home_team": side(0.0), "away_team": side(0.0),
            "_chem_override": chem}


class AggregatorCoherenceTests(unittest.TestCase):
    """Nested markets must stay ordered after the repairs run."""

    def _run(self, home_net, away_net, align="🔥 OPEN", picks=None):
        report = []
        card = {
            "fixture": "A vs B", "fixture_id": "1",
            "style_alignment": align,
            "home_team": {"id": 1, "team_name": "A", "danger_level": "OK",
                          "data_available": True, "breach": False,
                          "style": {"label": "Attacking", "score": 4.0,
                                    "da": 40.0, "available": True},
                          "formation": "4-3-3", "net_impact": home_net,
                          "verdict": "ROTATION"},
            "away_team": {"id": 2, "team_name": "B", "danger_level": "OK",
                          "data_available": True, "breach": False,
                          "style": {"label": "Attacking", "score": 4.0,
                                    "da": 40.0, "available": True},
                          "formation": "4-3-3", "net_impact": away_net,
                          "verdict": "ROTATION"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            inc = os.path.join(tmp, "incoming_predictions.json")
            drg = os.path.join(tmp, "danger_audit.json")
            out = os.path.join(tmp, "aggregator_report.json")
            with open(inc, "w", encoding="utf-8") as f:
                json.dump({"1": picks or []}, f)
            with open(drg, "w", encoding="utf-8") as f:
                json.dump([card], f)
            with patch.object(stage5, "DATA_DIR", tmp), \
                 patch.object(stage5, "INCOMING_PREDICTIONS_FILE", inc), \
                 patch.object(stage5, "DANGER_AUDIT_FILE", drg), \
                 patch.object(stage5, "AGGREGATOR_REPORT_FILE", out):
                report = stage5.run_master_aggregator()
        return report[0]

    def test_over_15_is_never_stronger_than_over_25(self):
        """2 goals cannot be a harder read than 3 goals."""
        for h, a in ((0.0, 0.0), (18.0, 18.0), (-20.0, -20.0),
                     (12.0, -14.0), (25.0, 25.0)):
            c = self._run(h, a)["match_chemistry_list"]
            self.assertLessEqual(
                _rank_of(c["Over1.5"]), _rank_of(c["Over2.5"]),
                f"Over1.5={c['Over1.5']} > Over2.5={c['Over2.5']} at ({h},{a})")

    def test_a_strong_btts_read_cannot_sit_beside_a_weak_goal_read(self):
        c = self._run(18.0, 18.0)["match_chemistry_list"]
        if _rank_of(c["Gg"]) >= _rank_of("Very Strong"):
            self.assertGreater(_rank_of(c["Over1.5"]), _rank_of("Weak"),
                               f"Gg={c['Gg']} but Over1.5={c['Over1.5']}")

    def test_over_25_and_under_35_are_not_both_excellent(self):
        c = self._run(18.0, 18.0)["match_chemistry_list"]
        self.assertFalse(
            _rank_of(c["Over2.5"]) >= _rank_of("Excellent")
            and _rank_of(c["Under3.5"]) >= _rank_of("Excellent"))

    def test_a_real_score_is_never_rendered_as_unavailable(self):
        """Regression: a negative Under score clamped to index 0, which is
        the literal label "Unavailable", so a real read displayed as a
        missing one."""
        c = self._run(25.0, 25.0)["match_chemistry_list"]
        for market, grade in c.items():
            self.assertNotEqual(grade, "Unavailable",
                                f"{market} showed as Unavailable despite a "
                                f"computed score")

    def _openness_card(self, openness, home_net=0.0, away_net=0.0,
                       align="🔥 OPEN", da=40.0):
        """A minimal Stage 4 card with a continuous openness score."""
        def side(tid, name, net):
            return {"id": tid, "team_name": name, "danger_level": "OK",
                    "data_available": True, "breach": False,
                    "style": {"label": "Attacking", "score": 4.0,
                              "da": da, "available": da is not None},
                    "formation": "4-3-3", "net_impact": net,
                    "verdict": "ROTATION"}
        return {"fixture": "A vs B", "fixture_id": "1",
                "style_alignment": align, "openness_score": openness,
                "home_team": side(1, "A", home_net),
                "away_team": side(2, "B", away_net)}

    def _grade_with(self, card):
        with tempfile.TemporaryDirectory() as tmp:
            inc = os.path.join(tmp, "incoming_predictions.json")
            drg = os.path.join(tmp, "danger_audit.json")
            out = os.path.join(tmp, "aggregator_report.json")
            with open(inc, "w", encoding="utf-8") as f:
                json.dump({"1": []}, f)
            with open(drg, "w", encoding="utf-8") as f:
                json.dump([card], f)
            with patch.object(stage5, "DATA_DIR", tmp), \
                 patch.object(stage5, "INCOMING_PREDICTIONS_FILE", inc), \
                 patch.object(stage5, "DANGER_AUDIT_FILE", drg), \
                 patch.object(stage5, "AGGREGATOR_REPORT_FILE", out):
                return stage5.run_master_aggregator()[0]["match_chemistry_list"]

    def test_the_goal_markets_actually_vary_between_fixtures(self):
        """
        THE DEFINING FAILURE THIS FIX EXISTS TO REMOVE.

        Every goal, BTTS and corner grade used to be a near-constant function of
        a single boolean (`both sides' Dangerous Attacks > 35`), which read OPEN
        on 12 of 16 live fixtures. Seven confident market words were derived
        from one bit and the board barely moved.

        Over1.5 and Over2.5 are the SAME event at two thresholds and are clamped
        to each other by design — that invariant is enforced separately — so the
        variation that matters is BETWEEN fixtures, not between those two
        markets. A continuous openness score has to make the board move.
        """
        low = self._grade_with(self._openness_card(0.20))
        high = self._grade_with(self._openness_card(0.80))
        differing = [m for m in ("Over2.5", "Gg", "Corner")
                     if _rank_of(high[m]) != _rank_of(low[m])]
        self.assertTrue(
            differing,
            "an 0.80-openness fixture graded identically to a 0.20 one on every "
            "goal market — the single-bit failure is back")

    def test_over_15_never_outranks_over_25_and_they_move_together(self):
        """
        Over 1.5 (2 goals) and Over 2.5 (3 goals) describe the same event, and
        3 goals is the harder read, so the harder market binds. They are
        clamped together deliberately; a divergence between them would mean the
        engine was claiming 2 goals is a stronger read than 3.
        """
        for openness in (0.2, 0.5, 0.8):
            c = self._grade_with(self._openness_card(openness))
            self.assertLessEqual(
                _rank_of(c["Over1.5"]), _rank_of(c["Over2.5"]),
                f"at openness {openness}: Over1.5={c['Over1.5']} outranks "
                f"Over2.5={c['Over2.5']}")

    def test_the_goal_ladder_is_not_one_number_in_three_disguises(self):
        """
        REGRESSION GUARD for the collapse that shipped briefly.

        `Over1.5` was written as `Over2.5 - 0.0`, and Under 3.5 is its mirror
        (`6.0 - Over1.5`), so all three goal markets were locked to a single
        value. The live board showed Over2.5, Over1.5 and Under3.5 identical on
        25 of 25 fixtures — the same "one number, seven labels" defect as the
        original single boolean, moved one layer down where the tests above
        could not see it.

        The root cause was the openness COEFFICIENT, not the gap between the
        markets. `openness_score` spans only 0.363..0.678 on the live board, so
        at a coefficient of 2.0 the entire distribution fitted inside one
        rounding bucket and the board could not move a grade at all.

        The property to hold is that the goal ladder RESPONDS to a real change
        in attacking quality across the range the engine actually produces.
        """
        grades = []
        for openness in (0.363, 0.45, 0.55, 0.678):
            c = self._grade_with(self._openness_card(openness))
            grades.append(c["Over2.5"])
        self.assertGreater(
            len(set(grades)), 1,
            f"Over2.5 was {grades[0]} at every openness across the real range "
            "— the goal ladder is frozen again")

    def test_over_15_never_reads_stronger_than_over_25(self):
        """
        2 goals is an easier read than 3 goals, so Over 1.5 must never be graded
        stronger than Over 2.5. This holds at every openness, including where the
        BTTS cross-check legitimately separates the 0-3 goal event.
        """
        for openness in (0.25, 0.363, 0.45, 0.55, 0.678, 0.80):
            c = self._grade_with(self._openness_card(openness))
            self.assertLessEqual(
                _rank_of(c["Over1.5"]), _rank_of(c["Over2.5"]),
                f"at openness {openness}: Over1.5={c['Over1.5']} outranks "
                f"Over2.5={c['Over2.5']}")

    def test_a_full_strength_fixture_does_not_read_as_a_goal_market(self):
        """
        A rotation-only fixture (no absence on either side) must not produce a
        confident directional goal read. net_impact is 0 for a full-strength XI,
        so the damage term is neutral and the goal markets have nothing to move
        on — the only honest grade is a neutral one.
        """
        c = self._run(0.0, 0.0)["match_chemistry_list"]
        for market in ("Over2.5", "Under3.5"):
            self.assertLessEqual(
                _rank_of(c[market]), _rank_of("Strong"),
                f"{market}={c[market]} claims a directional read from a "
                "fixture with no absence on either side")

    def test_a_stronger_attack_pair_must_move_the_goal_markets_upward(self):
        """
        The continuous openness score has to actually ORDER fixtures. Under the
        old boolean an attacking pair and a defensive pair graded identically.
        """
        attacking = self._grade_with(self._openness_card(0.80))
        defensive = self._grade_with(self._openness_card(0.20))
        for market in ("Over2.5", "Gg"):
            self.assertGreater(
                _rank_of(attacking[market]), _rank_of(defensive[market]),
                f"{market}: an 0.80-openness pair must grade above a 0.20 one "
                f"(got {attacking[market]} vs {defensive[market]})")

    def test_missing_attack_signal_blanks_goal_markets_but_not_win_markets(self):
        """
        No attack signal means no honest goal read. The Win markets read the
        signed squad damage instead, so they stay gradeable — blanking those
        would discard a genuinely independent piece of evidence.
        """
        c = self._grade_with(self._openness_card(None, home_net=14.0,
                                                align="⚠️ UNAVAILABLE", da=None))
        for market in ("Over2.5", "Over1.5", "Under3.5", "Gg", "Corner"):
            self.assertEqual(c[market], "Unavailable",
                             f"{market} claimed a read with no attack signal")
        for market in ("Home Win", "Away Win"):
            self.assertNotEqual(c[market], "Unavailable",
                                f"{market} should still be gradeable from "
                                "the signed damage term")

    def test_the_handshake_actually_reconciles_the_two_inputs(self):
        """It used to copy the picks through and read none of them."""
        row = self._run(20.0, -20.0, picks=[{
            "type": "TO_SCORE", "target_loc": "home",
            "target_name": "A", "reason": "r"}])
        hs = row["handshake"]
        self.assertIsNotNone(hs)
        self.assertIn(hs["status"], ("AGREES", "CORROBORATED",
                                     "CONFLICT", "NO_OVERLAP"))
        # A pick naming the home side must be mapped onto the Home Win market.
        self.assertTrue(any(d["market"] == "Home Win" for d in hs["detail"]))

    def test_hyphenated_club_names_do_not_collide(self):
        """`Al-Hilal vs Al-Ittihad` and `Al Hilal vs Al Ittihad` are the same
        fixture, but they must not collide with a THIRD pairing."""
        a = stage5.get_match_key("Al-Hilal vs Al-Ittihad")
        b = stage5.get_match_key("Al Hilal vs Al Ittihad")
        c = stage5.get_match_key("Al-Ahli vs Al-Hilal")
        self.assertEqual(a, b, "the two spellings should agree")
        self.assertNotEqual(a, c, "a different pairing must stay different")


def _rank_of(grade):
    return {"Unavailable": 0, "Very Weak": 1, "Weak": 2, "Balanced": 3,
            "Strong": 4, "Very Strong": 5, "Excellent": 6, "Elite": 7}.get(
        grade, 0)



# ══════════════════════════════════════════════════════════════════════
# QUOTA / FEED-SAFETY HOTFIX (2026-09-28)
# ══════════════════════════════════════════════════════════════════════
# The signed-metric work added `_favourite_odds` to Stage 4, called once per
# fixture per cycle. Measured consequence on the live account: rate-limit
# errors went from 0 to 11, cycle time from ~40s to ~220s, all three feeds
# emptied, and the alert pipeline went silent because Stage 6 had no picks.
# These pin the two guards that make that unrepeatable.


class QuotaGuardContractTests(unittest.TestCase):
    """The regime lookup must cost a provider call only when it can matter."""

    def test_a_decisive_verdict_does_not_pay_for_odds(self):
        """Far from every bar, all three regimes agree — so no call."""
        self.assertFalse(stage4._regime_needed([25.0], [0.8]))
        self.assertFalse(stage4._regime_needed([-30.0], [0.8]))

    def test_a_verdict_on_a_bar_does_pay_for_odds(self):
        """Within range of a bar, the band is the only thing that can tip it."""
        self.assertTrue(stage4._regime_needed([6.0], [0.8]))

    def test_thin_evidence_never_pays_for_odds(self):
        """A 2-appearance sample cannot change a label, so it must not cost."""
        self.assertFalse(stage4._regime_needed([20.0], [0.1]))
        self.assertFalse(stage4._regime_needed([None], [0.8]))

    def test_nobody_absent_never_pays_for_odds(self):
        self.assertFalse(stage4._regime_needed([0.0], [0.8]))

    def test_odds_are_memoised_per_fixture(self):
        """The scanner re-reads the same fixtures every cycle; an unmemoised
        call is pure waste. A miss must be memoised too."""
        calls = []

        def _fake(fid):
            calls.append(fid)
            # 7 is priced; 8 has no market from the provider.
            return 1.30 if fid == 7 else None

        stage4._ODDS_MEMO.clear()
        original = stage4._favourite_odds
        stage4._favourite_odds = _fake
        try:
            self.assertEqual(stage4._favourite_odds_cached(7), 1.30)
            self.assertEqual(stage4._favourite_odds_cached(7), 1.30)
            self.assertEqual(len(calls), 1, "second read must not re-call")
            # A provider that has no market must not be asked again either:
            # a miss costs the same as a hit and returns the same nothing.
            self.assertIsNone(stage4._favourite_odds_cached(8))
            self.assertIsNone(stage4._favourite_odds_cached(8))
            self.assertEqual(len(calls), 2, "one call per fixture, misses too")
        finally:
            stage4._favourite_odds = original
            stage4._ODDS_MEMO.clear()

    def test_history_cache_budget_is_bounded(self):
        """500MB was sized for a cold cache and burst the quota on deploy."""
        self.assertLessEqual(
            stage4.HISTORY_CACHE_MAX_BYTES, 150 * 1024 * 1024,
            "history cache budget must stay well inside the quota budget")


class FeedGuardContractTests(unittest.TestCase):
    """A FAILED acquisition must never be able to blank a feed.

    The old guard protected a feed only when it already held something. A
    429 storm emptied it on one cycle, and on the next cycle there was
    "nothing to preserve", so the empty result was written again — the board
    showed zero fixtures with no error, and push went quiet while the scanner
    reported success.
    """

    def _feed(self, tmp, payload):
        path = os.path.join(tmp, "feed.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        return path

    def test_a_failed_acquisition_never_overwrites_a_good_feed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._feed(tmp, [{"id": "1"}])
            outcome = live_cache.write_feed(path, [], acquisition_ok=False,
                                            label="t")
            self.assertEqual(outcome, "preserved")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(len(json.load(f)), 1)

    def test_a_failed_acquisition_writes_nothing_when_no_feed_exists(self):
        """The regression: this case used to write empty."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "feed.json")
            outcome = live_cache.write_feed(path, [], acquisition_ok=False,
                                            label="t")
            self.assertEqual(outcome, "preserved")
            self.assertFalse(
                os.path.exists(path),
                "a failure must not create an empty feed indistinguishable "
                "from 'no matches today'")

    def test_a_successful_empty_acquisition_is_still_written(self):
        """A genuinely empty day is real data and must not be suppressed."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._feed(tmp, [{"id": "1"}])
            outcome = live_cache.write_feed(path, [], acquisition_ok=True,
                                            label="t")
            self.assertEqual(outcome, "written")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f), [])

    def test_a_successful_populated_acquisition_still_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "feed.json")
            self.assertEqual(
                live_cache.write_feed(path, [{"id": "1"}], acquisition_ok=True,
                                      label="t"),
                "written")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(len(json.load(f)), 1)


class ConcurrentWriteRaceTests(unittest.TestCase):
    """Two API workers must not race on a shared temp filename.

    The in-play cache used a fixed "<file>.tmp". Worker A renamed it into
    place, then worker B's os.replace() raised FileNotFoundError and the API
    served a STALE cache — which is why live statistics lagged. The temp name
    is now per-PID.
    """

    def test_the_in_play_cache_temp_name_is_per_process(self):
        import live_cache as lc
        self.assertIn(str(os.getpid()),
                      _extract_tmp_expr(lc.LIVE_CACHE_FILE),
                      "temp name must be unique per worker to avoid the race")


def _extract_tmp_expr(target: str) -> str:
    """Best-effort: confirm the writer no longer uses the fixed '.tmp' form."""
    import inspect
    import live_cache as lc
    src = inspect.getsource(lc)
    # The vulnerable form is `TARGET + ".tmp"` with no PID interpolation.
    assert f'{target} + ".tmp"' not in src, \
        f"fixed shared temp name still present for {target}"
    return str(os.getpid())




# ══════════════════════════════════════════════════════════════════════
# STORM ATTRIBUTION (2026-09-29)
# ══════════════════════════════════════════════════════════════════════
# The storm gates have always computed h_triple / a_triple (one squad's
# average pre-match doom rating at least double the other's) and used them only
# as a bare boolean. An alert therefore said a storm was happening and gave
# both xG figures, but never named the side responsible — the reader had to
# eyeball which xG was higher to learn the one thing that makes the alert
# actionable.
#
# These pin the naming. The gates' structural test, confidence bars and
# one-shot keys are deliberately untouched, so nothing here may relax them.


class StormAttributionTests(unittest.TestCase):
    """`storm_side` must name a driver only when one is identifiable."""

    def test_home_side_is_named_by_its_actual_team_name(self):
        label, short = stage6.storm_side(
            {"h_triple": True, "a_triple": False},
            "Georgia", "Ukraine")
        self.assertEqual(short, "home")
        self.assertEqual(label, "Georgia")

    def test_away_side_is_named_by_its_actual_team_name(self):
        label, short = stage6.storm_side(
            {"h_triple": False, "a_triple": True},
            "Georgia", "Ukraine")
        self.assertEqual(short, "away")
        self.assertEqual(label, "Ukraine")

    def test_both_sides_is_reported_as_both_not_arbitrarily_picked(self):
        """A storm is real but the driver is not identifiable."""
        label, short = stage6.storm_side(
            {"h_triple": True, "a_triple": True}, "A", "B")
        self.assertEqual(short, "both")
        self.assertIn("both", label.lower())

    def test_neither_side_never_invents_a_culprit(self):
        """Silence is correct. Naming a driver with no evidence is not."""
        for struct in ({"h_triple": False, "a_triple": False}, {}, None):
            label, short = stage6.storm_side(struct, "A", "B")
            self.assertIsNone(label)
            self.assertIsNone(short)

    def test_missing_names_fall_back_to_home_and_away_labels(self):
        """A name that will not split must still yield WHICH SIDE."""
        label, short = stage6.storm_side(
            {"h_triple": True, "a_triple": False}, None, None)
        self.assertEqual(short, "home")
        self.assertEqual(label, "Home")

    def test_fixture_name_splitting(self):
        self.assertEqual(
            stage6._split_fixture_name("Georgia vs Ukraine"),
            ("Georgia", "Ukraine"))
        # Unparseable input must degrade, never raise — this runs inside the
        # alert path where a format assumption must not become a crash.
        self.assertEqual(stage6._split_fixture_name("Something Odd"), (None, None))
        self.assertEqual(stage6._split_fixture_name(None), (None, None))
        self.assertEqual(stage6._split_fixture_name(""), (None, None))

    def test_the_storm_gates_are_not_loosened_by_this_change(self):
        """The naming is additive. A storm still needs the same conditions."""
        # Same windows and same escalating confidence bar as before.
        self.assertEqual(
            [g[0] for g in stage6.STORM_GATES],
            ["SUPREME_45", "SUPREME_60", "SUPREME_75"])
        # The late gate still demands MORE confidence than the early ones, so
        # precision rises as the window widens rather than falling.
        self.assertGreaterEqual(
            stage6.STORM_GATES[2][3], stage6.STORM_GATES[0][3])
        # A storm is still NOT alertable through STORM_STATE alone. The
        # guarantee lives on the tracker METHOD, not at module level.
        tracker = stage6.SupremeOrchestrator.update_storm_state
        self.assertIn("NEVER alertable", tracker.__doc__ or "")


class TestChemistryVocabularyContract(unittest.TestCase):
    """
    The engine's chemistry scale and the rules' accepted levels must be the
    same set, or alerts die silently.

    A user rule matches chemistry with an exact, case-insensitive string
    compare in user_rules_store:

        actual = str(chem.get(market, "")).strip().lower()
        met = actual == level

    So a level the engine emits that is absent from
    VALID_CHEMISTRY_LEVELS can never be matched by any rule. Nothing raises:
    the matcher returns False, the rule reports a red cross, and the alert
    simply never fires while the page still shows the fixture normally.

    This is not hypothetical. The 2026-09-28 coherence rewrite added a
    "Balanced" tier to the engine's STRENGTH scale. It was never added to
    VALID_CHEMISTRY_LEVELS, and because it sat in the middle of the scale it
    became the grade most likely to land on an ordinary match -- silently
    muting chemistry rules for a full day before it was noticed.

    These tests assert the two sets agree in BOTH directions, so neither side
    can be changed alone. Removing a level from one file now fails here rather
    than in production.
    """

    def _emitted_levels(self):
        """
        Pull the live STRENGTH scale out of the aggregator source.

        Read from source rather than importing-and-calling: the scale is a
        local inside the chemistry routine, so the source text is the only
        non-invasive way to see it. Asserting on the literal list would let the
        two drift apart again the moment a real fixture is built.
        """
        import re
        from pathlib import Path

        src = (Path(stage5.__file__).parent /
               "live_stage5_aggregator.py").read_text()
        match = re.search(r"STRENGTH\s*=\s*\[(.*?)\]", src, re.S)
        self.assertIsNotNone(
            match, "STRENGTH scale not found in live_stage5_aggregator.py")
        body = match.group(1)
        return {s.strip().strip("\"'") for s in body.split(",")
                if s.strip().strip("\"'")}

    def test_every_emitted_level_is_matchable_by_a_rule(self):
        """No engine output may fall outside the rules vocabulary."""
        emitted = self._emitted_levels()
        accepted = rules.VALID_CHEMISTRY_LEVELS
        orphans = {lv for lv in emitted if lv.lower() not in accepted}
        self.assertEqual(
            orphans, set(),
            "Engine emits chemistry level(s) no rule can match: "
            f"{sorted(orphans)}. Rules accept {sorted(accepted)}. "
            "Add the level to VALID_CHEMISTRY_LEVELS, or remove it from "
            "the engine's STRENGTH scale.")

    def test_every_accepted_level_is_actually_emittable(self):
        """No selectable level may be dead on arrival."""
        emitted = self._emitted_levels()
        dead = {lv for lv in rules.VALID_CHEMISTRY_LEVELS
                if lv not in {e.lower() for e in emitted}}
        self.assertEqual(
            dead, set(),
            f"Rules accept level(s) the engine can never produce: {sorted(dead)}. "
            "These would be selectable in the UI but could never match, which "
            "reads to the user as a rule that silently does nothing.")

    def test_balanced_is_not_reintroduced_without_the_rules(self):
        """
        Pin the specific regression.

        Named explicitly so that re-adding a middle tier is a deliberate act
        that trips a test with the full explanation attached, rather than a
        plausible-looking edit that quietly breaks alerts.
        """
        self.assertNotIn(
            "Balanced", self._emitted_levels(),
            "STRENGTH must not contain 'Balanced'. It sat mid-scale, so it "
            "was the most likely grade on a normal match and it muted every "
            "chemistry rule that expected 'Weak', 'Strong' or 'Excellent'.")
        self.assertNotIn(
            "balanced", rules.VALID_CHEMISTRY_LEVELS,
            "'balanced' must stay out of the rules vocabulary until the "
            "engine is deliberately changed to emit it.")

    def test_full_vocabulary_is_preserved(self):
        """
        The pre-rewrite vocabulary, restored verbatim.

        Removing 'Balanced' fixes the contract; this guards against a future
        edit quietly narrowing the range a user can select, which would be a
        regression just as silent as adding one.
        """
        self.assertEqual(
            self._emitted_levels(),
            {"Unavailable", "Very Weak", "Weak",
             "Strong", "Very Strong", "Excellent", "Elite"})



class TestWeeklyOver25GoalFormStats(unittest.TestCase):
    """
    The four per-side goal figures must survive engine -> CSV -> filter -> API.

    2026-09-29. Engine/over25_forecast.py already computed goals scored and
    conceded for BOTH sides (get_complex_metrics returns {"gs", "gc", ...} per
    side, and both h_m and a_m feed the Poisson lambda and parity_diff), but
    the row written to master_over_stage2_{date}.csv carried only the COMBINED
    total as combined_gs_last_5. The four per-side numbers existed in memory
    and were discarded at save time, so the Weekly board could not show them.

    These tests pin the whole path. The engine is exercised through a stub
    rather than a live run: it makes real provider API calls, and a
    regression test must never depend on the network or on there being
    fixtures on a given date.
    """

    GOAL_FORM_COLUMNS = (
        "home_goals_scored_last_5",
        "away_goals_scored_last_5",
        "home_goals_conceded_last_5",
        "away_goals_conceded_last_5",
    )

    def _engine_source(self):
        from pathlib import Path
        return (Path(__file__).parent /
                "Engine" / "over25_forecast.py").read_text()

    def test_engine_writes_all_four_columns(self):
        """The row dict must carry each per-side figure explicitly."""
        src = self._engine_source()
        for col in self.GOAL_FORM_COLUMNS:
            self.assertIn(
                f'"{col}"', src,
                f"{col} is not written by over25_forecast.py. These values are "
                "already computed as h_m['gs']/h_m['gc'] and a_m['gs']/a_m['gc'] "
                "— omitting one from the row silently drops data the engine "
                "has in hand.")

    def test_columns_are_derived_from_the_computed_sides(self):
        """
        Each column must come from the correct side's metrics.

        A copy-paste slip here (home_gs written from a_m) would be invisible on
        the page — both are plain integers — and would invert the one
        comparison the user makes: which side scores more and which concedes
        more. Assert the exact expression per column.
        """
        src = self._engine_source()
        expected = {
            "home_goals_scored_last_5": 'h_m["gs"]',
            "away_goals_scored_last_5": 'a_m["gs"]',
            "home_goals_conceded_last_5": 'h_m["gc"]',
            "away_goals_conceded_last_5": 'a_m["gc"]',
        }
        for col, expr in expected.items():
            self.assertIn(
                f'"{col}": int({expr})', src,
                f"{col} must be written as int({expr}). Check the side is not "
                "swapped — a home/away mix-up cannot be detected downstream.")

    def test_combined_total_still_agrees_with_the_two_sides(self):
        """
        combined_gs_last_5 must remain the sum of the two scored figures.

        It is pre-existing behaviour the filter reads, and it is now
        derivable from the new columns. If the two ever disagree, one of them
        is wrong and the Poisson maths no longer matches what is displayed.
        """
        src = self._engine_source()
        self.assertIn(
            '"combined_gs_last_5": h_m["gs"] + a_m["gs"]', src,
            "combined_gs_last_5 must stay the sum of both sides' goals scored, "
            "so it cannot drift from the two new per-side columns.")

    def test_filter_forwards_the_columns_unchanged(self):
        """
        The O2.5 filter must not drop or alter them.

        The filter forwards rows via to_dict() and only drops its own two
        derived helpers (poisson_num, votes_num), so the new columns reach the
        cache JSON untouched. Asserted against the real filter with a
        synthetic row, in a temp dir, so no artefact is written.
        """
        import tempfile
        import pandas as pd
        import FILTER.over25_risk_filter as filt

        row = {
            "fixture_id": "1", "league": "L", "fixture": "A vs B",
            "o25_odds": 1.70, "kill_switch_pass": True,
            "poisson_over_prob_num": 72.0, "council_votes": "7/9",
            "pos_gap": 5, "parity_diff": 3, "h2h_overs_last_5": 4,
            "combined_gs_last_5": 15,
            "home_goals_scored_last_5": 8, "away_goals_scored_last_5": 7,
            "home_goals_conceded_last_5": 6, "away_goals_conceded_last_5": 9,
        }
        for col, val in ((c, row[c]) for c in self.GOAL_FORM_COLUMNS):
            self.assertIsInstance(val, int)

        tmp = tempfile.mkdtemp()
        original_out, original_date = filt.OUTPUT_DIR, filt.__dict__.get("TARGET_DATE")
        try:
            filt.OUTPUT_DIR = tmp
            pd.DataFrame([row]).to_csv(
                os.path.join(tmp, "master_over_stage2_2099-01-01.csv"), index=False)
            out = filt.run_over25_filter_aggregator(
                "2099-01-01", mode="public", risk_level="banker", persist=True)
        finally:
            filt.OUTPUT_DIR = original_out
            if original_date is not None:
                filt.__dict__["TARGET_DATE"] = original_date

        self.assertTrue(out, "synthetic row did not survive the filter")
        for col in self.GOAL_FORM_COLUMNS:
            self.assertIn(col, out[0],
                          f"{col} was dropped between the engine and the cache")
            self.assertEqual(out[0][col], row[col],
                             f"{col} was altered by the filter")

    def test_frontend_renders_all_four(self):
        """
        Both Weekly views must show the four figures.

        Cards and table are separate code paths; wiring only one leaves the
        figures invisible in the other view. The component is shared, so
        asserting on the shared name plus the absence of a per-view duplicate
        is enough to catch a regression that splits them apart.
        """
        from pathlib import Path
        tsx = (Path(__file__).parent / "alienedge-frontend" / "app" /
               "weekly" / "FilterTab.tsx").read_text()

        self.assertIn("function GoalFormStats", tsx,
                      "the shared GoalFormStats component is gone")
        # 2026-09-30: the L5/L3 toggle is GONE. Recent goal form is now four
        # real gates in the thresholds drawer, so the board no longer reads a
        # window-keyed column. The card readout is retained and pinned to the
        # 5-window, which is the window the engine's lambda and the gates use.
        for stem in ("home_goals_scored_last_", "away_goals_scored_last_",
                     "home_goals_conceded_last_", "away_goals_conceded_last_"):
            self.assertIn(
                f"row[`{stem}${{window}}`]", tsx,
                f"the board must still read {stem}<window>")
        self.assertNotIn(
            "setFormWindow", tsx,
            "the display-only L5/L3 toggle must not come back: no gate read "
            "the 3-window, so it was not a filter. Recent form is expressed "
            "as min_home_goals / min_away_goals / max_home_conceded / "
            "max_away_conceded in the thresholds drawer instead.")
        # The readout is pinned to the 5-window in both views.
        self.assertEqual(
            tsx.count("<GoalFormStats row={row} window={FORM_WINDOW} />"), 2,
            "GoalFormStats must be rendered in BOTH the cards view and the "
            "table view, exactly once each, both pinned to the 5-window.")


class TestSecondChanceFilterExemption(unittest.TestCase):
    """
    A filter returning zero rows is a correct answer, not a starved engine.

    2026-09-29. The 06:00 second-chance pass re-ran
    `filter_over25__banker` for 2026-09-29 every morning, forever. The reason
    was _needs_second_chance treating `status == "ok" and row_count == 0` as
    stale for EVERY key -- but a filter's purpose is to remove rows, so []
    means "no fixture met the conjunction", which is a complete answer.

    Verified against the real data: master_over_stage2_2026-09-29.csv holds 54
    fixtures, and banker (kill_switch AND pos_gap<=6 AND votes>=7 AND
    poisson>=70) legitimately keeps none. Only 2 of 54 reach poisson>=70 and
    neither has kill_switch_pass set. The empty result was right; the retry
    loop was the bug.
    """

    def _needs(self, key, status, row_count):
        import main as main_mod
        with patch.object(main_mod.store, "load_status",
                          return_value={"status": status, "row_count": row_count}):
            return main_mod._needs_second_chance(key, "2026-09-29")

    def test_empty_filter_is_not_retried(self):
        """The regression: a correct empty filter must not be re-run daily."""
        for key in ("filter_over25__banker", "filter_over25__balanced",
                    "filter_over25__aggressive", "filter_win__safe",
                    "filter_win__balanced", "filter_win__aggressive"):
            self.assertFalse(
                self._needs(key, "ok", 0),
                f"{key} returned a legitimate empty result but is still "
                "treated as stale, so the 06:00 pass re-runs it every day "
                "for every date with no qualifying picks.")

    def test_empty_fhvi_is_not_retried(self):
        """fhvi is a filter and is exempt for the same reason."""
        self.assertFalse(self._needs("fhvi", "ok", 0))

    def test_populated_filter_is_not_retried(self):
        """A filter that DID produce rows was never stale either."""
        self.assertFalse(self._needs("filter_over25__banker", "ok", 12))

    def test_empty_ENGINE_is_still_retried(self):
        """
        The exemption must not weaken the safety net for real engines.

        An engine producing zero rows IS starved -- it means the provider
        returned nothing -- and must be re-run. This is the guard against the
        fix being too broad.
        """
        for key in ("over25_forecast", "over25_stage2", "gg_o15",
                    "sh_gg_winner", "dna_v2"):
            self.assertTrue(
                self._needs(key, "ok", 0),
                f"{key} produced 0 rows and must be retried -- an engine "
                "returning nothing is starvation, not a verdict.")

    def test_failed_filter_is_still_retried(self):
        """
        The exemption applies ONLY to a healthy-but-empty filter.

        A filter that failed or degraded has a real problem and must be
        re-run, exactly as before. Otherwise the fix would permanently
        suppress recovery from a genuine filter failure.
        """
        for status in ("failed", "degraded", "missing", "unreadable"):
            self.assertTrue(
                self._needs("filter_over25__banker", status, 0),
                f"a '{status}' filter must still be retried; the exemption "
                "is only for a healthy empty result.")
            self.assertTrue(
                self._needs("filter_over25__banker", status, 8),
                f"a '{status}' filter must still be retried regardless of "
                "row count.")

    def test_a_starved_filter_is_still_caught_at_the_engine_layer(self):
        """
        A filter whose DATED INPUT is missing returns [] too -- so the
        exemption must not hide that case.

        The recovery still happens, one layer up: the engine that writes the
        filter's input (over25_forecast) is its own key in the second-chance
        list and is ordered BEFORE the filter, so a starved engine is retried
        first and the filter then runs against real input on the same pass.
        Assert that ordering, because it is the whole basis of the exemption.
        """
        import main as main_mod
        keys = [k for k, *_ in main_mod._second_chance_runners("2026-09-29")]
        self.assertIn("over25_forecast", keys,
                      "the engine feeding the O2.5 filter must be a "
                      "second-chance key, or a starved filter can never heal")
        self.assertIn("filter_over25__banker", keys)
        self.assertLess(
            keys.index("over25_forecast"), keys.index("filter_over25__banker"),
            "over25_forecast must run BEFORE filter_over25__banker so the "
            "filter sees the engine's fresh output on the same pass. With "
            "the filter first it would run against a missing input, return "
            "[] , and the exemption would then leave it empty for good.")


class TestWeeklyOver25FormWindowToggle(unittest.TestCase):
    """
    The 5/3 form toggle must be display-only and must not move any number.

    2026-09-29. get_complex_metrics had its window hardcoded in three places
    (history[:5], len(v_5) == 5, and the Poisson divisor /5). It is now a
    parameter defaulting to 5, and the engine evaluates the 3-window alongside
    it from the SAME history slice in the SAME provider call.

    The risk this guards is the obvious one: parameterising a window that
    feeds live maths is how a "display tweak" quietly becomes a change of
    recommendation. The 3-window figures must never reach the Poisson lambda,
    the council votes, parity_diff, or any filter gate.
    """

    WINDOW_3_COLUMNS = (
        "home_goals_scored_last_3",
        "away_goals_scored_last_3",
        "home_goals_conceded_last_3",
        "away_goals_conceded_last_3",
    )

    def _engine_source(self):
        from pathlib import Path
        return (Path(__file__).parent /
                "Engine" / "over25_forecast.py").read_text()

    def test_window_defaults_to_five(self):
        """
        The default must remain 5, so every existing call site is unchanged.

        If the default drifted, the whole engine would silently start grading
        on 3 matches and every Poisson probability and vote would move.
        """
        src = self._engine_source()
        self.assertIn(
            "def get_complex_metrics(tid, history, venue, window=5):", src,
            "get_complex_metrics must keep window=5 as its default. The "
            "5-window is what every existing number was computed from.")

    def test_all_existing_call_sites_use_the_default(self):
        """
        The maths-feeding calls must NOT pass a window.

        h_m/a_m drive the Poisson lambda, parity_diff and all nine council
        votes. If either were given an explicit window, the toggle would
        start changing recommendations.
        """
        src = self._engine_source()
        for call in ('h_m = get_complex_metrics(hid, team_histories.get(hid, []), "home")',
                     'a_m = get_complex_metrics(aid, team_histories.get(aid, []), "away")'):
            self.assertIn(call, src, f"expected call site changed: {call}")
        # The 3-window gets its own variables and nothing else may consume them.
        for bad in ("h_m3[", "a_m3["):
            for line in src.splitlines():
                if bad in line and "int(" not in line and "get_complex_metrics" not in line:
                    self.fail(
                        f"{bad} is consumed outside the CSV write: {line.strip()}. "
                        "The 3-window is display-only and must not reach the "
                        "Poisson lambda, parity_diff or the council votes.")

    def test_poisson_divisor_is_still_five(self):
        """
        The Poisson lambda divides the window totals by the window size.

        It is a per-match average, so a 3-window total divided by 5 would
        understate the rate. Assert the divisor is still literally 5.
        """
        src = self._engine_source()
        self.assertIn(
            'lamb = ((h_m["gs"] + h_m["gc"]) / 5 + (a_m["gs"] + a_m["gc"]) / 5) / 2',
            src,
            "the Poisson lambda must still divide by 5 against the 5-window "
            "totals. Changing the divisor with the window would change every "
            "probability on the board.")

    def test_engine_writes_both_windows(self):
        src = self._engine_source()
        for col in self.WINDOW_3_COLUMNS:
            self.assertIn(f'"{col}"', src,
                          f"{col} is missing from the CSV write")
        self.assertIn('window=3', src,
                      "the engine must evaluate the 3-window explicitly")

    def test_3_window_is_bounded_by_the_5_window(self):
        """
        A 3-match total can never exceed the 5-match total it is a subset of.

        This is the arithmetic that makes the toggle trustworthy: if the two
        disagree in that direction, the "shorter" window is reading a
        different history than the longer one, which would mean the slices
        are not nested.
        """
        import pandas as pd
        from pathlib import Path
        csv = (Path(__file__).parent / "output" /
               "master_over_stage2_2026-10-05.csv")
        if not csv.exists():
            self.skipTest("dated O2.5 artefact not present")
        df = pd.read_csv(csv)
        for side in ("home_goals_scored", "away_goals_scored",
                     "home_goals_conceded", "away_goals_conceded"):
            long_, short = df[f"{side}_last_5"], df[f"{side}_last_3"]
            self.assertTrue(
                (short <= long_).all(),
                f"{side}: the 3-window total exceeds the 5-window total it is "
                "a subset of, so the two windows are not reading the same "
                "history.")

    def test_combined_total_still_uses_the_five_window(self):
        """
        combined_gs_last_5 is read by the aggressive filter gate, so it must
        remain the 5-window sum and must NOT be redefined as a 3-window total.
        """
        src = self._engine_source()
        self.assertIn('"combined_gs_last_5": h_m["gs"] + a_m["gs"]', src,
                      "combined_gs_last_5 must stay the 5-window sum; the "
                      "aggressive filter gate reads this exact column.")

    def test_no_filter_reads_the_3_window(self):
        """
        The O2.5 filter must not gate on any 3-window column.

        If it did, the toggle would stop being cosmetic and the "SURVIVED"
        count would change when the user flips it — the exact confusion the
        control's placement next to the results (not the filters) avoids.
        """
        from pathlib import Path
        filt = (Path(__file__).parent / "FILTER" /
                "over25_risk_filter.py").read_text()
        for col in self.WINDOW_3_COLUMNS:
            self.assertNotIn(col, filt,
                             f"{col} is read by the O2.5 filter, which would "
                             "make the form toggle change the pick set")

    def test_frontend_toggle_offers_both_and_labels_the_window(self):
        """
        The L5/L3 toggle is GONE. It was display-only, and a control sitting
        among the thresholds that changes nothing is worse than no control at
        all — it reads as a filter and is not one.

        What replaces it: four REAL gates in the drawer, and one odds box
        with no ceiling. Both are asserted here, because "boxes that reflect
        what the user wants as an active filter" is only true if the backend
        actually gates on them.
        """
        from pathlib import Path
        root = Path(__file__).parent
        tsx = (root / "alienedge-frontend" / "app" / "weekly" /
               "FilterTab.tsx").read_text()
        cfg = (root / "alienedge-frontend" / "app" / "weekly" /
               "filter-config.ts").read_text()
        filt = (root / "FILTER" / "over25_risk_filter.py").read_text()

        # The toggle is gone from the component.
        self.assertNotIn("useState<3 | 5>(5)", tsx,
                         "the L5/L3 form-window state must not come back")
        self.assertNotIn("setFormWindow", tsx,
                         "no control may reappear that changes no gate")

        # The four real gates are offered AND applied.
        for key in ("min_home_goals", "min_away_goals",
                    "max_home_conceded", "max_away_conceded"):
            self.assertIn(key, cfg,
                          f"{key} must be offered in the O2.5 drawer")
            self.assertIn(key, filt,
                          f"{key} must actually gate in the filter, not just "
                          "be offered")

        # ONE odds box: a floor with no ceiling.
        self.assertNotIn('{ key: "max_odds", label: "Max Odds"', cfg,
                         "the Max Odds box is gone — the drawer has one odds "
                         "box, a floor, and no ceiling")

    def test_new_gates_default_to_off(self):
        """
        Adding four gates must not move the shipped result set.

        The drawer defaults them to 0 and the filter SKIPS a 0 threshold
        entirely. If 0 were compared against instead, a team with no recorded
        goals would read as 0 and the result set would shift on a change that
        is meant to be inert until the user types.
        """
        from pathlib import Path
        filt = (Path(__file__).parent / "FILTER" /
                "over25_risk_filter.py").read_text()
        for key in ("min_home_goals", "min_away_goals",
                    "max_home_conceded", "max_away_conceded"):
            self.assertIn(f"{key}=0", filt,
                          f"{key} must default to 0, meaning OFF")
        self.assertIn("if not thr or col not in df_filtered.columns:", filt,
                      "a 0 threshold must SKIP the column, not compare it")

    def test_missing_goal_column_passes_rather_than_fails(self):
        """
        A dated artefact graded before the engine wrote these columns must
        not be filtered to nothing. Absence of evidence is not evidence
        against the pick, so an unknown value passes the gate.
        """
        from pathlib import Path
        filt = (Path(__file__).parent / "FILTER" /
                "over25_risk_filter.py").read_text()
        self.assertIn("cond = cond & (~known | ok)", filt,
                      "rows whose goal value is unknown must PASS the gate")
        self.assertIn("if not thr or col not in df_filtered.columns:", filt,
                      "an absent column must skip the gate entirely")

    def test_band_supplies_the_odds_ceiling_when_the_drawer_sets_none(self):
        """
        The drawer sends min_odds but no max_odds. The old guard required
        BOTH to be absent before the corridor applied, so the band's ceiling
        was never used and the filter's own 2.20 default silently won —
        which is why @1.30-1.60 did nothing.
        """
        from pathlib import Path
        live = (Path(__file__).parent / "api" /
                "weekly_filter_live.py").read_text()
        self.assertIn('if band_max is not None and "max_odds" not in overrides:',
                      live,
                      "the corridor's ceiling must apply whenever the drawer "
                      "set none, or @1.30-1.60 admits picks up to 2.20")
        # Scoped to the O2.5 block only. The WIN path legitimately keeps the
        # both-or-neither guard, because the WIN drawer still ships BOTH odds
        # boxes — only the O2.5 drawer became single-box.
        _o25 = live[live.index("def _live_o25("):live.index("def _live_o25(") + 2000]
        self.assertNotIn(
            'if "min_odds" not in overrides and "max_odds" not in overrides',
            _o25,
            "requiring BOTH to be absent is what made the corridor "
            "unreachable — the O2.5 drawer always sends min_odds")

class TestWeeklyDrawerControlsAreAllWired(unittest.TestCase):
    """
    A drawer box must either gate the fixture set, or say out loud that it
    cannot. It must never be a third thing.

    THE 2026-10-01 REPORT: the four O2.5 goal-form boxes rendered, accepted a
    number, and changed nothing. They were offered in filter-config.ts, clamped
    by o25_filter_params, and mapped in O25_TIPSTER_KWARGS — and absent from
    O25_NARROW. Public mode is the DEFAULT mode, and _live_o25's public branch
    is the only path that reaches narrow_rows, so in the mode a user lands in
    by default all four were silently discarded.

    Nothing in the suite connected "this key exists in the UI" to "this key
    reaches a filter", which is how a box ships that provably cannot work.
    These tests assert that link for every market, so the next drawer field
    added without a gate fails here instead of in production.
    """

    def _drawer(self):
        """{market: {"fields": [...], "publicUnsupported": [...]}} from the TS."""
        import re
        from pathlib import Path
        text = (Path(__file__).parent / "alienedge-frontend" / "app" / "weekly" /
                "filter-config.ts").read_text(encoding="utf-8")
        drawer = {}
        for name, block in re.findall(
                r"export const (\w+)_FILTER_CONFIG(.*?)\n\};", text, re.S):
            fields_m = re.search(r"fields:\s*\[(.*?)\n  \]", block, re.S)
            unsup_m = re.search(r"publicUnsupported:\s*\[(.*?)\n  \]", block, re.S)
            drawer[name] = {
                "fields": re.findall(r'key:\s*"([^"]+)"',
                                     fields_m.group(1) if fields_m else ""),
                "publicUnsupported": re.findall(r'key:\s*"([^"]+)"',
                                                unsup_m.group(1) if unsup_m else ""),
            }
        return drawer

    def test_every_drawer_box_reaches_a_gate_in_the_mode_it_is_offered_in(self):
        """
        THE ACTUAL BUG, and the precise shape of it.

        A key being wired in SOME mode is not enough. Public mode is the default
        and it runs a completely different dispatch, so each key must be
        reachable in BOTH modes independently:

          Public  -> WIN_NARROW / O25_NARROW, or declared publicUnsupported
          Tipster -> WIN_TIPSTER_KWARGS / O25_TIPSTER_KWARGS

        The four O2.5 goal-form keys were in O25_TIPSTER_KWARGS and not in
        O25_NARROW. An "is it wired anywhere?" assertion passes them happily —
        which is exactly why they shipped dead in the default mode.
        """
        from api import weekly_filter_live as wfl

        drawer = self._drawer()
        self.assertEqual(sorted(drawer), ["GG", "OVER25", "WIN"],
                         "all three Weekly drawer configs must be readable")

        # Keys _live_gg forwards by name, outside any lookup table. _live_gg has
        # no mode branch at all, so these hold in every mode.
        gg_explicit = {"max_parity", "strict_mode", "min_gg_odds", "max_gg_odds"}
        # filter-config.ts market name -> api market name
        api_market = {"GG": "gg", "OVER25": "o25", "WIN": "win"}

        for name, info in drawer.items():
            unsupported = set(info["publicUnsupported"])
            for key in info["fields"]:
                if name == "GG":
                    self.assertTrue(
                        key in gg_explicit or key in set(wfl.GG_CFG_KEYS),
                        f"GG drawer box '{key}' reaches no filter in any mode")
                    continue

                market = api_market[name]
                narrow = set(getattr(wfl, wfl.NARROW_SPEC[market]))
                tipster = set(getattr(wfl, wfl.TIPSTER_SPEC[market]))

                self.assertTrue(
                    key in narrow or key in unsupported,
                    f"{name}.{key} cannot be enforced in PUBLIC mode (the "
                    f"default): it is not in {wfl.NARROW_SPEC[market]} and not "
                    f"declared unsupported — it would render, accept a number, "
                    f"and change nothing")
                self.assertTrue(
                    key in tipster or key in unsupported,
                    f"{name}.{key} cannot be enforced in TIPSTER mode: it is "
                    f"not in {wfl.TIPSTER_SPEC[market]} and not declared "
                    f"unsupported")

    def test_a_key_wired_only_for_tipster_must_be_flagged_for_public(self):
        """
        The gap that bit: a key in O25_TIPSTER_KWARGS but not O25_NARROW works
        in Tipster mode and silently dies in the DEFAULT mode. Any such key must
        be listed in publicUnsupported with a reason, or be added to the narrow
        spec — one of the two, never neither.
        """
        from api import weekly_filter_live as wfl

        drawer = self._drawer()
        for name, (narrow_name, kwargs_map) in {
                "OVER25": ("O25_NARROW", wfl.O25_TIPSTER_KWARGS),
                "WIN": ("WIN_NARROW", wfl.WIN_TIPSTER_KWARGS)}.items():
            narrow = set(getattr(wfl, narrow_name))
            for key in drawer[name]["fields"]:
                if key in kwargs_map and key not in narrow:
                    self.assertIn(
                        key, drawer[name]["publicUnsupported"],
                        f"{name}.{key} works only in Tipster mode; it must be "
                        f"in O25_NARROW/{narrow_name} or declared unsupported "
                        f"for Public mode")

    def test_frontend_and_backend_agree_on_what_public_cannot_do(self):
        """
        PUBLIC_UNSUPPORTED is the backend's statement of what Public mode cannot
        enforce. The frontend disables exactly those boxes. If the two drift,
        the UI disables a working control or leaves a dead one live.
        """
        from api import weekly_filter_live as wfl

        drawer = self._drawer()
        self.assertEqual(set(drawer["WIN"]["publicUnsupported"]),
                         set(wfl.PUBLIC_UNSUPPORTED["win"]),
                         "backend and frontend must agree on WIN's "
                         "Public-mode limitations")
        self.assertEqual(set(drawer["OVER25"]["publicUnsupported"]),
                         set(wfl.PUBLIC_UNSUPPORTED["o25"]))
        # GG forwards strict_mode in every mode, so it must NOT be flagged.
        self.assertNotIn("strict_mode", drawer["GG"]["publicUnsupported"],
                         "GG's _live_gg forwards strict_mode in Public mode too")

    def test_each_goal_form_gate_actually_removes_rows(self):
        """
        Behavioural proof, not a lookup-table assertion: each of the four boxes,
        set on its own, must change the surviving set. This is the difference
        between "the key is named somewhere" and "the box filters fixtures".
        """
        from api.weekly_filter_live import narrow_rows

        rows = [
            {"fixture": "A", "home_goals_scored_last_5": 12, "away_goals_scored_last_5": 11,
             "home_goals_conceded_last_5": 1, "away_goals_conceded_last_5": 2},
            {"fixture": "B", "home_goals_scored_last_5": 3, "away_goals_scored_last_5": 2,
             "home_goals_conceded_last_5": 14, "away_goals_conceded_last_5": 13},
        ]
        cases = {
            "min_home_goals": 8,       # keeps A only
            "min_away_goals": 8,       # keeps A only
            "max_home_conceded": 5,    # keeps A only
            "max_away_conceded": 5,    # keeps A only
        }
        for key, bound in cases.items():
            kept = narrow_rows(rows, "o25", {key: bound})
            self.assertEqual([r["fixture"] for r in kept], ["A"],
                             f"{key}={bound} must keep exactly A")

    def test_a_zero_threshold_is_off_in_both_modes(self):
        """
        0 means "do not gate on this" in the engine
        (`if not thr: continue`), so it must mean the same in Public mode.

        Without this, typing 0 into "Max Home Conceded" reads as "<= 0" and
        deletes every fixture here while meaning nothing in Tipster mode — one
        box, two meanings, chosen by a toggle the user cannot see.
        """
        from api.weekly_filter_live import narrow_rows

        rows = [{"fixture": "A", "home_goals_conceded_last_5": 9}]
        for key in ("max_home_conceded", "min_home_goals"):
            self.assertEqual(len(narrow_rows(rows, "o25", {key: 0})), 1,
                             f"{key}=0 must be OFF, not a gate at zero")
        # And an explicit 0 alongside a real threshold changes nothing.
        kept = narrow_rows(rows, "o25", {"max_home_conceded": 0, "min_home_goals": 5})
        self.assertEqual(len(kept), 1)

    def test_an_unknown_goal_value_passes_here_as_it_does_in_the_engine(self):
        """
        The engine does `cond & (~known | ok)` — an unknown value PASSES, so a
        dated artifact graded before these columns existed is not wiped out.
        narrow_rows used to EXCLUDE on a missing operand (correct for the strict
        gates, wrong for these), which meant the same fixture survived in
        Tipster mode and vanished in Public mode.
        """
        from api.weekly_filter_live import narrow_rows

        blank = [{"fixture": "no_columns", "poisson_over_prob_num": 70.0}]
        kept = narrow_rows(blank, "o25", {"min_home_goals": 5})
        self.assertEqual(len(kept), 1,
                         "an absent goal column must PASS, matching the engine")

        # A strict gate still excludes on a missing operand — unchanged.
        no_poisson = [{"fixture": "no_poisson"}]
        strict = narrow_rows(no_poisson, "o25", {"min_poisson": 50})
        self.assertEqual(len(strict), 0,
                         "the strict gates keep their no-operand-no-verdict rule")

    def test_public_and_tipster_agree_on_a_typed_zero(self):
        """
        End-to-end: the two modes run the same four gates through two different
        implementations, so a value typed into the same box must not produce
        two different pick sets.
        """
        import inspect
        from api import weekly_filter_live as wfl
        from FILTER import over25_risk_filter as filt

        # Engine side skips a falsy threshold.
        engine_src = inspect.getsource(filt)
        self.assertIn("if not thr or col not in df_filtered.columns:", engine_src)
        # API side must skip it identically rather than compare it.
        self.assertIn('if op.endswith("_opt") and not bound:', inspect.getsource(wfl.narrow_rows))


class TestOver15LegacySnapshotCannotBeClobbered(unittest.TestCase):
    """
    The frozen PRE-FIX Over 1.5 verdict is the only remaining record of what
    the old engine said. It is worthless the moment a pipeline run overwrites
    it, and the overwrite is silent — the file is simply replaced by newer
    rows and the pre-fix picks are gone with no trace.

    So the snapshot's safety is asserted here rather than trusted:

      * no engine, and not main.py, may write the `over15_legacy` key;
      * the snapshot tool refuses to overwrite an existing capture;
      * the date whose data the report was about (2026-10-01) still holds the
        pre-fix rows, with the pre-fix generation stamp.
    """

    SNAPSHOT_KEY = "over15_legacy"
    REPORTED_DATE = "2026-10-01"
    # The last pre-fix artifact, generated by the 18:00:21 pipeline run.
    PREFIX_STAMP = "2026-09-30T18:21:52"

    def test_no_engine_or_main_writes_the_snapshot_key(self):
        """
        The snapshot lives at output/cache/over15_legacy__<date>.json. If any
        pipeline code ever wrote that key, the next 18:00 run would replace the
        frozen verdicts and the comparison would quietly become a copy of the
        live output — two identical tables that look like a result.
        """
        from pathlib import Path
        root = Path(__file__).parent
        offenders = []
        for path in [root / "main.py", *sorted(root.glob("Engine/*.py")),
                     *sorted(root.glob("PSYCHOLOGY/*.py")),
                     *sorted(root.glob("AGGREGATOR/*.py")),
                     *sorted(root.glob("CORE/*.py"))]:
            if self.SNAPSHOT_KEY in path.read_text(encoding="utf-8"):
                offenders.append(path.name)
        self.assertEqual(offenders, [],
                         f"these files write/read '{self.SNAPSHOT_KEY}' and "
                         f"would clobber the frozen pre-fix snapshot: "
                         f"{offenders}")

    def test_the_snapshot_tool_never_overwrites_a_capture(self):
        """
        A snapshot means "what the old engine said on this date". A later run
        must not quietly relabel it, or the frozen verdict stops being
        evidence and becomes decoration.
        """
        from pathlib import Path
        src = (Path(__file__).parent / "tools" /
               "snapshot_o15_prefix.py").read_text(encoding="utf-8")
        self.assertIn("if r[\"exists\"] and not force:", src,
                      "an existing capture must be skipped, not overwritten")
        self.assertIn("--force", src,
                      "--force is the deliberate escape hatch and must exist")

    def test_the_reported_date_still_holds_its_pre_fix_rows(self):
        """
        The 2026-10-01 report was that the Over 1.5 output was not coming from
        the fixed engine. These are the rows it was talking about. If they are
        gone, the diagnosis cannot be re-checked and the next run erases it.
        """
        from pathlib import Path
        cache = Path(__file__).parent / "output" / "cache" / \
            f"{self.SNAPSHOT_KEY}__{self.REPORTED_DATE}.json"
        if not cache.exists():
            self.skipTest("snapshot not taken in this checkout "
                          "(run tools/snapshot_o15_prefix.py)")
        payload = json.loads(cache.read_text(encoding="utf-8"))
        self.assertTrue(payload.get("data") or [],
                        "the pre-fix snapshot for the reported date is empty")
        self.assertTrue(str(payload.get("legacy_generated_at", ""))
                        .startswith(self.PREFIX_STAMP),
                        "the snapshot must carry the PRE-FIX generation stamp "
                        f"({self.PREFIX_STAMP}...), not a later run's")
        self.assertEqual(payload.get("legacy_of"), "over15_psychology",
                         "the snapshot must record what it was taken from")

    def test_the_legacy_endpoint_is_served_and_left_unaltered(self):
        """
        The endpoint must exist, and must NOT run the CURRENT intelligent-pass
        evaluator over old picks — that would stamp today's judgement onto
        yesterday's engine and make the comparison meaningless.
        """
        from pathlib import Path
        main = (Path(__file__).parent / "api" / "main.py").read_text(encoding="utf-8")
        route = '@app.get("/api/over15/legacy/{date}"'
        self.assertIn(route, main, "the legacy endpoint must be registered")
        # Anchor on the DECORATOR, not on the prose above it: the explanation
        # comment also names the route, and matching that would read the whole
        # rest of main.py instead of the handler.
        block = main[main.index(route):]
        block = block[:block.index("\n@app.")] if "\n@app." in block else block
        self.assertNotIn("_with_intelligent_pass", block,
                         "the current evaluator must not judge frozen old picks")
        self.assertIn("load_status", block,
                      "the endpoint must report the snapshot's real generation "
                      "time so a stale verdict cannot look live")

    def test_the_page_shows_both_the_fixed_and_the_pre_fix_engine(self):
        """
        The comparison is the point of the block. If either half disappears,
        the page silently reverts to showing one engine's verdict with no way
        to tell which one it is.
        """
        from pathlib import Path
        page = (Path(__file__).parent / "alienedge-frontend" / "app" / "over15" /
                "page.tsx").read_text(encoding="utf-8")
        self.assertIn("over15Api.getPsychology(date)", page,
                      "the live FIXED engine block must stay")
        self.assertIn("over15Api.getLegacy(date)", page,
                      "the frozen PRE-FIX block must stay")
        self.assertIn("PRE-FIX", page,
                      "the frozen block must say what it is; a stale table "
                      "with a live-sounding title is the failure this guards")


class TestNullPlayerIdDoesNotEmptyTheDangerFeed(unittest.TestCase):
    """A lineup row with `player_id: null` must not empty danger_audit.json.

    THE 2026-09-29 OUTAGE. Stage 4 built its starting-XI and bench id sets with
    an unguarded `int(l['player_id'])`. SportMonks returns lineup rows whose
    player_id is null, so the cast raised TypeError inside the per-fixture
    `except: continue` — which swallowed it and skipped the fixture. Because the
    offending rows appeared on nearly every live fixture, the whole feed went to
    `[]` and Code 5 reported "chemistry not available" on the whole board.
    """

    def test_a_null_player_id_starter_row_does_not_raise(self):
        """The exact cast that raised, on the exact shape that raised it."""
        lineups = [
            {"team_id": 10, "type_id": 11, "player_id": 555},        # normal
            {"team_id": 10, "type_id": 11, "player_id": None},       # the landmine
            {"team_id": 10, "type_id": 12, "player_id": None},       # bench too
        ]
        starters = [l for l in lineups if l.get("type_id") == 11]

        # This is the production comprehension, verbatim.
        starters_set = {int(l["player_id"]) for l in starters
                        if l.get("player_id") is not None}
        bench_set = {int(l["player_id"]) for l in lineups
                     if int(l.get("team_id", 0)) == 10
                     and int(l.get("type_id", 0)) == 12
                     and l.get("player_id") is not None}

        self.assertEqual(starters_set, {555})
        self.assertEqual(bench_set, set())

    def test_the_guarded_comprehension_is_what_stage4_actually_ships(self):
        """The source must carry the guard, so a refactor cannot silently drop it."""
        src = Path(stage4.__file__).read_text(encoding="utf-8")
        self.assertIn("l.get('player_id') is not None", src,
                      "Stage 4 must skip null player_id rows instead of raising")

    def test_a_null_id_row_is_excluded_rather_than_counted_as_absent(self):
        """A skipped row must not become a phantom 'missing' player."""
        starters = [{"player_id": 111}, {"player_id": None}]
        ids = {int(l["player_id"]) for l in starters
               if l.get("player_id") is not None}
        self.assertNotIn(0, ids, "a null id must never become the integer 0")
        self.assertEqual(len(ids), 1)

    def test_an_exception_is_reported_rather_than_swallowed(self):
        """The bare `except: continue` is what made this take a day to find."""
        src = Path(stage4.__file__).read_text(encoding="utf-8")
        self.assertNotIn("except Exception as e: continue", src,
                         "Stage 4 must not silently skip a fixture that raised")
        self.assertIn("error_skips", src,
                      "Stage 4 must count and report skipped fixtures")

    def test_the_rotation_ledger_reads_a_name_that_exists(self):
        """A second bug the bare `except` was hiding, found by Fix 2.

        The ledger append read `fav_regime`, a local inside `audit_side`, from the
        enclosing scope. It raised NameError on EVERY fixture. Because it fired
        after `output_pool.append` the cards were still written, so the only
        symptom was "[ROTATION LEDGER] 0 call(s) recorded" on every cycle: the
        rotation-uplift claim was never once recorded against a result.
        """
        import ast
        tree = ast.parse(Path(stage4.__file__).read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "run_danger_forensic_aggregator")
        assigned = {n.id for n in ast.walk(fn)
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
        loaded = {n.id for n in ast.walk(fn)
                  if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        # Every name read in this scope must also be bound in it (or be a
        # builtin/param). `fav_regime` was read but never bound here.
        for name in sorted(loaded - assigned):
            self.assertNotIn(
                name, {"fav_regime"},
                f"{name} is read in run_danger_forensic_aggregator but never "
                f"assigned in that scope — it is a local of audit_side")


class TestClassifierPublishesIsNotStarted(unittest.TestCase):
    """`is_not_started` must exist, or two stages silently drop the whole board.

    Stage 3 and Stage 4 both guard with
    `_state.get("is_live") or _state.get("is_not_started")`. The classifier
    never returned that key, so `.get()` gave None and every NOT_STARTED fixture
    was skipped by both feeds with no error anywhere.
    """

    def test_live_fixture(self):
        info = classifier.classify_fixture(
            {"id": 1, "state_id": 22, "starting_at": "2026-09-29T13:00:00+00:00"})
        self.assertTrue(info["is_live"])
        self.assertFalse(info["is_not_started"])

    def test_finished_fixture(self):
        info = classifier.classify_fixture(
            {"id": 2, "state_id": 5, "starting_at": "2026-09-29T13:00:00+00:00"})
        self.assertTrue(info["is_finished"])
        self.assertFalse(info["is_not_started"])

    def test_not_started_fixture(self):
        info = classifier.classify_fixture(
            {"id": 3, "state_id": 1, "starting_at": "2099-01-01T13:00:00+00:00"})
        self.assertTrue(info["is_not_started"],
                        "a not-yet-started fixture must be identifiable by key")

    def test_the_guard_used_by_stage3_and_stage4_now_admits_prematch(self):
        """The whole point: a pre-match fixture must survive the guard."""
        info = classifier.classify_fixture(
            {"id": 4, "state_id": 1, "starting_at": "2099-01-01T13:00:00+00:00"})
        admitted = bool(info.get("is_live") or info.get("is_not_started"))
        self.assertTrue(admitted,
                        "a not-yet-started fixture is the entire point of a "
                        "PRE-MATCH feed and must not be dropped")

    def test_a_finished_fixture_is_still_excluded_by_the_same_guard(self):
        info = classifier.classify_fixture(
            {"id": 5, "state_id": 5, "starting_at": "2026-09-29T13:00:00+00:00"})
        admitted = bool(info.get("is_live") or info.get("is_not_started"))
        self.assertFalse(admitted)


class TestFailedSquadPullIsNotCachedAsEmpty(unittest.TestCase):
    """A 429 must not be cached as "this team has no history".

    Stage 1's squad fetch is the only source of the key eleven. Caching `{}` on
    a failed pull made Burundi read FULL STRENGTH / 0 missing / KMV 0.0% with no
    XI table — a missed call presented as a finding. 73 cache entries were
    empty while Burundi's own 150-day window held 19 usable lineup rows.
    """

    def _run_with_response(self, response, cached=None):
        """Call the real function, then return (result, cache-after-the-call).

        The cache state is captured BEFORE the cleanup runs. Asserting against it
        after a `finally: clear()` would be a false pass — the cache would be
        empty because the test emptied it, not because the engine did.
        """
        from LIVE_SCANNER import live_stage1_prematch as stage1
        stage1.SQUAD_CACHE.clear()
        if cached is not None:
            stage1.SQUAD_CACHE.update(cached)
        original_get = stage1.GET
        stage1.GET = lambda *a, **k: response
        try:
            result = stage1.get_squad_data_standardized(18834)
            return result, dict(stage1.SQUAD_CACHE)
        finally:
            stage1.GET = original_get
            stage1.SQUAD_CACHE.clear()

    def test_a_failed_pull_is_not_written_into_the_cache(self):
        failed = {"data": [], "_failure": "HTTP 429 rate limit",
                  "_http_status": 429}
        _, cache_after = self._run_with_response(failed)
        self.assertNotIn("18834", cache_after,
                         "a failed pull must not be cached as an empty squad")

    def test_a_failed_pull_does_not_fabricate_a_squad(self):
        failed = {"data": [], "_failure": "HTTP 429 rate limit"}
        result, _ = self._run_with_response(failed)
        self.assertEqual(result, {},
                         "with no data and no cache the honest answer is empty")

    def test_a_failed_pull_reuses_a_known_good_squad(self):
        """The last-known-good window must survive a rate limit."""
        good = {"123": {"id": "123", "name": "Known Good", "pos": "Defender",
                        "det_pos": "Centre-Back", "worth": 100.0,
                        "avg_rating": 7.0, "apps": 3, "mins": 270,
                        "c_p90": 0.5, "vuln": 1.0}}
        failed = {"data": [], "_failure": "HTTP 429 rate limit"}
        result, _ = self._run_with_response(failed, cached={"18834": good})
        self.assertIn("123", result,
                      "a 429 must fall back to the cached squad, not empty it")

    def test_a_genuinely_empty_success_is_still_cacheable(self):
        """A real empty answer is real data and must not refetch every cycle."""
        _, cache_after = self._run_with_response({"data": []})
        self.assertIn("18834", cache_after,
                      "a successful pull with no usable rows is a real answer")

    def test_loading_the_cache_purges_poisoned_empty_entries(self):
        """Entries poisoned by the OLD build must be cleared from disk.

        The write guard stops new poisoning but cannot un-poison what is already
        saved. Because `if tid_str in SQUAD_CACHE` serves an entry without
        refetching, a stale `{}` keeps a team at FULL STRENGTH / 0 missing
        forever. load_cache() is the only place that can clear it.
        """
        from LIVE_SCANNER import live_stage1_prematch as stage1
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "squad_cache.json")
            with open(path, "w") as f:
                json.dump({"111": {"p": 1}, "222": {}, "333": {"p": 3}}, f)
            original = stage1.CACHE_FILE
            stage1.CACHE_FILE = path
            try:
                stage1.load_cache()
                loaded = dict(stage1.SQUAD_CACHE)
            finally:
                stage1.CACHE_FILE = original
                stage1.SQUAD_CACHE.clear()

        self.assertIn("111", loaded)
        self.assertIn("333", loaded)
        self.assertNotIn("222", loaded,
                         "a poisoned empty entry must be dropped so it refetches")

    def test_a_purged_team_is_actually_refetched(self):
        """Purging must translate into a real refetch, not a permanent blank."""
        from LIVE_SCANNER import live_stage1_prematch as stage1
        stage1.SQUAD_CACHE.clear()
        calls = []

        def _fake_get(path, params=None):
            calls.append(path)
            return {"data": []}

        original_get = stage1.GET
        stage1.GET = _fake_get
        try:
            stage1.get_squad_data_standardized(18834)
            self.assertTrue(calls, "an uncached team must trigger a fetch")
        finally:
            stage1.GET = original_get
            stage1.SQUAD_CACHE.clear()


class TestIncomingDetailReportsRealAvailability(unittest.TestCase):
    """The page's 'not available' copy must reflect a real join, not a crash.

    The drill-down page is honest by design: it names the missing piece instead
    of rendering an empty card. That honesty is only useful if the underlying
    feed is healthy, so these pin that populated Code 4 + Code 5 rows actually
    satisfy the availability flags the page reads.
    """

    def test_availability_flags_track_real_rows(self):
        for danger_rows, agg_rows, expect in (
            ([], [], (False, False)),
            ([{"fixture_id": "1"}], [], (True, False)),
            ([{"fixture_id": "1"}], [{"fixture_id": "1"}], (True, True)),
        ):
            self.assertEqual((bool(danger_rows), bool(agg_rows)), expect)

    def test_the_partial_banner_names_exactly_the_missing_pieces(self):
        """Mirrors the endpoint's `partial` computation and the page's filter."""
        availability = {"picks": True, "table": True,
                        "danger": False, "chemistry": False}
        partial = any(availability.values()) and not all(availability.values())
        self.assertTrue(partial)
        named = [k for k, ok in availability.items() if not ok]
        self.assertEqual(sorted(named), ["chemistry", "danger"])

    def test_a_fully_populated_fixture_is_not_partial(self):
        availability = {"picks": True, "table": True,
                        "danger": True, "chemistry": True}
        partial = any(availability.values()) and not all(availability.values())
        self.assertFalse(partial)

    def test_the_frontend_still_renders_the_unavailable_panels(self):
        """The graceful copy must remain — it is correct when data is late."""
        tsx = Path("alienedge-frontend/app/live/incoming/[fixtureId]/page.tsx")
        if not tsx.exists():
            self.skipTest("frontend not present in this checkout")
        text = tsx.read_text(encoding="utf-8")
        self.assertIn("No reconciliation available", text)
        self.assertIn("No market grades", text)


if __name__ == "__main__":
    unittest.main()
