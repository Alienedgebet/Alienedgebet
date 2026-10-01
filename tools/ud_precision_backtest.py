#!/usr/bin/env python3
"""
UNDERDOG PACK PRECISION BACKTEST  --  read-only measurement harness.

Graded to the CORRECT target: "does the underdog SCORE at least one goal".
That is what this pack predicts -- Engine/underdog_engine.py defines
get_underdog_score_prob as "% chance of scoring 1 or more goals" and the
Apex asks np.sum(sim_goals > 0). Grading it against "did the underdog
WIN" instead produces a fictitious ~34pp error and leads to the wrong
conclusion; that mistake was made and corrected on 2026-10-01.

Joins each stage to archive_<date>.json and reports correlation,
calibration and ranking power per stage. Changes no engine behaviour.
"""
import json
import math
import os
import sys
from glob import glob

import pandas as pd

OUT = "/var/www/backend/output"


def norm(s):
    return "".join(c for c in str(s).lower() if c.isalnum())


def load():
    base, aud, apx = {}, {}, {}
    for fp in sorted(glob(os.path.join(OUT, "backtest_underdog_*.csv"))):
        d = os.path.basename(fp).replace("backtest_underdog_", "").replace(".csv", "")
        for _, r in pd.read_csv(fp).iterrows():
            base[(d, str(r["fixture_id"]))] = r.to_dict()
    for fp in sorted(glob(os.path.join(OUT, "audited_underdog_backtest_*.csv"))):
        d = os.path.basename(fp).replace("audited_underdog_backtest_", "").replace(".csv", "")
        for _, r in pd.read_csv(fp).iterrows():
            aud[(d, str(r["fixture_id"]))] = r.to_dict()
    for fp in sorted(glob(os.path.join(OUT, "FINAL_APEX_UD_SCORE_*.csv"))):
        d = os.path.basename(fp).replace("FINAL_APEX_UD_SCORE_", "").replace(".csv", "")
        for _, r in pd.read_csv(fp).iterrows():
            apx[(d, str(r["fixture_id"]))] = r.to_dict()

    rows = []
    for fp in sorted(glob(os.path.join(OUT, "audited_underdog_backtest_*.csv"))):
        date = os.path.basename(fp).replace("audited_underdog_backtest_", "").replace(".csv", "")
        ap = os.path.join(OUT, f"archive_{date}.json")
        if not os.path.exists(ap):
            continue
        truth = {str(f.get("fixture_id")): (f.get("h_ft"), f.get("a_ft"),
                                             f.get("home_team", ""), f.get("away_team", ""))
                 for f in json.load(open(ap)).get("fixtures", []) if f.get("h_ft") is not None}
        for _, r in pd.read_csv(fp).iterrows():
            k = (date, str(r["fixture_id"]))
            if k[1] not in truth:
                continue
            h, a, ht, at = truth[k[1]]
            t = str(r.get("underdog_team", ""))
            if not t or t == "None":
                continue
            side = "home" if norm(t) == norm(ht) else ("away" if norm(t) == norm(at) else None)
            if side is None:
                continue
            dg = h if side == "home" else a
            rec = {"date": date, "fid": k[1],
                   "scored": int(dg >= 1), "dog_goals": dg,
                   "base_dsp": base.get(k, {}).get("dog_score_prob"),
                   "aud_dsp": r.get("Dog_Score_Prob"),
                   "aud_arp": r.get("Audit_Real_Prob"),
                   "aud_dg": r.get("Dominance_Gap"),
                   "apx_mp": apx.get(k, {}).get("Monte_UD_Prob")}
            rows.append(rec)
    d = pd.DataFrame(rows)
    p = lambda s: pd.to_numeric(d[s].astype(str).str.replace("%", "", regex=False), errors="coerce")
    d["base_dsp"] = p("base_dsp"); d["aud_dsp"] = p("aud_dsp")
    d["aud_arp"] = p("aud_arp"); d["apx_mp"] = p("apx_mp")
    d["aud_dg"] = pd.to_numeric(d["aud_dg"], errors="coerce")
    return d


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - m) * 100, min(1.0, c + m) * 100)


def main():
    d = load()
    if d.empty:
        print("No settled underdog data.")
        return 1
    base = d["scored"].mean()
    print("=" * 92)
    print(" UNDERDOG BACKTEST  |  target = 'underdog scores 1+ goal'")
    print(f" {len(d)} rows / {d['date'].nunique()} dates | base rate {base*100:.1f}%")
    print("=" * 92)

    print(f"\n  {'stage':<34} {'n':>5} {'corr':>9} {'|err|':>8}")
    print("  " + "-" * 60)
    for col, lab in [("base_dsp", "1. base dog_score_prob"),
                     ("aud_dsp", "2. audit Dog_Score_Prob"),
                     ("aud_arp", "3. audit Audit_Real_Prob"),
                     ("apx_mp", "4. apex Monte_UD_Prob")]:
        s = d[col].notna()
        if s.sum() < 30:
            continue
        x = d[s]
        t = x.groupby(pd.cut(x[col], [0, 60, 70, 80, 90, 100]),
                      observed=True).agg(n=("scored", "size"), pr=(col, "mean"), ac=("scored", "mean"))
        e = t.pr - t.ac * 100
        print(f"  {lab:<34} {s.sum():>5} {x[col].corr(x['scored']):>+9.4f} "
              f"{(t.n*e.abs()).sum()/t.n.sum():>7.1f}pp")

    a = d.dropna(subset=["apx_mp", "aud_arp"])
    if len(a) >= 20:
        print(f"\n### APEX RANKING POWER  (n={len(a)}, base {base*100:.1f}%)")
        print("\n  The Apex should at minimum preserve its own input's ranking.")
        print(f"\n  {'top':>6} {'apex out':>10} {'apex input':>11} {'base':>8}")
        print("  " + "-" * 40)
        for k in (5, 10, 20, 30):
            n = int(len(a) * k / 100)
            if n < 5:
                continue
            print(f"  {k:>5}% {a.nlargest(n,'apx_mp')['scored'].mean()*100:>9.1f}% "
                  f"{a.nlargest(n,'aud_arp')['scored'].mean()*100:>10.1f}% {base*100:>7.1f}%")
        print("\n  A NEGATIVE or badly-lagging 'apex out' column means the")
        print("  aggregator is anti-selecting. Fixed 2026-10-01: the value is")
        print("  now passed through and shrunk, preserving the input ranking.")

    for col, lab in [("aud_arp", "audit Audit_Real_Prob"), ("apx_mp", "apex Monte_UD_Prob")]:
        s = d[col].notna()
        if s.sum() < 30:
            continue
        x = d[s]
        print(f"\n### {lab} — confidence vs reality")
        t = x.groupby(pd.cut(x[col], [0, 60, 70, 80, 90, 100]),
                      observed=True).agg(n=("scored", "size"), claimed=(col, "mean"), actual=("scored", "mean"))
        t["error_pp"] = (t.claimed - t.actual * 100).round(1)
        print("  " + t.to_string().replace("\n", "\n  "))

    d.to_csv("/tmp/ud_backtest_rows.csv", index=False)
    print("\n  row detail -> /tmp/ud_backtest_rows.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
