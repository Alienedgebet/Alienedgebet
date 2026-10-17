#!/usr/bin/env python3
"""Background monitor for the alienedge-pipeline midnight run (oneshot service).
Writes a concise run report (start, end, runtime, 429 tally) to:
  /var/www/backend/output/ops/midnight_run_report.txt
No engine code is read or written by this monitor; it only observes systemd + logs.
"""
import subprocess, os, time, datetime, glob

SVC = "alienedge-pipeline.service"
REPORT = "/var/www/backend/output/ops/midnight_run_report.txt"
LOG = "/var/www/backend/output/pipeline_scheduler.log"
HB = "/var/www/backend/data/pipeline_heartbeat.json"
os.makedirs(os.path.dirname(REPORT), exist_ok=True)

def sh(c, t=8):
    try:
        o = subprocess.run(c, shell=True, capture_output=True, text=True, timeout=t)
        return (o.stdout + o.stderr).strip()
    except Exception as e:
        return f"ERR {e}"

def dt_from_systemd(s):
    # "Tue 2026-10-13 00:00:08 WAT" -> drop tz word -> parse
    if not s or not s[0].isalpha():
        return None
    try:
        return datetime.datetime.strptime(s.rsplit(" ", 1)[0], "%a %Y-%m-%d %H:%M:%S")
    except Exception:
        return None

def tally_429():
    hits = 0
    bursts = 0
    if os.path.exists(LOG):
        try:
            for line in open(LOG, errors="replace"):
                if "429" in line:
                    hits += 1
                if "API Rate Limit Hit (429)" in line:
                    bursts += 1
        except Exception:
            pass
    return hits, bursts

start_ts = sh(f"systemctl show -p ExecMainStartTimestamp --value {SVC}")
start_dt = dt_from_systemd(start_ts)
init_hits, init_bursts = tally_429()
with open(REPORT, "w") as f:
    f.write("=== AlienEdge Midnight Pipeline Run Monitor ===\n")
    f.write(f"monitor start : {datetime.datetime.now().strftime('%F %T %Z')}\n")
    f.write(f"service start : {start_ts}  (parsed: {start_dt})\n")
    f.write(f"initial 429 lines/bursts: {init_hits} / {init_bursts}\n\n")
    f.write(f"[start] is-active={sh('systemctl is-active ' + SVC)} 429sofar={init_hits}/{init_bursts}\n")

last = None
while True:
    state = sh(f"systemctl is-active {SVC}")
    if state in ("inactive", "failed"):
        end_ts = sh(f"systemctl show -p InactiveEnterTimestamp --value {SVC}")
        end_dt = dt_from_systemd(end_ts)
        runtime = "unknown"
        if start_dt and end_dt:
            secs = (end_dt - start_dt).total_seconds()
            runtime = f"{secs:.0f}s  (~{secs/60:.1f} min)"
        hits, bursts = tally_429()
        with open(REPORT, "a") as f:
            f.write(f"\n=== RUN ENDED ===\n")
            f.write(f"final state : {state}\n")
            f.write(f"service end : {end_ts}  (parsed: {end_dt})\n")
            f.write(f"runtime     : {runtime}\n")
            f.write(f"429 lines   : {hits}   discrete 429 events: {bursts}\n")
            f.write(f"\n--- heartbeat (data/pipeline_heartbeat.json, last 8 lines) ---\n")
            f.write((open(HB, errors="replace").read().splitlines()[-8:] and "\n".join(open(HB, errors="replace").read().splitlines()[-8:])) + "\n")
            f.write(f"\n--- scheduler log tail (last 25 lines) ---\n")
            try:
                f.write("\n".join(open(LOG, errors="replace").read().splitlines()[-25:]) + "\n")
            except Exception as e:
                f.write(f"ERR {e}\n")
        break
    if state != last:
        hits, bursts = tally_429()
        with open(REPORT, "a") as f:
            f.write(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] still {state}  429 lines={hits} bursts={bursts}\n")
        last = state
    time.sleep(20)

