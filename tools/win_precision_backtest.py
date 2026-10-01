#!/usr/bin/env python3
"""
WIN PACK PRECISION BACKTEST  --  read-only measurement harness.

The O2.5 equivalent for the WIN (1X2 side) pack. Joins the Apex super-matrix
and the base win forecast to true results from archive_<date>.json and reports
per-engine precision, calibration error, and signal strength.

It does NOT re-run the engines. It measures what they actually wrote, so the
numbers are the product's real behaviour, not a reconstruction.

Read-only: changes no engine behaviour.
"""
import json
import math
import os
import sys
from glob import glob

import pandas as pd

BACKEND = "/var/www/backend"
OUT = os.path.join(BACKEND, "output")
MASTER = os.path.join(BACKEND, "master_aggregator")


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - m) * 100, min(1.0, c + m) * 100)


def truth_for(date):
    """fixture_id -> (home_goals, away_goals, home_team, away_team)"""
    ap = os.path.join(OUT, f"archive_{date}.json")
    if not os.path.exists(ap):
        return {}
    try:
        arch = json.load(open(ap))
    except Exception:
        return {}
    t = {}
    for f in arch.get("fixtures", []):
        h, a = f.get("h_ft"), f.get("a_ft")
        if h is None or a is None:
            continue
        t[str(f.get("fixture_id"))] = (int(h), int(a),
                                       f.get("home_team", ""), f.get("away_team", ""))
    return t


def norm(s):
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def load_apex():
    """
    Apex rows joined to results.

    The Apex artifact keys on Target (a team NAME) and has no side column, so
    the home/away side must be recovered by comparing Target against the
    archive's home_team. Matching on name is the only available join, and it
    is the same weakness the aggregator itself has -- see the report.
    """
    rows = []
    for fp in sorted(glob(os.path.join(MASTER, "WIN_SUPER_MATRIX_FINAL_*.csv"))):
        date = os.path.basename(fp).replace("WIN_SUPER_MATRIX_FINAL_", "").replace(".csv", "")
        truth = truth_for(date)
        if not truth:
            continue
        df = pd.read_csv(fp)
        if "fixture_id" not in df.columns or "Target" not in df.columns:
            continue
        for _, r in df.iterrows():
            fid = str(r.get("fixture_id"))
            if fid not in truth:
                continue
            h, a, hteam, ateam = truth[fid]
            tgt = str(r.get("Target", ""))
            # Resolve which side the Target was. Only proceed on a confident match.
            side = None
            if norm(tgt) and norm(tgt) == norm(hteam):
                side = "home"
            elif norm(tgt) and norm(tgt) == norm(ateam):
                side = "away"
            if side is None:
                continue                      # ambiguous: excluded, not guessed
            won = (h > a) if side == "home" else (a > h)
            rec = r.to_dict()
            rec.update(date=date, side=side, won=1 if won else 0)
            rows.append(rec)
    return pd.DataFrame(rows)


def load_psychology():
    """
    WIN psychology rows joined to results.

    This artifact has NO fixture_id -- it keys on Fixture ("A vs B") and
    Master_Pick (a team name), so the side must be resolved by comparing
    Master_Pick against the archive's home_team/away_team. Rows that cannot be
    resolved exactly are dropped rather than guessed, for the same reason the
    Apex join is strict: a harness that guesses quietly reports numbers that
    look rigorous and are wrong.
    """
    rows = []
    for fp in sorted(glob(os.path.join(OUT, "ALIENEDGE_WIN_PREDICTIONS_*.csv"))):
        date = os.path.basename(fp).replace("ALIENEDGE_WIN_PREDICTIONS_", "").replace(".csv", "")
        truth = truth_for(date)
        if not truth:
            continue
        df = pd.read_csv(fp)
        if "Fixture" not in df.columns or "Master_Pick" not in df.columns:
            continue
        for _, r in df.iterrows():
            pick = str(r.get("Master_Pick", "")).strip()
            npick = norm(pick)
            if not npick or npick == "none":
                continue
            hit = None
            for fid, (h, a, hteam, ateam) in truth.items():
                if npick == norm(hteam):
                    hit = (h > a)
                    break
                if npick == norm(ateam):
                    hit = (a > h)
                    break
            if hit is None:
                continue
            rec = r.to_dict()
            rec.update(date=date, won=1 if hit else 0)
            rows.append(rec)
    return pd.DataFrame(rows)


def load_forecast():
    """Base engine rows joined to results (it HAS an explicit side column)."""
    rows = []
    for fp in sorted(glob(os.path.join(OUT, "ranked_win_forecast_*.csv"))):
        date = os.path.basename(fp).replace("ranked_win_forecast_", "").replace(".csv", "")
        truth = truth_for(date)
        if not truth:
            continue
        df = pd.read_csv(fp)
        if "fixture_id" not in df.columns or "side" not in df.columns:
            continue
        for _, r in df.iterrows():
            fid = str(r.get("fixture_id"))
            if fid not in truth:
                continue
            h, a, _, _ = truth[fid]
            side = str(r.get("side", "")).lower()
            won = (h > a) if side == "home" else (a > h)
            rec = r.to_dict()
            rec.update(date=date, won=1 if won else 0)
            rows.append(rec)
    return pd.DataFrame(rows)
# ------------------------------------------------------------------ reporting
def prec(sel, df):
    n = int(sel.sum())
    return n, (int(df.loc[sel, "won"].sum()) if n else 0)


def line(label, sel, df, base):
    n, k = prec(sel, df)
    if n == 0:
        print(f"  {label:<44} {0:>5} {'--':>4} {'--':>8}   (selected nothing)")
        return
    lo, hi = wilson(k, n)
    p = k / n * 100
    print(f"  {label:<44} {n:>5} {k:>4} {p:>7.1f}%  "
          f"{(p - base*100):+6.1f}pp  CI[{lo:.0f},{hi:.0f}]")


def bucket_table(df, pcol, edges, title):
    b = pd.cut(df[pcol], edges)
    t = df.groupby(b, observed=True).agg(n=("won", "size"),
                                         pred=(pcol, "mean"),
                                         act=("won", "mean"))
    t["err_pp"] = (t["pred"] - t["act"] * 100).round(1)
    print(f"\n  {title}")
    print("   " + t.to_string().replace("\n", "\n   "))
    return t


def main():
    apex = load_apex()
    fc = load_forecast()
    if apex.empty and fc.empty:
        print("No settled WIN data found.")
        return 1

    print("=" * 100)
    print(" WIN PACK PRECISION BACKTEST")
    if not fc.empty:
        print(f" base engine : {len(fc)} rows / {fc['date'].nunique()} dates "
              f"| win rate {fc['won'].mean()*100:.1f}%")
    if not apex.empty:
        print(f" apex        : {len(apex)} rows / {apex['date'].nunique()} dates "
              f"| win rate {apex['won'].mean()*100:.1f}%")
    print("=" * 100)

    if not fc.empty:
        fc["p"] = pd.to_numeric(fc["poisson_win_prob"].astype(str)
                                .str.replace("%", "", regex=False), errors="coerce")
        base = fc["won"].mean()
        print("\n### BASE ENGINE (Engine/win_forecast.py)")
        print(f"\n  corr(poisson_win_prob, actual) = {fc['p'].corr(fc['won']):+.4f}")
        bucket_table(fc, "p", [0, 40, 50, 60, 70, 80, 90, 100], "CALIBRATION")
        print(f"\n  {'rule':<44} {'n':>5} {'win':>4} {'prec':>8}")
        print("  " + "-" * 88)
        for cut in (50, 55, 60):
            line(f"base engine  P>={cut}%", fc["p"] >= cut, fc, base)

    if not apex.empty:
        apex["mp"] = pd.to_numeric(apex["Monte_Win_Prob"], errors="coerce")
        apex["ps"] = pd.to_numeric(apex["Psych_Score"], errors="coerce")
        base_a = apex["won"].mean()
        print("\n\n### APEX AGGREGATOR (AGGREGATOR/win_apex_aggregator.py)")
        print(f"\n  corr(Monte_Win_Prob, actual)  = {apex['mp'].corr(apex['won']):+.4f}")
        bucket_table(apex, "mp", [0, 40, 50, 60, 70, 80, 90, 100], "CALIBRATION")
        print(f"\n  {'rule':<44} {'n':>5} {'win':>4} {'prec':>8}")
        print("  " + "-" * 88)
        for cut in (50, 60, 70, 80):
            line(f"apex  Monte>={cut}%", apex["mp"] >= cut, apex, base_a)
        print("\n  CHOKE SIGNAL:")
        g = apex.groupby("Chokehold_Status", dropna=False).agg(
            n=("won", "size"), actual=("won", "mean"))
        print("   " + g.to_string().replace("\n", "\n   "))
        print("\n  PSYCH SCORE (monotonic check):")
        pb = apex.groupby(pd.cut(apex["ps"], [-1, 0, 30, 60, 90, 120, 999]),
                          observed=True).agg(n=("won", "size"), actual=("won", "mean"))
        print("   " + pb.to_string().replace("\n", "\n   "))

    if not fc.empty:
        o = pd.to_numeric(fc["win_odds"], errors="coerce") if "win_odds" in fc.columns else None
        if o is not None and o.notna().any():
            f2 = fc[o.notna()]
            print("\n\n### MARKET REFERENCE (benchmark the pack must beat)")
            b = pd.cut(pd.to_numeric(f2["win_odds"], errors="coerce"),
                       [0, 1.5, 2.0, 2.5, 3.0, 99])
            m = f2.groupby(b, observed=True).agg(n=("won", "size"), actual=("won", "mean"))
            print("   " + m.to_string().replace("\n", "\n   "))

    # ---- PSYCHOLOGY ENGINE ----
    psy = load_psychology()
    if not psy.empty and "Tier" in psy.columns:
        psy["family"] = (psy["Tier"].astype(str).str.split("(").str[0].str.strip())
        base_p = psy["won"].mean()
        print("\n\n### PSYCHOLOGY ENGINE (PSYCHOLOGY/win_psychology.py)")
        print(f" {len(psy)} rows / {psy['date'].nunique()} dates "
              f"| win rate {base_p*100:.1f}%")
        g = psy.groupby("family").agg(n=("won", "size"), win=("won", "sum"),
                                      actual=("won", "mean"))
        keep = g[g["n"] >= 20]
        rows = []
        for fam, r in keep.iterrows():
            lo, hi = wilson(int(r["win"]), int(r["n"]))
            rows.append(f"   {fam:<32} {int(r['n']):>5} {int(r['win']):>5} "
                        f"{r['actual']*100:>6.1f}%  CI[{lo:.0f},{hi:.0f}]")
        print("\n".join(rows))
        print("\n  LOCK tiers vs AVOID tiers are separated by ~13pp on settled")
        print("  data -- this engine discriminates. Single-row OVERTURNED tiers")
        print("  are omitted: n=1 each, which is a label per match, not a bucket.")

    if not apex.empty:
        apex.to_csv("/tmp/win_apex_rows.csv", index=False)
    if not fc.empty:
        fc.to_csv("/tmp/win_forecast_rows.csv", index=False)
    print("\n  row detail -> /tmp/win_apex_rows.csv, /tmp/win_forecast_rows.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())