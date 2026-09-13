import os
import sys
import time
import logging

# Ensure root paths are accessible
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | [LIVE SCANNER] | %(message)s"
)

# --- IMPORT ALL LIVE SCANNER ENGINES ---
try:
    from LIVE_SCANNER.live_stage1_prematch import run_prematch_engine
    from LIVE_SCANNER.live_stage3_incoming import run_incoming_forensic_engine
    from LIVE_SCANNER.live_stage4_danger import run_danger_forensic_aggregator
    from LIVE_SCANNER.live_stage5_aggregator import run_master_aggregator
    from LIVE_SCANNER.live_stage2_verification import run_live_validator_once
    from LIVE_SCANNER.live_stage6_alerts import SupremeOrchestrator
except ImportError as e:
    logging.error(f"Import error in live engines: {e}")
    sys.exit(1)


def live_scanner_master_loop():
    logging.info("════════════════════════════════════════════════════════")
    logging.info("  ALIENEDGE 24/7 CONTINUOUS LIVE SCANNER RELAY ACTIVE")
    logging.info("  Stages: 1 (Audit) ➔ 3 (Lineups) ➔ 4 (Danger) ➔ 5 (Handshake) ➔ 2 (Stats) ➔ 6 (Alerts)")
    logging.info("════════════════════════════════════════════════════════")

    # Initialize Code 6 Orchestrator instance
    orchestrator = SupremeOrchestrator()

    cycle_count = 0

    while True:
        cycle_count += 1
        cycle_start = time.time()
        logging.info(f"--- Starting Live Scan Cycle #{cycle_count} ---")

        # ── 1. STAGE 1: SCAN ACTIVE MATCH CONTEXT ─────────────────────────────
        try:
            run_prematch_engine()
        except Exception as e:
            logging.error(f"[Stage 1 Prematch/Active] Error: {e}")

        # ── 2. STAGE 3: LINEUPS & FORMATIONS HUNTER ──────────────────────────
        try:
            run_incoming_forensic_engine()
        except Exception as e:
            logging.error(f"[Stage 3 Incoming Lineups] Error: {e}")

        # ── 3. STAGE 4: DANGER FORENSICS ─────────────────────────────────────
        try:
            run_danger_forensic_aggregator()
        except Exception as e:
            logging.error(f"[Stage 4 Danger] Error: {e}")

        # ── 4. STAGE 5: PRE-MATCH & DANGER HANDSHAKE ─────────────────────────
        try:
            run_master_aggregator()
        except Exception as e:
            logging.error(f"[Stage 5 Aggregator Handshake] Error: {e}")

        # ── 5. STAGE 2: IN-PLAY MINUTE-BY-MINUTE VALIDATOR ───────────────────
        # Single-cycle variant: the legacy run_live_validator_engine() owns an
        # infinite while-True loop and would block stages 6 forever.
        try:
            run_live_validator_once(cycle_count)
        except Exception as e:
            logging.error(f"[Stage 2 Validator] Error: {e}")

        # ── 6. STAGE 6: EVALUATION & USER ALERTS ─────────────────────────────
        # run_single_cycle() performs one full pass (prematch load → live
        # analysis → fire_alert → save_orchestrator_board) and writes
        # orchestrator_board.json + ready_to_push.json for the API. The old
        # block only refreshed memory and never ran the actual evaluation,
        # which is why /api/live/orchestrator and /api/live/alerts were empty.
        try:
            orchestrator.run_single_cycle()
        except Exception as e:
            logging.error(f"[Stage 6 Orchestrator] Error: {e}")

        duration = round(time.time() - cycle_start, 2)
        logging.info(f"Cycle #{cycle_count} completed in {duration}s. Sleeping 45s...")
        time.sleep(45)


if __name__ == "__main__":
    live_scanner_master_loop()
