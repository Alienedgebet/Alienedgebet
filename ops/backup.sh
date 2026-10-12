#!/bin/bash
# ============================================================================
# AlienEdge nightly backup — /var/www/backend/ops/backup.sh
#
# WHY THIS EXISTS (2026-10-12): the hosting outage left tracked files missing
# from disk (run_pipeline_watchdog.sh among them) and a stale skip-worktree
# flag hid the deletion from git status. The code survived only because it
# happened to be in git. The auth database, the settlement archives and the
# engine snapshots have NO other copy — one disk failure and the product is
# gone. This script makes one, every night, automatically.
#
# SCOPE (everything irreplaceable, nothing re-downloadable):
#   - /var/www/backend  : code + data/ + output/ (settlement archives live
#                         in output/) minus venv, node_modules, .next,
#                         __pycache__, the _backup_* scratch folders, logs,
#                         and the transient live-state files
#   - /var/lib/alienedge: the auth database — every user account lives here
#   - etc/systemd/system, etc/nginx : the service + proxy configuration
#   - .env IS included (it holds the SportMonks key and ADMIN_TOKEN), so the
#     tarball is chmod 600 root-only. NEVER share it or commit it anywhere.
#
# ROTATION: keeps the newest KEEP_DAYS tarballs (default 7).
# OFFSITE: this protects against deletion/corruption, NOT against disk
# failure. Pull a copy off the box at least weekly — see docs/OPS_RUNBOOK.md.
# ============================================================================
set -uo pipefail

BACKEND="/var/www/backend"
DEST="/var/backups/alienedge"
KEEP_DAYS="${KEEP_DAYS:-7}"
STAMP="$(date +%Y%m%d-%H%M%S)"
TARBALL="$DEST/alienedge-full-$STAMP.tar.gz"
LOG="$BACKEND/output/ops/backup.log"

mkdir -p "$DEST" "$(dirname "$LOG")"

say() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

say "backup start -> $TARBALL"

# Written to .tmp then renamed, so a reader never sees a partial tarball.
# Transient live-state files are excluded so tar never trips on a file that
# changes mid-read. tar exit 1 = "some files differ" (a warning here), exit
# 2 = fatal; only 2 counts as failure.
tar -czf "$TARBALL.tmp" -C / \
    --exclude='venv' \
    --exclude='node_modules' \
    --exclude='.next' \
    --exclude='__pycache__' \
    --exclude='_backup_*' \
    --exclude='*.log' \
    --exclude='*.pyc' \
    --exclude='pipeline_heartbeat.json' \
    --exclude='api_429_cooldown.lock' \
    --exclude='second_chance.env' \
    var/www/backend \
    var/lib/alienedge \
    etc/systemd/system \
    etc/nginx \
    2>>"$LOG"
rc=$?

if [ "$rc" -eq 0 ] || [ "$rc" -eq 1 ]; then
    mv "$TARBALL.tmp" "$TARBALL"
    chmod 600 "$TARBALL"
    say "backup OK: $(du -h "$TARBALL" | cut -f1) (tar rc=$rc)"
else
    say "backup FAILED (tar exit $rc)"
    rm -f "$TARBALL.tmp"
    exit 1
fi

# Rotation: delete tarballs older than KEEP_DAYS.
find "$DEST" -name 'alienedge-full-*.tar.gz' -mtime +"$KEEP_DAYS" -print -delete >>"$LOG" 2>&1
say "backup done — $(ls -1 "$DEST"/alienedge-full-*.tar.gz 2>/dev/null | wc -l) tarball(s) kept"
