#!/bin/bash
# AlienEdge Livekeeper (2026-09-20) — backstop watchdog for the live scanner.
#
# Complements the main.py interlock: if the scanner was SIGKILLed (OOM) or the
# box rebooted mid-pipeline and atexit never ran, this restarts it — but ONLY
# while no main.py run is active (never fights the interlock).
#
# Owner: alienedge-livekeeper.timer (every 10 min)
set -u
UNIT=alienedge-live.service
PATTERN=run_live_scanner_24_7.py

main_running() {
    pgrep -f "/var/www/backend/main.py" >/dev/null 2>&1
}

if main_running; then
    echo "[livekeeper] main.py active — interlock owns the scanner, standing down"
    exit 0
fi

# "enabled" includes activating/restart backoff states.
if systemctl is-enabled --quiet "$UNIT" 2>/dev/null && \
   systemctl is-active --quiet "$UNIT" 2>/dev/null; then
    exit 0
fi

# Process alive but unit showing dead/inactive? Trust the process (stop in
# progress); systemd will settle it.
if pgrep -f "$PATTERN" >/dev/null 2>&1; then
    echo "[livekeeper] process present, unit not yet active — waiting"
    exit 0
fi

echo "[livekeeper] scanner DOWN and no main.py running — restarting ${UNIT}"
systemctl start "$UNIT" && echo "[livekeeper] restart issued OK" \
    || echo "[livekeeper] ERROR: restart failed"
