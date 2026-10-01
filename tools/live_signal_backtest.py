#!/usr/bin/env python3
"""
Does anything the Live Scanner emits actually predict a result?

WHY THIS EXISTS
---------------
Nothing in LIVE_SCANNER has ever been backtested. The engines emit confident
verdicts (DANGER / BLESSING / ROTATION, signed net impacts, chemistry grades,
TO_SCORE picks) and the whole live chain assumes they carry information. That
assumption has never been measured.

A verdict that fires on 100% of fixtures carries zero information by
construction, so "the model says X" is not evidence for X. The only question
that matters is whether X beats the base rate.

WHAT THIS MEASURES
------------------
A walk-forward backtest over the fixtures already cached in
data/danger_history_cache.json. For every fixture, features are computed from
that team's EARLIER cached matches only - never from the match being scored -
and tested against that match's full-time total goals and both-teams-scored.

Reported per signal: n (evaluable), base rate, hit rate, lift in percentage
points, and whether the lift clears the 95% confidence half-width. The lift is
the only number that matters: no lift is a coin flip, negative lift is worse
than ignoring the signal entirely.

NO NEW API CALLS, NO NETWORK. Offline, deterministic, read-only.

    python3 tools/live_signal_backtest.py
"""
import json
import math
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "danger_history_cache.json")
# ── extraction ───────────────────────────────────────────────────────────────
def full_time_goals(fx):
    """{participant_id: goals} at full time, or None if not finished."""
    out = {}
    for s in fx.get("scores") or []:
        if (s.get("description") or "").upper() == "FULL_TIME" or s.get("type_id") == 2:
            g = (s.get("score") or {}).get("goals")
            if g is not None:
                out[s.get("participant_id")] = int(g)
    return out if len(out) == 2 else None


def side_features(prior):
    """
    Pre-match features for one side, from THAT TEAM'S EARLIER MATCHES ONLY.

    `prior` holds that team's already-scored finished totals, oldest first.
    Nothing here reads the match being tested, which is what keeps this free of
    lookahead.
    """
    if not prior:
        return None
    last3, last5 = prior[-3:], prior[-5:]
    return {"over3": sum(1 for g in last3 if g > OVER_BAR) / len(last3),
            "over5": sum(1 for g in last5 if g > OVER_BAR) / len(last5),
            "avg_goals": sum(prior) / len(prior),
            "n_prior": len(prior)}
OVER_BAR = 2.5          # "over" means strictly more than this
# ── the backtest ─────────────────────────────────────────────────────────────
def run():
    if not os.path.exists(CACHE):
        print("no history cache at " + CACHE)
        return 1
    with open(CACHE, "r", encoding="utf-8") as f:
        cache = json.load(f)

    # The cache is keyed per team, so a fixture appears once per side that
    # played it. De-duplicate first or every match counts twice.
    fixtures = {}
    for _tid, v in cache.items():
        for fx in (v.get("data") or []):
            fixtures.setdefault(str(fx.get("id")), fx)
    ordered = sorted(fixtures.values(),
                     key=lambda x: x.get("starting_at_timestamp") or 0)

    history = defaultdict(list)     # only ever holds EARLIER matches
    rows = []
    for fx in ordered:
        ft = full_time_goals(fx)
        if not ft:
            continue
        tids = list(ft.keys())
        feats = {t: side_features(history[t]) for t in tids}
        total = sum(ft.values())
        rows.append({"total": total,
                     "over": total > OVER_BAR,
                     "btts": all(v > 0 for v in ft.values()),
                     "feat": {t: f for t, f in feats.items() if f}})
        for t in tids:
            history[t].append(total)

    n = len(rows)
    if not n:
        print("no finished fixtures with a full-time score")
        return 1
    base_over = sum(1 for r in rows if r["over"]) / n
    base_btts = sum(1 for r in rows if r["btts"]) / n

    print("=" * 74)
    print("LIVE SCANNER SIGNAL BACKTEST - walk-forward, no lookahead")
    print("=" * 74)
    print("unique finished fixtures scored : %d" % n)
    print("with usable pre-match history   : %d"
          % sum(1 for r in rows if r["feat"]))
    print()
    print("BASE RATES - what guessing already gets you")
    print("  Over 2.5          %5.1f%%" % (base_over * 100))
    print("  Both teams score  %5.1f%%" % (base_btts * 100))
    print()

    out = []

    def report(name, fires, hits, base):
        rate = hits / fires if fires else None
        out.append((name, fires, rate,
                    None if rate is None else rate - base))

    def two(r):
        return len(r["feat"]) == 2

    def mx3(r):
        return max(f["over3"] for f in r["feat"].values())

    def mn3(r):
        return min(f["over3"] for f in r["feat"].values())

    def mxg(r):
        return max(f["avg_goals"] for f in r["feat"].values())

    def tally(pred, event, base, name):
        f = h = 0
        for r in rows:
            if not two(r) or not pred(r):
                continue
            f += 1
            if event(r):
                h += 1
        report(name, f, h, base)

    tally(lambda r: mx3(r) == 1.0, lambda r: r["over"], base_over,
          "Either side: last 3 ALL over 2.5 -> Over 2.5")
    tally(lambda r: mx3(r) >= 2 / 3, lambda r: r["over"], base_over,
          "Either side: last 3 >=2/3 over -> Over 2.5")
    tally(lambda r: mx3(r) == 0.0, lambda r: r["over"], base_over,
          "Either side: last 3 ALL under -> Over 2.5")
    tally(lambda r: mxg(r) > OVER_BAR, lambda r: r["over"], base_over,
          "Either side: last 5 avg goals > 2.5 -> Over 2.5")
    tally(lambda r: mn3(r) >= 2 / 3, lambda r: r["btts"], base_btts,
          "Both sides: last 3 >=2/3 over -> BTTS")
    tally(lambda r: mn3(r) == 0.0, lambda r: r["btts"], base_btts,
          "Both sides: last 3 ALL under -> BTTS")

    print("SIGNAL PERFORMANCE")
    print("%-46s %6s %7s %7s %9s  %s"
          % ("signal", "fired", "hit", "base", "lift", "verdict"))
    print("-" * 74)
    for name, fires, rate, lift in out:
        if not fires or rate is None:
            print("%-46s %6d %7s %7s %9s  NO EVIDENCE"
                  % (name, fires, "-", "-", "-"))
            continue
        base = base_btts if "BTTS" in name else base_over
        hw = 1.96 * math.sqrt(rate * (1 - rate) / fires)
        v = "BEATS" if lift > hw else ("TIES" if lift >= -hw else "WORSE")
        print("%-46s %6d %6.1f%% %6.1f%% %+8.1fpp  %s"
              % (name, fires, rate * 100, base * 100, lift * 100, v))
    print("-" * 74)
    print("lift = hit rate minus base rate. BEATS only when the lift clears")
    print("the 95% half-width; otherwise the signal is a coin flip.")
    print()
    print("NO LIVE-SCANNER SIGNAL WAS EVER BACKTESTED BEFORE THIS SCRIPT.")
    return 0


if __name__ == "__main__":
    sys.exit(run())