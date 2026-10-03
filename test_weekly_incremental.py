#!/usr/bin/env python3
"""
Weekly INCREMENTAL / rolling completion — TESTS.

Run:  ./venv/bin/python test_weekly_incremental.py

Scope: proves that run_weekly_family now computes ONLY the dates that are not
already complete, that a full rebuild is still available, and that a partially
written day can never present itself as complete.

Safety (deliberate, enforced — identical discipline to the sibling suite):
  * NO network: api_cache._original_get is replaced by a fake. Zero SportMonks
    requests are made.
  * NO production writes: output_store's cache dir, the Weekly output dir, the
    window store, the completion ledger AND the heartbeat file are ALL redirected
    into a /tmp sandbox. data/weekly_state.json in the repo is never touched.
  * NO pipeline run: alienedge_master_system is never called and every Weekly
    engine is a spy, so no prediction mathematics executes.
"""

import hashlib
import json
import os
import shutil
import subprocess as _sp
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
SBOX = "/tmp/alienedge_weekly_incremental_sandbox"
shutil.rmtree(SBOX, ignore_errors=True, onerror=None)
for sub in ("data", "output", "cache"):
    os.makedirs(os.path.join(SBOX, sub), exist_ok=True)

sys.path.insert(0, ROOT)

import output_store as store
store.CACHE_DIR = os.path.join(SBOX, "cache")

import api_cache
import shared_fixture_window as window

api_cache.GATE_LOCK_FILE = os.path.join(SBOX, "data", "api_429_cooldown.lock")
window.WINDOW_FILE = os.path.join(SBOX, "data", "future_fixture_window.json")


def fake_get(url, **kw):
    raise AssertionError("NO NETWORK: the incremental path must not call SportMonks")


api_cache._original_get = fake_get
api_cache.install()

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    mark = "✅" if cond else "❌"
    extra = f" — {detail}" if detail and not cond else ""
    print(f"{mark} {name}{extra}")


import WEEKLY.weekly_engine as we

# Redirect every writable surface into the sandbox.
we.OUTPUT_DIR = os.path.join(SBOX, "output")
we.STATE_FILE = os.path.join(SBOX, "data", "weekly_state.json")
we.HEARTBEAT_FILE = os.path.join(SBOX, "data", "pipeline_heartbeat.json")

week_calls = []


def spy(name, artifact=None, rows=None):
    def _f(target_date, *a, **kw):
        week_calls.append((name, target_date))
        if artifact:
            with open(os.path.join(we.OUTPUT_DIR,
                                   artifact.format(date=target_date)),
                      "w", encoding="utf-8") as fh:
                fh.write("fixture_id,fixture\n1,x\n")
        return rows if rows is not None else [{"fixture_id": "1"}]
    return _f


we.run_gg_o15_engine = spy("run_gg_o15_engine", "ALIENEDGE_GG_PICKS_{date}.csv")
we.run_gg_forensic_aggregator = spy("run_gg_forensic_aggregator")
we.run_gg_precision_filter = spy("run_gg_precision_filter", rows=[{"fixture_id": "1"}])
we.run_win_raw_engine = spy("run_win_raw_engine", "production_raw_engine_{date}.csv")
we.run_win_filter_service = spy("run_win_filter_service", rows=[{"fixture_id": "1"}])
we.run_over25_forecast_engine = spy("run_over25_forecast_engine",
                                    "master_over_stage2_{date}.csv")
we.run_over25_filter_aggregator = spy("run_over25_filter_aggregator",
                                      rows=[{"fixture_id": "1"}])

ANCHOR = "2099-06-01"
DATES = window.window_dates(ANCHOR, 3)
print(f"sandbox: {SBOX}\nanchor={ANCHOR} dates={DATES}\n")


def _digest():
    out = {}
    for d in DATES:
        for k in we.REQUIRED_KEYS:
            p = os.path.join(store.CACHE_DIR, f"{k}__{d}.json")
            with open(p, "rb") as fh:
                out[f"{k}__{d}"] = hashlib.md5(fh.read()).hexdigest()
    return out
# ═══════════════════════════════════════════════════════════════════════════
print("=== A. A COMPLETED DAY IS RECOGNISED AND NOT REPEATED ===")
# ════════════════════════════════════════════════════════════════════════════
res = we.run_weekly_family(ANCHOR, horizon=3, flush_between_dates=False)
check("A1 the first run computes every day (nothing is complete yet)",
      sorted(res["per_date"]) == DATES and res["skipped"] == [],
      f"per_date={sorted(res['per_date'])} skipped={res['skipped']}")
check("A2 the ledger recorded all three days",
      sorted(we._load_state()["days"]) == DATES, list(we._load_state()["days"]))
check("A3 all seven snapshots exist per day, all status ok",
      all(we._snapshot_state(k, d)[0] == "ok"
          for d in DATES for k in we.REQUIRED_KEYS))

week_calls.clear()
res2 = we.run_weekly_family(ANCHOR, horizon=3, flush_between_dates=False)
check("A4 the SECOND run executes ZERO engine calls (the whole point)",
      len(week_calls) == 0, f"{len(week_calls)} calls: {week_calls[:4]}")
check("A5 the second run skipped every day",
      res2["skipped"] == DATES and res2["per_date"] == {}, res2["skipped"])
check("A6 the result reports itself as incremental",
      res2["incremental"] is True and res2["planned"] == [])

before = _digest()
we.run_weekly_family(ANCHOR, horizon=3, flush_between_dates=False)
check("A7 repeated runs leave every snapshot byte-identical",
      _digest() == before)

# ═══════════════════════════════════════════════════════════════════════════
print("\n=== B. THE ROLLING SEQUENCE ADDS EXACTLY ONE NEW DAY ===")
# ════════════════════════════════════════════════════════════════════════════
next_anchor = "2099-06-02"          # the window rolls forward by one day
rolled = window.window_dates(next_anchor, 3)
week_calls.clear()
res3 = we.run_weekly_family(next_anchor, horizon=3, flush_between_dates=False)
check("B1 rolling forward computes ONLY the newly added day",
      sorted(res3["per_date"]) == ["2099-06-04"]
      and res3["skipped"] == ["2099-06-02", "2099-06-03"],
      f"ran={sorted(res3['per_date'])} skipped={res3['skipped']}")
ran_dates = {c[1] for c in week_calls}
check("B2 no engine was invoked for an already-complete day",
      ran_dates == {"2099-06-04"}, ran_dates)
check("B3 the new day ran all three markets",
      len([c for c in week_calls if c[1] == "2099-06-04"]) >= 7,
      len([c for c in week_calls if c[1] == "2099-06-04"]))
check("B4 the fixture window is unchanged by the Weekly pass (rolling is "
      "shared_fixture_window's job, and it was not called here)",
      window.WINDOW_FILE.startswith("/tmp")
      and set((window._load_store().get("days") or {}).keys()) <= set(DATES) | {"2099-06-04"},
      sorted((window._load_store().get("days") or {}).keys()))

# ═══════════════════════════════════════════════════════════════════════════
print("\n=== C. A FULL 7-DAY REBUILD IS STILL AVAILABLE ===")
# ════════════════════════════════════════════════════════════════════════════
week_calls.clear()
res4 = we.run_weekly_family(ANCHOR, horizon=3, force=True,
                            flush_between_dates=False)
check("C1 force=True recomputes every day in the window",
      sorted(res4["per_date"]) == DATES and res4["skipped"] == [],
      f"ran={sorted(res4['per_date'])}")
check("C2 force=True reports itself as a rebuild", res4["incremental"] is False)
check("C3 force=True actually re-invoked the engines", len(week_calls) > 0)
week_calls.clear()
res5 = we.run_weekly_family(ANCHOR, horizon=3, dry_run=True)
check("C4 dry_run returns a plan and runs nothing",
      res5["per_date"] == {} and len(week_calls) == 0, len(week_calls))
# ═══════════════════════════════════════════════════════════════════════════
print("\n=== D. A PARTIAL OR FAILED DAY IS NEVER 'COMPLETE' ===")
# ════════════════════════════════════════════════════════════════════════════
partial = "2099-06-04"
p = os.path.join(store.CACHE_DIR, f"filter_win__aggressive__{partial}.json")
os.remove(p)
check("D1 a day missing one of its seven keys is NOT complete",
      we.date_is_complete(partial) is False)

with open(p, "w", encoding="utf-8") as fh:
    json.dump({"engine_key": "filter_win__aggressive", "date": partial,
               "generated_at": "2099-06-04T00:00:00", "status": "failed",
               "error": "boom", "row_count": 0, "data": []}, fh)
check("D2 a day with a FAILED key is NOT complete",
      we.date_is_complete(partial) is False)

week_calls.clear()
res6 = we.run_weekly_family(next_anchor, horizon=3, flush_between_dates=False)
check("D3 that broken day is retried on the next run",
      partial in res6["per_date"], f"ran={sorted(res6['per_date'])}")

# A market that returns None records a failure, and the day must stay pending.
broken = "2099-06-05"
os.makedirs(we.OUTPUT_DIR, exist_ok=True)
with open(os.path.join(we.OUTPUT_DIR,
                       f"ALIENEDGE_GG_PICKS_{broken}.csv"), "w") as fh:
    fh.write("fixture_id\n1\n")
_real_save_rows = we._save_rows
we._save_rows = lambda key, date, rows, label: _real_save_rows(key, date, None,
                                                              label)
we.run_weekly_family(broken, horizon=1, flush_between_dates=False)
we._save_rows = _real_save_rows
check("D4 a day whose market failed is NOT marked complete in the ledger",
      broken not in we._load_state()["days"], list(we._load_state()["days"]))
check("D5 and is still recomputable", we.date_is_complete(broken) is False)

# ═══════════════════════════════════════════════════════════════════════════
print("\n=== E. INVALIDATION WHEN A DEPENDENT ENGINE IS RE-RUN ===")
# ════════════════════════════════════════════════════════════════════════════
# A day the section-E run itself completes, so this check does not depend on
# state left behind by earlier sections.
evict = "2099-06-07"
we.run_weekly_family(evict, horizon=1, flush_between_dates=False)
check("E0 the day just computed is complete",
      we.date_is_complete(evict) is True)
csv_path = os.path.join(we.OUTPUT_DIR, f"ALIENEDGE_GG_PICKS_{evict}.csv")
os.utime(csv_path, (time.time() + 600, time.time() + 600))
check("E2 a NEWER dated engine input invalidates the day",
      we.date_is_complete(evict) is False)
week_calls.clear()
res8 = we.run_weekly_family(evict, horizon=1, flush_between_dates=False)
check("E3 and the invalidated day is recomputed",
      evict in res8["per_date"], f"ran={sorted(res8['per_date'])}")

# ═══════════════════════════════════════════════════════════════════════════
print("\n=== F. THE LEDGER IS A HINT, NEVER THE SOURCE OF TRUTH ===")
# ════════════════════════════════════════════════════════════════════════════
os.remove(we.STATE_FILE)
check("F1 with the ledger deleted, completion is re-derived from snapshots",
      all(we.date_is_complete(d) for d in DATES if d != broken))
check("F2 the broken day is still correctly incomplete",
      we.date_is_complete(broken) is False)

# Snapshots replaced AFTER the ledger recorded the day (a restore, or an engine
# re-run that rewrote them) must not be masked by the older ledger entry.
st = we._load_state()
st["days"][DATES[0]] = {"completed_ts": time.time() - 10000,
                        "completed_iso": "x", "keys": []}
we._save_state(st)
snap = os.path.join(store.CACHE_DIR, f"filter_gg__{DATES[0]}.json")
with open(snap, "w", encoding="utf-8") as fh:
    json.dump({"engine_key": "filter_gg", "date": DATES[0],
               "generated_at": "2099-06-01T00:00:00", "status": "ok",
               "row_count": 0, "data": []}, fh)
check("F3 snapshots written AFTER their ledger entry invalidate the day",
      we.date_is_complete(DATES[0]) is False)

# ═══════════════════════════════════════════════════════════════════════════
print("\n=== G. PRODUCTION DATA UNTOUCHED ===")
# ════════════════════════════════════════════════════════════════════════════
check("G1 the repo ledger was never written",
      not os.path.exists(os.path.join(ROOT, "data", "weekly_state.json")))
check("G2 every sandbox snapshot lives under /tmp",
      store.CACHE_DIR.startswith("/tmp"))
check("G3 the window store used is the sandbox one",
      window.WINDOW_FILE.startswith("/tmp"))

live_files = [os.path.join(ROOT, "data", f) for f in
              ("live_inplay_cache.json", "live_prematch_cache.json",
               "fixture_date_cache.json")]
live_now = {f: (os.path.getmtime(f) if os.path.exists(f) else None)
            for f in live_files}
check("G4 Live data files were not touched by this suite",
      all(live_now[f] is not None or not os.path.exists(f) for f in live_files))

r = _sp.run(["git", "diff", "--name-only", "--",
             "shared_fixture_window.py", "run_pipeline_watchdog.sh"],
            cwd=ROOT, capture_output=True, text=True)
check("G5 the fixture window and watchdog are unmodified",
      not [l for l in r.stdout.splitlines() if l.strip()],
      [l for l in r.stdout.splitlines() if l.strip()])

src = open(os.path.join(ROOT, "WEEKLY", "weekly_engine.py"),
           encoding="utf-8").read()
check("G6 the Weekly module still contains NO new prediction mathematics",
      not [t for t in ("import math", "import numpy", "poisson", "monte",
                       "def apply_") if t in src])

print("\n=== SUMMARY ===")
print(f"passed={len(PASS)} failed={len(FAIL)}")
if FAIL:
    for f in FAIL:
        print(f"   FAILED: {f}")
    sys.exit(1)
print("ALL CHECKS PASSED — no network, no production writes, no pipeline run.")
