#!/usr/bin/env python3
"""
O2.5 CALIBRATION MONITOR  --  ongoing precision reporting.

o25_precision_backtest.py answers "what was the precision?". This answers
"what IS the precision?", on whatever is settled today, using the artifacts
the pipeline actually wrote. Run it after each daily settlement.

It reports each engine's hit rate, its 95% Wilson confidence interval, and
whether that interval clears the base rate -- so a good day is not mistaken
for a good engine, and a bad day is not mistaken for a broken one.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from glob import glob

import pandas as pd

OUT = "/var/www/backend/output"
MIN_N = 30          # below this, a rate is noise and is labelled as such


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - m) * 100, min(1.0, c + m) * 100)


def verdict(lo, hi, base, n):
    """Only claim an edge when the WHOLE interval sits above the base rate."""
    if n < MIN_N:
        return "TOO FEW (noise)"
    if lo > base:
        return "EDGE (CI clears base)"
    if hi < base:
        return "NEGATIVE (CI below base)"
    return "indistinguishable"


def load(days=21):
    rows = []
    files = sorted(glob(os.path.join(OUT, "master_over_stage2_*.csv")))
    for feat_path in files[-days:]:
        date = os.path.basename(feat_path).replace("master_over_stage2_", "").replace(".csv", "")
        arch_path = os.path.join(OUT, f"archive_{date}.json")
        if not os.path.exists(arch_path):
            continue
        try:
            arch = json.load(open(arch_path))
        except Exception:
            continue
        truth = {str(f.get("fixture_id")): f.get("total_goals")
                 for f in arch.get("fixtures", []) if f.get("total_goals") is not None}
        if not truth:
            continue
        df = pd.read_csv(feat_path)
        if "fixture_id" not in df.columns:
            continue
        for _, r in df.iterrows():
            fid = str(r.get("fixture_id"))
            if fid in truth:
                rows.append(dict(
                    date=date,
                    odds=r.get("o25_odds"),
                    poisson=r.get("poisson_over_prob_num"),
                    votes=r.get("council_votes"),
                    kill=r.get("kill_switch_pass"),
                    hit=1 if int(truth[fid]) >= 3 else 0,
                ))
    return pd.DataFrame(rows)


def line(label, sel, df, base):
    """
    base is passed as a FRACTION (0.543) while the Wilson interval comes back
    in PERCENT (54.3). Compare in percent or every verdict is wrong -- a 53.7%
    rate with CI[47,61] reads as an "edge" against 0.543.
    """
    base_pct = base * 100
    n = int(sel.sum())
    k = int(df.loc[sel, "hit"].sum())
    if n == 0:
        print(f"  {label:<40} {0:>5} {'--':>5} {'--':>7}  {verdict(0, 0, base_pct, 0)}")
        return
    lo, hi = wilson(k, n)
    print(f"  {label:<40} {n:>5} {k:>5} {k/n*100:>6.1f}%  "
          f"CI[{lo:.0f},{hi:.0f}] {verdict(lo, hi, base_pct, n)}")


def main():
    df = load()
    if df.empty:
        print("No settled fixtures available yet. Run this after the daily settlement.")
        return 1
    base = df["hit"].mean()

    print("=" * 104)
    print(f" O2.5 CALIBRATION MONITOR | {len(df)} settled | {df['date'].nunique()} dates "
          f"| base rate {base*100:.1f}%")
    print("=" * 104)
    print("\nPer-engine precision (a rate is only meaningful with enough samples)\n")

    df["votes_n"] = pd.to_numeric(df["votes"].astype(str).str.split("/").str[0], errors="coerce").fillna(0)
    df["poisson_n"] = pd.to_numeric(df["poisson"], errors="coerce")

    for cut in (6, 7):
        line(f"Forecast council  votes>={cut}/9", df["votes_n"] >= cut, df, base)
    for cut in (60, 70):
        line(f"Forecast Poisson  P>={cut}%", df["poisson_n"] >= cut, df, base)

    apex_path = os.path.join(OUT, "master_aggregator", "O25_MASTER_LIVE.csv")
    if os.path.exists(apex_path):
        ap = pd.read_csv(apex_path)
        if "Super_Monte_Prob" in ap.columns:
            merged = df.merge(ap[["Fixture", "Super_Monte_Prob"]],
                              left_on=None, right_on=None, how="inner") \
                if "Fixture" in df.columns else None
            if merged is not None and len(merged):
                for cut in (60, 66):
                    line(f"Apex Super_Monte  P>={cut}%",
                         pd.to_numeric(merged["Super_Monte_Prob"], errors="coerce") >= cut,
                         merged, base)

    print("\nMarket reference (the benchmark the pack must beat)\n")
    o = pd.to_numeric(df["odds"], errors="coerce")
    for lo_, hi_ in ((0, 1.4), (1.4, 1.6), (1.6, 1.85), (1.85, 2.2), (2.2, 99)):
        line(f"O2.5 odds {lo_}-{hi_}", (o >= lo_) & (o < hi_), df, base)

    print("\n  Read this as: a pack that cannot clear the base rate inside its CI")
    print("  is not selecting, it is filtering noise.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())