#!/bin/bash
# ============================================================================
# AlienEdge healthcheck — /var/www/backend/ops/healthcheck.sh
#
# WHY: on 2026-10-12 the pipeline service failed at 16:42 and nothing said so.
# A dead API or a failed pipeline must page someone the moment it happens,
# not surface as angry users. Runs every 15 minutes via
# alienedge-healthcheck.timer.
#
# CHECKS:
#   1. alienedge-api.service is active AND /health answers 200
#   2. alienedge-live.service + alienedge-scorekeeper.service are active
#   3. The last pipeline run finished successfully (systemd Result)
#   4. Tonight's expected snapshot exists (win_forecast__{today-or-tomorrow})
#   5. Disk below 85%, memory has headroom
#
# ALERTING: if ALIENEDGE_ALERT_WEBHOOK is set in the environment, any failure
# is POSTed there as JSON (paste an UptimeRobot / Better Stack / Slack /
# Discord webhook URL into the service Environment=). Without it, failures
# are logged to output/ops/health.log — still better than silence, but
# nobody is woken up. Set the webhook before launch.
# ============================================================================
set -uo pipefail

BACKEND="/var/www/backend"
LOG="$BACKEND/output/ops/health.log"
STATE="$BACKEND/output/ops/health-state.json"
WEBHOOK="${ALIENEDGE_ALERT_WEBHOOK:-}"

mkdir -p "$(dirname "$LOG")"

PROBLEMS=()

say() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

# 1. API service + endpoint
if ! systemctl is-active --quiet alienedge-api.service; then
    PROBLEMS+=("alienedge-api.service is NOT active")
else
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:8000/health)
    if [ "$code" != "200" ]; then
        PROBLEMS+=("/health returned HTTP $code (expected 200)")
    fi
fi

# 2. Live services — with the pipeline interlock in mind.
# BY DESIGN the live scanner is STOPPED while the pipeline runs (the
# scorekeeper keeps scores fresh in its place — see the [INTERLOCK] line in
# the pipeline log). Flagging live.service as down mid-pipeline would be a
# false alarm every single night. While the pipeline is active, check the
# scorekeeper instead; when no pipeline is running, the live scanner must
# be up.
pipeline_active=0
# NOTE: `systemctl is-active` exits 3 for a Type=oneshot service that is
# mid-run (state "activating"), so is-active --quiet CANNOT be used here.
# Read ActiveState directly and treat activating|active as "running".
_pipeline_state=$(systemctl show alienedge-pipeline.service -p ActiveState --value 2>/dev/null)
case "$_pipeline_state" in activating|active) pipeline_active=1 ;; esac
if [ "$pipeline_active" = "1" ]; then
    systemctl is-active --quiet alienedge-scorekeeper.service \
        || PROBLEMS+=("alienedge-scorekeeper.service is NOT active (pipeline is running — it must cover live scores)")
else
    systemctl is-active --quiet alienedge-live.service \
        || PROBLEMS+=("alienedge-live.service is NOT active (no pipeline running — it should be up)")
    systemctl is-active --quiet alienedge-scorekeeper.service \
        || PROBLEMS+=("alienedge-scorekeeper.service is NOT active")
fi

# 3. Last pipeline run result — only meaningful when the pipeline is idle;
# a mid-run service has no Result yet, and judging it would fire a false
# alert every night between 00:00 and ~01:15.
if [ "$pipeline_active" = "0" ]; then
    result=$(systemctl show alienedge-pipeline.service -p Result --value 2>/dev/null)
    if [ "$result" != "success" ]; then
        PROBLEMS+=("last pipeline run Result=$result (expected success)")
    fi
fi

# 4. Fresh snapshot for tomorrow (the pipeline prepares next-day picks)
tomorrow=$(date -d tomorrow +%F)
snap="$BACKEND/output/cache/win_forecast__${tomorrow}.json"
if [ ! -f "$snap" ]; then
    age_h=999
    newest=$(ls -t "$BACKEND"/output/cache/win_forecast__*.json 2>/dev/null | head -1)
    if [ -n "$newest" ]; then
        age_h=$(( ( $(date +%s) - $(stat -c %Y "$newest") ) / 3600 ))
    fi
    if [ "$age_h" -gt 20 ]; then
        PROBLEMS+=("no win_forecast snapshot for $tomorrow; newest is ${age_h}h old")
    fi
fi

# 5. Disk + memory
disk_pct=$(df --output=pcent / | tail -1 | tr -dc '0-9')
if [ "$disk_pct" -ge 85 ]; then
    PROBLEMS+=("disk at ${disk_pct}% (>= 85%)")
fi
mem_avail_mb=$(free -m | awk '/^Mem:/{print $7}')
if [ "$mem_avail_mb" -lt 300 ]; then
    PROBLEMS+=("only ${mem_avail_mb}MB memory available (< 300MB)")
fi

# Report
if [ ${#PROBLEMS[@]} -eq 0 ]; then
    say "OK — api+live up, pipeline ok, disk ${disk_pct}%, mem ${mem_avail_mb}MB free"
    printf '{"status":"ok","checked_at":"%s","disk_pct":%s,"mem_avail_mb":%s}\n' \
        "$(date -Is)" "$disk_pct" "$mem_avail_mb" > "$STATE"
    exit 0
fi

say "ALERT — ${#PROBLEMS[@]} problem(s):"
for p in "${PROBLEMS[@]}"; do say "  - $p"; done
printf '{"status":"alert","checked_at":"%s","problems":%s}\n' \
    "$(date -Is)" "$(printf '%s\n' "${PROBLEMS[@]}" | /var/www/backend/venv/bin/python -c 'import json,sys; print(json.dumps([l.rstrip() for l in sys.stdin]))')" \
    > "$STATE"

if [ -n "$WEBHOOK" ]; then
    curl -s --max-time 15 -X POST -H 'Content-Type: application/json' \
        -d "{\"text\":\"🚨 AlienEdge healthcheck ALERT:\n$(printf '%s\n' "${PROBLEMS[@]}")\"}" \
        "$WEBHOOK" >>"$LOG" 2>&1 || say "webhook POST failed"
fi
exit 1
