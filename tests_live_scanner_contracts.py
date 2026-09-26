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
        self.assertFalse(stage2.engine_3_momentum_escalator(weak, "1")[0])

        state, label, _ = stage2.old_engine_statistical_judge(weak, pick)
        self.assertEqual(label, "STATS_1/3")
        self.assertEqual(state, stage2.V_INSUFFICIENT)
        self.assertNotEqual(state, stage2.V_SUPPORTED)

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
        self.assertTrue(stage2.BOX_STAT_FALLBACK)

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
            "REJECTED")
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
        orchestrator.maintenance_thread = lambda db: None
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
        orchestrator.maintenance_thread = lambda db: None
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
    def test_under_locks_final_approved_at_45(self):
        verdict, _ = stage2.locked_verdict_at_45(stage2.V_SUPPORTED, self._ctx())
        self.assertEqual(verdict, stage2.VERDICT_FINAL_APPROVED)

    def test_under_locks_final_rejected_at_45(self):
        verdict, _ = stage2.locked_verdict_at_45(stage2.V_CONTRADICTED, self._ctx())
        self.assertEqual(verdict, stage2.VERDICT_FINAL_REJECTED)

    def test_under_returns_unclear_when_data_says_nothing(self):
        # The third allowed answer. A match with no shots on target at 45' has
        # produced no evidence either way, and the engine must SAY that rather
        # than stay silent until the match dies.
        for gate in (stage2.V_NEUTRAL, stage2.V_INSUFFICIENT):
            verdict, note = stage2.locked_verdict_at_45(gate, self._ctx())
            self.assertEqual(verdict, stage2.VERDICT_UNCERTAIN)
            self.assertIn("UNCLEAR", note)

    def test_under_is_rejected_when_three_goals_already_scored(self):
        verdict, note = stage2.locked_verdict_at_45(
            stage2.V_NEUTRAL, self._ctx(home=1, away=2))
        self.assertEqual(verdict, stage2.VERDICT_FINAL_REJECTED)
        self.assertIn("already lost", note)

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


if __name__ == "__main__":
    unittest.main()
