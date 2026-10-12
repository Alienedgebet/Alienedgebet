#!/bin/bash
# ============================================================================
# AlienEdge retention cleanup — /var/www/backend/ops/cleanup.sh
#
# Deletes ONLY things that are safe to delete. Run with APPLY=1 to act;
# without it, everything is a dry run that prints what WOULD be deleted.
#
# SCOPE — and the reasons:
#   1. output/cache/*.json older than CACHE_KEEP_DAYS (45)
#      Engine snapshots. The frontend reads only recent dates (5-day history
#      strip, 7-day weekly window, exact-date routes); settlement reads
#      output/archive_*.json (a different file, NOT touched here). Nothing
#      on a live read path ever reaches a 45-day-old snapshot.
#   2. output/*.log rotation is handled by /etc/logrotate.d/alienedge
#      (copytruncate — systemd keeps its fd, so no service restart needed).
#   3. Old backup tarballs are rotated by ops/backup.sh itself.
#
# NEVER TOUCHED: data/ (auth DB lives elsewhere but DNA profiles, league
# caches, the heartbeat and the cooldown lock are live state), output/
# archive_*.json (settlement history), anything under the current or
# tomorrow's date, the .env, or any engine directory.
# ============================================================================
set -uo pipefail

BACKEND="/var/www/backend"
CACHE_KEEP_DAYS="${CACHE_KEEP_DAYS:-45}"
APPLY="${APPLY:-0}"
LOG="$BACKEND/output/ops/cleanup.log"

mkdir -p "$(dirname "$LOG")"
say() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

if [ "$APPLY" = "1" ]; then
    say "cleanup APPLY — cache snapshots older than ${CACHE_KEEP_DAYS}d"
    find "$BACKEND/output/cache" -maxdepth 1 -name '*.json' -mtime +"$CACHE_KEEP_DAYS" \
        -printf '  deleting %TY-%Tm-%Td  %s bytes  %p\n' | tee -a "$LOG"
    find "$BACKEND/output/cache" -maxdepth 1 -name '*.json' -mtime +"$CACHE_KEEP_DAYS" -delete
else
    say "cleanup DRY RUN — nothing deleted (set APPLY=1 to act)"
    find "$BACKEND/output/cache" -maxdepth 1 -name '*.json' -mtime +"$CACHE_KEEP_DAYS" \
        -printf '  would delete %TY-%Tm-%Td  %s bytes  %p\n' | tee -a "$LOG"
fi

# Housekeeping report — what the cache looks like after any cleanup.
total=$(ls -1 "$BACKEND/output/cache" 2>/dev/null | wc -l)
size=$(du -sh "$BACKEND/output/cache" 2>/dev/null | cut -f1)
say "cache now holds $total files ($size)"
