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
    from LIVE_SCANNER.live_stage2_verification import run_live_validator_engine
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
        try:
            run_live_validator_engine()
        except Exception as e:
            logging.error(f"[Stage 2 Validator] Error: {e}")

        # ── 6. STAGE 6: EVALUATION & USER ALERTS ─────────────────────────────
        # Note: If your Code 6 `SupremeOrchestrator.run()` is an infinite loop,
        # running `orchestrator.run_single_cycle()` or running Code 6 in a separate
        # thread keeps the loop moving smoothly every 45-60 seconds.
        try:
            # Refresh prematch memory & run evaluation
            db = orchestrator.load_all_prematch_data()
            orchestrator.maintenance_thread(db)
            live_data = orchestrator.fetch_live_scores()
            live_ids = {str(fx['id']) for fx in live_data}
            orchestrator.cleanup_stale_memory(live_ids)
            
            # (Or call orchestrator.run() directly if running standalone)
        except Exception as e:
            logging.error(f"[Stage 6 Orchestrator] Error: {e}")

        duration = round(time.time() - cycle_start, 2)
        logging.info(f"Cycle #{cycle_count} completed in {duration}s. Sleeping 45s...")
        time.sleep(45)


if __name__ == "__main__":
    live_scanner_master_loop()
