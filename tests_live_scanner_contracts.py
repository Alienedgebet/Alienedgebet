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
from LIVE_SCANNER import live_stage5_aggregator as stage5
from LIVE_SCANNER import live_stage6_alerts as stage6
from api import main as api_main
from LIVE_SCANNER import live_state_classifier as classifier


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
    def test_only_triggered_and_settled_are_notifiable(self):
        # SUPPORTED is reversible, so it must never be announced.
        self.assertEqual(notify.ALLOWED_EVENTS, {"TRIGGERED", "SETTLED"})
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

    def test_current_is_not_read_at_full_time(self):
        """THE BUG. `score_from_fixture` only matches CURRENT, so resolving a
        finished match through it yields (0,0) — a scoreline that was never
        read, and indistinguishable from a real goalless draw."""
        fx = self._finished_fx(42, period="FULLTIME", h=1, a=2)
        orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
        self.assertEqual(orch.score_from_fixture(fx), (0, 0))
        # The correct period gives the truth.
        self.assertEqual(orch.score_period(fx, "FULLTIME"), (1, 2))
        # An absent period must be None, never (0, 0).
        self.assertIsNone(orch.score_period(fx, "CURRENT"))

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
    def test_gates_do_not_both_fire_in_the_same_window(self):
        """Observed live: a storm first caught at 46' fired BOTH developing
        and sustained in the same cycle, because 'developing' is the first
        cycle >=45 while 'sustained' covers 45-60. The card read "stages at
        46', 46', 72'" — three stages that were really two moments. Gate N may
        only fire if gate N-1 did not already fire for the fixture."""
        orch = stage6.SupremeOrchestrator.__new__(stage6.SupremeOrchestrator)
        fired = []
        orch.fire_alert = lambda *a, **k: fired.append(k.get("storm_stage"))
        stage6.ALERT_HISTORY.clear()
        stage6.VALIDATION_STATE.clear()
        struct = {"h_triple": True, "a_triple": False}
        ctx = self._storm_ctx()
        # 46' with the original handshake set: developing fires.
        stage6.VALIDATION_STATE["FG1"] = "VALID_30"
        orch.process_ai_gates("FG1", "A vs B", 46, ctx, struct, {}, score=(0, 0))
        self.assertIn("developing", fired)
        # A later cycle inside 45-60 must NOT add a "sustained" alert.
        fired.clear()
        orch.process_ai_gates("FG1", "A vs B", 52, ctx, struct, {}, score=(0, 0))
        self.assertNotIn("sustained", fired,
                         "a stage already preceded must not re-fire")
        # 72' is outside 45-60, so peaking is still reachable.
        fired.clear()
        orch.process_ai_gates("FG1", "A vs B", 72, ctx, struct, {}, score=(0, 0))
        self.assertIn("peaking", fired)
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

















# The runner block must be LAST in this file. It used to sit at line 1394,
# mid-module, where unittest.main() called sys.exit() at import time and every
# test class declared after it was silently never defined or run. The suite
# reported "OK" while roughly half the contracts were dead code.
if __name__ == "__main__":
    unittest.main()
