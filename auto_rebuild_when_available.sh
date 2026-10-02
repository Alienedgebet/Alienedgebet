#!/bin/bash
# Auto-rebuild once the provider lifts a fixture-endpoint suspension (2026-10-02).
#
# WHY THIS EXISTS: on 2026-10-02 SportMonks answered /fixtures/date/* with
# HTTP 429 and retry-after ≈ 1000s WHILE quota sat at 176/180. That is an
# endpoint-level suspension, not a rate-limit we caused, so no amount of retrying
# produces fixtures. The honest outcome is a full rebuild once the provider
# actually serves again — so this waits for that moment instead of hammering the
# endpoint or leaving the boards empty.
#
# MEMORY DISCIPLINE: this is a 1-CPU VPS with ~3.9GB RAM shared by the API
# server, the live scanner and the pipeline. The live scanner is paused for the
# whole rebuild and restored afterwards, so the two memory-heavy consumers never
# overlap — the same interlock the nightly 18:00 run already uses.
set -uo pipefail

BACKEND="/var/www/backend"
PY="$BACKEND/venv/bin/python3"
LIVE_UNIT="${LIVE_UNIT:-alienedge-live.service}"
PIPE_UNIT="${PIPE_UNIT:-alienedge-pipeline.service}"
TARGET_DATE="${TARGET_DATE:-$(date +%F)}"
PROBE_DATE="${PROBE_DATE:-$TARGET_DATE}"
MAX_WAIT_S="${MAX_WAIT_S:-21600}"      # give up after 6h
POLL_S="${POLL_S:-120}"

LOG="$BACKEND/output/auto_rebuild.log"
mkdir -p "$BACKEND/output"
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

# Never race the real nightly pipeline.
if systemctl is-active --quiet "$PIPE_UNIT" || pgrep -f "main\.py --date" >/dev/null 2>&1; then
    log "SKIP: a pipeline run is already active."
    exit 0
fi

log "AUTO-REBUILD armed for $TARGET_DATE (max wait $((MAX_WAIT_S/60)) min)."

END=$(( $(date +%s) + MAX_WAIT_S ))
while [ "$(date +%s)" -lt "$END" ]; do
    # One cheap probe of the exact endpoint the engines need.
    CODE=$("$PY" -c "
import sys
sys.path.insert(0, '$BACKEND')
try:
    import Engine.unders_engine as E
    r = E.requests.get(E.BASE_URL + '/fixtures/date/$PROBE_DATE',
                       params={'api_token': E.API_KEY, 'per_page': 1}, timeout=20)
    print(r.status_code)
except Exception:
    print('ERR')
" 2>/dev/null || echo ERR)

    if [ "$CODE" = "200" ]; then
        log "Provider serving /fixtures/date again — starting rebuild for $TARGET_DATE."
        systemctl stop "$LIVE_UNIT" 2>/dev/null \
            && log "Live scanner paused for the duration of the rebuild."
        cd "$BACKEND" || exit 1
        TARGET_DATE="$TARGET_DATE" STALE_AFTER="${STALE_AFTER:-1200}" POLL=30 \
            bash "$BACKEND/run_pipeline_watchdog.sh" >> "$LOG" 2>&1
        RC=$?
        log "Rebuild finished rc=$RC; restoring the live scanner."
        systemctl start "$LIVE_UNIT" 2>/dev/null && log "Live scanner restored."
        exit "$RC"
    fi

    log "Still suspended (probe HTTP $CODE). Waiting ${POLL_S}s."
    sleep "$POLL_S"
done

log "Gave up after $((MAX_WAIT_S/60)) min. Nothing was rebuilt; boards left untouched."
exit 1