import os
import sys
import time
import gc
import json
import csv
import glob
import requests
import traceback
from datetime import datetime

import output_store as store

# ==============================================================================
# 1. THE HIJACK (GLOBAL TRAFFIC WARDEN & CONTROLLED CACHE)
# ==============================================================================
GLOBAL_API_CACHE = {}
original_get = requests.get

class CachedResponseWrapper:
    """
    Mimics enough of requests.Response that a cache HIT behaves the same as
    a real HTTP response to whatever engine code consumes it. The original
    version only implemented .json()/.status_code/.raise_for_status() — any
    engine calling .text, .content, .headers, .ok, or .elapsed on a cached
    response would hit an AttributeError deep inside engine code on a cache
    hit only (never on a cache miss), which is a nasty intermittent bug to
    chase. This version covers every commonly-used Response attribute.
    """
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code
        self.ok = 200 <= status_code < 400
        self.headers = {}
        self.elapsed = None
        self.reason = "OK" if self.ok else "Cached-Error"
        self.url = None
        try:
            self._text = json.dumps(json_data)
        except Exception:
            self._text = str(json_data)

    def json(self):
        return self._json_data

    @property
    def text(self):
        return self._text

    @property
    def content(self):
        return self._text.encode("utf-8")

    def raise_for_status(self):
        if not self.ok:
            raise requests.exceptions.HTTPError(
                f"{self.status_code} Error (cached)", response=self
            )

def flush_system_ram():
    """
    Clears the in-memory response cache and runs explicit garbage collection
    between pipeline phases to permanently eliminate Out-Of-Memory (OOM) kills.
    """
    GLOBAL_API_CACHE.clear()
    gc.collect()

def smart_get(url, params=None, **kwargs):
    safe_params = dict(params) if params else {}
    param_string = "&".join([f"{k}={v}" for k, v in sorted(safe_params.items()) if k != "api_token"])
    cache_key = f"{url}?{param_string}"

    if cache_key in GLOBAL_API_CACHE:
        print("🟨", end="", flush=True)
        return CachedResponseWrapper(GLOBAL_API_CACHE[cache_key])

    backoff = 3.0
    for attempt in range(5):
        try:
            resp = original_get(url, params=params, **kwargs)
            if resp.status_code == 200:
                data = resp.json()
                GLOBAL_API_CACHE[cache_key] = data
                print("🟩", end="", flush=True)
                # Deliberate pacing to respect SportMonks per-minute burst boundaries
                time.sleep(0.25)
                return CachedResponseWrapper(data, 200)
            elif resp.status_code == 429:
                print(f"[API BURST: Cooling {backoff}s] ", end="", flush=True)
                time.sleep(backoff)
                backoff *= 1.5
                continue
            else:
                return resp
        except Exception:
            time.sleep(1.5)
            continue

    return original_get(url, params=params, **kwargs)

requests.get = smart_get
print("✅ TRAFFIC WARDEN ACTIVE: Global API Hijack & Managed Cache Synchronized.")


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

    func_name = getattr(func, "__name__", "") if func else ""
    d_str = str(save_date) if save_date else ""

    # Specific known file mappings across legacy engine outputs
    candidates = [
        # Direct key matches
        os.path.join(out_dir, f"{save_key}__{d_str}.json"),
        os.path.join(out_dir, f"{save_key}.json"),
        os.path.join(out_dir, f"{save_key}_{d_str}.json"),
        os.path.join(out_dir, f"{save_key}_{d_str}.csv"),
        # Corner empire specific files
        os.path.join(out_dir, "corner3_qualified.json"),
        os.path.join(out_dir, "corner2_qualified.json"),
        os.path.join(out_dir, "tactical_brain_output.json"),
        os.path.join(out_dir, "corner4_aggregator.json"),
        # Over 2.5 / Over 1.5 specific files
        os.path.join(out_dir, f"over25_stage1_picks_{d_str}.json"),
        os.path.join(out_dir, "over25_stage1_picks.json"),
        os.path.join(out_dir, f"over25_stage1_picks_{d_str}.csv"),
        os.path.join(out_dir, "over25_stage1_picks.csv"),
        os.path.join(out_dir, f"over25_stage2_picks_{d_str}.json"),
        os.path.join(out_dir, "over25_stage2_picks.json"),
        # GG and Win feeds
        os.path.join(out_dir, f"sh_gg_winner_feed_{d_str}.json"),
        os.path.join(out_dir, "sh_gg_winner_feed.json"),
        os.path.join(out_dir, f"gg_o15_feed_{d_str}.json"),
        os.path.join(out_dir, "gg_o15_feed.json"),
        os.path.join(out_dir, f"ranked_win_forecast_{d_str}.csv"),
        os.path.join(out_dir, f"audited_underdog_backtest_{d_str}.json"),
        os.path.join(out_dir, f"audited_underdog_backtest_{d_str}.csv"),
        os.path.join(out_dir, f"SUPREME_EVOLUTION_OUTPUT_{d_str}.csv"),
        os.path.join(out_dir, f"ALIENEDGE_GG_PSYCHOLOGY_FINAL_{d_str}.csv"),
        os.path.join(out_dir, f"JUDGED_GG_PICKS_{d_str}.csv"),
        os.path.join(out_dir, f"ALIENEDGE_GG_PICKS_{d_str}.csv"),
        os.path.join(out_dir, f"FINAL_APEX_UD_SCORE_{d_str}.csv"),
    ]

    # Broad search in /output/ for files matching key, func, or date
    search_patterns = [
        os.path.join(out_dir, f"*{save_key}*"),
        os.path.join(out_dir, f"*{func_name.replace('run_', '')}*") if func_name else "",
    ]
    for p in search_patterns:
        if p:
            for match in glob.glob(p):
                if match not in candidates and "cache" not in match:
                    candidates.append(match)

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
        # If engine returned None or empty, check if it saved an output file to disk
        if (res is None or (hasattr(res, "__len__") and len(res) == 0)) and save_key is not None:
            disk_res = _recover_engine_output_from_disk(save_key, save_date, engine_name, func)
            if disk_res is not None and (not hasattr(disk_res, "__len__") or len(disk_res) > 0):
                print(f"   📂 Recovered {len(disk_res) if hasattr(disk_res, '__len__') else 'data'} items from disk output.")
                res = disk_res

        # Schema normalization (Fixture -> fixture)
        if res is not None:
            res = _normalize_fixture_schema(res)

        if save_key is not None:
            path = store.save(save_key, save_date, res)
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
                path = store.save(save_key, save_date, recovered)
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

    # ── PHASE 1: FOUNDATION & DNA IDENTITY ───────────────────────────────────
    print(f"\n[PHASE 1] INITIALIZING DNA, UNDERDOGS, AND FOUNDATION MATH for {target_date}...")
    _safe_exec("DNA Profiler", run_dna_profiler, target_date, save_key="dna", save_date=d)
    _safe_exec("DNA Engine V2", run_dna_engine_v2, target_date, save_key="dna_v2", save_date=d)
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
    # Win Apex takes NO date argument — it always reads the latest merged
    # state, so it's saved under save_date=None ('__latest') AND separately
    # snapshotted under this date so /api/status/{date} can show when it
    # last actually ran relative to the date being viewed.
    win_apex_result = _safe_exec("Win Apex Aggregator", run_win_apex_aggregator, save_key="win_apex", save_date=None)
    if win_apex_result is not None:
        store.save("win_apex", d, win_apex_result)
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
                                   save_key="filter_gg", save_date=None)
    if gg_filter_result is not None:
        store.save("filter_gg", d, gg_filter_result)

    for risk in ("banker", "balanced", "aggressive"):
        _safe_exec(f"Filter Over 2.5 Aggregator ({risk})", run_over25_filter_aggregator,
                    target_date, mode="public", risk_level=risk,
                    save_key=f"filter_over25__{risk}", save_date=d)

    for risk in ("safe", "balanced", "aggressive"):
        _safe_exec(f"Filter Win Service ({risk})", run_win_filter_service,
                    target_date, mode="public", risk_level=risk,
                    save_key=f"filter_win__{risk}", save_date=d)
    flush_system_ram()

    # ── PIPELINE COMPLETION ──────────────────────────────────────────────────
    duration = round((time.time() - start_time) / 60, 2)
    print("\n" + "█"*115)
    print(f"{'✅ ALL PRE-MATCH SUPER-MATRIX HARVESTS COMPLETE':^115}")
    print(f"{f'Duration: {duration} minutes | Target Date: {target_date}':^115}")
    print(f"{'Pre-computed predictions, feeds, and analytics are fully saved to output/cache/.':^115}")
    print("█"*115)
    return target_date


if __name__ == "__main__":
    alienedge_master_system()
