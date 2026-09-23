import os
import sys
import time
import gc
import json
import csv
import random
import requests
import traceback
from datetime import datetime, timedelta

import output_store as store

# ==============================================================================
# 1. THE HIJACK (GLOBAL TRAFFIC WARDEN & CONTROLLED CACHE)
# ==============================================================================
# The traffic warden now lives in api_cache.py so BOTH the pipeline and the
# shared future-fixture window use one implementation. Every name this module
# used to expose is re-exported here with identical semantics:
#   GLOBAL_API_CACHE        — the same dict object (raw JSON payloads)
#   CachedResponseWrapper   — the same class
#   smart_get(url, params=None, **kwargs) — the same signature and cache key
#   requests.get = smart_get — the same process-wide hijack
#   flush_system_ram()      — the same memory reset between phases (OOM guard)
# The layer is still the umbrella protecting EVERY engine and EVERY acquisition
# path; nothing is bypassed, removed or weakened.
import api_cache
from api_cache import (GLOBAL_API_CACHE, CachedResponseWrapper, smart_get,
                       original_get)

def flush_system_ram():
    """
    Clears the in-memory response cache and runs explicit garbage collection
    between pipeline phases to permanently eliminate Out-Of-Memory (OOM) kills.

    Now delegates to api_cache.flush_memory(), which clears exactly the same
    GLOBAL_API_CACHE plus the layer's own metadata/alias index (so no stale alias
    can survive a flush) and releases the window's single in-RAM day copy. The
    on-disk shared window is untouched — it is the durable store, which is why a
    post-flush fixture request is still served with ZERO API calls.
    """
    api_cache.flush_memory()
    gc.collect()

api_cache.install()


# ==============================================================================
# 2. PRE-MATCH PIPELINE IMPORTS (STRICTLY PRE-MATCH ONLY)
# ==============================================================================

# --- PHASE A: CORE BRAIN & FOUNDATION ENGINES ---
from CORE.dna_profiler import run_dna_profiler
from CORE.dna_engine_v2 import run_dna_engine_v2
from CORE.dna_v2_market_factors import build_market_factor_counts
from Engine.underdog_engine import run_underdog_engine
from Engine.master_underdog_audit import run_underdog_master_engine
from CORE.handshake_logic import run_total_visibility_merger
from Engine.win_forecast import run_win_forecast_engine
from Engine.sh_gg_winner import run_sh_gg_winner_engine

# --- PHASE B: THE PSYCHOLOGY LAYER ---
from PSYCHOLOGY.corner_psychology import run_corner3_psychology_engine
from PSYCHOLOGY.gg_psychology import run_gg_psychology_engine
from PSYCHOLOGY.over25_psychology import run_o25_psychology_engine
from PSYCHOLOGY.win_psychology import run_win_psychology_engine
from PSYCHOLOGY.u2s_psychology import run_u2s_psychology_engine

# --- PHASE C: THE CORNER EMPIRE ---
from Engine.corner_miner import run_corner_engine_stage1
from Engine.corner_refiner import run_corner_engine_stage2
from Engine.corner_catalyst import run_catalyst_corner_engine
from AGGREGATOR.corner4_aggregator import run_corner4_aggregator_engine

# --- PHASE D: THE GG EMPIRE ---
from Engine.gg_precision_engine import run_gg_o15_engine
from AGGREGATOR.gg_forensics_audit import run_gg_forensic_aggregator
from AGGREGATOR.gg_supreme_vip import run_supreme_gg_aggregator

# --- PHASE E: THE OVER 2.5 EMPIRE ---
from Engine.over25_probabilistic import run_over25_stage1
from Engine.over25_council import run_over25_stage2
from AGGREGATOR.over25_killswitch import run_over25_stage3
from Engine.gold_over25 import run_gold_over_25_engine
from AGGREGATOR.over25_apex import run_over25_aggregator
from Engine.over25_forecast import run_over25_forecast_engine

# --- PHASE F: THE OVER 1.5 EMPIRE ---
from Engine.over15_stage3 import run_over15_stage3
from PSYCHOLOGY.over15_psychology import run_o15_psychology_engine
from AGGREGATOR.over15_apex import run_o15_apex_engine

# --- PHASE G: REGIONAL PRECISION ENGINES ---
from Engine.draw_engine import run_draw_engine
from Engine.unders_engine import run_unders_engine
from Engine.sot_engine import run_sot_engine
from Engine.fhvi_engine import run_fhvi_engine
from Engine.shvi_engine import run_shvi_engine

# --- PHASE H: WINS, UNDERDOGS & SH MASTER ---
from AGGREGATOR.win_apex_aggregator import run_win_apex_aggregator
from Engine.sh_master_vortex import run_sh_master_vortex
from AGGREGATOR.sh_8goal_aggregator import run_sh_gg_8goal_aggregator
from AGGREGATOR.apex_ud_aggregator import run_apex_underdog_aggregator
from Engine.win_raw_engine import run_win_raw_engine

# --- PHASE I: REAL FILTER ENGINES (FROM FILTER/) ---
from FILTER.gg_precision_filter import run_gg_precision_filter
from FILTER.over25_risk_filter import run_over25_filter_aggregator
from FILTER.win_filter_service import run_win_filter_service


# ==============================================================================
# 3. FAULT-TOLERANT EXECUTION BARRIER — now saves output on success
# ==============================================================================
def _normalize_fixture_schema(payload):
    """
    Ensures case-insensitive compatibility between engines producing 'Fixture'
    and api/main.py expecting lowercase 'fixture'.
    """
    if isinstance(payload, list):
        for row in payload:
            if isinstance(row, dict) and "Fixture" in row and "fixture" not in row:
                row["fixture"] = row["Fixture"]
    elif isinstance(payload, dict):
        if "Fixture" in payload and "fixture" not in payload:
            payload["fixture"] = payload["Fixture"]
        if "data" in payload and isinstance(payload["data"], list):
            for row in payload["data"]:
                if isinstance(row, dict) and "Fixture" in row and "fixture" not in row:
                    row["fixture"] = row["Fixture"]
    return payload


# Verified per-key recovery map (RULE 4/5). Each save_key may ONLY recover
# from legacy /output/ files that its OWN engine writes (filenames confirmed
# against the module sources). No cross-market entries and no glob/filename
# discovery — a key absent here has no recovery sources at all.
_RECOVERY_SOURCES = {
    # ── CORNER EMPIRE (engines return None after writing) ──
    "corners_stage1":     ["corner3_qualified.json"],                # Engine/corner_miner.py
    "corners_stage2":     ["backend_2_output.json"],                 # Engine/corner_refiner.py:919
    "corners_catalyst":   ["tactical_brain_output.json"],            # Engine/corner_catalyst.py
    "corners_aggregator": ["SUPREME_EVOLUTION_OUTPUT_{date}.csv"],   # AGGREGATOR/corner4_aggregator.py:1072
    # ── WIN EMPIRE ──
    "win_forecast":       ["ranked_win_forecast_{date}.csv"],        # Engine/win_forecast.py:312
    # ── UNDERDOG ──
    "underdog_base":      ["backtest_underdog_{date}.json",          # Engine/underdog_engine.py
                           "backtest_underdog_{date}.csv"],
    "underdog_audit":     ["audited_underdog_backtest_{date}.json",  # Engine/master_underdog_audit.py
                           "audited_underdog_backtest_{date}.csv"],
    "underdog_apex":      ["FINAL_APEX_UD_SCORE_{date}.csv"],        # AGGREGATOR/apex_ud_aggregator.py
    # ── OVER 2.5 / OVER 1.5 ──
    "over25_stage1":      ["over25_stage1_picks.json",               # Engine/over25_probabilistic.py
                           "over25_stage1_picks.csv"],
    "over25_stage2":      ["over25_stage2_picks.json",               # Engine/over25_council.py
                           "over25_stage2_picks.csv"],
    "over25_stage3":      ["over25_stage3_final.json",               # AGGREGATOR/over25_killswitch.py
                           "over25_stage3_final.csv"],
    "over15_stage3":      ["over15_stage3_final.json",               # Engine/over15_stage3.py
                           "over15_stage3_final.csv"],
    # ── GG EMPIRE ──
    "sh_gg_winner":       ["sh_gg_winner_feed.json"],                # Engine/sh_gg_winner.py
    "gg_o15":             ["gg_o15_feed_{date}.json",                # Engine/gg_precision_engine.py
                           "ALIENEDGE_GG_PICKS_{date}.csv",
                           "ALIENEDGE_O15_PICKS_{date}.csv"],
    "gg_forensics":       ["JUDGED_GG_PICKS_{date}.csv"],            # AGGREGATOR/gg_forensics_audit.py
    "gg_psychology":      ["ALIENEDGE_GG_PSYCHOLOGY_FINAL_{date}.csv"],  # PSYCHOLOGY/gg_psychology.py
    # ── SH MASTER ──
    "sh_master":          ["shvi_vortex_report_{date}.json",         # Engine/sh_master_vortex.py
                           "shvi_vortex_report_{date}.csv"],
}


def _recover_engine_output_from_disk(save_key, save_date=None, engine_name="", func=None):
    """
    If an engine wrote its results directly to disk in /output/ (CSV or JSON)
    instead of returning them to memory, this finds, parses, and loads the data
    so output_store can register it into output/cache/.
    """
    out_dir = "/var/www/backend/output"
    if not os.path.exists(out_dir):
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    if not os.path.exists(out_dir):
        return None

    d_str = str(save_date) if save_date else ""

    # RULE 4/5: candidates are strictly the files THIS save_key's engine
    # writes. Unknown keys (filter_*, gg_supreme, ...) recover nothing.
    candidates = [
        os.path.join(out_dir, template.format(date=d_str))
        for template in _RECOVERY_SOURCES.get(save_key, [])
    ]

    for target_path in candidates:
        if not target_path or not os.path.exists(target_path):
            continue
        try:
            # Skip empty 0-byte files
            if os.path.getsize(target_path) == 0:
                continue

            if target_path.endswith(".json"):
                with open(target_path, "r", encoding="utf-8") as jf:
                    data = json.load(jf)
                    if data:
                        return _normalize_fixture_schema(data)
            elif target_path.endswith(".csv"):
                with open(target_path, "r", encoding="utf-8") as cf:
                    reader = csv.DictReader(cf)
                    rows = list(reader)
                    if rows:
                        return _normalize_fixture_schema(rows)
        except Exception:
            continue

    return None


def _safe_exec(engine_name, func, *args, save_key=None, save_date=None, **kwargs):
    """
    Executes a mathematical engine safely. Checks both in-memory return values
    AND physical disk files in /var/www/backend/output/ so that engines which
    write directly to disk are seamlessly captured and persisted to output/cache/.

    If save_key is given, the successful result is written to
    output/cache/{save_key}__{save_date or 'latest'}.json via output_store —
    this is the ONLY place any engine's result gets persisted, and it's the
    exact same lookup key api/main.py reads. Nothing is ever guessed.
    """
    try:
        print(f"\n> ⚙️ Initializing: {engine_name}...")
        res = func(*args, **kwargs)

        # ── DISK FALLBACK CHECK ───────────────────────────────────────────────
        # RULE 1-3: a legitimate [] is a final result and is saved as-is;
        # recovery only for an explicit None, only from this key's own files.
        if res is None and save_key is not None:
            disk_res = _recover_engine_output_from_disk(save_key, save_date, engine_name, func)
            if disk_res is not None and (not hasattr(disk_res, "__len__") or len(disk_res) > 0):
                print(f"   📂 Recovered {len(disk_res) if hasattr(disk_res, '__len__') else 'data'} items from disk output.")
                res = disk_res

        # Schema normalization (Fixture -> fixture)
        if res is not None:
            res = _normalize_fixture_schema(res)

        if save_key is not None:
            if res is None:
                # None-with-no-recovery is an explicit failure state, not "ok"
                # with null data (store docstring: failures go through
                # save_failure so /api/status can tell them apart).
                path = store.save_failure(save_key, save_date,
                                          error=f"{engine_name}: returned None (no disk fallback)")
                print(f"   ⚠️ recorded failure -> {path}")
            else:
                # ── 429-DEGRADED GUARD ────────────────────────────────────
                # A critical engine returning a 0-row result while the shared
                # 429 cooldown gate is active means the run was starved, not
                # that tomorrow has no football. Retry (gate-aware), and only
                # persist as "degraded" — never as a green "ok" empty day —
                # when the retries cannot recover rows.
                if (save_key in CRITICAL_MARKET_KEYS
                        and res is not None and not res
                        and _429_gate_remaining() > 0):
                    recovered = _retry_starved_engine(engine_name, func, args, kwargs)
                    if recovered is not None:
                        res = _normalize_fixture_schema(recovered)
                    else:
                        path = store.save(save_key, save_date, res,
                                          status="degraded",
                                          error=(f"{engine_name}: 0 rows while 429 "
                                                 f"cooldown gate active"),
                                          guard=bool(save_date))
                        print(f"   ⚠️ saved DEGRADED (0 rows under 429 gate) -> {path}")
                        return res
                # SNAPSHOT GUARD (Batch A): date-scoped writes are guarded so a
                # run that fetched a suspiciously collapsed fixture universe
                # (the 2026-09-15 evening run saw 3 fixtures instead of 63) can
                # never replace a good same-date snapshot. `guard=bool(save_date)`
                # keeps the two '__latest' keys (save_date=None) unguarded, since
                # a non-date file has no date universe to compare.
                path = store.save(save_key, save_date, res, guard=bool(save_date))
                print(f"   💾 saved -> {path}")
        return res
    except Exception as e:
        print(f"⚠️ [NON-CRITICAL ENGINE NOTICE in {engine_name}]: {e}")
        
        # Before declaring failure, verify if disk or existing cache holds valid data
        recovered = None
        if save_key is not None:
            recovered = _recover_engine_output_from_disk(save_key, save_date, engine_name, func)
            if recovered is not None:
                recovered = _normalize_fixture_schema(recovered)
                path = store.save(save_key, save_date, recovered, guard=bool(save_date))
                print(f"   💾 rescued from disk -> {path}")
                return recovered

            # Check if cache file already exists with good data from a previous run
            existing_cache = f"/var/www/backend/output/cache/{save_key}__{save_date or 'latest'}.json"
            if os.path.exists(existing_cache) and os.path.getsize(existing_cache) > 200:
                print(f"   🛡️ Retained existing valid cache: {existing_cache}")
                return None

            # Only record explicit failure if neither memory, disk, nor cache had data
            store.save_failure(save_key, save_date, error=f"{engine_name}: {e}")
        return None

# ==============================================================================
# 4. 429-DEGRADED RUN GUARD — never persist a starved empty day as "ok"
# ==============================================================================
# The 2026-09-18 outage: the 23:30 pipeline ran while the shared SportMonks 429
# cooldown gate was active. Starved feeds returned "Feed is empty" and every
# critical engine legitimately saved a 0-row snapshot with status "ok" — which
# the API then served all day as an honest-but-blank market page.
#
# Fix: a CRITICAL engine that returns a 0-row result while a 429 gate window is
# ACTIVE is (a) retried up to twice with gate-aware waits (this is a background
# job — waiting is free) and, if every retry stays empty, (b) persisted with
# status "degraded" instead of "ok" so /api/status and the 06:00 second-chance
# re-run can tell a genuinely quiet day from a starved one.
CRITICAL_MARKET_KEYS = {
    "dna", "dna_v2", "dna_market_factors",
    "underdog_base", "underdog_audit", "calibration", "underdog_apex",
    "win_forecast", "sh_gg_winner",
    "corners_stage1", "corners_stage2", "corners_psychology",
    "corners_catalyst", "corners_aggregator",
    "gg_o15", "gg_forensics", "gg_psychology", "gg_supreme",
    "over25_stage1", "over25_stage2", "over25_stage3", "over25_psychology",
    "over25_gold", "over25_apex", "over25_forecast",
    "over15_stage3", "over15_psychology", "over15_apex",
    "unders", "draw", "sot", "fhvi", "shvi", "u2s_psychology",
    "win_psychology", "win_apex", "sh_master", "sh_8goal", "win_raw",
    "filter_gg",
    "filter_win__safe", "filter_win__balanced", "filter_win__aggressive",
    "filter_over25__banker", "filter_over25__balanced",
    "filter_over25__aggressive",
}

_GATE_LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "data", "api_429_cooldown.lock")
_DEGRADED_RETRY_DELAYS = (180.0, 300.0)  # 3 min, then 5 min
_RETRY_BUDGET_S = 2700.0                 # total retry wait budget per run (45 min)
_retry_budget_used = 0.0


def _429_gate_remaining() -> float:
    """Seconds left in an ACTIVE shared 429 cooldown window, else 0."""
    try:
        with open(_GATE_LOCK_FILE, "r") as f:
            gate = json.load(f)
        return max(0.0, float(gate.get("until", 0)) - time.time())
    except Exception:
        return 0.0


def _retry_starved_engine(engine_name, func, args, kwargs):
    """Gate-aware retry of a critical engine that returned 0 rows while a 429
    cooldown gate was active. Returns the recovered result, or None when every
    attempt stayed empty (caller then records status='degraded')."""
    global _retry_budget_used
    for attempt, wait_s in enumerate(_DEGRADED_RETRY_DELAYS, start=1):
        if _retry_budget_used + wait_s > _RETRY_BUDGET_S:
            print(f"   ⏳ [{engine_name}] retry wait budget exhausted "
                  f"({_retry_budget_used:.0f}s used) — recording degraded")
            return None
        _retry_budget_used += wait_s
        print(f"   ⏳ [{engine_name}] 0 rows under active 429 gate — retry "
              f"{attempt}/{len(_DEGRADED_RETRY_DELAYS)} in {wait_s:.0f}s")
        time.sleep(wait_s)
        gate_left = _429_gate_remaining()
        if gate_left > 0:
            # Jittered + capped pacing (was a bare sleep of the full remaining
            # window, up to 300s): stagger the wake-up so the retry does not
            # collide with every sibling, and never wait more than 60s before
            # attempting the wire anyway — a live 429 with its server-provided
            # backoff is far better information than another blind sleep.
            import random as _random
            pace = min(gate_left, 60.0) + _random.random() * 5.0
            if _retry_budget_used + pace > _RETRY_BUDGET_S:
                print(f"   ⏳ [{engine_name}] retry wait budget exhausted — "
                      f"recording degraded")
                return None
            _retry_budget_used += pace
            print(f"   ⏳ [{engine_name}] gate still active — pacing {pace:.0f}s")
            time.sleep(pace)
        try:
            retry_res = func(*args, **kwargs)
        except Exception as e:
            print(f"   ⚠️ [{engine_name}] retry {attempt} threw: {e}")
            continue
        if retry_res:
            print(f"   ✅ [{engine_name}] retry {attempt} recovered "
                  f"{len(retry_res) if hasattr(retry_res, '__len__') else 'data'} rows")
            return retry_res
        print(f"   ⚠️ [{engine_name}] retry {attempt} still empty")
    return None


# ==============================================================================
# 4b. SHARED FUTURE FIXTURE ACQUISITION + WEEKLY FAMILY WIRING
# ==============================================================================
# PHASE 0 (below) prepares the reusable future-fixture window BEFORE any consumer
# runs, so PREMATCH and WEEKLY share the same seven future dates and no engine
# re-acquires a fixture list another consumer already has. The window itself sits
# UNDER the global API cache: every fetch it makes goes through smart_get.
#
# Both switches are additive — the default nightly run keeps its existing
# behaviour and phase order, and every failure here is non-fatal:
#   ALIENEDGE_FUTURE_WINDOW=0 / --no-window   disable the PHASE 0 window fill
#   ALIENEDGE_WEEKLY=1        / --weekly      also run the Weekly family (phase 12)
#   --weekly-only                             fill window + Weekly family, exit
WINDOW_HORIZON_DAYS = 7


def _env_flag(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in ("0", "false", "no", "off", "")


def window_enabled():
    return _env_flag("ALIENEDGE_FUTURE_WINDOW", True) and "--no-window" not in sys.argv


def weekly_enabled():
    return _env_flag("ALIENEDGE_WEEKLY", False) or "--weekly" in sys.argv


def fill_shared_future_window(target_date, horizon=WINDOW_HORIZON_DAYS):
    """PHASE 0 — acquire/roll the canonical 7-day future-fixture window.

    Rolling (never a full refetch): dates that left the horizon are evicted and
    only the newly required day is acquired. Non-fatal by design — if this fails
    (e.g. a 429 storm) every consumer simply falls through to its normal cached
    SportMonks call, i.e. exactly the pre-existing behaviour.
    """
    print(f"\n[PHASE 0] SHARED FUTURE FIXTURE ACQUISITION — 7-day window "
          f"anchored on {target_date}...")
    try:
        import shared_fixture_window as window
        return window.fill_window(target_date, horizon=horizon)
    except Exception as e:
        print(f"   ⚠️ [WINDOW] fill failed (non-fatal, pipeline continues): {e}")
        return None


def run_fixture_risk_classification(target_date, horizon=WINDOW_HORIZON_DAYS):
    """PHASE 0b — label EVERY window fixture as league / CUP / FRIENDLY.

    Runs the moment the shared window is filled, so the flags are derived from
    the SAME canonical payload every prematch engine is served — no extra API
    call, no second source of truth. Persisted PER DATE (output_store
    `fixture_risk__{date}.json`) because the window is rolling: the flags must
    outlive the 7-day horizon so historical pages can still show them.

    Non-fatal by design: a failure here only means the UI shows no warning, and
    every engine keeps running exactly as before.
    """
    print(f"\n[PHASE 0b] FIXTURE RISK CLASSIFICATION (cup / friendly) — {target_date}...")
    try:
        import fixture_classification as fc
        import shared_fixture_window as window
        dates = window.window_dates(target_date, horizon)
        saved, totals = {}, {"fixtures": 0, "cup": 0, "friendly": 0, "unknown": 0}
        for date in dates:
            rows = fc.build_window_flags([date])
            # guard=False: this is a COMPLETE per-date fixture inventory (one row
            # per fixture in the window), not an engine's filtered pick universe,
            # so the same-date collapse guard does not apply to it.
            saved[date] = store.save("fixture_risk", date, rows)
            for key in totals:
                totals[key] += fc.summary(rows).get(key, 0)
        print(f"   🏷️  {totals['fixtures']} fixtures labelled — "
              f"🏆 CUP {totals['cup']} · 🤝 FRIENDLY {totals['friendly']} · "
              f"❔ unknown {totals['unknown']} (dates: {', '.join(dates)})")
        return {"dates": dates, "totals": totals, "saved": saved}
    except Exception as e:
        print(f"   ⚠️ [FIXTURE RISK] classification failed (non-fatal, no labels): {e}")
        return None


def backfill_fixture_risk(target_date):
    """Backfill the cup/friendly labels for ONE already-processed date.

    Historical dates have left the rolling window, so their labels cannot be
    derived. This classifies a single day WITHOUT touching the window's other
    days (fill_window would evict them) and WITHOUT any network call when the
    day is still stored:

      * day already in the window store -> classify it (offline), or
      * day missing -> ONE acquisition through the window's own cached fetch
        (`fetch_day`, i.e. through the global API cache / 429 guards), then
        classify.

    Never rolls, never evicts, never refetches a day it already holds.
    """
    import fixture_classification as fc
    import shared_fixture_window as window

    date = str(target_date)[:10]
    store_obj = window._load_store()
    entry = (store_obj.get("days") or {}).get(date)
    if not (entry and entry.get("acquisition_ok")):
        print(f"   ↻ [FIXTURE RISK] {date} not in the window — one cached acquisition")
        entry = window.fetch_day(date)
        if entry:
            store_obj["days"][date] = entry          # additive: nothing evicted
            store_obj["updated_at"] = datetime.now(timezone.utc).isoformat()
            window._save_store(store_obj)
    rows = fc.build_window_flags([date])
    if not rows:
        print(f"   ⚠️ [FIXTURE RISK] no window data for {date} — cannot label it")
        return None
    path = store.save("fixture_risk", date, rows)
    totals = fc.summary(rows)
    print(f"   🏷️  {date}: {totals['fixtures']} fixtures labelled — "
          f"🏆 CUP {totals['cup']} · 🤝 FRIENDLY {totals['friendly']} · "
          f"❔ unknown {totals['unknown']} -> {path}")
    return {"date": date, "totals": totals, "path": path}


def run_weekly_phase(target_date, horizon=WINDOW_HORIZON_DAYS):
    """PHASE 12 — the Weekly engine family (GG / WIN / O2.5) over the window.

    Composes the EXISTING AlienEdge intelligence (see WEEKLY/weekly_engine.py) and
    persists each date's rows through output_store under the same keys the
    existing Weekly API routes already read. Non-fatal by design.
    """
    print("\n" + "=" * 115)
    print(f"{'📅 PHASE 12: WEEKLY ENGINE FAMILY (GG / WIN / O2.5)':^115}")
    print("=" * 115)
    try:
        from WEEKLY.weekly_engine import run_weekly_family
        return run_weekly_family(target_date, horizon=horizon)
    except Exception as e:
        print(f"   ⚠️ [WEEKLY] family failed (non-fatal): {e}")
        traceback.print_exc()
        return None


# ==============================================================================
# 5. THE SUPREME MASTER PIPELINE (PURE PRE-MATCH ARCHITECTURE)
# ==============================================================================

# ==============================================================================
# 4. THE SUPREME MASTER PIPELINE (PURE PRE-MATCH ARCHITECTURE)
# ==============================================================================
def alienedge_master_system(cli_date_override: str = None):
    print("\n" + "█"*115)
    print(f"{'🚀 ALIENEDGE SUPER-MATRIX COMMAND CENTER v11.0':^115}")
    print(f"{'THE TOTAL FORENSIC & PSYCHOLOGICAL PRE-MATCH BETTING MACHINE':^115}")
    print("█"*115)

    # ── CLI ARGUMENT & DATE RESOLUTION ────────────────────────────────────────
    cli_date = cli_date_override
    if not cli_date:
        for arg in sys.argv[1:]:
            if arg.startswith("--date="):
                cli_date = arg.split("=")[1].strip()

    if cli_date:
        target_date = cli_date
        print(f"\n📅 [TARGET DATE]: {target_date}")
    else:
        try:
            target_date = input("\n📅 Enter Target Date (YYYY-MM-DD) or [Enter] for Today: ").strip()
        except (EOFError, OSError):
            target_date = ""

        if not target_date:
            target_date = datetime.now().strftime("%Y-%m-%d")

    d = target_date  # shorthand used below in save_date=

    start_time = time.time()

    # ── PHASE 0: SHARED FUTURE FIXTURE ACQUISITION ───────────────────────────
    # Prepares the reusable 7-day future-fixture window BEFORE any consumer, so
    # PREMATCH (whose target date is the window's first day) and WEEKLY read the
    # same future fixture data instead of each acquiring it. Fixture identity for
    # the window's dates is then served to every engine by the global API cache
    # with zero extra API calls. Failure is non-fatal: engines fall back to their
    # normal cached calls.
    if window_enabled():
        fill_shared_future_window(target_date)
        # PHASE 0b: label every window fixture CUP / FRIENDLY from that same
        # canonical payload (no extra API call) and persist it per date, so every
        # page can warn the user on cup/friendly picks.
        run_fixture_risk_classification(target_date)

    # ── PHASE 1: FOUNDATION & DNA IDENTITY ───────────────────────────────────
    print(f"\n[PHASE 1] INITIALIZING DNA, UNDERDOGS, AND FOUNDATION MATH for {target_date}...")
    # DNA Engine V2 must run BEFORE the profiler: the profiler scopes its
    # return to this date by reading the engine's home_id/away_id clash rows
    # off disk — running profiler-first would always read the PREVIOUS run's
    # clashes (different date or pre-id format) and silently fall back to the
    # full global library. Market factors last (reads both outputs).
    _safe_exec("DNA Engine V2", run_dna_engine_v2, target_date, save_key="dna_v2", save_date=d)
    _safe_exec("DNA Profiler", run_dna_profiler, target_date, save_key="dna", save_date=d)
    _safe_exec("DNA Market Factors", build_market_factor_counts, target_date, save_key="dna_market_factors", save_date=d)

    _safe_exec("Underdog Base Engine", run_underdog_engine, target_date, save_key="underdog_base", save_date=d)
    _safe_exec("Underdog Master Engine", run_underdog_master_engine, target_date, save_key="underdog_audit", save_date=d)
    _safe_exec("Total Visibility Merger", run_total_visibility_merger, target_date, save_key="calibration", save_date=d)
    _safe_exec("Apex Underdog Aggregator", run_apex_underdog_aggregator, target_date, save_key="underdog_apex", save_date=d)
    _safe_exec("Win Forecast Base Engine", run_win_forecast_engine, target_date, save_key="win_forecast", save_date=d)
    _safe_exec("SH-GG Winner Engine", run_sh_gg_winner_engine, target_date, save_key="sh_gg_winner", save_date=d)

    flush_system_ram()

    # ── PHASE 2: SECTIONAL HARVESTS ─────────────────────────────────────────
    print("\n" + "="*115)
    print(f"{'🧠 INITIATING SUPER-MATRIX: SECTIONAL HARVESTS':^115}")
    print("="*115)

    # 1. Corners Empire
    print("\n> 🚩 Processing Corner Empire...")
    _safe_exec("Corner Stage 1 (Miner)", run_corner_engine_stage1, target_date, save_key="corners_stage1", save_date=d)
    _safe_exec("Corner Stage 2 (Refiner)", run_corner_engine_stage2, target_date, save_key="corners_stage2", save_date=d)
    _safe_exec("Corner Stage 3 (Psychology)", run_corner3_psychology_engine, target_date, save_key="corners_psychology", save_date=d)
    _safe_exec("Corner Catalyst Engine", run_catalyst_corner_engine, target_date, save_key="corners_catalyst", save_date=d)
    _safe_exec("Corner Stage 4 Aggregator", run_corner4_aggregator_engine, target_date, save_key="corners_aggregator", save_date=d)
    flush_system_ram()

    # 2. GG & Over 1.5 Unified Head — returns (gg, o15) tuple, saved as one composite file
    print("\n> ⚽ Running Unified GG & Over 1.5 Precision Head Engine...")
    _safe_exec("Unified GG & O1.5 Head Engine", run_gg_o15_engine, target_date, verbose=False, save_key="gg_o15", save_date=d)

    # 3. GG Forensic Pipeline
    print("\n> ⚽ Processing Downstream GG Forensics...")
    _safe_exec("GG Forensic Aggregator", run_gg_forensic_aggregator, target_date, save_key="gg_forensics", save_date=d)
    _safe_exec("GG Psychology Engine", run_gg_psychology_engine, target_date, save_key="gg_psychology", save_date=d)
    _safe_exec("Supreme GG VIP Aggregator", run_supreme_gg_aggregator, target_date, save_key="gg_supreme", save_date=d)
    flush_system_ram()

    # 4. Over 2.5 Goals Pipeline
    print("\n> 🔥 Processing Over 2.5 Goals Pipeline...")
    _safe_exec("Over 2.5 Stage 1 (Probabilistic)", run_over25_stage1, target_date, save_key="over25_stage1", save_date=d)
    _safe_exec("Over 2.5 Stage 2 (Council)", run_over25_stage2, target_date, save_key="over25_stage2", save_date=d)
    _safe_exec("Over 2.5 Stage 3 (Killswitch)", run_over25_stage3, target_date, save_key="over25_stage3", save_date=d)
    _safe_exec("Over 2.5 Psychology Engine", run_o25_psychology_engine, target_date, save_key="over25_psychology", save_date=d)
    _safe_exec("Gold Over 2.5 Engine", run_gold_over_25_engine, target_date, save_key="over25_gold", save_date=d)
    _safe_exec("Over 2.5 Apex Aggregator", run_over25_aggregator, target_date, save_key="over25_apex", save_date=d)
    _safe_exec("Over 2.5 Forecast Engine", run_over25_forecast_engine, target_date, save_key="over25_forecast", save_date=d)
    flush_system_ram()

    # 5. Over 1.5 Goals Pipeline
    print("\n> ⚡ Processing Over 1.5 Goals Pipeline...")
    _safe_exec("Over 1.5 Stage 3", run_over15_stage3, target_date, save_key="over15_stage3", save_date=d)
    _safe_exec("Over 1.5 Psychology Engine", run_o15_psychology_engine, target_date, save_key="over15_psychology", save_date=d)
    _safe_exec("Over 1.5 Apex Aggregator", run_o15_apex_engine, target_date, save_key="over15_apex", save_date=d)
    flush_system_ram()

    # 6. Defensive Under Empire — returns (u25, u35) tuple, saved as one composite file
    print("\n> 🛡️ Processing Defensive Under Empire...")
    _safe_exec("Unders Engine (U2.5 / U3.5)", run_unders_engine, target_date, verbose=False, save_key="unders", save_date=d)

    # 7. Draw Magnet Engine — returns (draws, parity, amateurs) tuple, saved as one composite file
    print("\n> ⚖️ Processing Draw Magnet Index...")
    _safe_exec("Draw Magnet Engine", run_draw_engine, target_date, verbose=False, save_key="draw", save_date=d)

    # 8. SOT Cerberus Engine
    print("\n> 🎯 Processing Cerberus S.O.T. Engine...")
    _safe_exec("SOT Cerberus Engine", run_sot_engine, target_date, verbose=False, save_key="sot", save_date=d)

    # 9. Half-Time Streak Miners
    print("\n> ⛏️ Processing Half-Time Streak Miners...")
    _safe_exec("FHVI First Half Engine", run_fhvi_engine, target_date, verbose=False, save_key="fhvi", save_date=d)
    _safe_exec("SHVI Second Half Engine", run_shvi_engine, target_date, verbose=False, save_key="shvi", save_date=d)
    flush_system_ram()

    # 10. Wins, U2S & SH Master Vortex
    print("\n> 🏆 Processing Win, U2S, & SH Elite Aggregation...")
    _safe_exec("U2S Psychology Engine", run_u2s_psychology_engine, target_date, save_key="u2s_psychology", save_date=d)
    _safe_exec("Win Psychology Engine", run_win_psychology_engine, target_date, save_key="win_psychology", save_date=d)
    # Win Apex DOES take a date argument (run_win_apex_aggregator(target_date)
    # uses it for every input CSV path — ranked_win_forecast_{date}.csv etc.).
    # DATE FIX (2026-09-23): it previously got NO date, so on the nightly run
    # (--date=tomorrow) it read TODAY's CSVs while its output was saved under
    # TOMORROW's key — the Win Intelligence table then showed yesterday's
    # fixtures. It is saved under save_date=None ('__latest') AND separately
    # snapshotted under this date so /api/status/{date} can show when it
    # last actually ran relative to the date being viewed.
    win_apex_result = _safe_exec("Win Apex Aggregator", run_win_apex_aggregator, target_date, save_key="win_apex", save_date=None)
    if win_apex_result is not None:
        store.save("win_apex", d, win_apex_result, guard=True)
    _safe_exec("SH Master Vortex", run_sh_master_vortex, target_date, save_key="sh_master", save_date=d)
    _safe_exec("SH-GG 8-Goal Aggregator", run_sh_gg_8goal_aggregator, target_date, save_key="sh_8goal", save_date=d)
    _safe_exec("Win Raw Probability Engine", run_win_raw_engine, target_date, save_key="win_raw", save_date=d)
    flush_system_ram()

    # 11. Real Filter Engines (Risk Modes)
    # main.py's own defaults (banker / safe) plus every OTHER risk level the
    # frontend's interactive Weekly Filter page can request (see
    # app/weekly/filter-config.ts) — precomputed here so that page never
    # needs a live engine call at request time either.
    print("\n> 🎯 Running FILTER/ Precision Engines...")
    gg_filter_result = _safe_exec("Filter GG Precision Filter", run_gg_precision_filter,
                                   target_date, save_key="filter_gg", save_date=d)
    if gg_filter_result is not None:
        # Conforms to the WIN / O2.5 daily-snapshot model: rows are this date's
        # fixture universe, so the collapse guard is NOT exempted for filter_gg.
        store.save("filter_gg", d, gg_filter_result, guard=True)

    for risk in ("banker", "balanced", "aggressive"):
        _safe_exec(f"Filter Over 2.5 Aggregator ({risk})", run_over25_filter_aggregator,
                    target_date, mode="public", risk_level=risk,
                    save_key=f"filter_over25__{risk}", save_date=d)

    for risk in ("safe", "balanced", "aggressive"):
        _safe_exec(f"Filter Win Service ({risk})", run_win_filter_service,
                    target_date, mode="public", risk_level=risk,
                    save_key=f"filter_win__{risk}", save_date=d)
    flush_system_ram()

    # ── PHASE 12: WEEKLY ENGINE FAMILY (opt-in) ──────────────────────────────
    # Runs the SAME existing GG / WIN / O2.5 intelligence over the shared 7-day
    # future window (PHASE 0) and writes each date's snapshots under the keys the
    # existing /api/filter/*/weekly routes already read. Opt-in so the default
    # nightly run is unchanged until it is switched on.
    if weekly_enabled():
        run_weekly_phase(target_date)

    # ── PIPELINE COMPLETION ──────────────────────────────────────────────────
    duration = round((time.time() - start_time) / 60, 2)
    print("\n" + "█"*115)
    print(f"{'✅ ALL PRE-MATCH SUPER-MATRIX HARVESTS COMPLETE':^115}")
    print(f"{f'Duration: {duration} minutes | Target Date: {target_date}':^115}")
    print(f"{'Pre-computed predictions, feeds, and analytics are fully saved to output/cache/.':^115}")
    print("█"*115)
    return target_date


def _needs_second_chance(key: str, date_str: str) -> bool:
    """True when a critical engine key for this date is missing, failed,
    degraded, or a list-key that ran 'ok' but produced zero rows. Composite
    dict payloads always carry a non-zero row_count (their dict length), so a
    starved composite is caught by its 'degraded' status instead."""
    try:
        st = store.load_status(key, date_str)
    except Exception:
        return True
    status = st.get("status", "missing")
    if status in ("missing", "failed", "degraded", "unreadable"):
        return True
    if status == "ok" and int(st.get("row_count", 0) or 0) == 0:
        return True
    return False


def alienedge_second_chance(target_date: str) -> int:
    """06:00 safety net: re-run ONLY the critical keys that are missing,
    failed, degraded, or empty for the target date. Full runs stay on the
    23:30 timer; this catches whatever that run starved (429) or failed."""
    print("\n" + "█" * 115)
    print(f"{'🛟 ALIENEDGE SECOND-CHANCE RECOVERY':^115}")
    print(f"{f'Target Date: {target_date}':^115}")
    print("█" * 115)

    stale = []
    seen = set()
    for key, label, func, extra in _second_chance_runners(target_date):
        if key in seen:
            continue
        seen.add(key)
        try:
            if _needs_second_chance(key, target_date):
                stale.append((key, label, func, extra))
        except Exception as e:
            print(f"   ⚠️ status check failed for {key}: {e}")
            stale.append((key, label, func, extra))

    if not stale:
        print("✅ All critical keys healthy for this date — nothing to do.")
        return 0

    print(f"🔎 {len(stale)} key(s) need a re-run: "
          + ", ".join(k for k, *_ in stale))
    for key, label, func, extra in stale:
        _safe_exec(label, func, target_date, save_key=key, save_date=target_date, **extra)
        flush_system_ram()

    print("\n✅ SECOND-CHANCE PASS COMPLETE")
    return 0


def _second_chance_runners(td: str):
    """(engine_key, label, callable, extra kwargs) for every critical key.
    Same phase imports the full pipeline uses, so the 429-degraded retry
    guard in _safe_exec applies here too. `td` keeps the signature parallel
    to the full pipeline; the current engines take only (date, ...)."""
    return [
        # DNA Engine V2 FIRST — run_dna_profiler scopes its return via the
        # engine's home_id/away_id clash rows (same ordering as the full
        # pipeline; profiler-first would read a stale/ID-less clashes file).
        ("dna_v2", "DNA Engine V2", run_dna_engine_v2, {}),
        ("dna", "DNA Profiler", run_dna_profiler, {}),
        ("dna_market_factors", "DNA Market Factors", build_market_factor_counts, {}),
        ("underdog_base", "Underdog Base Engine", run_underdog_engine, {}),
        ("underdog_audit", "Underdog Master Engine", run_underdog_master_engine, {}),
        ("calibration", "Total Visibility Merger", run_total_visibility_merger, {}),
        ("underdog_apex", "Apex Underdog Aggregator", run_apex_underdog_aggregator, {}),
        ("win_forecast", "Win Forecast Base Engine", run_win_forecast_engine, {}),
        ("sh_gg_winner", "SH-GG Winner Engine", run_sh_gg_winner_engine, {}),
        ("corners_stage1", "Corner Stage 1 (Miner)", run_corner_engine_stage1, {}),
        ("corners_stage2", "Corner Stage 2 (Refiner)", run_corner_engine_stage2, {}),
        ("corners_psychology", "Corner Stage 3 (Psychology)", run_corner3_psychology_engine, {}),
        ("corners_catalyst", "Corner Catalyst Engine", run_catalyst_corner_engine, {}),
        ("corners_aggregator", "Corner Stage 4 Aggregator", run_corner4_aggregator_engine, {}),
        ("gg_o15", "Unified GG & O1.5 Head Engine", run_gg_o15_engine, {"verbose": False}),
        ("gg_forensics", "GG Forensic Aggregator", run_gg_forensic_aggregator, {}),
        ("gg_psychology", "GG Psychology Engine", run_gg_psychology_engine, {}),
        ("gg_supreme", "Supreme GG VIP Aggregator", run_supreme_gg_aggregator, {}),
        ("over25_stage1", "Over 2.5 Stage 1 (Probabilistic)", run_over25_stage1, {}),
        ("over25_stage2", "Over 2.5 Stage 2 (Council)", run_over25_stage2, {}),
        ("over25_stage3", "Over 2.5 Stage 3 (Killswitch)", run_over25_stage3, {}),
        ("over25_psychology", "Over 2.5 Psychology Engine", run_o25_psychology_engine, {}),
        ("over25_gold", "Gold Over 2.5 Engine", run_gold_over_25_engine, {}),
        ("over25_apex", "Over 2.5 Apex Aggregator", run_over25_aggregator, {}),
        ("over25_forecast", "Over 2.5 Forecast Engine", run_over25_forecast_engine, {}),
        ("over15_stage3", "Over 1.5 Stage 3", run_over15_stage3, {}),
        ("over15_psychology", "Over 1.5 Psychology Engine", run_o15_psychology_engine, {}),
        ("over15_apex", "Over 1.5 Apex Aggregator", run_o15_apex_engine, {}),
        ("unders", "Unders Engine (U2.5 / U3.5)", run_unders_engine, {"verbose": False}),
        ("draw", "Draw Magnet Engine", run_draw_engine, {"verbose": False}),
        ("sot", "SOT Cerberus Engine", run_sot_engine, {"verbose": False}),
        ("fhvi", "FHVI First Half Engine", run_fhvi_engine, {"verbose": False}),
        ("shvi", "SHVI Second Half Engine", run_shvi_engine, {"verbose": False}),
        ("u2s_psychology", "U2S Psychology Engine", run_u2s_psychology_engine, {}),
        ("win_psychology", "Win Psychology Engine", run_win_psychology_engine, {}),
        # Reads date-keyed CSVs the forecast/psych engines above write — the
        # nightly positional-arg call passes target_date the same way.
        ("win_apex", "Win Apex Aggregator", run_win_apex_aggregator, {}),
        ("sh_master", "SH Master Vortex", run_sh_master_vortex, {}),
        ("sh_8goal", "SH-GG 8-Goal Aggregator", run_sh_gg_8goal_aggregator, {}),
        ("win_raw", "Win Raw Probability Engine", run_win_raw_engine, {}),
        ("filter_gg", "Filter GG Precision Filter", run_gg_precision_filter, {}),
        ("filter_over25__banker", "Filter Over 2.5 Aggregator (banker)",
         run_over25_filter_aggregator, {"mode": "public", "risk_level": "banker"}),
        ("filter_over25__balanced", "Filter Over 2.5 Aggregator (balanced)",
         run_over25_filter_aggregator, {"mode": "public", "risk_level": "balanced"}),
        ("filter_over25__aggressive", "Filter Over 2.5 Aggregator (aggressive)",
         run_over25_filter_aggregator, {"mode": "public", "risk_level": "aggressive"}),
        ("filter_win__safe", "Filter Win Service (safe)",
         run_win_filter_service, {"mode": "public", "risk_level": "safe"}),
        ("filter_win__balanced", "Filter Win Service (balanced)",
         run_win_filter_service, {"mode": "public", "risk_level": "balanced"}),
        ("filter_win__aggressive", "Filter Win Service (aggressive)",
         run_win_filter_service, {"mode": "public", "risk_level": "aggressive"}),
    ]


# ==============================================================================
# 🤝 LIVE SCANNER INTERLOCK (2026-09-20)
# ==============================================================================
# main.py is a ONE-SHOT batch job (nightly pipeline / second-chance / manual).
# While it runs, the 24/7 live scanner must be PAUSED: both are memory-heavy,
# the box has 3.8GB RAM, and concurrent runs caused the Sep 19/20 OOM kill-loop
# (5 scanner kills + 1 API worker death). The scanner is restarted the moment
# this process exits — normal completion, sys.exit(), unhandled exception or
# SIGTERM (atexit) — and alienedge-livekeeper.timer backstops a hard SIGKILL.
import atexit as _atexit
import signal as _signal
import subprocess as _sub

LIVE_UNIT = "alienedge-live.service"
_LIVE_PROC_PATTERN = "run_live_scanner_24_7.py"


def _systemctl(*args: str, timeout: float = 90.0) -> bool:
    try:
        _r = _sub.run(["systemctl", *args], timeout=timeout,
                      stdout=_sub.DEVNULL, stderr=_sub.DEVNULL)
        return _r.returncode == 0
    except Exception:
        return False


def live_scanner_pause(reason: str = "pipeline start") -> None:
    """Stop the 24/7 live scanner and wait until it is fully gone.

    Bounded: never blocks more than ~3.5 min even if the old process is
    swap-thrashing (as observed during the OOM loop)."""
    if not _systemctl("is-active", "--quiet", LIVE_UNIT, timeout=15.0):
        print(f"🤝 [INTERLOCK] live scanner already down ({reason}) — nothing to pause",
              flush=True)
        return
    print(f"🤝 [INTERLOCK] pausing 24/7 live scanner ({reason}) ...", flush=True)
    _systemctl("stop", LIVE_UNIT, timeout=150.0)
    # Belt & braces: SIGTERM any straggler, then SIGKILL, waiting for exit.
    for _sig in ("-TERM", "-KILL"):
        _sub.run(["pkill", _sig, "-f", _LIVE_PROC_PATTERN],
                 stdout=_sub.DEVNULL, stderr=_sub.DEVNULL)
        for _ in range(30):
            _probe = _sub.run(["pgrep", "-f", _LIVE_PROC_PATTERN],
                              stdout=_sub.DEVNULL, stderr=_sub.DEVNULL)
            if _probe.returncode != 0:
                print("🤝 [INTERLOCK] live scanner fully stopped — RAM freed",
                      flush=True)
                return
            time.sleep(3)
    print("⚠️ [INTERLOCK] live scanner still alive after stop — continuing anyway",
          flush=True)


def live_scanner_resume(reason: str = "pipeline finished") -> None:
    """(Re)start the 24/7 live scanner. Idempotent."""
    if _systemctl("is-active", "--quiet", LIVE_UNIT, timeout=15.0):
        return
    _ok = _systemctl("start", LIVE_UNIT, timeout=90.0)
    print(f"🤝 [INTERLOCK] live scanner "
          f"{'restarted' if _ok else 'FAILED to restart'} ({reason})", flush=True)


def _resume_live_scanner_on_exit() -> None:
    try:
        live_scanner_resume("main.py exiting")
    except Exception as _e:
        print(f"⚠️ [INTERLOCK] resume-on-exit failed: {_e}", flush=True)


def _sigterm_to_systemexit(_signum, _frame) -> None:
    # SystemExit (a BaseException) is NOT swallowed by engine `except Exception`
    # blocks; the interpreter unwinds and atexit still fires.
    raise SystemExit(143)


if __name__ == "__main__":
    # 🤝 LIVE SCANNER INTERLOCK: pause the 24/7 scanner for the whole run and
    # always restart it on exit.
    _atexit.register(_resume_live_scanner_on_exit)
    try:
        _signal.signal(_signal.SIGTERM, _sigterm_to_systemexit)
    except Exception:
        pass
    live_scanner_pause("main.py run starting")

    # --second-chance=<date>: 06:00 safety net — re-run only failed/empty/
    # degraded critical keys for the date, then exit. No argument (or
    # --date=...): the full 23:30 pipeline as before.
    _second_chance_date = None
    for _arg in sys.argv[1:]:
        if _arg.startswith("--second-chance="):
            _second_chance_date = _arg.split("=", 1)[1].strip()
            break

    if _second_chance_date:
        # 2026-09-20 guard: the timer previously resolved %T to "/tmp" and the
        # recovery then tried to heal a bogus "date", re-running every engine
        # against garbage. Validate the format; anything that isn't YYYY-MM-DD
        # falls back to TODAY so the recovery always heals a real day.
        import re as _re
        if not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", _second_chance_date):
            print(f"⚠️ [SECOND-CHANCE] invalid target '{_second_chance_date}' "
                  f"— falling back to TODAY", flush=True)
            _second_chance_date = datetime.now().strftime("%Y-%m-%d")
        _rc = alienedge_second_chance(_second_chance_date)
        _rejected = store.guard_rejections()
        if _rejected:
            print(f"\n⚠️ [SNAPSHOT GUARD] {len(_rejected)} same-date snapshot write(s) "
                  f"rejected as suspiciously collapsed and preserved.")
            _rc = 2
        sys.exit(_rc)

    # --weekly-only=<date> (or --weekly-only --date=<date>): fill the shared
    # future window and run ONLY the Weekly family (GG / WIN / O2.5). This is the
    # ops/validation path: it never runs the pre-match pipeline, never touches the
    # Live scanner and never writes outside the existing output_store keys.
    _weekly_only_date = None
    for _arg in sys.argv[1:]:
        if _arg.startswith("--weekly-only="):
            _weekly_only_date = _arg.split("=", 1)[1].strip()
            break
    if "--weekly-only" in sys.argv and not _weekly_only_date:
        for _arg in sys.argv[1:]:
            if _arg.startswith("--date="):
                _weekly_only_date = _arg.split("=", 1)[1].strip()
                break
        if not _weekly_only_date:
            from datetime import timedelta as _td
            _weekly_only_date = (datetime.now() + _td(days=1)).strftime("%Y-%m-%d")

    if _weekly_only_date:
        fill_shared_future_window(_weekly_only_date)
        run_fixture_risk_classification(_weekly_only_date)
        run_weekly_phase(_weekly_only_date)
        _rejected = store.guard_rejections()
        if _rejected:
            print(f"\n⚠️ [SNAPSHOT GUARD] {len(_rejected)} snapshot write(s) rejected "
                  f"as suspiciously collapsed and preserved.")
            sys.exit(2)
        sys.exit(0)

    # ── STANDALONE FIXTURE-RISK BACKFILL ─────────────────────────────────────
    #   main.py --backfill-fixture-risk=YYYY-MM-DD
    # Labels one already-processed date as cup/friendly WITHOUT rolling or
    # evicting the window and WITHOUT a network call when that day is still
    # stored. Historical dates simply gain their warning labels.
    _backfill_dates = [a.split("=", 1)[1].strip()
                       for a in sys.argv if a.startswith("--backfill-fixture-risk=")]
    if _backfill_dates:
        for _d in _backfill_dates:
            if _d:
                backfill_fixture_risk(_d)
        sys.exit(0)

    alienedge_master_system()

    # ── 06:00 SECOND-CHANCE HANDOFF ──────────────────────────────────────────
    # The full run generates TOMORROW's picks. If tonight's upstream 429 storm
    # starved any critical engine, tomorrow 06:00's second-chance timer must
    # know which date to heal — recorded here so the timer's EnvironmentFile
    # picks it up (bash falls back to today when the file is absent/stale).
    try:
        _tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "data", "second_chance.env")
        os.makedirs(os.path.dirname(_env_path), exist_ok=True)
        with open(_env_path, "w") as _ef:
            _ef.write(f"SC_DATE={_tomorrow}\n")
        print(f"🛟 second-chance target recorded: {_tomorrow} -> {_env_path}")
    except Exception as _env_err:
        print(f"⚠️ second-chance env write skipped: {_env_err}")

    # SNAPSHOT GUARD (Batch A): a run that had to REJECT collapsed same-date
    # snapshots must not look green. exit 2 marks the unit failed so
    # `systemctl is-failed alienedge-pipeline.service` and the log both surface
    # it, instead of a run that silently preserved old data looking successful.
    _rejected = store.guard_rejections()
    if _rejected:
        print(f"\n⚠️ [SNAPSHOT GUARD] {len(_rejected)} same-date snapshot write(s) "
              f"rejected as suspiciously collapsed and preserved:")
        for _r in _rejected:
            print(f"   • {_r['date']}/{_r['key']}: existing_fixtures="
                  f"{_r['existing_fixtures']} new_fixtures={_r['new_fixtures']} "
                  f"({_r['reason']})")
        sys.exit(2)
