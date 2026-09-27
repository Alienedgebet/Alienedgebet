"""
signal_backtest.py — is any field a RELIABLE front-of-list ranking signal?

WHAT THIS ANSWERS
------------------
"Can Corners / SOT be ordered so the rows at the top pass verification more
often?" Verification is a fixed threshold (corners: total >= 7, sot: total >
6) that does NOT read the pick, so the only thing an ordering can do is put
matches with a HIGHER EXPECTED TOTAL first. That is the hypothesis tested here.

HOW IT STAYS HONEST
-------------------
  * Verdicts come from settlement_service.grade_row (see signal_ledger) — the
    same grader the UI uses. Nothing is re-implemented here.
  * Every signal is scored by AUC, so "barely above 0.5" is visible rather
    than hidden inside a flattering top-5 percentage.
  * LEAVE-ONE-DAY-OUT is the decisive test. A threshold tuned on the same days
    it is scored on will always look good; LODO ranks on all days but one and
    tests on the unseen day, which is the only honest estimate.
  * Any threshold SEARCH is corrected with Bonferroni. Sweeping k cut-points
    and reporting the best one is how a pure-noise field gets a "92% accuracy"
    badge; the correction makes that visible.
  * Single-day results are always broken out. The 3-day investigation's
    apparent "perfect" SOT combo was one afternoon going 13-for-13.

USAGE
-----
    python3 signal_backtest.py                # full report
    python3 signal_backtest.py --market sot   # one market
    python3 signal_backtest.py --top 10       # top-k depth
"""

import argparse
import glob
import itertools
import os
from math import comb

import signal_ledger as sl

ALPHA = 0.05


def available_dates():
    """Every date the archiver has written a well-formed archive for."""
    dates = []
    for path in glob.glob(os.path.join(sl.ARCHIVE_DIR, "archive_*.json")):
        name = os.path.basename(path)
        if "Ctrl" in name:
            continue
        date = name[len("archive_"):-len(".json")]
        if len(date) == 10 and date[4] == "-" and date[7] == "-":
            dates.append(date)
    return sorted(dates)


def collect(market, dates):
    """date -> entries, only for dates that actually produced graded rows."""
    by_date = {}
    for date in dates:
        entries, _ = sl.build_entries(market, date)
        if entries:
            by_date[date] = entries
    return by_date


def auc(pairs):
    """Probability a random winner scores above a random loser. 0.5 = none."""
    pos = [s for s, won in pairs if won and s is not None]
    neg = [s for s, won in pairs if not won and s is not None]
    if not pos or not neg:
        return None
    wins = sum(1 for p in pos for n in neg if p > n)
    ties = sum(1 for p in pos for n in neg if p == n)
    return (wins + 0.5 * ties) / (len(pos) * len(neg))


def fisher_2x2(a, b, c, d):
    """Two-tailed Fisher exact p for the [[a,b],[c,d]] win/loss table."""
    n = a + b + c + d
    if n == 0 or not (0 <= a + b <= n) or not (0 <= a + c <= n):
        return 1.0
    r1, c1 = a + b, a + c

    def prob(x):
        if x < 0 or x > r1 or (c1 - x) < 0 or (c1 - x) > (n - r1):
            return 0.0
        return comb(r1, x) * comb(n - r1, c1 - x) / comb(n, c1)

    observed = prob(a)
    lo = max(0, c1 - (n - r1))
    hi = min(r1, c1)
    return sum(prob(x) for x in range(lo, hi + 1) if prob(x) <= observed + 1e-12)


def report_market(market, by_date, signals, top):
    rows = [e for entries in by_date.values() for e in entries]
    won = sum(1 for e in rows if e["verdict"] == "WON")
    base = 100.0 * won / len(rows) if rows else 0.0

    print("=" * 78)
    print("MARKET: %s    n=%d graded rows over %d days"
          % (market.upper(), len(rows), len(by_date)))
    print("BASELINE (as served): %d won / %d = %.1f%%" % (won, len(rows), base))
    print("=" * 78)

    print("\n-- per-day baseline (is one day carrying the result?) --")
    for date in sorted(by_date):
        day = by_date[date]
        w = sum(1 for e in day if e["verdict"] == "WON")
        print("   %s  n=%3d  won=%3d  %5.1f%%" % (date, len(day), w, 100.0 * w / len(day)))

    print("\n-- per-signal discrimination --")
    print("   %-20s %7s %10s %9s" % ("signal", "AUC", "top-k", "lift"))
    for name in signals:
        a = auc([(e.get(name), e["verdict"] == "WON") for e in rows])
        usable = [e for e in rows if e.get(name) is not None]
        if a is None or len(usable) < top:
            continue
        ranked = sorted(usable, key=lambda e: e[name], reverse=True)
        hits, size = sum(1 for e in ranked[:top] if e["verdict"] == "WON"), top
        rate = 100.0 * hits / size
        print("   %-20s %7.3f %4d/%-4d %+8.1f"
              % (name, a, hits, size, rate - base))
    return rows, by_date, signals, base



def _top_vs_rest(entries, name, top):
    """Hit-rate of the top-k by `name` vs the remainder of the SAME list."""
    usable = [e for e in entries if e.get(name) is not None]
    if len(usable) < top:
        return None, None
    ranked = sorted(usable, key=lambda e: e[name], reverse=True)
    hits = sum(1 for e in ranked[:top] if e["verdict"] == "WON")
    rest = ranked[top:]
    rest_rate = (100.0 * sum(1 for e in rest if e["verdict"] == "WON") / len(rest)) if rest else None
    return 100.0 * hits / top, rest_rate


def lodo(by_date, signals, top):
    """Leave-one-day-out: rank on all days but one, then score the unseen day.

    This is the only test that answers the real question. Ranking and scoring
    on the same days (which is what a plain top-k does) rewards any field that
    happened to suit that particular sample.
    """
    print("\n-- LEAVE-ONE-DAY-OUT (the decisive test) --")
    summary = {}
    for name in signals:
        margins = []
        for held in sorted(by_date):
            if len(by_date[held]) < 5:
                continue
            train = [e for d, es in by_date.items() if d != held for e in es]
            _top_vs_rest(train, name, top)          # "tuned" on train
            test_hit, test_rest = _top_vs_rest(by_date[held], name, top)
            if test_hit is None or test_rest is None:
                continue
            margins.append(test_hit - test_rest)
        if margins:
            summary[name] = (sum(1 for m in margins if m > 0), len(margins),
                             sum(margins) / len(margins))
    if not summary:
        print("   (not enough per-day rows to run LODO)")
        return
    print("   %-20s %s" % ("signal", "unseen days it beat the rest"))
    for name, (good, total, mean) in sorted(summary.items(), key=lambda kv: -kv[1][0]):
        print("   %-20s %d/%d days   (mean margin %+.1f pp)"
              % (name, good, total, mean))



def sweep(rows, signals):
    """Threshold / combination search WITH a Bonferroni correction."""
    quantiles = {}
    for name in signals:
        values = sorted(e[name] for e in rows if e.get(name) is not None)
        if len(values) < 20:
            continue
        quantiles[name] = sorted({values[int(len(values) * q)] for q in (0.4, 0.5, 0.6)})
    if not quantiles:
        return
    names = sorted(quantiles)
    tests = []
    for name in names:
        for cut in quantiles[name]:
            tests.append(((name, ">=", cut), [(name, cut)]))
    for a, b in itertools.combinations(names, 2):
        for ca in quantiles[a]:
            for cb in quantiles[b]:
                tests.append(((a, ca, "+", b, cb), [(a, ca), (b, cb)]))

    results = []
    for label, clauses in tests:
        chosen, rest = [], []
        for e in rows:
            ok = all(e.get(n) is not None and e[n] >= c for n, c in clauses)
            (chosen if ok else rest).append(e)
        if len(chosen) < 15 or not rest:
            continue
        w = sum(1 for e in chosen if e["verdict"] == "WON")
        rate = 100.0 * w / len(chosen)
        rw = sum(1 for e in rest if e["verdict"] == "WON")
        rest_rate = 100.0 * rw / len(rest)
        p = fisher_2x2(w, len(chosen) - w, rw, len(rest) - rw)
        results.append((label, len(chosen), rate, rate - rest_rate, p))

    if not results:
        return
    results.sort(key=lambda r: -r[3])
    threshold = ALPHA / len(results)
    print("\n-- threshold / combination search (%d combinations) --" % len(results))
    print("   Bonferroni-corrected threshold: p < %.5f" % threshold)
    print("   %-42s %5s %8s %8s %9s" % ("combination", "n", "rate", "lift", "p"))
    for label, n, rate, lift, p in results[:10]:
        print("   %-42s %5d %7.1f%% %+7.1f %9.3f" % (str(label)[:42], n, rate, lift, p))
    survivors = [r for r in results if r[4] < threshold]
    if survivors:
        print("\n   SURVIVES CORRECTION: %d of %d" % (len(survivors), len(results)))
        for label, n, rate, lift, p in survivors:
            print("      %-38s n=%d  %.1f%%  lift %+.1f  p=%.5f"
                  % (str(label)[:38], n, rate, lift, p))
    else:
        unadj = sum(1 for r in results if r[4] < ALPHA)
        print("\n   NO combination survives the correction.")
        print("   Only %d of %d reached even p<%.2f before correction — the flat"
              % (unadj, len(results), ALPHA))
        print("   profile of noise, not a hidden edge.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", choices=sorted(sl.MARKETS), default=None)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--no-sweep", action="store_true")
    args = parser.parse_args()

    dates = available_dates()
    print("Signal backtest: %d archive dates on disk" % len(dates))
    for market in ([args.market] if args.market else sorted(sl.MARKETS)):
        by_date = collect(market, dates)
        if not by_date:
            print("\n%s: no graded rows yet." % market)
            continue
        probe = [e for entries in by_date.values() for e in entries]
        # A signal counts as numeric if it is a real number in AT LEAST ONE
        # row. Deriving the list from a single row would silently drop any
        # field that happened to be null in that row.
        signals = []
        for key in probe[0].keys():
            if key == "actual_total":
                continue
            if any(isinstance(e.get(key), (int, float)) for e in probe):
                signals.append(key)
        rows, by_date, signals, _ = report_market(market, by_date, signals, args.top)
        lodo(by_date, signals, args.top)
        if not args.no_sweep:
            sweep(rows, signals)
        print()

if __name__ == "__main__":
    main()
