# AlienEdge Ops Runbook

*Written 2026-10-12, after the hosting outage and the pipeline-timer move.*
Read this before touching the server during an incident.

---

## 1. Daily schedule (all times WAT)

| Time | Job | What it does |
|------|-----|--------------|
| continuous | `alienedge-live.service` | 24/7 live scanner (paused while the pipeline runs, by design) |
| continuous | `alienedge-scorekeeper.service` | keeps live scores fresh — especially DURING the pipeline |
| continuous | `alienedge-livekeeper.timer` | restarts the live scanner if it dies while no pipeline runs |
| **00:00** | `alienedge-pipeline.timer` | nightly homework: all engines, tomorrow's picks (+ weekly 7-day board) |
| **02:00** | `alienedge-archiver.timer` | archives yesterday's finished results (settlement history) |
| **02:30** | `alienedge-backup.timer` | full backup to /var/backups/alienedge |
| **03:00** | `alienedge-cleanup.timer` | prunes cache snapshots >45 days old |
| **06:00** | `alienedge-second-chance.timer` | re-runs any engine that failed/degraded overnight |
| every 15 min | `alienedge-healthcheck.timer` | health check + alert |

A healthy night: pipeline 00:00→~01:15, everything verified by 06:30, users
wake to fresh data. All timers are `Persistent=true` — a missed run (e.g. the
box was off) fires on next boot.

---

## 2. Incident checklist (in order)

### "Something is wrong" — first 60 seconds

```bash
tail -20 /var/www/backend/output/ops/health.log     # what the checker saw
cat /var/www/backend/output/ops/health-state.json   # machine-readable state
systemctl list-timers 'alienedge-*' --no-pager      # did tonight's jobs fire?
systemctl is-active alienedge-api alienedge-live alienedge-scorekeeper
curl -s http://127.0.0.1:8000/health                # direct to the app
```

### "The pipeline failed" 

```bash
journalctl -u alienedge-pipeline.service --no-pager | tail -30
tail -50 /var/www/backend/output/pipeline_scheduler.log
```

**First suspect after any outage or disk incident: the watchdog script.**
`alienedge-pipeline.service` executes `/var/www/backend/run_pipeline_watchdog.sh`
— if that file is missing the service dies instantly with **exit 127**.
On 2026-10-12 the file was missing from disk and a stale **skip-worktree**
flag hid the deletion from `git status`. Check for BOTH:

```bash
ls -la /var/www/backend/run_pipeline_watchdog.sh          # exists?
git -C /var/www/backend ls-files -v | grep -v '^H '        # ANY flag here is suspicious
git -C /var/www/backend ls-files -z | while IFS= read -r -d '' f; do \
  [ -e "$f" ] || echo "MISSING: $f"; done                   # tracked but not on disk
```

If the script is missing but in git:
`git -C /var/www/backend update-index --no-skip-worktree run_pipeline_watchdog.sh &&
 git -C /var/www/backend checkout-index -f -- run_pipeline_watchdog.sh`

### "The app is slow at night"

That is the pipeline running. Check: `systemctl is-active alienedge-pipeline.service`
(shows `activating` while running). It is *supposed* to run at night now —
users should never notice. If they do, the pipeline is running long: see §4.

### "Users report missing/stale picks"

```bash
# What does the API have for tomorrow?
ls -la /var/www/backend/output/cache/win_forecast__$(date -d tomorrow +%F).json
# What does the pipeline think happened?
grep -E 'saved ->|BLOCKED|degraded|FAILED' /var/www/backend/output/pipeline_scheduler.log | tail -20
```

If engines ran but a key is missing: trigger a manual re-run of just the
second-chance set: `systemctl start alienedge-second-chance.service`
(or a full manual pipeline: `cd /var/www/backend && ALIENEDGE_WEEKLY=1
./venv/bin/python main.py --date=$(date -d tomorrow +%F)` — expensive,
spends SportMonks quota; prefer second-chance).

---

## 3. Restore from backup

Backups land in `/var/backups/alienedge/alienedge-full-<stamp>.tar.gz`
(newest 7 kept, chmod 600 — they contain the SportMonks key and ADMIN_TOKEN;
treat them like passwords).

```bash
# 1. Look before you touch
tar -tzf /var/backups/alienedge/alienedge-full-<stamp>.tar.gz | head

# 2. Extract to a scratch dir FIRST and verify
mkdir -p /tmp/restore && tar -xzf <tarball> -C /tmp/restore
/var/www/backend/venv/bin/python -c "import sqlite3; c=sqlite3.connect('/tmp/restore/var/lib/alienedge/auth.sqlite3'); print(c.execute('PRAGMA integrity_check').fetchone()[0], c.execute('SELECT COUNT(*) FROM users').fetchone()[0])"

# 3. Only then copy live pieces back (stop the API first)
sudo systemctl stop alienedge-api.service
sudo cp -a /tmp/restore/var/lib/alienedge/auth.sqlite3* /var/lib/alienedge/
sudo systemctl start alienedge-api.service
```

**OFFSITE — do this weekly, it is not automated:**
this backup protects against deletion/corruption, NOT disk failure.
From your own machine:
`rsync -avz root@api.alienedge.tech:/var/backups/alienedge/ ~/alienedge-backups/`
(The provider's own server snapshots, if available, are a second layer.)

---

## 4. SportMonks API quota (measured 2026-10-12)

**What we measured:** an 18:00 pipeline run produced **19 hard 429s**, each
with `retry-after` of **628–754 seconds (~10–13 minutes)**. The engines'
429-gate machinery handled it correctly — paced politely and finished honestly
instead of thrashing — but the run took 95+ minutes largely WAITING on
cooldowns.

**Why:** at 18:00 the live scanner + scorekeeper + pipeline all share ONE
SportMonks key during peak hours. At **00:00** the live scanner is idle, so the
pipeline gets the full quota — this is the main reason the pipeline moved to
midnight.

**If 429s still slow the midnight run:**
1. Check when they fire: `grep -B2 429 output/pipeline_scheduler.log | tail`
2. If they cluster in the WEEKLY phase (per-team 35-game lookbacks over the
   7-day window), the lever is `ALIENEDGE_WEEKLY=0` in
   `/etc/systemd/system/alienedge-pipeline.service` — the weekly board
   disappears, the nightly run gets much lighter. Feature-vs-quota trade-off.
3. If they cluster in the base engines, the SportMonks plan itself is the
   ceiling — the SportMonks dashboard shows usage vs plan.

**Never** add a second SportMonks key to dodge this: one key = one shared
gate; two keys = two pipelines fighting for the same quota with no
coordination.

---

## 5. Memory budget

Box: 3.8GB RAM + 8GB swapfile. Pipeline capped at MemoryHigh=1500M /
MemoryMax=2500M (systemd). API ~130MB. Live services ~200MB.

- Swap in use during the pipeline is normal (it absorbs the nightly spike).
- The healthcheck alerts below 300MB free.
- If the pipeline ever gets OOM-killed: check `journalctl -u
alienedge-pipeline.service | grep -i kill`, and either move it later
(it is already at the quietest hour) or turn off the weekly phase (§4).

---

## 6. Monitoring — turn on the webhook before launch

The healthcheck (`ops/healthcheck.sh`) runs every 15 min and logs to
`output/ops/health.log`. **Without a webhook it alerts nobody.** To get
paged:

1. Create a free UptimeRobot / Better Stack / Slack / Discord webhook.
2. Add to `/etc/systemd/system/alienedge-healthcheck.service`:
   `Environment=ALIENEDGE_ALERT_WEBHOOK=https://...`
3. `systemctl daemon-reload`

Also add an EXTERNAL uptime check (UptimeRobot) against
`https://www.alienedge.tech` — it catches the failure mode the local checker
cannot: the box being unreachable from the internet.

---

## 7. Deploying changes

```bash
cd /var/www/backend
git status                 # check for skip-worktree weirdness (see §2)
git fetch origin && git log --oneline origin/main -3
git merge origin/main      # fast-forward
git ls-files -v | grep -v '^H '   # flags = trouble
./venv/bin/python -m py_compile main.py api/main.py   # then the touched files
sudo systemctl restart alienedge-api.service
curl -s http://127.0.0.1:8000/health
```

Frontend deploys itself: push to GitHub `main` → Vercel builds and deploys.
Backend does NOT — it only changes when you run the commands above.
