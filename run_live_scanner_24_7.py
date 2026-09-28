import os
import sys
import time
import gc
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
    from LIVE_SCANNER.live_stage6_alerts import SupremeOrchestrator
except ImportError as e:
    logging.error(f"Import error in live engines: {e}")
    sys.exit(1)


def _feed_health():
    """Are the live feeds populated right now?

    An empty feed is the visible symptom of a starved scanner: when
    acquisition is rate-limited the engines see no fixtures, so they write
    nothing, so the board goes blank and Stage 6 has no picks to turn into
    alerts. Checking the feed is a far more reliable tripwire than trusting any
    individual stage's return value, because the blankness is what actually
    breaks the product.
    """
    try:
        import json as _json
        for name in ("incoming_predictions.json", "danger_audit.json"):
            path = os.path.join(ROOT, "data", name)
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8") as f:
                payload = _json.load(f)
            # A dict feed is keyed by fixture id; a list feed is a row list.
            if not payload:
                continue
            return True
    except Exception:
        # Never let the tripwire itself take the loop down.
        pass
    return False


def live_scanner_master_loop():
    logging.info("════════════════════════════════════════════════════════")
    logging.info("  ALIENEDGE 24/7 CONTINUOUS LIVE SCANNER RELAY ACTIVE")
    logging.info("  Stages: 1 (Audit) ➔ 3 (Lineups) ➔ 4 (Danger) ➔ 5 (Handshake) ➔ 6 (Alerts)")
    logging.info("════════════════════════════════════════════════════════")

    # Initialize Code 6 Orchestrator instance
    orchestrator = SupremeOrchestrator()

    cycle_count = 0
    # 2026-09-28 HOTFIX: quota circuit breaker. A rate-limit storm used to be
    # answered by retrying on the very next cycle, which kept the account over
    # its limit and turned a temporary throttle into a blank board (and a dead
    # push pipeline) lasting far longer than the storm itself. After
    # STARVE_AFTER consecutive empty cycles we back off hard and re-probe
    # slowly, so the quota gets a real chance to recover.
    STARVED_STREAK = 0
    STARVE_AFTER = 2
    STARVE_SLEEP = 180

    while True:
        cycle_count += 1
        cycle_start = time.time()
        logging.info(f"--- Starting Live Scan Cycle #{cycle_count} ---")

        if STARVED_STREAK >= STARVE_AFTER:
            # Quota is still exhausted. Do not spend a cycle proving it again.
            wait = STARVE_SLEEP * min(6, STARVED_STREAK - STARVE_AFTER + 1)
            logging.warning(
                f"[QUOTA BREAKER] feeds have been empty for {STARVED_STREAK} "
                f"consecutive cycles — backing off {wait}s and re-probing. "
                f"Skipping provider work so the rate limit can recover."
            )
            time.sleep(wait)
            if _feed_health():
                logging.info("[QUOTA BREAKER] feeds have repopulated — resuming.")
                STARVED_STREAK = 0
                continue
            STARVED_STREAK += 1
            continue

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

        # ── 5. STAGE 2: REMOVED ─────────────────────────────────────────────
        # The live validator (live_stage2_verification.py) no longer runs. Its
        # module is kept on disk so it stays reversible and its contract tests
        # keep executing, but nothing invokes it, so it costs nothing per cycle.
        # Its board endpoint is retired with it; the live page now reads team
        # statistics from the Code 6 board, which already computes them.
        # Settlement never depended on this stage and is unaffected.

        # ── 6. STAGE 6: EVALUATION & USER ALERTS ─────────────────────────────
        # run_single_cycle() performs one full pass (prematch load → live
        # analysis → fire_alert → save_orchestrator_board) and writes
        # orchestrator_board.json + ready_to_push.json for the API. The old
        # block only refreshed memory and never ran the actual evaluation,
        # which is why /api/live/orchestrator and /api/live/alerts were empty.
        # Stage 6 still runs on a starved cycle: it costs no provider quota, it
        # settles anything already pending, and skipping it would strand
        # alerts fired before the throttle.
        try:
            orchestrator.run_single_cycle()
        except Exception as e:
            logging.error(f"[Stage 6 Orchestrator] Error: {e}")

        if _feed_health():
            if STARVED_STREAK:
                logging.info(f"[QUOTA BREAKER] feeds healthy again after "
                             f"{STARVED_STREAK} starved cycle(s).")
            STARVED_STREAK = 0
            sleep_s = 45
        else:
            STARVED_STREAK += 1
            logging.warning(
                f"[QUOTA BREAKER] no populated feed after cycle #{cycle_count} "
                f"(streak {STARVED_STREAK}) — likely rate-limited. Alerts may be "
                f"delayed until acquisition recovers."
            )
            sleep_s = 45 if STARVED_STREAK < STARVE_AFTER else STARVE_SLEEP

        duration = round(time.time() - cycle_start, 2)
        # 2026-09-20 OOM guard: free per-cycle garbage (payload dicts, cache
        # reload copies) BEFORE the sleep so RSS returns toward baseline
        # every cycle instead of creeping toward the OOM line.
        gc.collect()
        logging.info(f"Cycle #{cycle_count} completed in {duration}s (gc done). "
                     f"Sleeping {sleep_s}s...")
        time.sleep(sleep_s)


if __name__ == "__main__":
    live_scanner_master_loop()
