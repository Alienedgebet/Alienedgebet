import os
import sys
import time
import requests
import threading
from datetime import datetime

# ==============================================================================
# 1. THE HIJACK (GLOBAL TRAFFIC WARDEN - FULL UNLOCKED MODE)
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

def smart_get(url, params=None, **kwargs):
    safe_params = dict(params) if params else {}
    param_string = "&".join([f"{k}={v}" for k, v in sorted(safe_params.items()) if k != "api_token"])
    cache_key = f"{url}?{param_string}"

    if cache_key in GLOBAL_API_CACHE:
        print("🟨", end="", flush=True)
        return CachedResponseWrapper(GLOBAL_API_CACHE[cache_key])

    backoff = 2.0
    for attempt in range(5):
        try:
            resp = original_get(url, params=params, **kwargs)
            if resp.status_code == 200:
                data = resp.json()
                GLOBAL_API_CACHE[cache_key] = data
                print("🟩", end="", flush=True)
                time.sleep(0.15)
                return CachedResponseWrapper(data, 200)
            elif resp.status_code == 429:
                print(f"[API LIMIT: Pausing {backoff}s] ", end="", flush=True)
                time.sleep(backoff)
                backoff *= 1.5
                continue
            else:
                return resp
        except Exception:
            time.sleep(1)
            continue

    return original_get(url, params=params, **kwargs)

requests.get = smart_get
print("✅ TRAFFIC WARDEN ACTIVE: Global API Hijack & Memory Cache Successful.")


# ==============================================================================
# 2. PIPELINE IMPORTS (STRICT ARCHITECTURAL ROUTING)
# ==============================================================================

# --- PHASE A: CORE BRAIN & FOUNDATION ENGINES ---
from CORE.dna_profiler import run_dna_profiler

# ✅ NEW: DNA Engine V2 — fully independent, parallel DNA provider.
# Does not replace or touch run_dna_profiler / team_dna_profiles.json.
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
from FILTER.gg_precision_filter import run_gg_precision_filter

# ✅ NEW: Standalone GG weekly filter engine
from Engine.gg_engine_weekly import (
    run_gg_filter_service,
    run_gg_weekly_filter,
)

# --- PHASE E: THE OVER 2.5 EMPIRE ---
from Engine.over25_probabilistic import run_over25_stage1
from Engine.over25_council import run_over25_stage2
from AGGREGATOR.over25_killswitch import run_over25_stage3
from Engine.gold_over25 import run_gold_over_25_engine
from AGGREGATOR.over25_apex import run_over25_aggregator
from Engine.over25_forecast import run_over25_forecast_engine

# ✅ NEW: Over 2.5 weekly filter engine
from Engine.over25_engine_weekly import (
    run_over25_filter_service,
    run_over25_weekly_filter,
)

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

# ✅ NEW: Win weekly filter engine + precision command
from Engine.win_engine_weekly import (
    run_win_filter_service,
    run_win_weekly_filter,
)
from FILTER.win_precision_filter import (
    run_win_precision_filter,
    run_win_weekly_precision,
)

# --- PHASE I: LIVE FORENSIC SEQUENCE ---
from LIVE_SCANNER.live_stage1_prematch import run_prematch_engine
from LIVE_SCANNER.live_stage3_incoming import run_incoming_forensic_engine
from LIVE_SCANNER.live_stage4_danger import run_danger_forensic_aggregator
from LIVE_SCANNER.live_stage5_aggregator import run_master_aggregator
from LIVE_SCANNER.live_stage2_verification import run_live_validator_engine
from LIVE_SCANNER.live_stage6_alerts import SupremeOrchestrator


# ==============================================================================
# 3. THE SUPREME MASTER PIPELINE SEQUENCE
# ==============================================================================
def alienedge_master_system():
    print("\n" + "█"*115)
    print(f"{'🚀 ALIENEDGE SUPER-MATRIX COMMAND CENTER v11.0':^115}")
    print(f"{'THE TOTAL FORENSIC & PSYCHOLOGICAL BETTING MACHINE':^115}")
    print("█"*115)

    # --- INITIALIZATION ---
    target_date = input("\n📅 Enter Target Date (YYYY-MM-DD) or [Enter] for Today: ").strip()
    if not target_date:
        target_date = datetime.now().strftime("%Y-%m-%d")

    # ── PHASE 1: FOUNDATION ──────────────────────────────────────────────────
    print("\n[PHASE 1] INITIALIZING DNA, UNDERDOGS, AND FOUNDATION MATH...")
    run_dna_profiler(target_date)

    # ✅ NEW: DNA Engine V2 — runs alongside v1, writes its own separate files.
    run_dna_engine_v2(target_date)
    build_market_factor_counts(target_date)

    run_underdog_engine(target_date)
    run_underdog_master_engine(target_date)
    run_total_visibility_merger(target_date)
    run_apex_underdog_aggregator(target_date)
    run_win_forecast_engine(target_date)
    run_sh_gg_winner_engine(target_date)

    # ── PHASE 2: SECTIONAL HARVESTS ─────────────────────────────────────────
    print("\n" + "="*115)
    print(f"{'🧠 INITIATING SUPER-MATRIX: SECTIONAL HARVESTS':^115}")
    print("="*115)

    # 1. Corners
    print("\n> 🚩 Processing Corner Empire...")
    run_corner_engine_stage1(target_date)
    run_corner_engine_stage2(target_date)
    run_corner3_psychology_engine(target_date)
    run_catalyst_corner_engine(target_date)
    run_corner4_aggregator_engine(target_date)

    # 2. GG & Over 1.5 Unified Head
    print("\n> ⚽ Running Unified GG & Over 1.5 Precision Head Engine...")
    run_gg_o15_engine(target_date, verbose=False)

    # 3. GG Forensic Pipeline
    print("\n> ⚽ Processing Downstream GG Forensics...")
    run_gg_forensic_aggregator(target_date)
    run_gg_psychology_engine(target_date)
    run_supreme_gg_aggregator(target_date)
    run_gg_precision_filter()

    # ✅ NEW: GG standalone filter engine (single date, all 4 modes)
    print("\n> ⚽ Running GG Standalone Filter Engine...")
    run_gg_filter_service(target_date, mode="public",   risk_level="balanced")
    run_gg_filter_service(target_date, mode="public",   risk_level="banker")
    run_gg_filter_service(target_date, mode="advanced")

    # 4. Over 2.5 Pipeline
    print("\n> 🔥 Processing Over 2.5 Goals Pipeline...")
    run_over25_stage1(target_date)
    run_over25_stage2(target_date)
    run_over25_stage3(target_date)
    run_o25_psychology_engine(target_date)
    run_gold_over_25_engine(target_date)
    run_over25_aggregator(target_date)
    run_over25_forecast_engine(target_date)

    # ✅ NEW: Over 2.5 standalone filter engine (single date, all 3 modes)
    print("\n> 🔥 Running Over 2.5 Standalone Filter Engine...")
    run_over25_filter_service(target_date, mode="public",   risk_level="balanced")
    run_over25_filter_service(target_date, mode="public",   risk_level="banker")
    run_over25_filter_service(target_date, mode="tipster",  min_poisson=65, min_votes=7)

    # 5. Over 1.5 Pipeline
    print("\n> ⚡ Processing Over 1.5 Goals Pipeline...")
    run_over15_stage3(target_date)
    run_o15_psychology_engine(target_date)
    run_o15_apex_engine(target_date)

    # 6. Defensive Under Empire
    print("\n> 🛡️ Processing Defensive Under Empire...")
    run_unders_engine(target_date, verbose=False)

    # 7. Draw Engine
    print("\n> ⚖️ Processing Draw Magnet Index...")
    run_draw_engine(target_date, verbose=False)

    # 8. SOT Cerberus Engine
    print("\n> 🎯 Processing Cerberus S.O.T. Engine...")
    run_sot_engine(target_date, verbose=False)

    # 9. Half-Time Streak Miners
    print("\n> ⛏️ Processing Half-Time Streak Miners...")
    run_fhvi_engine(target_date, verbose=False)
    run_shvi_engine(target_date, verbose=False)

    # 10. Wins, U2S & SH Master
    print("\n> 🏆 Processing Win, U2S, & SH Elite Aggregation...")
    run_u2s_psychology_engine(target_date)
    run_win_psychology_engine(target_date)
    run_win_apex_aggregator()
    run_sh_master_vortex(target_date)
    run_sh_gg_8goal_aggregator(target_date)
    run_win_raw_engine(target_date)

    # ✅ NEW: Win standalone filter engine (single date, all 3 modes)
    print("\n> 🏆 Running Win Standalone Filter Engine...")
    run_win_filter_service(target_date, mode="public",  risk_level="balanced")
    run_win_filter_service(target_date, mode="public",  risk_level="safe")
    run_win_filter_service(target_date, mode="tipster",
                           min_parity_gap=10, min_overall_wins=3, strict_mode=True)

    # ✅ NEW: Win precision command (single date)
    print("\n> 🏆 Running Win Precision Command...")
    run_win_precision_filter(target_date)

    # ── PHASE 3: LIVE DASHBOARD PREP ────────────────────────────────────────
    print("\n" + "="*115)
    print(f"{'📡 PREPARING LIVE FORENSIC DASHBOARD':^115}")
    print("="*115)
    run_prematch_engine()
    run_incoming_forensic_engine()
    run_danger_forensic_aggregator()
    run_master_aggregator()

    # ── PHASE 4: WEEKLY FILTER OPTION ───────────────────────────────────────
    print("\n" + "="*115)
    run_weekly = input(
        "\n📅 Run Weekly Filter Scans for full week? (y/n): "
    ).strip().lower()

    if run_weekly == "y":
        print("\n> 📅 Running Weekly Scans for all 3 filter engines...")

        print("\n  → GG Weekly Filter (public balanced)...")
        run_gg_weekly_filter(anchor_date=target_date, mode="public",
                             risk_level="balanced")

        print("\n  → Over 2.5 Weekly Filter (public balanced)...")
        run_over25_weekly_filter(anchor_date=target_date, mode="public",
                                 risk_level="balanced")

        print("\n  → Win Weekly Filter (public balanced)...")
        run_win_weekly_filter(anchor_date=target_date, mode="public",
                              risk_level="balanced")

        print("\n  → Win Weekly Precision Cross-Verification...")
        run_win_weekly_precision(anchor_date=target_date)

        print("\n✅ All Weekly Scans Complete.")

    # ── PHASE 5: LIVE EXECUTION ──────────────────────────────────────────────
    print("\n" + "█"*115)
    print(f"{'✅ ALL PRE-MATCH SUPER-MATRIX HARVESTS COMPLETE':^115}")
    print("█"*115)

    start_live = input(
        "\n📡 Ready for the field. Start LIVE 30' Verification & Alerts? (y/n): "
    ).strip().lower()

    if start_live == "y":
        print("\n🚀 [LIVE MODE ACTIVE] Monitoring 30' Exploitations & Supreme Alerts...")
        try:
            def validator_loop():
                while True:
                    try:
                        run_live_validator_engine()
                    except Exception:
                        pass
                    time.sleep(60)

            validator_thread = threading.Thread(target=validator_loop, daemon=True)
            validator_thread.start()

            orchestrator = SupremeOrchestrator()
            orchestrator.run()

        except KeyboardInterrupt:
            print("\n🛑 Shutting down Super-Matrix Command Center.")
    else:
        print("\nPipeline Finished. VIP locks are ready in your Output & Master directories.")


if __name__ == "__main__":
    alienedge_master_system()