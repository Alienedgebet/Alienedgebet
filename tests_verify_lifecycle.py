"""Focused regression tests for permanent match verification.

These tests use only synthetic data and temporary files. They never call the
SportMonks API and never modify the production snapshot or archive stores.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import live_cache
import settlement_service as settlement


DATE = "2099-01-02"


def standardized_match(*, total_corners=0, total_sot=0, finished=True):
    h_corners = 1
    a_corners = max(0, total_corners - h_corners)
    h_sot = 2
    a_sot = max(0, total_sot - h_sot)
    return {
        "fixture_id": "999999",
        "home_team": "Alpha FC",
        "away_team": "Beta United",
        "h_ht": 0,
        "a_ht": 0,
        "h_ft": 1,
        "a_ft": 1,
        "ft_score": "1-1",
        "total_goals": 2,
        "sh_goals_home": 1,
        "sh_goals_away": 1,
        "sh_goals": 2,
        "h_corners": h_corners,
        "a_corners": a_corners,
        "total_corners": total_corners,
        "h_sot": h_sot,
        "a_sot": a_sot,
        "total_sot": total_sot,
        "has_started": True,
        "is_finished": finished,
        "score_available": True,
        "minute": 90 if finished else 45,
        "match_date": DATE,
    }


class VerificationMathTests(unittest.TestCase):
    def test_sot_boundary_is_seven_plus(self):
        six = settlement.grade_row("sot", {}, standardized_match(total_sot=6))
        seven = settlement.grade_row("sot", {}, standardized_match(total_sot=7))
        self.assertEqual(six["verdict"], "LOST")
        self.assertEqual(seven["verdict"], "WON")
        self.assertEqual(seven["h_sot"], 2)
        self.assertEqual(seven["a_sot"], 5)
        self.assertEqual(seven["total_sot"], 7)

    def test_corner_boundary_is_seven_plus(self):
        six = settlement.grade_row("corners", {}, standardized_match(total_corners=6))
        seven = settlement.grade_row("corners", {}, standardized_match(total_corners=7))
        self.assertEqual(six["verdict"], "LOST")
        self.assertEqual(seven["verdict"], "WON")
        self.assertEqual(seven["total_corners"], 7)

    def test_live_market_split_is_in_payload(self):
        sot = settlement.grade_row(
            "sot", {}, standardized_match(total_sot=6, finished=False)
        )
        corners = settlement.grade_row(
            "corners", {}, standardized_match(total_corners=6, finished=False)
        )
        self.assertEqual(sot["status"], "LIVE")
        self.assertEqual((sot["h_sot"], sot["a_sot"], sot["total_sot"]), (2, 4, 6))
        self.assertEqual(corners["status"], "LIVE")
        self.assertEqual(
            (corners["h_corners"], corners["a_corners"], corners["total_corners"]),
            (1, 5, 6),
        )


class PersistenceTests(unittest.TestCase):
    def test_finished_snapshot_survives_empty_live_feed(self):
        result = standardized_match(total_sot=7)
        row = {"fixture_id": result["fixture_id"], "Fixture": "Alpha FC vs Beta United"}
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_path = Path(temp_dir) / "ft_result_snapshot.json"
            snapshot_path.write_text(
                json.dumps({"fixtures": {DATE: {result["fixture_id"]: result}}}),
                encoding="utf-8",
            )
            with patch.object(settlement, "FT_SNAPSHOT_FILE", str(snapshot_path)), \
                 patch.object(settlement, "ARCHIVE_DIR", temp_dir):
                settlement._FT_SNAPSHOT_CACHE.clear()
                settled = settlement.settle_predictions(
                    [row], [], market_type="sot", date_str=DATE
                )
            self.assertEqual(len(settled), 1)
            self.assertEqual(settled[0]["verification"]["status"], "FINISHED")
            self.assertEqual(settled[0]["verification"]["verdict"], "WON")
            self.assertEqual(settled[0]["verification"]["total_sot"], 7)

    def test_empty_feed_recovery_handles_today_and_yesterday(self):
        result = standardized_match(total_sot=7)
        response = type("Response", (), {
            "status_code": 200,
            "json": lambda self: {"data": []},
        })()
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "live_inplay_cache.json"
            with patch.object(live_cache, "DATA_DIR", temp_dir), \
                 patch.object(live_cache, "LIVE_CACHE_FILE", str(cache_path)), \
                 patch.object(live_cache, "API_KEY", "test-key"), \
                 patch.object(live_cache.requests, "get", return_value=response), \
                 patch("settlement_service.load_ft_snapshot", return_value={}), \
                 patch("settlement_service.load_finished_archive", return_value={"old": result}), \
                 patch("settlement_service.write_ft_snapshot") as write_snapshot:
                rows = live_cache.get_live_scores_cached(force_refresh=True)
            self.assertEqual(rows, [])
            write_snapshot.assert_called_once()
            today = live_cache.datetime.now().strftime("%Y-%m-%d")
            yesterday = (live_cache.datetime.now() - live_cache.timedelta(days=1)).strftime("%Y-%m-%d")
            self.assertEqual(
                write_snapshot.call_args.args[0],
                {today: [result], yesterday: [result]},
            )

    def test_cached_live_payload_is_scanned_for_finished_fixtures(self):
        raw = {
            "id": "888888",
            "starting_at": f"{DATE}T12:00:00+00:00",
            "state": {"state": "FT"},
            "scores": [
                {"description": "FULL_TIME", "score": {"participant": "home", "goals": 2}},
                {"description": "FULL_TIME", "score": {"participant": "away", "goals": 1}},
            ],
            "participants": [
                {"id": 1, "name": "Alpha FC", "meta": {"location": "home"}},
                {"id": 2, "name": "Beta United", "meta": {"location": "away"}},
            ],
            "statistics": [
                {
                    "participant_id": 1,
                    "type": {"name": "Shots On Target"},
                    "data": {"value": 4},
                },
                {
                    "participant_id": 2,
                    "type": {"name": "Shots On Target"},
                    "data": {"value": 3},
                },
            ],
        }
        with patch("settlement_service.write_ft_snapshot") as write_snapshot:
            count = live_cache._persist_finished_from_live([raw])
        self.assertEqual(count, 1)
        write_snapshot.assert_called_once()
        written = write_snapshot.call_args.args[0]
        self.assertEqual(written[DATE][0]["fixture_id"], "888888")
        self.assertEqual(written[DATE][0]["total_sot"], 7)


if __name__ == "__main__":
    unittest.main()
