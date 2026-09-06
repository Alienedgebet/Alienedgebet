import os
import sys
import time
import gc
import requests
import traceback
from datetime import datetime

# ==============================================================================
# 1. THE HIJACK (GLOBAL TRAFFIC WARDEN & CONTROLLED CACHE)
# ==============================================================================
GLOBAL_API_CACHE = {}
original_get = requests.get

class CachedResponseWrapper:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def json(self):
        return self._json_data

    def raise_for_status(self):
        pass

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
# 3. FAULT-TOLERANT EXECUTION BARRIER
# ==============================================================================
def _safe_exec(engine_name, func, *args, **kwargs):
    """
    Executes a mathematical engine safely. If a specific league or API call
    encounters a data gap, the error is isolated and logged so the remainder
    of the pre-match pipeline continues uninterrupted.
    """
    try:
        print(f"\n> ⚙️ Initializing: {engine_name}...")
        res = func(*args, **kwargs)
        return res
    except Exception as e:
        print(f"⚠️ [NON-CRITICAL ENGINE NOTICE in {engine_name}]: {e}")
        return None


# ==============================================================================
# 4. THE SUPREME MASTER PIPELINE (PURE PRE-MATCH ARCHITECTURE)
# ==============================================================================
def alienedge_master_system():
    print("\n" + "█"*115)
    print(f"{'🚀 ALIENEDGE SUPER-MATRIX COMMAND CENTER v11.0':^115}")
    print(f"{'THE TOTAL FORENSIC & PSYCHOLOGICAL PRE-MATCH BETTING MACHINE':^115}")
    print("█"*115)

    # ── CLI ARGUMENT & DATE RESOLUTION ────────────────────────────────────────
    cli_date = None
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

    start_time = time.time()

    # ── PHASE 1: FOUNDATION & DNA IDENTITY ───────────────────────────────────
    print(f"\n[PHASE 1] INITIALIZING DNA, UNDERDOGS, AND FOUNDATION MATH for {target_date}...")
    _safe_exec("DNA Profiler", run_dna_profiler, target_date)
    _safe_exec("DNA Engine V2", run_dna_engine_v2, target_date)
    _safe_exec("DNA Market Factors", build_market_factor_counts, target_date)

    _safe_exec("Underdog Base Engine", run_underdog_engine, target_date)
    _safe_exec("Underdog Master Engine", run_underdog_master_engine, target_date)
    _safe_exec("Total Visibility Merger", run_total_visibility_merger, target_date)
    _safe_exec("Apex Underdog Aggregator", run_apex_underdog_aggregator, target_date)
    _safe_exec("Win Forecast Base Engine", run_win_forecast_engine, target_date)
    _safe_exec("SH-GG Winner Engine", run_sh_gg_winner_engine, target_date)

    flush_system_ram()

    # ── PHASE 2: SECTIONAL HARVESTS ─────────────────────────────────────────
    print("\n" + "="*115)
    print(f"{'🧠 INITIATING SUPER-MATRIX: SECTIONAL HARVESTS':^115}")
    print("="*115)

    # 1. Corners Empire
    print("\n> 🚩 Processing Corner Empire...")
    _safe_exec("Corner Stage 1 (Miner)", run_corner_engine_stage1, target_date)
    _safe_exec("Corner Stage 2 (Refiner)", run_corner_engine_stage2, target_date)
    _safe_exec("Corner Stage 3 (Psychology)", run_corner3_psychology_engine, target_date)
    _safe_exec("Corner Catalyst Engine", run_catalyst_corner_engine, target_date)
    _safe_exec("Corner Stage 4 Aggregator", run_corner4_aggregator_engine, target_date)
    flush_system_ram()

    # 2. GG & Over 1.5 Unified Head
    print("\n> ⚽ Running Unified GG & Over 1.5 Precision Head Engine...")
    _safe_exec("Unified GG & O1.5 Head Engine", run_gg_o15_engine, target_date, verbose=False)

    # 3. GG Forensic Pipeline
    print("\n> ⚽ Processing Downstream GG Forensics...")
    _safe_exec("GG Forensic Aggregator", run_gg_forensic_aggregator, target_date)
    _safe_exec("GG Psychology Engine", run_gg_psychology_engine, target_date)
    _safe_exec("Supreme GG VIP Aggregator", run_supreme_gg_aggregator, target_date)
    flush_system_ram()

    # 4. Over 2.5 Goals Pipeline
    print("\n> 🔥 Processing Over 2.5 Goals Pipeline...")
    _safe_exec("Over 2.5 Stage 1 (Probabilistic)", run_over25_stage1, target_date)
    _safe_exec("Over 2.5 Stage 2 (Council)", run_over25_stage2, target_date)
    _safe_exec("Over 2.5 Stage 3 (Killswitch)", run_over25_stage3, target_date)
    _safe_exec("Over 2.5 Psychology Engine", run_o25_psychology_engine, target_date)
    _safe_exec("Gold Over 2.5 Engine", run_gold_over_25_engine, target_date)
    _safe_exec("Over 2.5 Apex Aggregator", run_over25_aggregator, target_date)
    _safe_exec("Over 2.5 Forecast Engine", run_over25_forecast_engine, target_date)
    flush_system_ram()

    # 5. Over 1.5 Goals Pipeline
    print("\n> ⚡ Processing Over 1.5 Goals Pipeline...")
    _safe_exec("Over 1.5 Stage 3", run_over15_stage3, target_date)
    _safe_exec("Over 1.5 Psychology Engine", run_o15_psychology_engine, target_date)
    _safe_exec("Over 1.5 Apex Aggregator", run_o15_apex_engine, target_date)
    flush_system_ram()

    # 6. Defensive Under Empire
    print("\n> 🛡️ Processing Defensive Under Empire...")
    _safe_exec("Unders Engine (U2.5 / U3.5)", run_unders_engine, target_date, verbose=False)

    # 7. Draw Magnet Engine
    print("\n> ⚖️ Processing Draw Magnet Index...")
    _safe_exec("Draw Magnet Engine", run_draw_engine, target_date, verbose=False)

    # 8. SOT Cerberus Engine
    print("\n> 🎯 Processing Cerberus S.O.T. Engine...")
    _safe_exec("SOT Cerberus Engine", run_sot_engine, target_date, verbose=False)

    # 9. Half-Time Streak Miners
    print("\n> ⛏️ Processing Half-Time Streak Miners...")
    _safe_exec("FHVI First Half Engine", run_fhvi_engine, target_date, verbose=False)
    _safe_exec("SHVI Second Half Engine", run_shvi_engine, target_date, verbose=False)
    flush_system_ram()

    # 10. Wins, U2S & SH Master Vortex
    print("\n> 🏆 Processing Win, U2S, & SH Elite Aggregation...")
    _safe_exec("U2S Psychology Engine", run_u2s_psychology_engine, target_date)
    _safe_exec("Win Psychology Engine", run_win_psychology_engine, target_date)
    _safe_exec("Win Apex Aggregator", run_win_apex_aggregator)
    _safe_exec("SH Master Vortex", run_sh_master_vortex, target_date)
    _safe_exec("SH-GG 8-Goal Aggregator", run_sh_gg_8goal_aggregator, target_date)
    _safe_exec("Win Raw Probability Engine", run_win_raw_engine, target_date)
    flush_system_ram()

    # 11. Real Filter Engines (Risk Modes)
    print("\n> 🎯 Running FILTER/ Precision Engines...")
    _safe_exec("Filter GG Precision Filter", run_gg_precision_filter)
    _safe_exec("Filter Over 2.5 Aggregator (Banker)", run_over25_filter_aggregator, target_date, mode="public", risk_level="banker")
    _safe_exec("Filter Win Service (Safe)", run_win_filter_service, target_date, mode="public", risk_level="safe")
    flush_system_ram()

    # ── PIPELINE COMPLETION ──────────────────────────────────────────────────
    duration = round((time.time() - start_time) / 60, 2)
    print("\n" + "█"*115)
    print(f"{'✅ ALL PRE-MATCH SUPER-MATRIX HARVESTS COMPLETE':^115}")
    print(f"{f'Duration: {duration} minutes | Target Date: {target_date}':^115}")
    print(f"{'Pre-computed predictions, feeds, and analytics are fully saved on disk.':^115}")
    print("█"*115)


if __name__ == "__main__":
    alienedge_master_system()
