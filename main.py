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
def _coerce_csv_row_types(rows):
    """
    Restore numbers in rows that were recovered from a CSV.

    WHY THIS EXISTS
    ---------------
    `csv.DictReader` returns EVERY value as a string. An engine that writes
    floats to /output/*.csv and returns None from memory (so `_safe_exec`
    falls through to the on-disk recovery path) therefore registers a row
    like `{"Odds": "1.41"}` where the in-memory engine produced `1.41`.

    That survived all the way to the browser, where lib/api.ts declares
    `Odds: number`, the column renderer called `r.Odds.toFixed(2)`, and the
    whole Over 2.5 page died with
    `e.Odds.toFixed is not a function (In 'e.Odds.toFixed(2)')`.
    Measured on 2026-10-04: `output/over25_stage2_picks_2026-10-03.json`
    held `Odds = 1.41` (float) while `output/cache/over25_stage2__2026-10-04.json`
    held `Odds = '1.41'` (str) — same engine, same day, different writer.

    Rules, all deliberately conservative — a wrong value is worse than an
    untouched one:
      * Only values that are unambiguously numeric become numbers.
      * Only these names are touched. An engine's free-text columns
        ("Reasons", "Algorithm", "fixture") are left exactly as written, and
        a fixture name that happens to look like a number is not mangled.
      * Booleans and empty strings are NEVER coerced.
      * A string that does not parse is left as the original string, so the
        payload is never made worse by this pass.

    Both engines and the API apply the same coercion, so the value a client
    sees matches what the engine actually computed.
    """
    # Column names that are numeric in every engine that writes them. Kept
    # explicit (rather than "anything that looks like a number") so a text
    # column can never be silently converted.
    numeric_keys = {
        # over25 / over15 council stages
        "Odds", "odds", "o25_odds", "dog_odds", "draw_odds", "win_odds",
        "Votes", "GradeNum", "Score", "poisson_over_prob_num",
        "Monte_Win_Prob", "Monte_Draw_Prob", "Super_Monte_Prob",
        "Psych_Score", "Cat_Priority", "Value",
        # aggregates / killswitches
        "expected_total_corners", "corners_line", "pos_gap", "parity_diff",
        "combined_gs_last_5", "poisson_over_prob", "poisson_under_prob",
        # stats feeds
        "total", "ft_score", "h_ft", "a_ft", "total_goals", "total_corners",
        "dangerous_attacks", "shots_on_target", "possession",
    }

    if isinstance(rows, dict):
        for row in rows.values():
            _coerce_csv_row_types(row)
        return rows
    if not isinstance(rows, list):
        return rows

    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in numeric_keys:
            if key not in row:
                continue
            val = row[key]
            # Booleans coerce to 1/0 in Python and 'True' is not numeric —
            # both are left strictly alone.
            if isinstance(val, bool) or val is None:
                continue
            if isinstance(val, (int, float)):
                continue
            if not isinstance(val, str):
                continue
            text = val.strip()
            if not text:
                continue
            try:
                number = float(text)
            except (TypeError, ValueError):
                continue
            # int(...) so a price/odds value reads as 1.41, not 1.41 float
            # artifacts in JSON, matching what the in-memory engine wrote.
            row[key] = int(number) if number.is_integer() and "." not in text \
                and "e" not in text.lower() else number
    return rows


def _normalize_fixture_schema(payload):
    """
    Ensures case-insensitive compatibility between engines producing 'Fixture'
    and api/main.py expecting lowercase 'fixture'.

    Also restores numeric types on rows that came back from a CSV — see
    _coerce_csv_row_types for why that matters.
    """
    if isinstance(payload, list):
        for row in payload:
            if isinstance(row, dict) and "Fixture" in row and "fixture" not in row:
                row["fixture"] = row["Fixture"]
        return _coerce_csv_row_types(payload)
    elif isinstance(payload, dict):
        if "Fixture" in payload and "fixture" not in payload:
            payload["fixture"] = payload["Fixture"]
        if "data" in payload and isinstance(payload["data"], list):
            for row in payload["data"]:
                if isinstance(row, dict) and "Fixture" in row and "fixture" not in row:
                    row["fixture"] = row["Fixture"]
            _coerce_csv_row_types(payload["data"])
        else:
            _coerce_csv_row_types(payload)
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
    #
    # 2026-10-01 FIX — dated artifact FIRST, undated name only as a fallback.
    #
    # This table is consulted by _recover_engine_output_from_disk whenever an
    # engine returns None (failed or blocked). It is a SEPARATE read path from
    # the one inside the engines themselves, so fixing the engines did not
    # close it.
    #
    # The undated names were serving stale data. Verified directly in the
    # cache: output/cache/over25_stage2__2026-09-30.json and
    # output/cache/over25_stage2__2026-10-01.json held a BYTE-IDENTICAL
    # payload — "Southend United vs Eastleigh" — a fixture that does not
    # appear anywhere in the 2026-10-01 fixture list. Yesterday's picks were
    # being published as today's.
    #
    # Ordering matters and is load-bearing: _recover_engine_output_from_disk
    # returns the FIRST candidate that exists and parses, so the dated file
    # must be attempted before the undated one. The engines now write dated
    # files alongside the legacy names, so both resolve and the dated one
    # wins.
    "over25_stage1":      ["over25_stage1_picks_{date}.csv",         # Engine/over25_probabilistic.py
                           "over25_stage1_picks_{date}.json",
                           "over25_stage1_picks.csv"],               # legacy fallback
    "over25_stage2":      ["over25_stage2_picks_{date}.csv",         # Engine/over25_council.py
                           "over25_stage2_picks_{date}.json",
                           "over25_stage2_picks.csv"],               # legacy fallback
    "over25_stage3":      ["over25_stage3_final_{date}.csv",         # AGGREGATOR/over25_killswitch.py
                           "over25_stage3_final_{date}.json",
                           "over25_stage3_final.csv"],               # legacy fallback
    # over15_stage3 is deliberately NOT dated here. Engine/over15_stage3.py
    # writes only the undated names (over15_stage3_final.csv/.json), so a
    # dated candidate would never resolve. Adding one would look like a fix
    # while changing nothing. This entry is left exactly as it was, and it
    # carries the same latent staleness risk as the Corners/Win/Underdog
    # entries -- tracked, not fixed, in this change.
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


def _record_engine_failure(engine_name, save_key, save_date, reason):
    """Record failure without destroying a previously valid same-date snapshot."""
    if save_key is None:
        return None
    _PIPELINE_FAILURES.add(save_key)
    try:
        status = store.load_status(save_key, save_date)
        if (status.get("status") == "ok"
                and int(status.get("row_count", 0) or 0) > 0):
            existing, _ = store.load(save_key, save_date, default=None)
            if existing is not None:
                path = store.save(
                    save_key, save_date, existing, status="degraded",
                    error=reason, guard=bool(save_date),
                )
                print(f"   🛡️ Preserved existing snapshot and marked degraded -> {path}")
                return None
    except Exception as exc:
        print(f"   ⚠️ Could not inspect existing {save_key} snapshot: {exc}")
    path = store.save_failure(save_key, save_date, error=reason)
    print(f"   ⚠️ recorded failure -> {path}")
    return None


# ── HEARTBEAT / NO-PROGRESS WATCHDOG (2026-10-02) ───────────────────────────
# A slow pipeline is CORRECT and must never be killed for being slow: engines
# paginate (per_page=50, max_needed=200) and a legitimate run takes 65-105 min.
# What must never happen is a run that makes NO PROGRESS at all -- that is what
# wedged the 2026-10-01 run for 12.5h inside hrtimer_nanosleep.
#
# So the watchdog keys off PROGRESS, not wall clock. Each engine updates a
# heartbeat file; systemd's ExecStartPost watchdog (see the .service) compares
# the mtime and only acts when it goes stale. A busy pipeline refreshes it every
# few seconds regardless of how long the whole run takes.
HEARTBEAT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "pipeline_heartbeat.json")
HEARTBEAT_INTERVAL_S = 30.0

_heartbeat = {"last": 0.0}


def heartbeat(note="", force=False):
    """
    Touch the heartbeat so the watchdog can tell 'slow' from 'wedged'.

    Cheap (one small JSON write, at most every HEARTBEAT_INTERVAL_S) and never
    raises: telemetry must not be able to kill a run.
    """
    now = time.time()
    if not force and (now - _heartbeat["last"]) < HEARTBEAT_INTERVAL_S:
        return
    try:
        payload = {
            "pid": os.getpid(),
            "ts": now,
            "iso": datetime.now().isoformat(),
            "note": note,
        }
        os.makedirs(os.path.dirname(HEARTBEAT_FILE), exist_ok=True)
        tmp = HEARTBEAT_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, HEARTBEAT_FILE)   # atomic: the watchdog never reads a partial file
        _heartbeat["last"] = now
    except Exception:
        pass


def pipeline_age_seconds():
    """Seconds since the last heartbeat, or None when no heartbeat exists."""
    try:
        with open(HEARTBEAT_FILE, "r", encoding="utf-8") as fh:
            return max(0.0, time.time() - float(json.load(fh).get("ts", 0)))
    except Exception:
        return None


def _mark_dependency_blocked(save_key, save_date, upstream_key, label):
    """Mark a dependent engine as failed without overwriting good old data."""
    reason = f"{label} blocked: upstream {upstream_key} is unavailable"
    _record_engine_failure(label, save_key, save_date, reason)


# ── ENGINE DEPENDENCY MAP (2026-10-02) ──────────────────────────────────────
# These engines do not call each other in-process: an aggregator READS THE CSV
# that the stage/psychology engine above it wrote to disk (see the win_apex entry
# in the pipeline list). So an aggregator that runs after a starved upstream does
# NOT fail -- it publishes a full, confident-looking board built on empty input.
#
# Observed on 2026-10-02 after the 429 wedge:
#     win_forecast 222 rows | win_psychology 0 rows | win_apex 104 rows
# 104 confident apex rows on a psychology engine that produced nothing. That is
# the same failure class as the Under 2.5 clamped-lambda bug: a poisoned input
# yielding a MORE convincing output.
#
# The rule is therefore not "abort the upstream engine" (that would starve every
# downstream consumer) but "never publish downstream output when the declared
# upstream produced zero rows".
ENGINE_UPSTREAM = {
    "win_apex":      ("win_psychology",    "Win Apex Aggregator"),
    "gg_forensics":  ("gg_o15",            "GG Forensic Aggregator"),
    "gg_supreme":    ("gg_psychology",     "Supreme GG VIP Aggregator"),
    "over25_apex":   ("over25_psychology", "Over 2.5 Apex Aggregator"),
    "over15_apex":   ("over15_psychology", "Over 1.5 Apex Aggregator"),
    "underdog_apex": ("underdog_audit",    "Underdog Apex"),
    "over25_gold":   ("over25_stage2",     "Gold Over 2.5 Engine"),
}


def _upstream_was_empty(upstream_key, save_date):
    """
    True when the declared upstream produced no rows for this date.

    Reads the same date-keyed snapshot the aggregator itself consumes, so this
    reflects exactly what the aggregator will see. Returns None when the
    upstream snapshot is missing entirely (never ran) -- the caller treats that
    as "unknown", which must NOT block, or a brand-new install could never run.
    """
    if upstream_key is None or save_date is None:
        return None
    try:
        data, _meta = store.load(upstream_key, save_date, default=None)
    except Exception:
        return None
    if data is None:
        return None
    try:
        return len(data) == 0
    except TypeError:
        return False


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
        heartbeat(f"start:{save_key or engine_name}", force=True)
        res = func(*args, **kwargs)
        heartbeat(f"done:{save_key or engine_name}", force=True)

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
                # save_failure so /api/status can tell them apart).  Preserve
                # a valid same-date snapshot as degraded rather than replacing
                # it with a new empty/failed result.
                _record_engine_failure(
                    engine_name, save_key, save_date,
                    f"{engine_name}: returned None (no disk fallback)",
                )
            else:
                # ── UPSTREAM PRECONDITION (2026-10-02) ─────────────────────────
                # An aggregator whose declared upstream produced ZERO rows must
                # not publish. It would otherwise emit a full, confident board
                # built on nothing -- the 2026-10-02 case was win_apex publishing
                # 104 rows while win_psychology produced none. Marking it blocked
                # keeps the frontend columns honest instead of showing a complete-
                # looking page with empty PSYCH_* fields.
                #
                # Deliberately NOT an upstream abort: engines read each other's
                # CSVs, so killing the upstream would starve this engine too.
                _up_key, _up_label = ENGINE_UPSTREAM.get(save_key, (None, None))
                if _up_key and _upstream_was_empty(_up_key, save_date) and res:
                    _mark_dependency_blocked(save_key, save_date, _up_key,
                                             _up_label or engine_name)
                    print(f"   🛑 BLOCKED: upstream {_up_key} returned 0 rows — "
                          f"not publishing {_up_label or engine_name} on empty input.")
                    return res

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

            # Preserve a valid same-date snapshot as degraded, but still return
            # None so dependency gates know this invocation did not succeed.
            existing_cache = f"/var/www/backend/output/cache/{save_key}__{save_date or 'latest'}.json"
            if os.path.exists(existing_cache) and os.path.getsize(existing_cache) > 200:
                _record_engine_failure(
                    engine_name, save_key, save_date,
                    f"{engine_name}: {e}",
                )
                return None

            # Only record explicit failure if neither memory, disk, nor cache had data
            _record_engine_failure(engine_name, save_key, save_date, f"{engine_name}: {e}")
        return None

# ==============================================================================
# 4. 429-DEGRADED RUN GUARD — never persist a starved empty day as "ok"
# ==============================================================================
# The 2026-09-18 outage: the evening pipeline ran while the shared SportMonks
# 429 cooldown gate was active. Starved feeds returned "Feed is empty" and every
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
_PIPELINE_FAILURES = set()
_REQUIRED_WIN_PIPELINE_KEYS = {
    "win_forecast", "win_psychology", "win_apex", "win_raw",
}


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


def run_weekly_phase(target_date, horizon=WINDOW_HORIZON_DAYS, force=False):
    """PHASE 12 — the Weekly engine family (GG / WIN / O2.5) over the window.

    Composes the EXISTING AlienEdge intelligence (see WEEKLY/weekly_engine.py) and
    persists each date's rows through output_store under the same keys the
    existing Weekly API routes already read. Non-fatal by design.

    Incremental by default (2026-10-03): only the dates that are not already
    complete are computed, so the nightly run processes the one newly added day
    instead of recomputing all seven. `force=True` is the deliberate FULL 7-day
    rebuild used by the operational --weekly-only path.
    """
    print("\n" + "=" * 115)
    print(f"{'📅 PHASE 12: WEEKLY ENGINE FAMILY (GG / WIN / O2.5)':^115}")
    print("=" * 115)
    try:
        from WEEKLY.weekly_engine import run_weekly_family
        return run_weekly_family(target_date, horizon=horizon, force=force)
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

    # Fresh API wait budget + breaker state for this run, and publish a
    # heartbeat so the watchdog can tell a slow run from a wedged one.
    try:
        import api_cache as _api_cache
        _api_cache.api_budget_reset()
        _api_cache.clear_suspension()
    except Exception:
        pass
    heartbeat("pipeline:start", force=True)

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
    win_forecast_result = _safe_exec(
        "Win Forecast Base Engine", run_win_forecast_engine, target_date,
        save_key="win_forecast", save_date=d,
    )
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

    # Win Psychology and Win Apex consume the dated forecast CSV.  Do not run
    # them against a missing/failed prerequisite; that used to create secondary
    # "No columns to parse" failures and misleading green empty snapshots.
    if win_forecast_result:
        _safe_exec("Win Psychology Engine", run_win_psychology_engine, target_date,
                   save_key="win_psychology", save_date=d)
        win_apex_result = _safe_exec(
            "Win Apex Aggregator", run_win_apex_aggregator, target_date,
            save_key="win_apex", save_date=None,
        )
        if win_apex_result is not None:
            store.save("win_apex", d, win_apex_result, guard=True)
        else:
            _mark_dependency_blocked("win_apex", d, "win_forecast", "Win Apex Aggregator")
    else:
        print("⛔ Win Psychology/Apex skipped: Win Forecast produced no usable rows.")
        _mark_dependency_blocked("win_psychology", d, "win_forecast", "Win Psychology Engine")
        _mark_dependency_blocked("win_apex", d, "win_forecast", "Win Apex Aggregator")

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

    if win_forecast_result:
        for risk in ("safe", "balanced", "aggressive"):
            _safe_exec(f"Filter Win Service ({risk})", run_win_filter_service,
                       target_date, mode="public", risk_level=risk,
                       save_key=f"filter_win__{risk}", save_date=d)
    else:
        print("⛔ Win filters skipped: Win Forecast is unavailable.")
        for risk in ("safe", "balanced", "aggressive"):
            _mark_dependency_blocked(
                f"filter_win__{risk}", d, "win_forecast",
                f"Filter Win Service ({risk})",
            )
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
    starved composite is caught by its 'degraded' status instead.

    FILTERS ARE EXEMPT from the zero-row rule.
    ------------------------------------------
    A filter's job is to REMOVE rows. `filter_over25__banker` returning []
    means "no fixture on this date met the conjunction", which is a complete,
    correct and useful answer -- not a starved engine. Treating it as stale
    made the 06:00 safety net re-run every filter, every day, forever, for any
    date with no qualifying picks: wasted provider calls, and a cache
    rewritten with the same empty result each morning.

    The distinction that matters is WHERE the emptiness came from:
      * an ENGINE that produced 0 rows  -> starved, must be retried
      * a FILTER that produced 0 rows   -> correct, must be left alone

    A starved engine is still caught, because the filter reads its dated input
    and raises/empties when that input is absent, which surfaces as
    'failed'/'degraded' on the filter's own status.
    """
    try:
        st = store.load_status(key, date_str)
    except Exception:
        return True
    status = st.get("status", "missing")
    if status in ("missing", "failed", "degraded", "unreadable"):
        return True
    if key.startswith("filter_") or key.startswith("fhvi"):
        return False
    if status == "ok" and int(st.get("row_count", 0) or 0) == 0:
        return True
    return False


def _win_forecast_healthy(date_str: str) -> bool:
    """A dated forecast must be a real non-empty ok snapshot for dependents."""
    status = store.load_status("win_forecast", date_str)
    return (status.get("status") == "ok"
            and int(status.get("row_count", 0) or 0) > 0)


def alienedge_second_chance(target_date: str) -> int:
    """06:00 safety net: re-run ONLY the critical keys that are missing,
    failed, degraded, or empty for the target date. Full runs stay on the
    18:00 timer (see /etc/systemd/system/alienedge-pipeline.timer,
    OnCalendar=*-*-* 18:00:00); this catches whatever that run starved (429)
    or failed."""
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
    win_dependents = {
        "win_psychology", "win_apex",
        "filter_win__safe", "filter_win__balanced", "filter_win__aggressive",
    }
    checked = set()
    for key, label, func, extra in stale:
        checked.add(key)
        if key in win_dependents and not _win_forecast_healthy(target_date):
            print(f"⛔ Skipping {label}: Win Forecast is still unavailable.")
            _mark_dependency_blocked(key, target_date, "win_forecast", label)
            continue
        _safe_exec(label, func, target_date, save_key=key,
                   save_date=target_date, **extra)
        flush_system_ram()

    # A failed prerequisite invalidates dependent snapshots even when those
    # snapshots were previously healthy and therefore were not in `stale`.
    if not _win_forecast_healthy(target_date):
        for key in win_dependents:
            if key not in checked:
                print(f"⛔ Marking {key} blocked: Win Forecast is unavailable.")
                _mark_dependency_blocked(
                    key, target_date, "win_forecast", key,
                )
                checked.add(key)

    failed = []
    for key in checked:
        status = store.load_status(key, target_date)
        if status.get("status") in {"failed", "degraded", "unreadable", "missing"}:
            failed.append(f"{key}({status.get('status')})")
    if failed:
        print(f"⚠️ SECOND-CHANCE INCOMPLETE: {', '.join(failed)}")
        return 2

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
    # --date=...): the full pipeline, which the systemd timer runs at 18:00
    # (OnCalendar=*-*-* 18:00:00). Do not hardcode that time here: the timer
    # unit is the single source of truth, and these comments were previously
    # stuck at "23:30" after the schedule had moved — which sent the operator
    # looking for a second, duplicate pipeline that never existed.
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
    #
    # It stays a DELIBERATE FULL 7-DAY REBUILD (force=True) — that is the whole
    # point of an operational rebuild path. The nightly pipeline is the opposite:
    # it runs incrementally and computes only the newly added day.
    # --weekly-dry-run prints the incremental plan and executes nothing.
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
        run_weekly_phase(_weekly_only_date, force=True)
        _rejected = store.guard_rejections()
        if _rejected:
            print(f"\n⚠️ [SNAPSHOT GUARD] {len(_rejected)} snapshot write(s) rejected "
                  f"as suspiciously collapsed and preserved.")
            sys.exit(2)
        sys.exit(0)

    # --weekly-dry-run[=<date>]: show exactly which days the INCREMENTAL pass
    # would compute tonight, then exit without executing anything. The ops tool for
    # answering "why did it run 7 days / why did it skip?" before committing.
    _weekly_dry_date = None
    for _arg in sys.argv[1:]:
        if _arg.startswith("--weekly-dry-run="):
            _weekly_dry_date = _arg.split("=", 1)[1].strip()
            break
    if "--weekly-dry-run" in sys.argv:
        from datetime import timedelta as _td2
        _weekly_dry_date = _weekly_dry_date or (
            datetime.now() + _td2(days=1)).strftime("%Y-%m-%d")
        try:
            from WEEKLY.weekly_engine import run_weekly_family as _wf
            print(f"[WEEKLY DRY RUN] anchor={_weekly_dry_date}")
            _wf(_weekly_dry_date, dry_run=True)
        except Exception as _e:
            print(f"⚠️ [WEEKLY DRY RUN] failed: {_e}")
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

    # ── API HEALTH REPORT ────────────────────────────────────────────────────
    # Makes the invisible explicit: how much of the run was spent waiting on the
    # provider, and whether the circuit breaker had to fire. On a healthy run
    # this is near-zero; a large number here is the early warning that the next
    # run is heading for a wedge.
    try:
        import api_cache as _api
        _spent = _api.API_WAIT_BUDGET_S - _api.api_budget_remaining()
        print(f"\n[API HEALTH] waited {_spent:.0f}s of a {_api.API_WAIT_BUDGET_S:.0f}s "
              f"budget | breaker trips: {_api._breaker['trips']}")
        if _spent >= _api.API_WAIT_BUDGET_S * 0.8:
            print("   ⚠️ API wait budget nearly exhausted — raise API_WAIT_BUDGET_S "
                  "or reduce per-engine pagination if runs are being starved.")
        if _api._breaker["trips"]:
            print("   ⚠️ Circuit breaker fired: the shared cooldown was repeatedly "
                  "stale. Check whether the provider is genuinely rate-limiting.")
        _susp = _api.suspension_note()
        if _susp or _api._suspension["seen"]:
            print(f"   ⚠️ PROVIDER SUSPENSION ({_api._suspension['seen']} event(s)): "
                  f"{_susp or 'resolved'}")
            print("      Engines that needed this endpoint produced NO data and were "
                  "marked degraded. Their columns are blank because the data was "
                  "unavailable — not because the engines are broken.")
    except Exception:
        pass

    win_failures = sorted(_PIPELINE_FAILURES & _REQUIRED_WIN_PIPELINE_KEYS)
    if win_failures:
        print(f"\n⚠️ [WIN PIPELINE] required stages failed: {', '.join(win_failures)}")
        sys.exit(2)
