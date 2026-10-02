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
GATE_LOCK="$BACKEND/data/api_429_cooldown.lock"

# STALE_AFTER is 45 min, NOT 20 (2026-10-02).
#
# The 20-minute value was shorter than the cooldowns the run was required to
# sit through, so the watchdog killed HEALTHY runs. Observed on the 2026-10-02
# 18:00 run: SportMonks returned 429 with retry-after=1617s (~27 min) on
# /fixtures/between/... and /fixtures/head-to-head/...; main.py correctly
# stopped calling that endpoint and moved on to other work, and 1221s later the
# watchdog declared the run wedged and SIGKILLed it mid weekly-pass (2026-10-09
# ended with 0 output files).
#
# A run obeying a server-provided backoff is not hung — it is waiting. The
# cooldown can legitimately reach ~28 min, so the hang threshold must sit above
# the longest wait a healthy run can be asked to perform.
STALE_AFTER=${STALE_AFTER:-2700}     # 45 min

# The clock above is a floor, not a verdict. While the shared 429 gate is
# ACTIVE the heartbeat can legitimately go quiet, so a quiet heartbeat during a
# known cooldown is not evidence of a hang. This checks the gate the same way
# main.py's _429_gate_remaining() does and grants an extension for as long as
# the cooldown still has time left on it.
#
# Without this the watchdog would still reap a run that is correctly waiting,
# just with a longer leash — the two mechanisms would fight again on the next
# long suspension.
GATE_GRACE_S=${GATE_GRACE_S:-300}     # 5 min of slack past each cooldown end

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

    # A run that is deliberately sitting out a shared 429 cooldown is WAITING,
    # not wedged. Give it until the cooldown expires (plus a little slack) so
    # the watchdog cannot reap a healthy run for obeying a server backoff.
    if [ "$AGE" -ge "$STALE_AFTER" ]; then
        GATE_LEFT=$("$PY" - "$GATE_LOCK" <<'PYEOF' 2>/dev/null || echo 0
import json, sys, time
try:
    with open(sys.argv[1]) as fh:
        print(max(0.0, float(json.load(fh).get("until", 0)) - time.time()))
except Exception:
    print(0)
PYEOF
)
        GATE_LEFT=${GATE_LEFT%%.*}
        if [ "${GATE_LEFT:-0}" -gt 0 ]; then
            echo "WATCHDOG: heartbeat quiet ${AGE}s, but a shared 429 cooldown is active for ${GATE_LEFT}s more — waiting, not aborting."
            sleep "$POLL"
            continue
        fi
        echo "WATCHDOG: no progress for ${AGE}s and no active cooldown — aborting wedged pipeline" >&2
        kill -ABRT $$
        exit 1
    fi
    sleep "$POLL"
done

wait "$RUNPID"
RC=$?
echo "PIPELINE exit rc=$RC"
exit "$RC"