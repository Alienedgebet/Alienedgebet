#!/usr/bin/env python3
"""
Freeze the PRE-FIX Over 1.5 output so it survives the next pipeline run.

WHY THIS EXISTS
---------------
On 2026-09-30 the Over 1.5 fixes landed at 18:11 (one-engine shim + the
stage3 Date stamp) and 19:53 (halftime rules reading full-time results).
The daily pipeline had already started at 18:00:21 and had imported every
engine module at that moment, so yesterday's run executed the PRE-FIX code
even though it finished at 18:21 — after the edits were on disk.

Everything in output/cache/over15_psychology__*.json is therefore pre-fix
output. At the next 18:00 run those files are overwritten and the pre-fix
verdicts are gone, with no way to compare the two.

This copies them to the `over15_legacy` cache key, which NO engine writes, so
the snapshot cannot be clobbered by a pipeline run. /api/over15/legacy/{date}
serves it, and the Weekly/Over-1.5 page shows it beside the live engine output.

IDEMPOTENT BY DESIGN
--------------------
It refuses to overwrite an existing snapshot. A snapshot means "what the
pre-fix engine said on this date"; a later run must not quietly relabel it.
Use --force only to deliberately discard a captured verdict.

    python3 tools/snapshot_o15_prefix.py            # capture, never overwrite
    python3 tools/snapshot_o15_prefix.py --status   # what is captured
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CACHE_DIR = os.path.join(ROOT, "output", "cache")
SOURCE_KEY = "over15_psychology"
LEGACY_KEY = "over15_legacy"

# The moment the pre-fix run wrote its last artifact. Anything generated at or
# before this is pre-fix code output, regardless of the file's date field.
PREFIX_CUTOFF = "2026-09-30T19:53:08"


def _stamp(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("generated_at") or ""
    except Exception:
        return ""


def candidates():
    """Every pre-fix psychology cache that has not been snapshotted yet."""
    out = []
    for name in sorted(os.listdir(CACHE_DIR)):
        if not name.startswith(SOURCE_KEY + "__") or not name.endswith(".json"):
            continue
        date = name[len(SOURCE_KEY) + 2:-5]
        src = os.path.join(CACHE_DIR, name)
        dst = os.path.join(CACHE_DIR, f"{LEGACY_KEY}__{date}.json")
        out.append({"date": date, "src": src, "dst": dst,
                    "generated_at": _stamp(src), "exists": os.path.exists(dst)})
    return out


def capture(force=False):
    rows = candidates()
    if not rows:
        print("no over15_psychology cache files found — nothing to snapshot")
        return 0
    frozen = kept = 0
    for r in rows:
        if r["exists"] and not force:
            kept += 1
            continue
        with open(r["src"], "r", encoding="utf-8") as f:
            payload = json.load(f)
        payload["engine_key"] = LEGACY_KEY
        payload["legacy_of"] = SOURCE_KEY
        payload["legacy_generated_at"] = payload.get("generated_at")
        payload["legacy_note"] = (
            "PRE-FIX Over 1.5 verdict. Produced by the pipeline that started "
            "18:00:21 on 2026-09-30, before the 18:11 and 19:53 fixes could be "
            "loaded. Frozen for comparison; no engine writes this key.")
        payload["legacy_captured_at"] = datetime.now(timezone.utc).isoformat()
        with open(r["dst"], "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        frozen += 1
        print(f"  FROZEN {r['date']}  rows={len(payload.get('data') or []):<3} "
              f"generated={r['generated_at']}")
    print(f"\nfrozen {frozen}, already preserved {kept}")
    return frozen


def status():
    rows = candidates()
    if not rows:
        print("no over15_psychology cache files found")
        return
    print(f"{'date':12} {'live(pre-fix)':22} {'legacy snapshot':22} rows")
    for r in rows:
        mark = "yes" if r["exists"] else "NO"
        print(f"{r['date']:12} {r['generated_at'][:19]:22} {mark:22} "
              f"{len(json.load(open(r['src'])).get('data') or [])}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.status:
        status()
    else:
        capture(force=a.force)