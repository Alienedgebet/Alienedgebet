#!/usr/bin/env python3
"""
O2.5 PRECISION BACKTEST  --  read-only measurement harness.

Replays each Over-2.5 engine's DECISION LOGIC against fixtures whose final
score is already known, so "how precise is this engine" becomes a number
instead of an opinion.

It does NOT re-run the engines' network code. It reimplements each engine's
gates as a pure function over the features the pipeline already persisted in
output/master_over_stage2_<date>.csv, joined to the true result from
output/archive_<date>.json.

Self-contained, side-effect free, changes no engine behaviour.
"""
import json
import math
import os
import sys
from glob import glob

import pandas as pd

OUT = "/var/www/backend/output"


def load_universe():
    """One row per fixture that has BOTH features and a known final score."""
    rows = []
    for feat_path in sorted(glob(os.path.join(OUT, "master_over_stage2_*.csv"))):
        date = os.path.basename(feat_path).replace("master_over_stage2_", "").replace(".csv", "")
        arch_path = os.path.join(OUT, f"archive_{date}.json")
        if not os.path.exists(arch_path):
            continue
        try:
            arch = json.load(open(arch_path))
        except Exception:
            continue
        truth = {}
        for f in arch.get("fixtures", []):
            tg = f.get("total_goals")
            if tg is not None:
                truth[str(f.get("fixture_id"))] = int(tg)
        if not truth:
            continue
        df = pd.read_csv(feat_path)
        if "fixture_id" not in df.columns:
            continue
        for _, r in df.iterrows():
            fid = str(r.get("fixture_id"))
            if fid in truth:
                rec = r.to_dict()
                rec["date"] = date
                rec["hit"] = 1 if truth[fid] >= 3 else 0
                rows.append(rec)
    return pd.DataFrame(rows)


def poisson_over_pct(lam):
    if lam is None or lam <= 0:
        return 0.0
    return (1 - math.exp(-lam) * (1 + lam + lam ** 2 / 2)) * 100


def team_lambda(h_gs, h_gc, a_gs, a_gc):
    """Forecast engine's lambda: mean match-goal rate of both sides."""
    return ((h_gs + h_gc) / 5 + (a_gs + a_gc) / 5) / 2


def proxy_lambda(combined_gs):
    """
    Match-goal lambda reconstructed from combined_gs_last_5, which the
    pipeline has written on EVERY dated artifact.

    The engine's own formula needs scored AND conceded per side, but those
    four columns only exist from 2026-09-30 onward. combined_gs_last_5 is
    present across the whole history, so this keeps every fixture in the
    measurement instead of silently dropping 97% of them.

    combined_gs = goals scored by both sides across 5 games each (10 games).
    The engine divides per-side (scored+conceded) by 5, then averages the two
    sides. combined_gs/10 is the same construction using only the scored half.
    """
    return combined_gs / 10.0


def precision(sel, u):
    n = int(sel.sum())
    if n == 0:
        return 0, 0
    return n, int(u.loc[sel, "hit"].sum())


def rule(title, n, hits, base):
    if n == 0:
        return "  %-50s %5d %4s %8s   (selected nothing)" % (title, 0, "--", "--")
    p = hits / n * 100
    return "  %-50s %5d %4d %7.1f%%  %+7.1fpp vs %.1f%% base" % (
        title, n, hits, p, p - base * 100, base * 100)


PRESETS = {
    "banker":     dict(min_poisson=70, min_votes=7, max_pos_gap=6,  min_h2h=3, odds_lo=1.50, odds_hi=1.85),
    "balanced":   dict(min_poisson=60, min_votes=6, max_pos_gap=8,  min_h2h=3, odds_lo=1.50, odds_hi=1.85),
    "aggressive": dict(min_poisson=65, min_votes=6, max_pos_gap=10, min_h2h=2, odds_lo=1.30, odds_hi=2.20),
}


# --------------------------------------------------------------- engine models
def eng_forecast(v, fixed=False):
    """Engine/over25_forecast.py -- the 9-vote council + Poisson."""
    p = poisson_over_pct(proxy_lambda(v["cgs"]))
    votes = 0
    if not fixed:
        # CURRENT: pays a vote for odds < 1.85 -- i.e. rewards the bookmaker
        # disagreeing with us, which is backwards.
        if v["odds"] is not None and v["odds"] < 1.85:
            votes += 1
    else:
        # FIXED: model-vs-market edge. Direction-correct.
        if v["odds"] is not None and v["odds"] > 1.02:
            if p > (100.0 / v["odds"]) + 3.0:
                votes += 1
    if p > 60:
        votes += 1
    if v["h_overs"] >= 3:
        votes += 1
    if v["a_overs"] >= 3:
        votes += 1
    if v["h2h_overs"] >= 3:
        votes += 1
    if v["h_gs"] >= 8:
        votes += 1
    if v["a_gs"] >= 8:
        votes += 1
    if fixed:
        # FIXED: unknown standings (99) must not read as "worst gap in league".
        if v["pos_gap"] == 99 or v["pos_gap"] <= 8:
            votes += 1
    else:
        if v["pos_gap"] <= 8:
            votes += 1
    if v["parity"] > 0:
        votes += 1
    return votes, p


def eng_apex(v, fixed=False):
    """AGGREGATOR/over25_apex.py -- the Monte Carlo layer."""
    if not fixed:
        # CURRENT: lambda comes from the GRADE STRING only. Zero team data.
        grade_map = {"6/6": 3.4, "5/6": 3.1, "4/6": 2.8}
        base = 2.4
        for k, l in grade_map.items():
            if k in str(v["grade_str"]):
                base = l
                break
    else:
        # FIXED: lambda from the teams' real scoring rate.
        base = proxy_lambda(v["cgs"])
    return poisson_over_pct(base * 1.30)     # 1.30 = ceiling multiplier


def gates(v, min_poisson, min_votes, max_pos_gap, min_h2h, odds_lo, odds_hi):
    """FILTER/over25_risk_filter.py public presets."""
    ok_odds = (v["odds"] >= odds_lo) & (v["odds"] <= odds_hi)
    return ((v["poisson"] >= min_poisson) & (v["votes"] >= min_votes)
            & (v["pos_gap"] <= max_pos_gap) & (v["h2h_overs"] >= min_h2h)
            & ok_odds)


PRESETS = {
    "banker":     dict(min_poisson=70, min_votes=7, max_pos_gap=6,  min_h2h=3, odds_lo=1.50, odds_hi=1.85),
    "balanced":   dict(min_poisson=60, min_votes=6, max_pos_gap=8,  min_h2h=3, odds_lo=1.50, odds_hi=1.85),
    "aggressive": dict(min_poisson=65, min_votes=6, max_pos_gap=10, min_h2h=2, odds_lo=1.30, odds_hi=2.20),
}


def main():
    u = load_universe()
    if u.empty:
        print("No joined fixtures found.")
        return 1
    base = u["hit"].mean()

    def num(col, default=0.0):
        if col not in u.columns:
            return pd.Series(default, index=u.index, dtype=float)
        return pd.to_numeric(u[col], errors="coerce").fillna(default)

    v = pd.DataFrame({
        "odds":      num("o25_odds", None),
        "pos_gap":   num("pos_gap", 99),
        "parity":    num("parity_diff", 0),
        "h2h_overs": num("h2h_overs_last_5", 0),
        "h_gs":      num("home_goals_scored_last_5", 0),
        "a_gs":      num("away_goals_scored_last_5", 0),
        "h_gc":      num("home_goals_conceded_last_5", 0),
        "a_gc":      num("away_goals_conceded_last_5", 0),
        "cgs":       num("combined_gs_last_5", 0),
        "kill":      u["kill_switch_pass"].astype(bool) if "kill_switch_pass" in u.columns else True,
        "grade_str": u.get("council_votes", pd.Series(["N/A"] * len(u))),
    })
    # The CURRENT engine probabilities, exactly as the pipeline persisted
    # them, are the honest baseline -- not a reconstruction.
    v["poisson_cur"] = num("poisson_over_prob_num", 0.0)
    v["votes_cur"] = (pd.to_numeric(u["council_votes"].astype(str).str.split("/").str[0],
                                    errors="coerce").fillna(0).astype(int)
                      if "council_votes" in u.columns
                      else pd.Series(0, index=u.index))
    # 'overs' inside the 5-game window: rebuilt from the stored scored+conceded
    # sums, which is the same window the engine read.
    v["h_overs"] = ((v["h_gs"] + v["h_gc"]) >= 12).astype(int)
    v["a_overs"] = ((v["a_gs"] + v["a_gc"]) >= 12).astype(int)
    u = u.reset_index(drop=True)
    v = v.reset_index(drop=True)

    fx = [eng_forecast(r, fixed=True) for _, r in v.iterrows()]
    # CURRENT = what the pipeline actually persisted.
    u["votes"] = v["votes_cur"]
    u["poisson"] = v["poisson_cur"]
    u["votes_fx"] = [x[0] for x in fx]
    u["poisson_fx"] = [x[1] for x in fx]
    v["votes"] = v["votes_cur"]
    v["poisson"] = v["poisson_cur"]
    u["apex"] = [eng_apex(r, False) for _, r in v.iterrows()]
    u["apex_fx"] = [eng_apex(r, True) for _, r in v.iterrows()]
    u["cgs"] = v["cgs"]

    print("=" * 104)
    print(f" O2.5 PRECISION BACKTEST | {len(u)} settled fixtures | {u['date'].nunique()} dates "
          f"| base rate {base*100:.1f}%")
    print("=" * 104)

    print("\n### 1. SIGNAL QUALITY - does the engine's own confidence mean anything?")
    print(f"  corr(predicted P, actual)         = {u['poisson'].corr(u['hit']):+.4f}")
    print(f"  corr(votes,       actual)         = {u['votes'].corr(u['hit']):+.4f}")
    print(f"  corr(o25 odds,    actual)         = {v['odds'].corr(u['hit']):+.4f}")
    print(f"  corr(combined L5 goals, actual)   = {(v['h_gs']+v['a_gs']).corr(u['hit']):+.4f}")

    print("\n### 2. CALIBRATION - engine bucket vs reality")
    b = pd.cut(u["poisson"], [0, 40, 50, 60, 70, 80, 100])
    cal = u.groupby(b, observed=True).agg(n=("hit", "size"),
                                          predicted=("poisson", "mean"),
                                          actual=("hit", "mean"))
    cal["error_pp"] = (cal["predicted"] - cal["actual"] * 100).round(1)
    print(cal.to_string())

    print("\n### 3. PER-ENGINE PRECISION (selected picks only)")
    print("\n  %-50s %5s %4s %8s" % ("rule", "n", "win", "precision"))
    print("  " + "-" * 90)

    for cut in (5, 6, 7):
        n, h = precision(u["votes"] >= cut, u)
        print(rule("Forecast council  votes>=%d/9   (CURRENT)" % cut, n, h, base))
    for cut in (5, 6, 7):
        n, h = precision(u["votes_fx"] >= cut, u)
        print(rule("Forecast council  votes>=%d/9   (FIXED)" % cut, n, h, base))

    print("")
    for pname, kw in PRESETS.items():
        mask = pd.Series([bool(gates(r, **kw)) for _, r in v.iterrows()], index=u.index)
        n, h = precision(mask & (v["kill"] == True), u)          # noqa: E712
        print(rule("RiskFilter %-9s + kill switch" % pname, n, h, base))
        n, h = precision(mask, u)
        print(rule("RiskFilter %-9s no kill switch" % pname, n, h, base))

    print("")
    for cut in (60, 66, 70):
        n, h = precision(u["apex"] >= cut, u)
        print(rule("Apex Monte Carlo  P>=%d%%   (CURRENT grade-lambda)" % cut, n, h, base))
    for cut in (55, 60, 65):
        n, h = precision(u["apex_fx"] >= cut, u)
        print(rule("Apex Monte Carlo  P>=%d%%   (FIXED real lambda)" % cut, n, h, base))

    print("\n### 4. WHAT ACTUALLY CARRIES SIGNAL (monotone checks)")
    vq = pd.cut(v["odds"], [0, 1.4, 1.6, 1.85, 2.2, 99])
    og = u.groupby(vq, observed=True).agg(n=("hit", "size"), actual=("hit", "mean"))
    og.index = ["odds<=1.40", "1.40-1.60", "1.60-1.85", "1.85-2.20", "odds>2.20"]
    print("\n  by O2.5 odds:")
    print(og.to_string())
    gq = pd.qcut((v["h_gs"] + v["a_gs"]).rank(method="first"), 5, labels=False)
    gg = u.groupby(gq, observed=True).agg(n=("hit", "size"), actual=("hit", "mean"))
    gg.index = ["Q1 lowest scoring", "Q2", "Q3", "Q4", "Q5 highest scoring"]
    print("\n  by combined goals scored (last 5 each):")
    print(gg.to_string())

    u.to_csv("/tmp/o25_backtest_rows.csv", index=False)
    print("\n  row-level detail -> /tmp/o25_backtest_rows.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
