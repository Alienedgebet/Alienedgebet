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
    PIPE_PID="$(pgrep -f "main\.py --date" | head -1)"
    if [ -n "$PIPE_PID" ] && kill -0 "$PIPE_PID" 2>/dev/null; then
        # ── PROGRESS CHECK (2026-10-02) ──────────────────────────────────────
        # Do NOT treat "the pipeline is running" as "the pipeline is working".
        # On 2026-10-01 a wedged run (12.5h inside hrtimer_nanosleep) kept the
        # scanner down for a full day because this check only asked whether a
        # process existed. A WEDGED pipeline is not competing for quota -- it is
        # asleep -- so the live scanner is exactly what should be running.
        #
        # A HEALTHY pipeline refreshes data/pipeline_heartbeat.json around every
        # engine. Only a run whose heartbeat is stale past STALE_AFTER counts as
        # wedged. STALE_AFTER (20 min) is deliberately far longer than the ~30s
        # heartbeat interval, so a legitimately slow-but-working run is never
        # mistaken for a hang.
        STALE_AFTER=$((20 * 60))
        HB=/var/www/backend/data/pipeline_heartbeat.json
        STALE=0
        if [ -f "$HB" ]; then
            NOW=$(date +%s)
            HB_TS=$(python3 -c "
import json
try: print(int(json.load(open('$HB'))['ts']))
except Exception: print(0)
" 2>/dev/null || echo 0)
            if [ "${HB_TS:-0}" -gt 0 ]; then
                AGE=$((NOW - HB_TS))
                [ "$AGE" -ge "$STALE_AFTER" ] && STALE=1
                log "pipeline alive (pid $PIPE_PID); heartbeat age ${AGE}s"
            else
                log "pipeline alive but heartbeat unreadable - treating as healthy"
            fi
        else
            log "pipeline alive, no heartbeat file yet - treating as healthy"
        fi

        if [ "$STALE" -eq 1 ]; then
            log "WARNING: pipeline WEDGED (no progress > ${STALE_AFTER}s) - not competing for API quota. Starting $LIVE_UNIT anyway."
        else
            log "SKIP: $LIVE_UNIT is down but the pre-match pipeline is running and making progress."
            exit 0
        fi
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
