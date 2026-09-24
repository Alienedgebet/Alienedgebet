"""Offline regression tests for the Win Forecast failure contract.

Run: ./venv/bin/python3 tests_win_forecast.py
No network or production output is used.
"""
import os
import sys
import tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import output_store as store
from Engine import win_forecast as wf

RESULTS = []


def check(label, condition):
    RESULTS.append((label, bool(condition)))
    print(("PASS  " if condition else "FAIL  ") + label)


def fixture(fid, home="Home", away="Away", complete=True):
    participants = [
        {"id": fid * 10, "name": home, "meta": {"location": "home"}},
        {"id": fid * 10 + 1, "name": away, "meta": {"location": "away"}},
    ]
    if not complete:
        participants[0].pop("meta")
    return {"id": fid, "name": f"{home} vs {away}", "participants": participants,
            "scores": []}


def past_fixture(home_id, away_id, home_goals=2, away_goals=1):
    return {
        "id": 9000 + home_id,
        "participants": [
            {"id": home_id, "name": "Home", "meta": {"location": "home"}},
            {"id": away_id, "name": "Away", "meta": {"location": "away"}},
        ],
        "scores": [
            {"score": {"participant": "home", "goals": home_goals}},
            {"score": {"participant": "away", "goals": away_goals}},
        ],
    }


def make_fake_get(calls, target, history=True, complete=True):
    def fake_get(path, params=None):
        calls.append((path, dict(params or {})))
        if path.startswith("/fixtures/date/"):
            page = int((params or {}).get("page", 1))
            return {"data": [target] if page == 1 else []}
        if path.startswith("/fixtures/between/"):
            if not history:
                return {"data": []}
            parts = path.split("/")
            home_id, away_id = int(parts[-1]), int(parts[-1]) + 1
            return {"data": [past_fixture(home_id, away_id)]}
        if path.startswith("/odds/pre-match/"):
            return {"data": [
                {"market_id": 1, "label": "Home", "value": "1.80"},
                {"market_id": 1, "label": "Away", "value": "3.20"},
            ]}
        if path.startswith("/fixtures/head-to-head/"):
            return {"data": []}
        raise AssertionError(f"unexpected fake GET: {path}")
    return fake_get


with tempfile.TemporaryDirectory(prefix="alienedge-win-test-") as sandbox:
    output_dir = os.path.join(sandbox, "output")
    os.makedirs(output_dir)
    old_output_dir = wf.OUTPUT_DIR
    old_get = wf.GET
    old_sleep = wf.sleep_short
    wf.OUTPUT_DIR = output_dir
    wf.sleep_short = lambda: None
    try:
        date = "2099-01-02"
        calls = []
        wf.GET = make_fake_get(calls, fixture(101), history=True)
        rows = wf.run_win_forecast_engine(date)
        check("successful forecast returns two side rows", len(rows) == 2)
        output = os.path.join(output_dir, f"ranked_win_forecast_{date}.csv")
        check("successful forecast writes a real CSV", os.path.getsize(output) > 100)
        check("successful forecast has Poisson columns",
              "poisson_win_prob" in open(output, encoding="utf-8").readline())
        check("history is bounded by target date, not wall clock",
              any(p.startswith("/fixtures/between/2098-01-02/2099-01-01/")
                  for p, _ in calls))

        # A malformed provider response must be visible, and an existing
        # artifact must not be replaced by a blank one.
        output_before = open(output, "rb").read()
        calls = []
        wf.GET = make_fake_get(calls, fixture(102, complete=False), history=True)
        try:
            wf.run_win_forecast_engine(date)
            raised = False
        except wf.ForecastDataError as exc:
            raised = "0 rows" in str(exc)
        check("all-fixture failure raises a visible ForecastDataError", raised)
        check("failed forecast preserves the prior valid artifact",
              open(output, "rb").read() == output_before)
        check("failed forecast creates no temporary CSV",
              not os.path.exists(output + ".tmp"))

        # A non-200 response is normalized instead of being treated as JSON.
        class Response:
            status_code = 429
            def json(self):
                return {"unexpected": True}
        try:
            wf._response_json(Response(), "/test")
            normalized = False
        except wf.ForecastDataError as exc:
            normalized = "HTTP 429" in str(exc)
        check("non-200 provider response is explicit", normalized)
    finally:
        wf.OUTPUT_DIR = old_output_dir
        wf.GET = old_get
        wf.sleep_short = old_sleep

# A headerless source must be reported as invalid rather than becoming a
# misleading zero-pick result.
from FILTER import win_filter_service as wfs
with tempfile.TemporaryDirectory(prefix="alienedge-win-filter-") as sandbox:
    old_filter_output = wfs.OUTPUT_DIR
    wfs.OUTPUT_DIR = sandbox
    try:
        bad_source = os.path.join(sandbox, "production_raw_engine_2099-01-03.csv")
        open(bad_source, "w", encoding="utf-8").close()
        try:
            wfs.run_win_filter_service("2099-01-03", mode="public", risk_level="safe")
            invalid_reported = False
        except RuntimeError as exc:
            invalid_reported = "no CSV header/columns" in str(exc)
        check("headerless filter source is explicit invalid input", invalid_reported)
    finally:
        wfs.OUTPUT_DIR = old_filter_output

# Output-store preservation: a failed replacement keeps valid rows but marks
# the snapshot degraded so second-chance can still see that it is unhealthy.
with tempfile.TemporaryDirectory(prefix="alienedge-win-store-") as sandbox:
    old_cache_dir = store.CACHE_DIR
    store.CACHE_DIR = os.path.join(sandbox, "cache")
    os.makedirs(store.CACHE_DIR, exist_ok=True)
    try:
        store.save("win_forecast", "2099-01-02", [{"fixture_id": 1}], status="ok")
        import main
        main._record_engine_failure(
            "Win Forecast Base Engine", "win_forecast", "2099-01-02",
            "synthetic failure",
        )
        status = store.load_status("win_forecast", "2099-01-02")
        data, _ = store.load("win_forecast", "2099-01-02", default=[])
        check("valid same-date snapshot is preserved on failure",
              status.get("status") == "degraded" and data == [{"fixture_id": 1}])
    finally:
        store.CACHE_DIR = old_cache_dir

failed = [label for label, ok in RESULTS if not ok]
print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
sys.exit(1 if failed else 0)
