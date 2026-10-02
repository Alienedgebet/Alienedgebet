#!/bin/bash
# AlienEdge pre-match pipeline runner WITH a no-progress watchdog.
#
# WHY THIS EXISTS (2026-10-02): the 2026-10-01 run wedged for 12.5 hours inside
# hrtimer_nanosleep, burning API cooldowns and — because livekeeper refuses to
# start the live scanner while a pipeline exists — taking live scanning down with
# it. TimeoutStartSec stayed 0 (infinite) the whole time.
#
# The rule this enforces, and the reason it is NOT a total runtime limit:
#   A SLOW pipeline is CORRECT. It must never be killed for being slow.
#   A pipeline making NO PROGRESS is a bug, and must be reaped.
# main.py touches data/pipeline_heartbeat.json around every engine, so a working
# run refreshes it continuously no matter how long the whole thing takes. Only a
# run silent for STALE_AFTER seconds is considered wedged.
#
# STALE_AFTER is 20 minutes — far longer than the ~30s heartbeat interval — so a
# legitimately slow-but-working run is never mistaken for a hang.
set -uo pipefail

BACKEND="/var/www/backend"
PY="$BACKEND/venv/bin/python3"
HEARTBEAT="$BACKEND/data/pipeline_heartbeat.json"
STALE_AFTER=${STALE_AFTER:-1200}     # 20 min
POLL=${POLL:-30}

TARGET_DATE="${TARGET_DATE:-$(date -d tomorrow +%F)}"
cd "$BACKEND" || exit 1

# A fresh heartbeat file must not let a previous run's timestamp mask a hang.
rm -f "$HEARTBEAT"

echo "PIPELINE start target=$TARGET_DATE watchdog_stale_after=${STALE_AFTER}s"

# A stale heartbeat from a PREVIOUS run must never mask a hang, and a run that
# dies before touching it must still be reaped -- so the file is removed here and
# the missing-heartbeat case is handled explicitly below.
rm -f "$HEARTBEAT"
START_TS=$(date +%s)

"$PY" main.py --date="$TARGET_DATE" &
RUNPID=$!

# systemd expects a watchdog process to die from SIGABRT; trap it so the run is
# reaped and the unit reports failure instead of a silent "success".
trap 'echo "WATCHDOG: terminating wedged pipeline (pid '"$RUNPID"')" >&2
      kill -TERM '"$RUNPID"' 2>/dev/null
      sleep 2
      kill -KILL '"$RUNPID"' 2>/dev/null
      exit 1' ABRT

while kill -0 "$RUNPID" 2>/dev/null; do
    AGE=$("$PY" - "$HEARTBEAT" <<'PYEOF' 2>/dev/null || echo -1
import json, sys, time
try:
    with open(sys.argv[1]) as fh:
        print(int(time.time() - float(json.load(fh)["ts"])))
except Exception:
    print(-1)
PYEOF
)
    # AGE == -1 means NO heartbeat exists: the run has not reached its first
    # engine yet (or died before doing so). That is NOT automatically a hang --
    # startup legitimately takes a while -- so fall back to elapsed wall time
    # since launch. Without this, a run that wedges BEFORE the first heartbeat
    # would be exempt from the watchdog forever, which is precisely the failure
    # this script exists to catch.
    if [ "${AGE:--1}" -lt 0 ]; then
        AGE=$(( $(date +%s) - START_TS ))
    fi

    if [ "$AGE" -ge "$STALE_AFTER" ]; then
        echo "WATCHDOG: no progress for ${AGE}s — aborting wedged pipeline" >&2
        kill -ABRT $$
        exit 1
    fi
    sleep "$POLL"
done

wait "$RUNPID"
RC=$?
echo "PIPELINE exit rc=$RC"
exit "$RC"