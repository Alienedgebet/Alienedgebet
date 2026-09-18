"""
WEEKLY/weekly_engine.py — the WEEKLY engine family (GG / WIN / O2.5).

WHAT THIS IS (and what it deliberately is NOT)
---------------------------------------------
The Weekly domain is an INDEPENDENT consumer of the shared future-fixture layer.
It runs the SAME seven dates that PREMATCH's target date anchors
(shared_fixture_window.fill_window) and it COMPOSES already-existing AlienEdge
intelligence — it introduces NO new prediction mathematics, NO new thresholds
and NO new formula:

  Weekly GG      Engine/gg_precision_engine.run_gg_o15_engine        (predictor)
                 AGGREGATOR/gg_forensics_audit.run_gg_forensic_aggregator
                 FILTER/gg_precision_filter.run_gg_precision_filter  (existing filter)
                    -> output/cache/filter_gg__{date}.json

  Weekly WIN     Engine/win_raw_engine.run_win_raw_engine            (predictor)
                 FILTER/win_filter_service.run_win_filter_service    (existing filter)
                    -> output/cache/filter_win__{risk}__{date}.json

  Weekly O2.5    Engine/over25_forecast.run_over25_forecast_engine   (the O2.5
                 intelligence that produces the DATED master_over_stage2_{date}.csv
                 the Weekly O2.5 filter actually consumes)
                 FILTER/over25_risk_filter.run_over25_filter_aggregator (existing filter)
                    -> output/cache/filter_over25__{risk}__{date}.json

Why `over25_forecast` and not stage1/stage2/stage3 for the Weekly chain: the
Weekly O2.5 page is served from FILTER/over25_risk_filter, whose ONLY dated input
is `output/master_over_stage2_{date}.csv` — written by over25_forecast.py. The
council stages (stage1/2/3) feed the PREMATCH O2.5 endpoints and are not part of
the Weekly contract, so including them would spend ~430 extra API calls per date
for rows the Weekly frontend never sees. That scope decision is deliberate and
reported.

Preview-only: `preview_weekly(target_date, ...)` resolves the exact call order and
the existing function objects WITHOUT running any engine — used by the tests to
prove the composition is existing intelligence, not new mathematics.

Nothing here touches LIVE, DNA, odds freshness, history semantics, the frontend,
or output_store's envelope: every row is persisted through output_store exactly
as main.py persists its own engine results.
"""

import gc
import os
import time
from datetime import datetime, timezone

import output_store as store

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# Risk levels are EXACTLY the ones main.py precomputes for the existing Weekly
# Filter page (see app/weekly/filter-config.ts + main.py phase 11).
WIN_RISK_LEVELS = ("safe", "balanced", "aggressive")
O25_RISK_LEVELS = ("banker", "balanced", "aggressive")

DEFAULT_HORIZON = 7

# Dated artefact each Weekly chain REQUIRES before its filter may run. Serving a
# filter from a stale/other-date input is exactly the failure class this guards.
_REQUIRED_INPUT = {
    "gg": "ALIENEDGE_GG_PICKS_{date}.csv",           # Engine/gg_precision_engine.py
    "win": "production_raw_engine_{date}.csv",       # Engine/win_raw_engine.py
    "over25": "master_over_stage2_{date}.csv",       # Engine/over25_forecast.py
}


def _out(name):
    return os.path.join(OUTPUT_DIR, name)


def _fresh_since(path, since_ts):
    """True when `path` exists AND was written at/after `since_ts`."""
    try:
        return os.path.exists(path) and os.path.getmtime(path) >= since_ts
    except OSError:
        return False


def _save_rows(key, date, rows, label):
    """Persist one Weekly snapshot using the EXISTING output_store envelope.

    Mirrors main.py's _safe_exec contract exactly: None is a failure (recorded
    via save_failure, never as an 'ok' null day) and a legitimate [] is saved
    as-is; dated snapshots keep the collapse guard on.
    """
    if rows is None:
        path = store.save_failure(key, date,
                                  error=f"{label}: returned None (no dated output)")
        print(f"   ⚠️ [WEEKLY] {key} {date}: recorded failure -> {path}")
        return {"status": "failed", "rows": 0}
    path = store.save(key, date, rows, guard=True)
    count = len(rows) if hasattr(rows, "__len__") else 0
    print(f"   💾 [WEEKLY] {key} {date}: {count} rows -> {path}")
    return {"status": "ok", "rows": count}


# ── the EXISTING AlienEdge intelligence this family composes ────────────────
# (module-level imports, the repo's convention, so the composition can be
#  inspected and spied on: WEEKLY/weekly_engine.py holds NO prediction maths.)
from Engine.gg_precision_engine import run_gg_o15_engine
from AGGREGATOR.gg_forensics_audit import run_gg_forensic_aggregator
from FILTER.gg_precision_filter import run_gg_precision_filter
from Engine.win_raw_engine import run_win_raw_engine
from FILTER.win_filter_service import run_win_filter_service
from Engine.over25_forecast import run_over25_forecast_engine
from FILTER.over25_risk_filter import run_over25_filter_aggregator


def _require_dated_input(market, date):
    """The dated artefact this market's filter must consume.

    Every Weekly filter's FIRST candidate input is a date-stamped file, so
    requiring that file to exist guarantees the filter can never fall back to a
    dateless (last-writer-wins) file — the failure class that would let one
    date's rows be served as another date's. A date-stamped filename cannot hold
    another date's rows, which is why existence (not mtime) is the correct test.
    """
    name = _REQUIRED_INPUT[market].format(date=date)
    path = _out(name)
    return path, os.path.exists(path)


def run_weekly_gg(target_date):
    """Weekly GG = existing GG predictor + existing GG forensics + existing GG filter."""
    steps = []

    run_gg_o15_engine(target_date, verbose=False)
    steps.append("run_gg_o15_engine")

    input_path, ok = _require_dated_input("gg", target_date)
    if not ok:
        print(f"   ⚠️ [WEEKLY GG] {target_date}: dated engine output missing "
              f"({os.path.basename(input_path)}) — filter NOT run.")
        return {"market": "gg", "date": target_date, "steps": steps,
                "guard": "missing_dated_engine_output",
                "saved": {"filter_gg": _save_rows(
                    "filter_gg", target_date, None,
                    "Weekly GG: missing dated engine output")}}

    run_gg_forensic_aggregator(target_date)
    steps.append("run_gg_forensic_aggregator")

    rows = run_gg_precision_filter(target_date)
    steps.append("run_gg_precision_filter")

    return {"market": "gg", "date": target_date, "steps": steps, "guard": None,
            "saved": {"filter_gg": _save_rows("filter_gg", target_date, rows,
                                              "Weekly GG precision filter")}}


def run_weekly_win(target_date, risk_levels=WIN_RISK_LEVELS):
    """Weekly WIN = existing WIN raw predictor + existing WIN filter (per risk)."""
    steps = ["run_win_raw_engine"]
    saved = {}

    run_win_raw_engine(target_date)

    input_path, ok = _require_dated_input("win", target_date)
    if not ok:
        print(f"   ⚠️ [WEEKLY WIN] {target_date}: dated engine output missing "
              f"({os.path.basename(input_path)}) — filter NOT run.")
        for risk in risk_levels:
            key = f"filter_win__{risk}"
            saved[key] = _save_rows(key, target_date, None,
                                    "Weekly WIN: missing dated engine output")
        return {"market": "win", "date": target_date, "steps": steps,
                "guard": "missing_dated_engine_output", "saved": saved}

    for risk in risk_levels:
        # Same arguments main.py uses for the existing Weekly Filter page.
        rows = run_win_filter_service(target_date, mode="public", risk_level=risk)
        steps.append(f"run_win_filter_service[{risk}]")
        key = f"filter_win__{risk}"
        saved[key] = _save_rows(key, target_date, rows, f"Weekly WIN filter ({risk})")

    return {"market": "win", "date": target_date, "steps": steps, "guard": None,
            "saved": saved}


def run_weekly_over25(target_date, risk_levels=O25_RISK_LEVELS):
    """Weekly O2.5 = existing O2.5 forecast intelligence + existing O2.5 filter."""
    steps = ["run_over25_forecast_engine"]
    saved = {}

    run_over25_forecast_engine(target_date)

    input_path, ok = _require_dated_input("over25", target_date)
    if not ok:
        # Without the DATED stage-2 file the filter would silently fall back to
        # the dateless output/over25_stage2_picks.csv (last writer wins) — the
        # one way a 7-date run could serve another date's rows. Never allowed.
        print(f"   ⚠️ [WEEKLY O2.5] {target_date}: dated engine output missing "
              f"({os.path.basename(input_path)}) — filter NOT run.")
        for risk in risk_levels:
            key = f"filter_over25__{risk}"
            saved[key] = _save_rows(key, target_date, None,
                                    "Weekly O2.5: missing dated engine output")
        return {"market": "over25", "date": target_date, "steps": steps,
                "guard": "missing_dated_engine_output", "saved": saved}

    for risk in risk_levels:
        # Same arguments main.py uses for the existing Weekly Filter page
        # (mode public, risk 'banker'/'balanced'/'aggressive', default odds band).
        rows = run_over25_filter_aggregator(target_date, mode="public",
                                            risk_level=risk)
        steps.append(f"run_over25_filter_aggregator[{risk}]")
        key = f"filter_over25__{risk}"
        saved[key] = _save_rows(key, target_date, rows,
                               f"Weekly O2.5 filter ({risk})")

    return {"market": "over25", "date": target_date, "steps": steps, "guard": None,
            "saved": saved}


# ── the family driver ───────────────────────────────────────────────────────

def run_weekly_family(target_date=None, horizon=DEFAULT_HORIZON,
                      markets=("gg", "win", "over25"), flush_between_dates=True,
                      window_file=None):
    """Run the Weekly family over the shared 7-day future-fixture window.

    `target_date` is the pipeline's target date, i.e. the FIRST day of the
    window (the same anchor shared_fixture_window.fill_window uses), so PREMATCH
    and WEEKLY consume the same future dates. Fixture acquisition is NOT repeated
    here: every engine's /fixtures/date/{date} request is answered by the global
    API cache from the shared window (0 API calls) whenever the window covers the
    narrower request safely.

    Memory: the pipeline's OOM protection is preserved — the in-memory API cache
    is flushed between dates (the DURABLE window on disk is untouched, so the
    next date is still served with zero API calls).
    """
    if target_date is None:
        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    import shared_fixture_window as window
    if window_file:
        window.WINDOW_FILE = window_file

    dates = window.window_dates(target_date, horizon)
    markers = [m for m in ("gg", "win", "over25") if m in markets]
    started = time.time()

    print("\n" + "=" * 115)
    print(f"{'📅 WEEKLY ENGINE FAMILY (GG / WIN / O2.5)':^115}")
    print(f"{f'anchor={target_date}  dates={dates[0]}..{dates[-1]}  horizon={horizon}':^115}")
    print("=" * 115)

    result = {"anchor": target_date, "dates": dates, "markets": markers,
              "per_date": {}, "started_at": started}

    for date in dates:
        print(f"\n> 🗓️  Weekly pass for {date}")
        day = {}
        for market in markers:
            if market == "gg":
                day["gg"] = run_weekly_gg(date)
            elif market == "win":
                day["win"] = run_weekly_win(date)
            else:
                day["over25"] = run_weekly_over25(date)
        result["per_date"][date] = day
        if flush_between_dates:
            try:
                import api_cache
                api_cache.flush_memory(report=False)
            except Exception:
                pass
            gc.collect()

    result["duration_minutes"] = round((time.time() - started) / 60, 2)
    mins = result["duration_minutes"]
    print("\n" + "=" * 115)
    print(f"{'✅ WEEKLY FAMILY COMPLETE':^115}")
    print(f"{f'Duration: {mins} minutes | {len(dates)} dates | ' + ', '.join(markers):^115}")
    print("=" * 115)
    return result


def preview_weekly(target_date, markets=("gg", "win", "over25"),
                 restore=False):
    """Resolve the composition WITHOUT running anything (tests/diagnostics).

    Returns the exact existing function objects each Weekly market calls, in
    call order, proving WEEKLY reuses the AlienEdge intelligence rather than
    re-implementing it. With restore=True the module-level names are first
    re-imported from their home modules — so the preview identifies the REAL
    Engine/AGGREGATOR/FILTER functions even when a test has replaced them with
    spies (spies are local to the importing test process only).
    """
    plan_fns = {
        "gg": ["run_gg_o15_engine", "run_gg_forensic_aggregator",
               "run_gg_precision_filter"],
        "win": ["run_win_raw_engine"] + ["run_win_filter_service"] * len(WIN_RISK_LEVELS),
        "over25": (["run_over25_forecast_engine"]
                   + ["run_over25_filter_aggregator"] * len(O25_RISK_LEVELS)),
    }
    sources = {
        "run_gg_o15_engine": "Engine.gg_precision_engine",
        "run_gg_forensic_aggregator": "AGGREGATOR.gg_forensics_audit",
        "run_gg_precision_filter": "FILTER.gg_precision_filter",
        "run_win_raw_engine": "Engine.win_raw_engine",
        "run_win_filter_service": "FILTER.win_filter_service",
        "run_over25_forecast_engine": "Engine.over25_forecast",
        "run_over25_filter_aggregator": "FILTER.over25_risk_filter",
    }
    out = {}
    for m in plan_fns:
        if m not in markets:
            continue
        rows = []
        for name in plan_fns[m]:
            if restore:
                import importlib
                home = importlib.import_module(sources[name])
                fn = getattr(home, name)
            else:
                fn = globals()[name]
            rows.append({"module": fn.__module__, "function": fn.__name__})
        out[m] = rows
    return out