#!/usr/bin/env python
# ==============================================================================
# ALIENEDGE — GG / OVER 1.5 PRECISION BACKTEST HARNESS
# ==============================================================================
# PURPOSE
#   Replays every dated engine artifact against settled results and reports the
#   numbers that decide whether a scoring change is an improvement:
#       - per-signal AUC (0.50 = the signal carries no information)
#       - per-tier hit rate vs. the do-nothing base rate
#       - out-of-sample AUC via GroupKFold grouped BY DATE (no future leakage)
#
#   Exits non-zero when a guarded metric regresses, so a change to
#   Engine/gg_precision_engine.py can never ship unmeasured.
#
# WHY IT EXISTS
#   The engine's Tier-1 label fired on 62% of all fixtures while hitting only
#   +2.4pp over base rate. That is invisible without a replay harness, because
#   a "LOCK" that locks 62% of the time still looks like a lock in a log file.
#
# USAGE
#   ./venv/bin/python tools/gg_o15_backtest.py            # full report
#   ./venv/bin/python tools/gg_o15_backtest.py --quiet    # summary + exit code
#   ./venv/bin/python tools/gg_o15_backtest.py --no-gate  # report, never fail
#
# READ-ONLY: opens output/ for reading only. Writes nothing. Deletes nothing.
# ==============================================================================
import argparse
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "output")
PICK_PATTERNS = {
    "o15": "ALIENEDGE_O15_PICKS_*.csv",
    "gg": "ALIENEDGE_GG_PICKS_*.csv",
}
ARCHIVE_PATTERN = os.path.join(OUT, "archive_*.json")

# ------------------------------------------------------------------------------
# BASELINE — frozen 2026-09-30 from 1,461 settled matches, 2026-09-09..09-29.
#
# Tier-1 is measured by the ENGINE'S OWN TIER LABEL, not a raw score cut.
# get_gg_tier()/get_o15_tier() are compound gates (score floor AND a
# signals-fired minimum), so "score >= 68" is a different set of fixtures.
# Every downstream consumer keys off the label, so the harness does too.
#
#   O1.5  base 78.2% | T1 80.6% (n=912) | top decile 83.9% | OOS AUC 0.5738
#   GG    base 55.0% | T1 60.5% (n=875) | top decile 66.3%
#
# A change that lowers a guarded metric must be reverted, not re-baselined.
# Re-baselining is legitimate only after the sample roughly doubles — at 20
# days these numbers move several points on ordinary sampling noise.
# ------------------------------------------------------------------------------
BASELINE = {
    "o15": {
        "rows": 1461,
        "base_rate": 0.7823,
        "o15_tier1_hit": 0.8059,
        "oos_auc": 0.5738,
    },
    "gg": {
        "rows": 1461,
        "base_rate": 0.5503,
        "gg_tier1_hit": 0.6046,
        "oos_auc": None,          # engine score is not a fitted model
    },
}
# Guarded metrics: (market, key, how far below baseline the metric may fall
# before a change is blocked). Default mode is a FLOOR — it stops a change from
# making things worse without demanding that every run be an improvement.
# --assert-gain inverts each entry into a required improvement instead.
GUARDS = [
    ("o15", "o15_tier1_hit", 0.01),
    ("o15", "oos_auc", 0.005),
    ("gg", "gg_tier1_hit", 0.01),
]
ASSERT_GAIN = [False]  # single-slot flag toggled by --assert-gain
TOL = 0.005  # tolerance band used when comparing two like measurements
# ==============================================================================
# LOADING
# ==============================================================================
def load_results():
    """fixture_id -> (home_ft, away_ft) for every settled fixture on disk."""
    res = {}
    for p in glob.glob(ARCHIVE_PATTERN):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        for f in d.get("fixtures", []) or []:
            if not f.get("is_finished"):
                continue
            if f.get("h_ft") is None or f.get("a_ft") is None:
                continue
            res[str(f.get("fixture_id"))] = (int(f["h_ft"]), int(f["a_ft"]))
    return res


def load_board(kind, results):
    """Load one market's dated picks, joined to settled results."""
    paths = sorted(glob.glob(os.path.join(OUT, PICK_PATTERNS[kind])))
    if not paths:
        return None
    frames = []
    score_col = "gg_score" if kind == "gg" else "o15_score"
    for p in paths:
        try:
            df = pd.read_csv(p)
        except Exception:
            continue
        if score_col not in df.columns:
            continue
        df["_src"] = os.path.basename(p)
        frames.append(df)
    if not frames:
        return None
    b = pd.concat(frames, ignore_index=True)
    b["fid"] = b["fixture_id"].astype(str)
    b = b[b.fid.isin(results)].copy()
    pair = b.fid.map(results)
    b["h_ft"] = [t[0] for t in pair]
    b["a_ft"] = [t[1] for t in pair]
    b["actual_goals"] = b.h_ft + b.a_ft
    if kind == "o15":
        b["hit"] = (b.actual_goals >= 2).astype(int)          # Over 1.5
    else:
        b["hit"] = ((b.h_ft > 0) & (b.a_ft > 0)).astype(int)  # BTTS / GG
    return b.reset_index(drop=True)


# ==============================================================================
# METRICS
# ==============================================================================
def auc(score, y):
    """Rank-based AUC. nan when undefined (too few rows / no spread)."""
    s = pd.to_numeric(pd.Series(np.asarray(score, dtype=float)), errors="coerce")
    y = np.asarray(y)
    m = s.notna().values
    if m.sum() < 50 or s[m].nunique() < 2:
        return np.nan
    s, y = s[m].values, y[m]
    r = pd.Series(s).rank().values
    n1 = int(y.sum())
    n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return np.nan
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2.0) / (n0 * n1))


def _verdict(a):
    if a < 0.5 - 0.02:
        return "INVERTED"
    if abs(a - 0.5) < 0.02:
        return "DEAD"
    if abs(a - 0.5) >= 0.06:
        return "STRONG"
    return "weak"


def signal_auc_table(board, kind):
    common = ["combined_lambda", "h2h_btts_rate", "combined_venue_goals_avg",
              "venue_btts_home", "venue_btts_away", "mc_btts_prob",
              "home_gk_cpg", "away_gk_cpg", "fatigue_home", "fatigue_away",
              "league_weight", "draw_odds"]
    head = ["gg_score", "sig1_mc_btts", "sig2_venue_btts", "sig3_gk_vuln",
            "sig4_h2h_btts", "sig5_directional", "venue_btts_combined",
            "gg_odds"] if kind == "gg" else \
           ["o15_score", "sig1_combined_lambda", "sig2_mc_over15",
            "sig3_venue_goals_avg", "sig4_league_weight",
            "sig5_fatigue_penalty", "mc_over15_prob"]
    y = board.hit.values
    rows = []
    for c in head + common:
        if c not in board.columns or c in [r[0] for r in rows]:
            continue
        a = auc(board[c], y)
        if np.isnan(a):
            continue
        rows.append((c, a, _verdict(a)))
    rows.sort(key=lambda r: -abs(r[1] - 0.5))
    return rows


def tier_table(board, col):
    y = board.hit.values
    out = []
    for t in board[col].dropna().unique():
        m = (board[col] == t).values
        if m.sum() == 0:
            continue
        out.append((t, int(m.sum()), 100.0 * m.mean(), 100.0 * float(y[m].mean())))
    out.sort(key=lambda r: -r[1])
    return out


def threshold_curve(board, col, cuts=(35, 50, 68, 75, 85, 95)):
    y = board.hit.values
    out = []
    for t in cuts:
        m = (board[col] >= t).values
        if m.sum() == 0:
            continue
        out.append((t, int(m.sum()), 100.0 * m.mean(), 100.0 * float(y[m].mean())))
    return out


def top_decile(board, col):
    """Hit rate of the highest-scoring decile — the real ceiling of the score."""
    y = board.hit.values
    m = (board[col] >= board[col].quantile(0.90)).values
    return int(m.sum()), 100.0 * float(y[m].mean())


def oos_auc(board, kind):
    """Out-of-sample AUC from a logistic fit, grouped BY DATE.

    Honest because no fold contains a date the model was fitted on. The fitted
    model is compared against the engine's own raw signal so both sides of the
    comparison are out-of-sample.
    """
    feats = (["combined_lambda", "h2h_btts_rate", "combined_venue_goals_avg",
              "home_gk_cpg", "away_gk_cpg", "fatigue_home", "fatigue_away",
              "league_weight", "draw_odds", "venue_btts_home"]
             if kind == "o15" else
             ["combined_lambda", "h2h_btts_rate", "venue_btts_combined",
              "venue_btts_home", "venue_btts_away", "home_gk_cpg",
              "away_gk_cpg", "fatigue_home", "fatigue_away", "draw_odds"])
    feats = [c for c in feats if c in board.columns]
    if len(feats) < 3 or board["date"].nunique() < 5:
        return None, None
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import GroupKFold
    except Exception:
        return None, None
    X = board[feats].apply(pd.to_numeric, errors="coerce")
    for c in feats:
        med = X[c].median()
        X[c] = X[c].fillna(0.0 if not np.isfinite(med) else med)
    y = board.hit.values
    groups = board["date"].values
    model_auc, base_auc = [], []
    for tr, te in GroupKFold(n_splits=5).split(X, y, groups):
        if len(np.unique(y[te])) < 2:
            continue
        lr = LogisticRegression(max_iter=3000, C=0.3).fit(X.iloc[tr], y[tr])
        model_auc.append(auc(lr.predict_proba(X.iloc[te])[:, 1], y[te]))
        b = auc(X.iloc[te]["combined_lambda"], y[te])
        if not np.isnan(b):
            base_auc.append(b)
    if not model_auc:
        return None, None
    return float(np.mean(model_auc)), (float(np.mean(base_auc)) if base_auc else None)


# ==============================================================================
# REPORTING
# ==============================================================================
def hr(t=""):
    print("=" * 78)
    if t:
        print(t)


def report_o15(b, quiet):
    y = b.hit.values
    base = float(y.mean())
    m1 = tier_mask(b, "o15", "TIER 1")
    t1 = float(y[m1].mean()) if m1.sum() else float("nan")
    m_oos, _ = oos_auc(b, "o15")
    if quiet:
        print("O1.5 rows=%d base=%.1f%% T1=%.1f%% (n=%d)" % (
            len(b), 100 * base, 100 * t1, int(m1.sum())))
        return {"base_rate": base, "o15_tier1_hit": t1, "oos_auc": m_oos}
    hr("OVER 1.5  —  target: total goals >= 2")
    print("rows %d | dates %s..%s (%d days)" % (
        len(b), b.date.min(), b.date.max(), b.date.nunique()))
    print("BASE RATE (do nothing) : %.1f%%" % (100 * base))
    print()
    print("TIER BREAKDOWN")
    for t, n, cov, hit in tier_table(b, "o15_tier"):
        print("  %-28s n=%4d (%4.1f%%)  hit=%5.1f%%" % (t, n, cov, hit))
    print()
    print("THRESHOLD CURVE")
    for t, n, cov, hit in threshold_curve(b, "o15_score"):
        print("  score>=%3d  n=%4d (%4.1f%% of all)  hit=%5.1f%%" % (t, n, cov, hit))
    n, hit = top_decile(b, "o15_score")
    print("  top decile   n=%4d            hit=%5.1f%%" % (n, hit))
    print()
    print("SIGNAL DISCRIMINATION (AUC)")
    for c, a, v in signal_auc_table(b, "o15"):
        print("  %-24s AUC=%.4f  %-8s %s" % (
            c, a, v, "#" * int(abs(a - 0.5) * 200)))
    m, basea = oos_auc(b, "o15")
    if m is not None and not quiet:
        print()
        print("OUT-OF-SAMPLE (GroupKFold by date)")
        print("  engine combined_lambda : %.4f" % (basea if basea else float("nan")))
        print("  fitted reference model : %.4f" % m)
    return {"base_rate": base, "o15_tier1_hit": t1, "oos_auc": m}


def report_gg(b, quiet):
    y = b.hit.values
    base = float(y.mean())
    m1 = tier_mask(b, "gg", "TIER 1")
    t1 = float(y[m1].mean()) if m1.sum() else float("nan")
    if quiet:
        print("GG   rows=%d base=%.1f%% T1=%.1f%% (n=%d)" % (
            len(b), 100 * base, 100 * t1, int(m1.sum())))
        return {"base_rate": base, "gg_tier1_hit": t1}
    hr("GG / BTTS  —  target: both teams score")
    print("rows %d | dates %s..%s (%d days)" % (
        len(b), b.date.min(), b.date.max(), b.date.nunique()))
    print("BASE RATE (do nothing) : %.1f%%" % (100 * base))
    print()
    print("TIER BREAKDOWN")
    for t, n, cov, hit in tier_table(b, "gg_tier"):
        print("  %-30s n=%4d (%4.1f%%)  hit=%5.1f%%" % (t, n, cov, hit))
    print()
    print("THRESHOLD CURVE")
    for t, n, cov, hit in threshold_curve(b, "gg_score"):
        print("  score>=%3d  n=%4d (%4.1f%% of all)  hit=%5.1f%%" % (t, n, cov, hit))
    n, hit = top_decile(b, "gg_score")
    print("  top decile   n=%4d            hit=%5.1f%%" % (n, hit))
    print()
    print("SIGNAL DISCRIMINATION (AUC)")
    for c, a, v in signal_auc_table(b, "gg"):
        print("  %-24s AUC=%.4f  %-8s %s" % (
            c, a, v, "#" * int(abs(a - 0.5) * 200)))
    if "home_gk_note" in b.columns:
        note = b.home_gk_note.fillna("")
        groups = {
            "REAL": note.str.contains("Solid|Liability|CRITICAL")
                    & ~note.str.contains("Exp #1"),
            "[Exp #1]": note.str.contains("Exp #1"),
            "PROXY": note.str.contains("Unlisted|No squad"),
        }
        if groups["PROXY"].sum() > 0:
            print()
            print("GOALKEEPER EVIDENCE QUALITY")
            for lab, mask in groups.items():
                if mask.sum() > 0:
                    print("  %-10s n=%4d  hit=%5.1f%%" % (
                        lab, int(mask.sum()), 100.0 * float(y[mask.values].mean())))
    return {"base_rate": base, "gg_tier1_hit": t1, "oos_auc": None}


def tier_mask(board, kind, tier_re):
    """Tier-1 membership by the ENGINE'S OWN LABEL.

    Deliberately uses the tier label rather than a raw score cut: TIER 1 in
    gg_precision_engine.get_gg_tier() is a compound gate (score floor AND a
    signals-fired minimum), so "score >= 68" is NOT the same set of fixtures.
    Every downstream consumer (over15_stage3, gg_forensics_audit,
    gg_precision_filter) keys off this label, so the harness must too.
    """
    if kind == "o15":
        return board.o15_tier.astype(str).str.contains(tier_re, na=False,
                                                        case=False).values
    return board.gg_tier.astype(str).str.contains(tier_re, na=False,
                                                  case=False).values


def check_guards(metrics):
    print()
    hr("REGRESSION GATE")
    failures = []
    for kind, key, margin in GUARDS:
        got = metrics.get(kind, {}).get(key)
        ref = BASELINE[kind].get(key)
        if got is None or ref is None:
            print("  %-4s %-16s SKIP (not measurable)" % (kind, key))
            continue
        delta = got - ref
        # A guard is a FLOOR, not a target. margin is how far BELOW baseline the
        # metric may fall before the change is blocked. Requiring the unmodified
        # engine to beat its own baseline would fail every clean checkout, which
        # is how a gate gets quietly disabled.
        #   --assert-gain flips this to a target for a deliberate improvement.
        if ASSERT_GAIN[0]:
            need = margin
        else:
            need = -abs(margin)
        # EPS absorbs float-representation noise of an identical measurement.
        eps = 1e-9
        ok = delta >= need - eps
        if not ok:
            failures.append((kind, key, ref, got))
        print("  %-4s %-16s baseline=%.4f now=%.4f (%+.4f) floor=%+.4f  %s" % (
            kind, key, ref, got, delta, need, "PASS" if ok else "FAIL"))
    print()
    if failures:
        print("  GATE FAILED — %d guarded metric(s) regressed:" % len(failures))
        for kind, key, ref, got in failures:
            print("    %s %s: %.4f -> %.4f" % (kind, key, ref, got))
        print("  Revert the change, or justify it against settled data first.")
    else:
        print("  GATE PASSED — no guarded metric regressed.")
    return failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true",
                    help="summary lines only")
    ap.add_argument("--no-gate", action="store_true",
                    help="report but always exit 0")
    ap.add_argument("--assert-gain", action="store_true",
                    help="require each guarded metric to IMPROVE on baseline "
                         "(default is only to block regressions)")
    args = ap.parse_args()
    ASSERT_GAIN[0] = args.assert_gain

    results = load_results()
    if not results:
        print("No settled results found matching %s" % ARCHIVE_PATTERN)
        print("Run the archiver first, or there is nothing to measure against.")
        return 2
    if not args.quiet:
        hr("ALIENEDGE GG / OVER 1.5 BACKTEST")
        print("settled fixtures on disk : %d" % len(results))
        print("output dir               : %s" % OUT)

    metrics = {}
    for kind, fn in (("o15", report_o15), ("gg", report_gg)):
        b = load_board(kind, results)
        if b is None:
            print("no %s artifacts found" % kind)
            continue
        metrics[kind] = fn(b, args.quiet)
        metrics[kind]["rows"] = len(b)

    if not metrics:
        print("no engine artifacts to measure")
        return 2

    if args.no_gate:
        print("\n(--no-gate) exiting 0 regardless of guarded metrics")
        return 0
    return 1 if check_guards(metrics) else 0


if __name__ == "__main__":
    sys.exit(main())
