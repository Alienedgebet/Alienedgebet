#!/usr/bin/env python3
"""
DRAW ENGINE PRECISION BACKTEST  --  read-only measurement harness.

WHY THIS EXISTS
  Every other major market in this repo has been measured against settled
  results: WIN (tools/win_precision_backtest.py), O2.5
  (tools/o25_precision_backtest.py), UNDERDOG (tools/ud_precision_backtest.py),
  GG/O1.5 (tools/gg_o15_backtest.py). The DRAW engine had NONE. It ships a
  "Perfect Draw List" tier, a composite score, a Poisson draw probability, a
  Monte-Carlo draw probability and a value edge -- and not one of those numbers
  had ever been compared to an outcome. This harness does that and nothing else.

GRADED TO THE CORRECT TARGET
  "Did the match end level after 90 minutes" = archive h_ft == a_ft.
  This is deliberately NOT the "parity" sub-list (parity is a goals-gap <= 2
  concept graded with market key "parity" in api/main.py) and NOT a
  "low-scoring game" concept.

JOIN RIGOUR
  Joined strictly on (date, fixture_id) -- the exact integer key both files
  carry. No name matching, no fuzzy matching, no fallback. A row that cannot be
  resolved EXACTLY is dropped and counted, never guessed. This matters: an
  exploratory version of the WIN harness guessed team sides and reported a
  correlation of +0.0093 where the true value was +0.2306 (commit 5b918f3).
  A harness that guesses quietly is worse than no harness.

READ-ONLY
  Changes no engine behaviour and writes nothing except its own row dump.
  Safe to run against production.
"""
import json
import math
import os
import sys
from glob import glob

import pandas as pd

OUT = "/var/www/backend/output"


# ----------------------------------------------------------------------------
# AUC without scipy: the probability a random positive outranks a random
# negative. 0.500 = the signal carries no information at all. Ties -> 0.5.
# ----------------------------------------------------------------------------
def auc(score, label):
    df = pd.DataFrame({"s": pd.to_numeric(score, errors="coerce"),
                       "y": pd.to_numeric(label, errors="coerce")}).dropna()
    n = len(df)
    if n < 20 or df["y"].nunique() < 2:
        return float("nan"), n
    r = df["s"].rank(method="average")
    n1 = int(df["y"].sum())
    n0 = n - n1
    if n1 == 0 or n0 == 0:
        return float("nan"), n
    return float((r[df["y"] == 1].sum() - n1 * (n1 + 1) / 2.0) / (n0 * n1)), n


def wilson(k, n, z=1.96):
    """Wilson 95% interval. A rate whose interval still crosses the base rate
    is NOT evidence of an edge -- one good day is not a good engine."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - m) * 100, min(1.0, c + m) * 100)


def rate(d):
    d = d.dropna(subset=["drew"])
    k, n = int(d["drew"].sum()), len(d)
    lo, hi = wilson(k, n)
    return k, n, (k / n * 100 if n else float("nan")), lo, hi


NUM_COLS = ("composite_draw_score", "mc_draw_prob", "poisson_draw_prob", "dmi",
            "parity", "value_edge", "draw_odds", "fatigue_score", "league_weight",
            "mc_spread", "most_likely_draw_pct", "total_draws", "home_draws",
            "away_draws", "h2h_draws", "home_position", "away_position")


def load():
    """Join every dated DRAW artifact to that date's settled archive."""
    rows, unresolved = [], 0
    for fp in sorted(glob(os.path.join(OUT, "ALIENEDGE_DRAW_PICKS_*.csv"))):
        base = os.path.basename(fp)
        date = base.replace("ALIENEDGE_DRAW_PICKS_", "").replace(".csv", "")
        if not date or "Ctrl" in date:
            continue
        ap = os.path.join(OUT, f"archive_{date}.json")
        if not os.path.exists(ap):
            continue
        try:
            truth = {}
            for f in json.load(open(ap)).get("fixtures", []):
                if f.get("h_ft") is None or f.get("a_ft") is None:
                    continue
                truth[str(f.get("fixture_id"))] = (int(f["h_ft"]), int(f["a_ft"]))
            if not truth:
                continue
        except Exception:
            continue

        try:
            df = pd.read_csv(fp)
        except Exception:
            continue
        if df.empty or "fixture_id" not in df.columns:
            continue

        for _, r in df.iterrows():
            fid = str(r.get("fixture_id"))
            if fid not in truth:
                unresolved += 1
                continue
            h, a = truth[fid]
            rec = {"date": date, "fixture_id": fid,
                   "h_ft": h, "a_ft": a,
                   "drew": int(h == a), "total_goals": h + a}
            for col in NUM_COLS:
                rec[col] = r.get(col)
            for col in ("tier", "section", "veto_reason", "mc_stability"):
                v = r.get(col)
                # NaN is truthy, so str(nan) would fabricate a non-empty
                # string and report a 100% veto rate. Treat it as empty.
                rec[col] = "" if v is None or pd.isna(v) else str(v)
            # The engine now emits composite/mc/poisson as NULL when a fixture
            # has too little history to estimate a draw probability at all.
            # pandas parses that blank CSV cell as NaN; keep it distinguishable
            # from a genuine 0.0 so "no data" is never scored as "0% confident".
            rec["no_data"] = False
            for col in ("composite_draw_score", "mc_draw_prob", "poisson_draw_prob"):
                if col in rec and pd.isna(rec.get(col)):
                    rec[col] = None
                    rec["no_data"] = True
            rows.append(rec)

    d = pd.DataFrame(rows)
    for c in NUM_COLS:
        if c in d.columns:
            d[c] = pd.to_numeric(d[c].astype(str).str.replace("%", "", regex=False),
                                 errors="coerce")
    return d, unresolved



def main():
    d, unresolved = load()
    if d.empty:
        print("No settled DRAW data.")
        return 1

    base = d["drew"].mean() * 100
    print("=" * 96)
    print(" DRAW ENGINE BACKTEST  |  target = 'match ended level at FT'")
    print(f" {len(d)} resolved rows / {d['date'].nunique()} dates"
          f" | base rate {base:.1f}%")
    print(f" {unresolved} artifact rows dropped (no EXACT fixture_id in archive)")
    print("=" * 96)

    # ---- 1. Does any signal rank draws at all? -----------------------------
    print("\n### 1. SIGNAL RANKING POWER   (AUC 0.500 = carries NO information)")
    print(f"  {'signal':<28} {'n':>6} {'AUC':>8} {'corr':>9} {'verdict'}")
    print("  " + "-" * 66)
    sig = [("composite_draw_score", "composite_draw_score (THE ranker)"),
           ("mc_draw_prob", "mc_draw_prob"),
           ("poisson_draw_prob", "poisson_draw_prob"),
           ("dmi", "dmi (draw magnet index)"),
           ("parity", "parity"),
           ("value_edge", "value_edge"),
           ("draw_odds", "draw_odds (inverted)")]
    for col, lab in sig:
        s = d[col].notna()
        if s.sum() < 30:
            continue
        x = d.loc[s]
        a, n = auc(x[col], x["drew"])
        c = x[col].corr(x["drew"])
        if col == "draw_odds":          # a rising price means a LESS likely draw
            a = 1 - a
            c = -c
        if a != a:
            v = "n/a"
        elif a >= 0.56:
            v = "INFORMATIVE"
        elif a >= 0.53:
            v = "weak"
        elif a >= 0.50:
            v = "noise"
        else:
            v = "INVERTED"
        print(f"  {lab:<28} {n:>6} {a:>8.4f} {c:>+9.4f} {v}")

    # ---- 2. Do the shipped tiers mean anything? ---------------------------
    print("\n### 2. TIER PRECISION   (the 'Perfect Draw List' claim)")
    print(f"  {'tier':<26} {'n':>5} {'draws':>7} {'rate':>8} {'95% CI':>16} {'vs base'}")
    print("  " + "-" * 74)
    for t, g in d.groupby("tier"):
        k, n, r, lo, hi = rate(g)
        if n == 0:
            continue
        clears = "clears base" if lo > base else "** OVERLAPS BASE **"
        print(f"  {t[:26]:<26} {n:>5} {k:>7} {r:>7.1f}% [{lo:>5.1f},{hi:>5.1f}]  {clears}")

    s1 = int((d["section"] == "Section 1").sum())
    print(f"\n  Section 1 rows (poisson>=0.40 & total_draws>=5): {s1}")
    if s1 >= 5:
        k, n, r, lo, hi = rate(d[d["section"] == "Section 1"])
        print(f"    -> {k}/{n} = {r:.1f}%  CI[{lo:.1f},{hi:.1f}]")


    # ---- 3. Ranking power: would picking the top of the board have worked? --
    print("\n### 3. RANKING POWER   (top X% by composite_draw_score)")
    print(f"  {'top':>6} {'n':>5} {'draw rate':>11} {'95% CI':>16} {'vs base'}")
    print("  " + "-" * 56)
    dd = d.dropna(subset=["composite_draw_score"]).sort_values(
        "composite_draw_score", ascending=False)
    for pct in (5, 10, 20, 30, 50):
        n = max(5, int(len(dd) * pct / 100))
        if n > len(dd):
            continue
        k, nn, r, lo, hi = rate(dd.head(n))
        clears = "clears base" if lo > base else "** OVERLAPS BASE **"
        print(f"  {pct:>5}% {nn:>5} {r:>10.1f}% [{lo:>5.1f},{hi:>5.1f}]  {clears}")

    # ---- 4. The benchmark the engine must beat ----------------------------
    print("\n### 4. MARKET BENCHMARK   (short draw odds)")
    print(f"  {'bucket':<22} {'n':>5} {'rate':>8} {'95% CI':>16}")
    print("  " + "-" * 56)
    o = d.dropna(subset=["draw_odds"])
    o = o[o["draw_odds"] > 1.0]
    if len(o) >= 20:
        for lo_, hi_, lab in [(1.0, 3.20, "odds < 3.20"), (3.20, 3.60, "3.20-3.60"),
                              (3.60, 4.20, "3.60-4.20"), (4.20, 99, "odds > 4.20")]:
            g = o[(o["draw_odds"] >= lo_) & (o["draw_odds"] < hi_)]
            if len(g) < 5:
                continue
            k, n, r, cl, ch = rate(g)
            print(f"  {lab:<22} {n:>5} {r:>7.1f}% [{cl:>5.1f},{ch:>5.1f}]")

    # ---- 5. Calibration of the shipped confidence numbers -----------------
    for col, lab in [("composite_draw_score", "composite_draw_score"),
                     ("mc_draw_prob", "mc_draw_prob"),
                     ("poisson_draw_prob", "poisson_draw_prob")]:
        x = d.dropna(subset=[col])
        if len(x) < 40:
            continue
        print(f"\n### 5. CALIBRATION -- {lab}   (claimed vs actual)")
        try:
            t = x.groupby(pd.qcut(x[col], 4, duplicates="drop"),
                          observed=True).agg(n=("drew", "size"),
                                             claimed=(col, "mean"),
                                             actual=("drew", "mean"))
            t["error_pp"] = ((t["claimed"] - t["actual"]) * 100).round(1)
            print("  " + t.to_string().replace("\n", "\n  "))
        except Exception as e:
            print(f"  (binning failed: {e})")

    # ---- 6. Structural audit of the shipped values ------------------------
    print("\n### 6. STRUCTURAL AUDIT of shipped values")
    print(f"  rows with league_weight == 0     : "
          f"{int((d['league_weight'].fillna(0) == 0).sum())}/{len(d)}")
    print("    -> the 0.04 league_weight term is DEAD on those rows.")
    print(f"  rows with non-empty veto_reason  : "
          f"{int((d['veto_reason'].str.len() > 0).sum())}/{len(d)}")
    if d["fatigue_score"].notna().any():
        print(f"  fatigue_score max observed       : {d['fatigue_score'].max():.3f}"
              "   (the VETO needs >= 0.750)")
    cd = d.dropna(subset=["composite_draw_score"])
    print(f"  composite_draw_score range       : "
          f"{cd['composite_draw_score'].min():.3f} .. {cd['composite_draw_score'].max():.3f}")
    print("    shipped gates: TIER1_COMPOSITE=0.78, TIER2_COMPOSITE=0.60")
    print(f"  mc_draw_prob vs poisson_draw_prob: corr "
          f"{d['mc_draw_prob'].corr(d['poisson_draw_prob']):+.4f}")
    print("    (mc is a 5,000-run resimulation of the SAME two lambdas)")

    # ---- 7. Is the base rate itself drifting? ----------------------------
    print("\n### 7. BASE RATE BY DATE  (is ~25% even the right hurdle?)")
    for dt, r in d.groupby("date")["drew"].agg(["size", "mean"]).iterrows():
        if r["size"] >= 5:
            print(f"  {dt}  n={int(r['size']):>3}  {r['mean']*100:>5.1f}%")

    # ---- 8. DEGENERATE ROWS: missing data masquerading as confidence -------
    # lambda is floored at 0.05 on both sides when a team has no usable last-5
    # sample (draw_engine.py:787-788), so P(0-0) = e^-0.1 lands at a single
    # constant. Detect that constant exactly rather than guessing a cut.
    dp = d["poisson_draw_prob"].dropna()
    deg_const = dp[dp > 0.85]
    print("\n### 8. DEGENERATE / EMPTY-HISTORY ROWS  (missing data as confidence)")
    if len(deg_const):
        print(f"  rows carrying the constant {deg_const.unique()[0]:.4f} : "
              f"{len(deg_const)}/{len(d)}")
        print(f"  that constant is e^-0.1 = 0.9048 -> both lambdas hit the 0.05 floor")
        print(f"  actual draw rate of those rows : "
              f"{d.loc[deg_const.index,'drew'].mean()*100:.1f}%  vs base {base:.1f}%")
        k, n, r_, lo_, hi_ = rate(d.loc[deg_const.index])
        print(f"    -> {k}/{n} = {r_:.1f}%  CI[{lo_:.1f},{hi_:.1f}]  "
              "(the number is an artifact, not a forecast)")
        pf = d[d["tier"] == "Perfect Draw List"]
        if len(pf):
            inf = int((pf["poisson_draw_prob"] > 0.85).sum())
            print(f"  of the {len(pf)} 'Perfect Draw List' rows, {inf} are this artifact "
                  f"({inf/len(pf)*100:.0f}%)")
        keep = d[d["poisson_draw_prob"] <= 0.85]
        print(f"\n  RE-SCORED WITHOUT THEM (n={len(keep)}, base "
              f"{keep['drew'].mean()*100:.1f}%):")
        for c in ("composite_draw_score", "dmi", "parity", "mc_draw_prob",
                  "poisson_draw_prob", "value_edge"):
            if keep[c].notna().sum() < 30:
                continue
            a, _ = auc(keep[c], keep["drew"])
            print(f"    {c:<24} AUC {a:.4f}")

    d.to_csv("/tmp/draw_backtest_rows.csv", index=False)
    print("\n  row detail -> /tmp/draw_backtest_rows.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())

