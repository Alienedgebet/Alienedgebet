#!/usr/bin/env python3
"""Score the Stage 8 prediction log against final results."""
import argparse
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DATA_DIR = os.path.join(ROOT, "data")
DEFAULT_LOG = os.path.join(DATA_DIR, "stage8_prediction_log.jsonl")
FT_SNAPSHOT = os.path.join(DATA_DIR, "ft_result_snapshot.json")


def _load_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except (ValueError, TypeError):
                continue
    return rows


def _ft_index():
    out = {}
    if not os.path.exists(FT_SNAPSHOT):
        return out
    try:
        with open(FT_SNAPSHOT, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except (ValueError, OSError, TypeError):
        return out
    rows = doc if isinstance(doc, list) else doc.get("fixtures", doc)
    if isinstance(rows, dict):
        rows = list(rows.values())
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        fid = str(r.get("fixture_id") or r.get("id") or "")
        hg = r.get("home_goals", r.get("home_score"))
        ag = r.get("away_goals", r.get("away_score"))
        if hg is None or ag is None:
            sc = str(r.get("score") or r.get("ft_score") or "")
            parts = sc.replace("-", " ").replace(":", " ").split()
            if len(parts) >= 2:
                try:
                    hg, ag = int(parts[0]), int(parts[1])
                except (TypeError, ValueError):
                    continue
            else:
                continue
        try:
            out[fid] = (int(hg), int(ag))
        except (TypeError, ValueError):
            continue
    return out


def _brier(prob_pct, outcome):
    p = float(prob_pct or 0) / 100.0
    return (p - (1.0 if outcome else 0.0)) ** 2


def score(log_path):
    entries = _load_jsonl(log_path)
    ft = _ft_index()
    if not entries:
        print("no log entries at %s yet." % log_path)
        return 1
    if not ft:
        print("no FT snapshot — %d entries waiting for results." % len(entries))
        return 1
    per_line = defaultdict(list)
    per_anchor = defaultdict(list)
    per_minute = defaultdict(list)
    buckets = defaultdict(lambda: [0, 0])
    settled = 0
    for e in entries:
        fid = str(e.get("fixture_id") or "")
        if fid not in ft:
            continue
        hg, ag = ft[fid]
        total = hg + ag
        minute = int(e.get("minute") or 0)
        preds = e.get("predictions") or {}
        lines = {
            "home_win": (preds.get("home_win"), hg > ag),
            "draw": (preds.get("draw"), hg == ag),
            "away_win": (preds.get("away_win"), hg < ag),
            "over_2_5": (preds.get("over_2_5"), total > 2),
        }
        row = []
        for name, (prob, outcome) in lines.items():
            if prob is None:
                continue
            b = _brier(prob, outcome)
            per_line[name].append(b)
            row.append(b)
            bk = int(float(prob or 0) // 10 * 10)
            buckets[bk][0] += 1
            buckets[bk][1] += 1 if outcome else 0
        if row:
            settled += 1
            mb = sum(row) / len(row)
            per_anchor[str(e.get("anchor") or "unknown")].append(mb)
            per_minute["%d-%d" % (minute // 15 * 15, minute // 15 * 15 + 14)].append(mb)
    print("=" * 70)
    print("STAGE 8 SCORE — settled readings only")
    print("=" * 70)
    print("settled: %d / %d logged" % (settled, len(entries)))
    print("%-12s %6s %8s" % ("line", "n", "brier"))
    for name in ("home_win", "draw", "away_win", "over_2_5"):
        vals = per_line.get(name, [])
        avg = sum(vals) / len(vals) if vals else float("nan")
        print("%-12s %6d %8.4f" % (name, len(vals), avg))
    print("Brier: 0 = perfect, 0.25 = coin-flip. Lower wins.")
    print("-- by anchor --")
    for a, vals in sorted(per_anchor.items()):
        print("  %-22s n=%-5d %.4f" % (a, len(vals), sum(vals) / len(vals)))
    print("-- by minute --")
    for b, vals in sorted(per_minute.items()):
        print("  %-9s n=%-5d %.4f" % (b, len(vals), sum(vals) / len(vals)))
    print("-- calibration (bucket -> observed) --")
    for b in sorted(buckets):
        n, hits = buckets[b]
        print("  %3d-%-3d n=%-5d obs %5.1f%%" % (b, b + 9, n, 100.0 * hits / n if n else 0))
    print("NOTE: to-score-next needs goal-TIME data — logged, not scored.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=DEFAULT_LOG)
    sys.exit(score(ap.parse_args().log))


if __name__ == "__main__":
    main()
