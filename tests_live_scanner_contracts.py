"""Offline regression tests for the live scanner stage contracts.

These tests use synthetic provider-shaped payloads and temporary files only. They
never call SportMonks, run a scanner cycle, write production artifacts, or
restart the live service.
"""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from LIVE_SCANNER import live_stage2_verification as stage2
from LIVE_SCANNER import live_stage4_danger as stage4
from LIVE_SCANNER import live_stage5_aggregator as stage5
from LIVE_SCANNER import live_stage6_alerts as stage6
from api import main as api_main


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
        self.assertEqual(stage2.check_if_done(base, pick), (False, ""))
        base["away"]["goals"] = 2
        self.assertTrue(stage2.check_if_done(base, pick)[0])

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
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
