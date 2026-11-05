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
import json
import os
import time
from datetime import datetime, timezone

import output_store as store

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
HEARTBEAT_FILE = os.path.join(BASE_DIR, "data", "pipeline_heartbeat.json")
STATE_FILE = os.path.join(BASE_DIR, "data", "weekly_state.json")

# ── INCREMENTAL / ROLLING COMPLETION LEDGER (2026-10-03)────────────────────
#
# WHY THIS EXISTS
# The original design is ROLLING: the shared fixture window keeps the previous
# six relevant days, acquires only the newly required one and evicts the oldest
# (shared_fixture_window.fill_window — UNCHANGED, it is correct). But the Weekly
# COMPUTATION loop recomputed all seven dates on every run, because nothing
# recorded that a day had already been done. That is ~6x the work every night and
# it is why the run stayed long enough for the watchdog to reap it.
#
# WHAT A COMPLETED DAY IS
# A day is complete when all seven Weekly snapshots exist with status "ok":
#   filter_gg, filter_win__{safe,balanced,aggressive},
#   filter_over25__{banker,balanced,aggressive}
# _save_rows() already records a genuine failure through store.save_failure()
# (status "failed"), so "all seven ok" cannot be satisfied by a half-finished or
# failed day. That rule alone already prevents a partial day counting as done.
#
# WHAT IS *NOT* AN INVALIDATION TRIGGER (deliberate, and the whole point)
# A completed day's bytes are NOT stable across reruns. Measured on this box, a
# rerun of 2026-10-09 changed every one of its snapshots, from two causes:
#   * gg_precision_filter stamps audit_timestamp = now() into every row, so the
#     file differs byte-for-byte on any rerun even when the picks are identical;
#   * odds are volatile and CANONICAL_INCLUDE deliberately excludes them so they
#     are always refetched.
# Treating either as a trigger would make every day permanently stale and reduce
# this straight back to recomputing all seven, so neither is one. Freshness of a
# 7-day-out pick's odds belongs to the match-day/live path, not here.
#
# The invalidation signals that ARE honoured are the ones meaning "the answer
# would genuinely be different now":
#   1. any of the seven keys missing or status != "ok"  (partial/failed day)
#   2. the day's dated engine input CSV is NEWER than the Weekly snapshot, i.e. a
#      dependent engine was re-run or fixed after this day was computed
#   3. an explicit rebuild (force=True, or --weekly-only=<date>)
#
# LEDGER DISCIPLINE
# The ledger is a cache/hint, never the source of truth: completion is ALWAYS
# re-derived from the seven on-disk snapshots. An entry is written only AFTER all
# three markets returned and all seven keys reported ok, in one atomic write at the
# END of the date. A crash mid-date therefore leaves no entry and no false
# "complete" — the day is simply recomputed next time. Nothing is ever written
# optimistically at the start of a date.
#
# Nothing else in the codebase reads this file; deleting it costs nothing but a
# recompute of the affected days.
REQUIRED_KEYS = ("filter_gg",
                 "filter_win__safe", "filter_win__balanced", "filter_win__aggressive",
                 "filter_over25__banker", "filter_over25__balanced",
                 "filter_over25__aggressive")

# ── PROGRESS HEARTBEAT ───────────────────────────────────────────────────────
#
# WHY THIS EXISTS (2026-10-03)
# The run watchdog (run_pipeline_watchdog.sh) SIGKILLs a run whose
# data/pipeline_heartbeat.json has not moved for STALE_AFTER (45 min). Until
# now ONLY main.py's _safe_exec() touched that file, so the heartbeat went
# silent the moment the WEEKLY family started — even though the weekly pass was
# demonstrably working and writing artefacts.
#
# Measured on the 2026-10-03 18:00 run: last heartbeat 18:13:56
# ("done:filter_win__aggressive"), killed 18:59:10 = 45.2 minutes silent,
# exactly at the threshold — while weekly artefacts were being written at
# 18:37, 18:38, 18:39 and 18:44. The watchdog did precisely what it was told;
# it was simply never told the run was alive.
#
# The same failure killed the 2026-10-02 run mid weekly-pass at 2026-10-09 (see
# the history note in run_pipeline_watchdog.sh), so this is a recurring kill of
# healthy runs, not a one-off. It silently cost the final day of the 7-day
# window every night.
#
# main.py cannot be imported from here (circular: main imports this module), so
# this writes the same file with the same shape and the same atomic
# tmp+os.replace discipline. It is deliberately self-contained, cheap (one small
# JSON write per step), and never raises — telemetry must not kill a run.
_heartbeat_last = [0.0]
HEARTBEAT_MIN_INTERVAL_S = 20.0


# ── ledger helpers (self-contained: main.py cannot be imported from here) ────
def _empty_state():
    return {"schema": 1, "days": {}}


def _load_state(path=None):
    """Read the ledger. Any problem yields an empty ledger -> full recompute."""
    p = path or STATE_FILE
    try:
        with open(p, "r", encoding="utf-8") as fh:
            s = json.load(fh)
        if not isinstance(s, dict) or not isinstance(s.get("days"), dict):
            return _empty_state()
        return s
    except Exception:
        return _empty_state()


def _save_state(state, path=None):
    """Atomic tmp+os.replace, mirroring output_store's discipline."""
    p = path or STATE_FILE
    try:
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = f"{p}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=1, sort_keys=True)
        os.replace(tmp, p)
        return True
    except Exception:
        return False


def _snapshot_state(key, date):
    """(status, mtime_epoch) for one Weekly snapshot, or (None, None).

    mtime, NOT the payload's `generated_at`: both engines and the store stamp
    `generated_at` with datetime.now(), which does not share a clock base with
    the filesystem mtime used for the engine-input comparison below. Comparing
    the two would make a day permanently unable to confirm itself complete.
    Every snapshot for one date is written by the same process within the same
    second, so their mtimes are directly comparable to each other.
    """
    path = os.path.join(store.CACHE_DIR, f"{key}__{date}.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, dict):
            return None, None
        return payload.get("status"), os.path.getmtime(path)
    except Exception:
        return None, None


def weekly_heartbeat(note, force=False):
    """Tell the watchdog the Weekly pass is alive. Never raises."""
    now = time.time()
    if not force and (now - _heartbeat_last[0]) < HEARTBEAT_MIN_INTERVAL_S:
        return
    try:
        payload = {
            "pid": os.getpid(),
            "ts": now,
            "iso": datetime.now().isoformat(),
            "note": note,
        }
        os.makedirs(os.path.dirname(HEARTBEAT_FILE), exist_ok=True)
        tmp = f"{HEARTBEAT_FILE}.{os.getpid()}.weekly.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, HEARTBEAT_FILE)
        _heartbeat_last[0] = now
    except Exception:
        pass

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


def date_is_complete(date, state=None, force=False):
    """True when this date needs no work.

    Deliberately re-derives completion from the seven on-disk snapshots rather
    than trusting the ledger, so a hand-deleted snapshot, a failed run or a
    restored backup can never present itself as complete.
    """
    if force:
        return False

    # (1) every key present with status ok
    snap_ts = []
    for key in REQUIRED_KEYS:
        status, ts = _snapshot_state(key, date)
        if status != "ok":
            return False
        if ts is not None:
            snap_ts.append(ts)
    if not snap_ts:
        return False

    # A stale ledger must never outrank a snapshot: if the ledger claims the day
    # was completed BEFORE these snapshots were written, the snapshots were
    # replaced by something else, so the day is treated as incomplete.
    entry = ((state if state is not None else _load_state()).get("days") or {}).get(date)
    if isinstance(entry, dict) and entry.get("completed_ts"):
        try:
            if float(entry["completed_ts"]) < min(snap_ts):
                return False
        except Exception:
            return False

    # (2) a dependent engine re-run after we computed this day invalidates it
    newest_snapshot = max(snap_ts)
    for market in ("gg", "win", "over25"):
        path, ok = _require_dated_input(market, date)
        if not ok:
            continue
        try:
            if os.path.getmtime(path) > newest_snapshot + 1:
                return False
        except OSError:
            continue
    return True


def mark_date_complete(date, detail=None):
    """Record a day as done. Called ONLY after all seven keys reported ok."""
    state = _load_state()
    state.setdefault("days", {})[str(date)[:10]] = {
        "completed_ts": time.time(),
        "completed_iso": datetime.now().isoformat(),
        "keys": list(REQUIRED_KEYS),
    }
    state["schema"] = 1
    return _save_state(state)


def plan_dates(dates, force=False, state=None, dry_run=False):
    """Split the window into (to_run, skipped) and explain every skip."""
    st = state if state is not None else _load_state()
    to_run, skipped = [], []
    for d in dates:
        (skipped if date_is_complete(d, st, force) else to_run).append(d)
    print("=" * 115)
    print(f"{'🔁 FULL REBUILD (force)' if force else '♻️  INCREMENTAL':^115}")
    print("=" * 115)
    print(f"  window   : {len(dates)} day(s)  [{dates[0]}..{dates[-1]}]")
    print(f"  to run   : {len(to_run)}  {to_run}")
    print(f"  complete : {len(skipped)}  {skipped}")
    if skipped:
        print("  ↻ skipped = all 7 snapshots ok AND no newer dependent-engine input")
    if force:
        print("  ⚠️  force=True: every day recomputed regardless of completion")
    if dry_run:
        print("  🧪 dry_run=True: nothing will be executed")
    print("=" * 115)
    return to_run, skipped


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
                      window_file=None, force=False, dry_run=False):
    """Run the Weekly family over the shared 7-day future-fixture window.

    `target_date` is the pipeline's target date, i.e. the FIRST day of the
    window (the same anchor shared_fixture_window.fill_window uses), so PREMATCH
    and WEEKLY consume the same future dates. Fixture acquisition is NOT repeated
    here: every engine's /fixtures/date/{date} request is answered by the global
    API cache from the shared window (0 API calls) whenever the window covers the
    narrower request safely.

    INCREMENTAL (2026-10-03): by default only the dates that are NOT already
    complete are computed, so a normal nightly run processes the one newly added
    day instead of recomputing all seven. Completion is re-derived from the seven
    on-disk snapshots every run (see date_is_complete) — never trusted from the
    ledger alone. `force=True` restores the full 7-day rebuild and is what the
    operational `--weekly-only=<date>` path passes, so the deliberate rebuild
    capability is preserved by this same switch rather than a second code path.
    `dry_run=True` prints the plan and returns without executing anything.

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

    to_run, skipped = plan_dates(dates, force=force, dry_run=dry_run)

    result = {"anchor": target_date, "dates": dates, "markets": markers,
              "per_date": {}, "skipped": skipped, "planned": to_run,
              "incremental": not force, "started_at": started}

    if dry_run:
        print("\n🧪 DRY RUN — no engine executed, nothing written.")
        return result

    if not to_run:
        print("\n✅ NOTHING TO DO — every day in the window is already complete.")

    total_dates = len(to_run)
    for idx, date in enumerate(to_run, start=1):
        # Beaten BEFORE the first market, so a slow first date is already
        # accounted for, and after each date, so one long date cannot
        # accumulate past the watchdog threshold while saying nothing.
        weekly_heartbeat(f"weekly:start:{date}", force=True)
        print(f"\n> 🗓️  Weekly pass for {date}  ({idx}/{total_dates})")
        day = {}
        for market in markers:
            weekly_heartbeat(f"weekly:{market}:{date}")
            if market == "gg":
                day["gg"] = run_weekly_gg(date)
            elif market == "win":
                day["win"] = run_weekly_win(date)
            else:
                day["over25"] = run_weekly_over25(date)
            weekly_heartbeat(f"weekly:{market}:done:{date}")
        result["per_date"][date] = day
        # Recorded ONLY here — after every market returned. Whether the day truly
        # completed is still re-derived from the snapshots next run, so a market
        # that recorded a failure simply leaves the day incomplete.
        if date_is_complete(date, force=False):
            mark_date_complete(date)
        else:
            print(f"   ⚠️ [WEEKLY] {date} did not reach a complete state — it stays "
                  f"pending and will be recomputed next run.")
        weekly_heartbeat(f"weekly:done:{date}", force=True)
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
    print(f"{f'Ran {len(to_run)} of {len(dates)} day(s) | skipped {len(skipped)} '
          f'| {mins} minutes | ' + ', '.join(markers):^115}")
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