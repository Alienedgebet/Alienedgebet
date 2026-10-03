#!/usr/bin/env python3
"""
Live Score Keeper — keeps live scores alive while the pre-match run is running.

THE PROBLEM IT SOLVES
---------------------
The daily pre-match pipeline deliberately STOPS the 24/7 live scanner for the
whole run (the interlock in main.py, added after the Sep 19/20 OOM kill-loop:
the box has ~3.9GB RAM and running both thrashed it). That is correct and stays
exactly as it is — this script does not touch that interlock.

But the scanner is what refreshes `data/live_inplay_cache.json`, so for the
1-2 hours the run holds it, EVERY live fixture on the site freezes: scores,
minutes and the "is it live" answer all go stale. Observed 2026-10-03 18:00-18:30
with `main.py --date=2026-10-04` running: the board was 33 minutes old and a
match genuinely in play at 55' was rendered as "not live now".

WHY IT IS SAFE
--------------
It is NOT a second engine. It is one process that:

  * imports ONLY live_cache (os/sys/time/json/requests/dotenv) — no engine, no
    squad history, no oracle. Measured RSS is ~40MB against the full scanner's
    1.1GB peak, so it cannot recreate the OOM it exists to avoid;
  * makes exactly ONE provider call per tick, to /livescores/inplay — the same
    call live_cache already makes for user-facing requests;
  * respects the shared 429 cooldown lock automatically, because it goes through
    live_cache.get_live_scores_cached(), which serves the stale cache and does
    not call out while the gate is active. It can never spend quota the
    pre-match run needs;
  * STANDS DOWN entirely while the real scanner is running, so it never
    duplicates a call the scanner is already making.

So during a normal evening it costs nothing at all and does nothing. It only
acts during the exact window where live data would otherwise be frozen.
"""

import os
import signal
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from live_cache import get_live_scores_cached  # noqa: E402

SCANNER_PATTERN = b"run_live_scanner_24_7.py"

# 90s. The scanner's own cycle is ~85s, so this matches the cadence the live
# pages expect to see; the cache TTL is 150s, so a tick usually lands inside it
# and the shared cache stays warm for user-facing requests too.
TICK_SECONDS = 90

_running = True


def _stop(signum, _frame):
    global _running
    _running = False
    print(f"[KEEPER] signal {signum} — shutting down", flush=True)


def full_scanner_running() -> bool:
    """True while the 24/7 scanner process exists.

    Read from /proc rather than shelling out, so a tick costs no subprocess.
    """
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/cmdline", "rb") as f:
                    if SCANNER_PATTERN in f.read():
                        return True
            except OSError:
                continue
    except Exception:
        pass
    return False


def main():
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    print(
        f"[KEEPER] live score keeper up — ticks every {TICK_SECONDS}s, "
        f"acts only while the full scanner is down",
        flush=True,
    )
    idle_logged = False

    while _running:
        try:
            if full_scanner_running():
                # The scanner is doing the work. Say so once, then stay quiet.
                if not idle_logged:
                    print(
                        "[KEEPER] full scanner is running — standing down",
                        flush=True,
                    )
                    idle_logged = True
            else:
                idle_logged = False
                rows = get_live_scores_cached(force_refresh=True)
                stamp = time.strftime("%H:%M:%S")
                print(
                    f"[KEEPER] {stamp} scanner paused — refreshed live "
                    f"scores ({len(rows)} in-play)",
                    flush=True,
                )
        except Exception as exc:
            # A keeper failure must never escalate into a crash-loop that eats
            # memory. Log and keep the cadence.
            print(f"[KEEPER] tick failed: {exc}", flush=True)

        # Sleep in slices so a SIGTERM is honoured promptly instead of after a
        # full tick interval.
        slept = 0.0
        while _running and slept < TICK_SECONDS:
            time.sleep(min(1.0, TICK_SECONDS - slept))
            slept += 1.0

    print("[KEEPER] stopped", flush=True)


if __name__ == "__main__":
    main()