#!/usr/bin/env python3
"""
Join the shadow ledger against settled results.

The question this answers is the one that decides whether the two-source rule
deserves to gate anything:

    were the picks the rule would have DROPPED mostly losers?

If yes, the rule earns its place. If the dropped picks won as often as the
kept ones, the rule is discarding good picks and must not be switched on.

The ledger keeps the first reading of each pick, so a decision is scored
against the reading that was made when the pick actually went out — not
against whatever the last cycle happened to think.
"""
import json
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BACKEND, "data")
LEDGER_FILE = os.path.join(DATA_DIR, "convergence_shadow_ledger.json")
RESULTS_FILE = os.path.join(DATA_DIR, "ft_result_snapshot.json")


def load(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback


def settle(pick, result):
    """
    Did this pick win?

    Returns True, False, or None when the result cannot decide it. A pick that
    cannot be scored is never counted as a win — quietly treating an unscored
    pick as a miss would manufacture a hit rate out of missing data.
    """
    if not result or not result.get("is_finished"):
        return None
    h, a = result.get("h_ft"), result.get("a_ft")
    if h is None or a is None:
        return None

    ptype = pick.get("type")
    if ptype == "TO_SCORE":
        target = pick.get("target")
        if target == "home":
            return h > 0
        if target == "away":
            return a > 0
        return None
    if ptype == "GG":
        return h > 0 and a > 0
    if ptype == "GG_OVER_2.5":
        return (h + a) > 2
    return None


def index_results(snapshot):
    """
    fixture_id -> settled result, across every date bucket.

    THE REAL SHAPE IS {"fixtures": {date: {fid: result}}, "updated_at": ...,
    "date": ...}. Walking that naively iterates the top level and reaches the
    DATE KEY STRINGS inside "fixtures", so they get indexed as if they were
    results and every real match is missed — the tool then reports "no scored
    picks" forever without ever raising. Both the wrapped shape and a bare
    {date: {fid: result}} map are handled, and a value only counts as a result
    if it actually looks like one.
    """
    out = {}

    def absorb(bucket):
        if not isinstance(bucket, dict):
            return
        for fid, res in bucket.items():
            if (isinstance(res, dict)
                    and ("h_ft" in res or "ft_score" in res)
                    and not isinstance(res.get("picks"), list)):
                out[str(fid)] = res

    def walk(node, depth=0):
        # Bounded depth: the real file nests three levels. Anything deeper is a
        # cycle or a shape we do not understand, and guessing at it is how a
        # string ends up being scored as a match.
        if depth > 4:
            return
        if not isinstance(node, dict):
            return
        if any(k in node for k in ("h_ft", "ft_score")):
            return  # this node IS a result, absorbed by the caller
        for value in node.values():
            if isinstance(value, dict):
                absorb(value)
                walk(value, depth + 1)

    if isinstance(snapshot, dict):
        walk(snapshot.get("fixtures", snapshot))
    elif isinstance(snapshot, list):
        walk({"fixtures": snapshot})
    return out


def main():
    ledger = load(LEDGER_FILE, {})
    results = index_results(load(RESULTS_FILE, {}))

    rows, by_type = [], {}
    for fid, block in (ledger or {}).items():
        result = results.get(str(fid))
        for pick in (block or {}).get("picks", []):
            verdict = settle(pick, result)
            row = {"fixture": block.get("fixture"), "fixture_id": fid,
                   "type": pick.get("type"), "target": pick.get("target"),
                   "team": pick.get("team"), "label": pick.get("label"),
                   "would_gate": pick.get("would_gate"),
                   "sources": pick.get("sources_agreeing"),
                   "won": verdict}
            rows.append(row)
            key = (pick.get("type"), pick.get("would_gate"))
            slot = by_type.setdefault(key, {"n": 0, "wins": 0, "scored": 0})
            slot["n"] += 1
            if verdict is not None:
                slot["scored"] += 1
                if verdict:
                    slot["wins"] += 1

    scored = [r for r in rows if r["won"] is not None]

    def rate(rows_subset):
        if not rows_subset:
            return "no scored picks"
        w = sum(1 for r in rows_subset if r["won"])
        return f"{w}/{len(rows_subset)} = {100.0 * w / len(rows_subset):.1f}%"

    gated = [r for r in scored if r["would_gate"] is True]
    kept = [r for r in scored if r["would_gate"] is False]

    print("=" * 66)
    print("SHADOW SETTLEMENT — are the DROPPED picks actually losers?")
    print("=" * 66)
    print(f"ledger picks          : {len(rows)}")
    print(f"scored against result : {len(scored)}")
    print(f"awaiting result       : {len(rows) - len(scored)}")
    print()
    print(f"WOULD HAVE BEEN GATED : {rate(gated)}")
    print(f"WOULD HAVE SURVIVED   : {rate(kept)}")
    print()

    if len(scored) < 5:
        print("Too few settled picks to conclude anything. Keep collecting.")
    else:
        gr = sum(1 for r in gated if r["won"]) / len(gated) if gated else None
        kr = sum(1 for r in kept if r["won"]) / len(kept) if kept else None
        if gr is not None and kr is not None:
            print(f"difference            : {100.0 * (kr - gr):+.1f} pts")
            if gr < kr:
                print("VERDICT: the rule IS separating losers from winners.")
            elif gr == kr:
                print("VERDICT: no separation — the rule is not earning its place.")
            else:
                print("VERDICT: REVERSED — it is dropping the BETTER picks. "
                      "Do not gate on this.")

    if by_type:
        print()
        print("by market:")
        for (ptype, gate), slot in sorted(
                by_type.items(), key=lambda kv: str(kv[0])):
            if slot["scored"]:
                pct = 100.0 * slot["wins"] / slot["scored"]
                mark = "gated" if gate else "kept "
            else:
                pct, mark = 0.0, "gated" if gate else "kept "
            print(f"  {str(ptype):14} {mark}  "
                  f"{slot['wins']}/{slot['scored']} = {pct:5.1f}%")

    if rows and not scored:
        print()
        print("detail (no result yet):")
        for r in rows[:15]:
            print(f"  {str(r['fixture'])[:28]:30} {r['type']:13} "
                  f"{str(r['team'] or ''):16} gate={r['would_gate']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
