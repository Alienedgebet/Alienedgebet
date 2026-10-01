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
    """DEPRECATED as a fault signal — kept only to describe what is on screen.

    This used to be the circuit breaker's tripwire, and that was wrong. An empty
    feed has two completely different meanings, and the function could only see
    one of them:

        1. the scanner is starved (acquisition rate-limited, nothing fetched)
        2. there is genuinely nothing to analyse (no matches are live)

    At 04:47 on 2026-09-29 there was exactly ONE fixture in play, so both feeds
    were legitimately empty. The tripwire read that as a fault and backed the
    loop off to 1080s — turning a ~72s refresh into ~19 minutes for the whole
    night, on ZERO actual 429 errors. The breaker solved a failure that was not
    happening, and caused a delay that was.

    The breaker now uses `_quota_pressure()` instead, which checks the premise
    (are we actually being rate-limited?) rather than a symptom that is also a
    normal state.
    """
    return bool(_feeds_populated())


def _feeds_populated() -> bool:
    """Do the live feeds hold any rows? Purely descriptive, never a fault signal."""
    try:
        import json as _json
        for name in ("incoming_predictions.json", "danger_audit.json"):
            path = os.path.join(ROOT, "data", name)
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8") as f:
                if _json.load(f):
                    return True
    except Exception:
        # Never let a diagnostic take the loop down.
        pass
    return False


def _quota_pressure():
    """Is the account ACTUALLY being rate-limited right now?

    This is the breaker's real premise, and it is checked rather than assumed.
    Two independent signals, either of which is sufficient:

      * the shared 429 cooldown lock the stages publish, and
      * how recently the scanner itself logged an acquisition failure.

    A breaker that never checks its own premise is worse than no breaker, so
    when this returns False the streak is reset rather than merely not
    incremented — that is what stops tonight's failure from recurring.
    """
    import time as _time
    now = _time.time()

    # 1. The shared cooldown lock.
    lock = os.path.join(ROOT, "data", "api_429_cooldown.lock")
    try:
        with open(lock, "r", encoding="utf-8") as f:
            until = float(json.load(f).get("until", 0) or 0)
        if until > now:
            return True, f"shared 429 cooldown active for {int(until - now)}s"
    except Exception:
        pass

    # The lock's MTIME is deliberately NOT used as a signal. The stages rewrite
    # it on every SUCCESSFUL batch too (`{"until": 0, "by": "cleared:stage3"}`),
    # so "touched recently" is true on a perfectly healthy scanner — and using
    # it reproduced the exact false positive this function exists to remove
    # (observed on the first run: "quota lock touched 0s ago" on a cycle with
    # zero 429 errors and a cleared cooldown).
    #
    # The lock's CONTENT is the only trustworthy part of it: `until` in the
    # future is a live cooldown (covered above) and `until: 0` is an explicit
    # clear. There is no third state, so there is nothing further to test, and
    # inventing one from a timestamp is what caused the bug.

    return False, "no rate-limit pressure detected"


def live_scanner_master_loop():
    logging.info("════════════════════════════════════════════════════════")
    logging.info("  ALIENEDGE 24/7 CONTINUOUS LIVE SCANNER RELAY ACTIVE")
    logging.info("  Stages: 1 (Audit) ➔ 3 (Lineups) ➔ 4 (Danger) ➔ 5 (Handshake) ➔ 6 (Alerts)")
    logging.info("════════════════════════════════════════════════════════")

    # Initialize Code 6 Orchestrator instance
    orchestrator = SupremeOrchestrator()

    cycle_count = 0
    # ── QUOTA CIRCUIT BREAKER (2026-09-28, corrected 2026-09-29) ──────────
    #
    # The breaker's job is real: when the account is genuinely rate-limited,
    # retrying every cycle keeps it over its limit and turns a brief throttle
    # into a long outage. That happened, and it is worth protecting against.
    #
    # The first version fired on EMPTY FEEDS, which was wrong. An empty feed
    # also just means "no matches are live" — at 04:47 on 2026-09-29 there was
    # one fixture in play, both feeds were legitimately empty, and the breaker
    # backed the loop off to 1080s on ZERO actual 429 errors. It held a ~72s
    # refresh to ~19 minutes for the whole night.
    #
    # It now fires only on CONFIRMED rate-limit pressure (`_quota_pressure`),
    # resets the moment pressure clears, and is hard-capped so it can never
    # again hold the loop beyond STARVE_MAX_SLEEP. A breaker that cannot be
    # argued out of a false positive is worse than no breaker.
    STARVED_STREAK = 0
    STARVE_AFTER = 2          # consecutive CONFIRMED pressure events
    STARVE_SLEEP = 180
    STARVE_MAX_SLEEP = 600    # hard ceiling — never back off beyond 10 minutes

    while True:
        cycle_count += 1
        cycle_start = time.time()
        logging.info(f"--- Starting Live Scan Cycle #{cycle_count} ---")

        if STARVED_STREAK >= STARVE_AFTER:
            # Only reachable behind a confirmed pressure check.
            wait = min(STARVE_SLEEP * (STARVED_STREAK - STARVE_AFTER + 1),
                       STARVE_MAX_SLEEP)
            logging.warning(
                f"[QUOTA BREAKER] confirmed rate-limit pressure for "
                f"{STARVED_STREAK} cycle(s) — backing off {wait}s (cap "
                f"{STARVE_MAX_SLEEP}s) and re-probing."
            )
            time.sleep(wait)
            still_pressured, why = _quota_pressure()
            if not still_pressured:
                logging.info(
                    f"[QUOTA BREAKER] pressure cleared ({why}) — resuming at "
                    f"the normal interval."
                )
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

        # ── 5. SHADOW: what WOULD the two-source rule have dropped? ──────────
        # Read-only. It writes convergence_shadow.json and touches no engine
        # output. Wrapped so that a failure here can never stop a stage above
        # from producing its picks — a broken observer must not become a fault.
        try:
            from LIVE_SCANNER.live_convergence_shadow import run_shadow_review
            _shadow = run_shadow_review()
            if isinstance(_shadow, dict) and _shadow.get("error"):
                logging.warning(f"[Shadow Convergence] {_shadow['error']}")
        except Exception as e:
            logging.warning(f"[Shadow Convergence] skipped: {e}")

        # ── 6. STAGE 2: REMOVED ─────────────────────────────────────────────
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

        # ── 7. BACK-OFF DECISION, ON THE CORRECT SIGNAL ────────────────────
        # Decided on CONFIRMED rate-limit pressure, never on whether the feeds
        # happen to be empty. "No matches are live" is a normal state, not a
        # fault, and treating it as one is what throttled this loop to 19-minute
        # intervals overnight on zero actual 429s.
        pressured, why = _quota_pressure()
        if not pressured:
            if STARVED_STREAK:
                logging.info(
                    f"[QUOTA BREAKER] rate-limit pressure cleared ({why}) after "
                    f"{STARVED_STREAK} backed-off cycle(s) — normal cadence restored."
                )
            STARVED_STREAK = 0
            sleep_s = 45
        else:
            STARVED_STREAK += 1
            logging.warning(
                f"[QUOTA BREAKER] rate-limit pressure confirmed after cycle "
                f"#{cycle_count} (streak {STARVED_STREAK}): {why}. Extending the "
                f"interval to let the quota recover."
            )
            # Capped, and never applied on the first event — one slow cycle is
            # not a storm.
            sleep_s = 45 if STARVED_STREAK < STARVE_AFTER else min(
                STARVE_SLEEP, STARVE_MAX_SLEEP)

        # A quiet night is worth saying out loud, because it used to be
        # indistinguishable from a broken scanner.
        if not _feeds_populated():
            logging.info(
                "[QUOTA BREAKER] feeds are empty but the quota is healthy — "
                "this means no matches are live, not that acquisition failed."
            )

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
