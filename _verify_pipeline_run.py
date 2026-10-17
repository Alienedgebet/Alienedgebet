"""Post-run verification for a pipeline date. Run AFTER main.py finishes.

Checks the invariants the 2026-09-11 fixes must guarantee:
  A. envelope integrity: status ok => data not None; failed => error present
  B. no silent-null-success (the old save(None, status=ok) bug)
  C. BUG-2: fixed aggregators emit integer fixture_ids, never 'N/A'/strings
  D. no cross-key identical data payloads (excluding legit latest/dated pairs)
  E. row counts per engine key
Usage: venv/bin/python3 _verify_pipeline_run.py 2026-09-11
"""
import sys
import os
import json
import glob
import hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import output_store as store

date = sys.argv[1] if len(sys.argv) > 1 else None
if not date:
    print("usage: _verify_pipeline_run.py YYYY-MM-DD")
    sys.exit(2)

files = sorted(glob.glob(os.path.join(store.CACHE_DIR, f"*__{date}.json")))
fails = []
warns = []

print(f"== VERIFYING {date} ({len(files)} dated cache files) ==\n")

# ── A/B: envelope integrity, no silent-null-success ────────────────────────
payloads = {}
for f in files:
    key = os.path.basename(f).replace(f"__{date}.json", "")
    try:
        with open(f, encoding="utf-8") as fh:
            p = json.load(fh)
    except Exception as e:
        fails.append(f"{key}: unreadable ({e})")
        continue
    status, error, data = p.get("status"), p.get("error"), p.get("data")
    if status == "ok" and data is None:
        fails.append(f"{key}: SILENT-NULL-SUCCESS (status ok, data null)")
    elif status == "failed" and not error:
        fails.append(f"{key}: status failed but no error message")
    elif status not in ("ok", "failed"):
        fails.append(f"{key}: unknown status {status!r}")
    payloads[key] = data
    rows = len(data) if isinstance(data, list) else (0 if data is None else "dict")
    if rows == 0:
        warns.append(f"{key}: status={status} rows=0 error={error!r}")

# ── C: BUG-2 fixture_id integrity in the five fixed aggregators ────────────
BUG2_KEYS = {
    "gg_supreme", "underdog_apex", "win_apex", "over25_apex",
}
for key in BUG2_KEYS:
    data = payloads.get(key)
    if data is None:
        warns.append(f"{key}: no data for BUG-2 check")
        continue
    if not isinstance(data, list):
        fails.append(f"{key}: expected list for BUG-2 check")
        continue
    bad = []
    for i, row in enumerate(data):
        fid = row.get("fixture_id")
        if not isinstance(fid, int) or isinstance(fid, bool):
            bad.append((i, fid))
    if bad:
        fails.append(f"{key}: {len(bad)} rows with non-integer fixture_id e.g. {bad[:3]}")
    else:
        print(f"[ok] {key}: {len(data)} rows, all fixture_ids integer")

# ── D: cross-key identical payloads (exclude legit latest/dated pairs) ────
hash_map = {}
for key, data in payloads.items():
    h = hashlib.md5(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
    hash_map.setdefault(h, []).append(key)
LEGIT_PAIRS = {"filter_gg"}  # filter_gg saves same data dated + latest (latest not in dated glob)
print("\n-- duplicate data payloads across keys --")
dups = {h: ks for h, ks in hash_map.items() if len(ks) > 1}
if not dups:
    print("[ok] no cross-key identical payloads")
else:
    for h, ks in dups.items():
        if set(ks) <= LEGIT_PAIRS:
            continue
        fails.append(f"cross-key pollution: {ks} share identical data")
        print(f"[FAIL] shared payload: {ks}")

# ── E: summary ─────────────────────────────────────────────────────────────
print("\n-- per-key row counts --")
for key in sorted(payloads):
    d = payloads[key]
    rows = len(d) if isinstance(d, list) else type(d).__name__
    print(f"  {key:35s} {rows}")

print("\n" + "=" * 60)
if warns:
    print("WARNINGS:")
    for w in warns:
        print("  !", w)
if fails:
    print("FAILURES:")
    for f in fails:
        print("  ✗", f)
    sys.exit(1)
print(f"ALL INVARIANTS OK for {date} ✅")
