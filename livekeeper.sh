#!/bin/bash
# AlienEdge Livekeeper
#
# Purpose: keep the 24/7 live scanner running, but ONLY when the pre-match
# daily pipeline (main.py) is not running. Both hit the same SportMonks quota,
# so the scanner is deliberately left down while the pipeline works; the
# 10-minute timer brings it back afterwards.
#
# Idempotent: safe to run on every timer tick. Never restarts a healthy
# service, and never races the pipeline.
#
# NOTE: this script went missing at some point, which left
# alienedge-livekeeper.service failing with 203/EXEC - meaning the watchdog
# had no watchdog and a stopped scanner stayed down. Reinstated as a tracked
# file so it cannot silently disappear again.

set -uo pipefail

# Overridable so the decision logic can be exercised in tests without
# touching real services. Defaults are the production units.
LIVE_UNIT="${ALIENEDGE_LIVE_UNIT:-alienedge-live.service}"
PIPE_UNIT="${ALIENEDGE_PIPE_UNIT:-alienedge-pipeline.service}"
LOG="${ALIENEDGE_LIVEKEEPER_LOG:-/var/www/backend/output/livekeeper.log}"

log() {
    mkdir -p "$(dirname "$LOG")" 2>/dev/null
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"
}

# Only root may act on these units; the timer runs as root but be explicit.
if ! systemctl is-active --quiet "$LIVE_UNIT"; then
    # Scanner is down. Only revive it when the pipeline is not competing.
    if systemctl is-active --quiet "$PIPE_UNIT" || pgrep -f "main\.py" >/dev/null 2>&1; then
        log "SKIP: $LIVE_UNIT is down but the pre-match pipeline is running."
        exit 0
    fi

    log "ACTION: $LIVE_UNIT is down and no pipeline is running - starting it."
    if systemctl start "$LIVE_UNIT"; then
        sleep 5
        if systemctl is-active --quiet "$LIVE_UNIT"; then
            log "OK: $LIVE_UNIT is active again."
        else
            log "WARN: $LIVE_UNIT did not come up cleanly."
        fi
    else
        log "ERROR: failed to start $LIVE_UNIT."
        exit 1
    fi
else
    log "OK: $LIVE_UNIT already active - nothing to do."
fi

exit 0
