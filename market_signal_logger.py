"""
market_signal_logger.py — append-only (signal -> outcome) ledger for Corners/SOT.

WHY
---
The 2026-09-26 investigation asked "can these two markets be ordered so the
rows at the top pass verification more often?". Answering it needs a durable,
per-row record of the signal values that were on screen at prediction time
AND the verdict that fixture eventually received. Without that, every question
has to be re-derived from whatever archives happen to still exist, and a
threshold that is chosen today cannot be re-checked honestly tomorrow once
the sample has grown.

WHAT IT DOES
------------
Once per day, for each configured market and each of the last N dates, it
joins that date's prediction rows to the archiver's settled results, grades
them with the single authoritative grader, and appends one JSON line per row
to `data/signal_ledger.jsonl`.

DESIGN RULES
------------
  * APPEND-ONLY, IDEMPOTENT. The (date, market, fixture) key is deduped
    against what is already on disk, so re-running is safe and never
    duplicates or rewrites a row. Nothing in `output/` is ever modified.
  * READ-ONLY on predictions. It grades, it never re-grades in place, and it
    never touches an engine, the API, or settlement.
  * ZERO new API calls. Every input is a file the pipeline already wrote.
  * HONEST about coverage. Rows that are unmatched, still PENDING, or that the
    grader refuses to settle are counted and reported, never quietly coerced
    into a loss — treating "no data" as "lost" is precisely the fabrication
    settlement_service goes out of its way to avoid.

USAGE
-----
    python3 market_signal_logger.py --days 14      # backfill + daily
    python3 market_signal_logger.py --days 1 --dry-run
"""

import argparse
import json
import os
import sys

import signal_ledger as sl


def load_existing_keys():
    """(date, market, fixture) already recorded, so appends stay idempotent."""
    seen = set()
    if not os.path.exists(sl.LEDGER_PATH):
        return seen
    with open(sl.LEDGER_PATH, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                # A torn final line from an interrupted append is skipped, not
                # fatal: the next run rewrites that row correctly.
                continue
            seen.add((row.get("date"), row.get("market"), row.get("fixture")))
    return seen


def run(days, markets, dry_run=False, rebuild=False):
    dates = []
    for path in sorted(os.listdir(sl.ARCHIVE_DIR)):
        if not (path.startswith("archive_") and path.endswith(".json")):
            continue
        date = path[len("archive_"):-len(".json")]
        if len(date) == 10 and date[4] == "-" and date[7] == "-":
            dates.append(date)
    dates.sort()
    dates = dates[-days:]

    if rebuild:
        # Rebuilding is the ONLY way to change the stored column set, and it
        # stays safe because build_entries() re-derives every row from the
        # immutable predictions + archives rather than editing the ledger in
        # place. Refused without an explicit flag so a routine daily run can
        # never truncate the file.
        print("[rebuild] replacing %s" % sl.LEDGER_PATH)
        existing = set()
        tmp = sl.LEDGER_PATH + ".rebuild"
        if not dry_run:
            with open(tmp, "w", encoding="utf-8") as handle:
                pass
    else:
        existing = load_existing_keys()
    pending, appended = [], 0
    totals = {}

    for market in markets:
        agg = {"predictions": 0, "joined": 0, "pending": 0,
               "unmatched": 0, "ungraded": 0, "written": 0, "skipped_dup": 0}
        for date in dates:
            entries, stats = sl.build_entries(market, date)
            for key in ("predictions", "joined", "pending", "unmatched", "ungraded"):
                agg[key] += stats.get(key, 0)
            for entry in entries:
                ident = (entry["date"], entry["market"], entry["fixture"])
                if ident in existing:
                    agg["skipped_dup"] += 1
                    continue
                existing.add(ident)
                pending.append(entry)
                agg["written"] += 1
        totals[market] = agg

    for market, agg in totals.items():
        print("[%s] preds=%d graded=%d pending=%d unmatched=%d ungraded=%d "
              "new=%d dup_skipped=%d"
              % (market, agg["predictions"], agg["joined"], agg["pending"],
                 agg["unmatched"], agg["ungraded"], agg["written"],
                 agg["skipped_dup"]))

    if not pending:
        print("Nothing new to log (%d dates scanned)." % len(dates))
        return 0

    if dry_run:
        print("[dry-run] would append %d rows to %s" % (len(pending), sl.LEDGER_PATH))
        return 0

    os.makedirs(sl.DATA_DIR, exist_ok=True)
    # A rebuild writes to a temp file and swaps it in atomically, so a crash
    # mid-write can never leave a truncated ledger behind.
    target = tmp if rebuild else sl.LEDGER_PATH
    mode = "w" if rebuild else "a"
    with open(target, mode, encoding="utf-8") as handle:
        for entry in pending:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    if rebuild:
        os.replace(tmp, sl.LEDGER_PATH)
    print("%s %d rows in %s" % ("Rebuilt with" if rebuild else "Appended",
                                 len(pending), sl.LEDGER_PATH))
    return len(pending)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14,
                        help="how many trailing archive dates to reconcile")
    parser.add_argument("--market", action="append", choices=sorted(sl.MARKETS),
                        default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rebuild", action="store_true",
                        help="re-derive the whole ledger (needed when the "
                             "logged column set changes)")
    args = parser.parse_args()
    markets = args.market or sorted(sl.MARKETS)
    run(args.days, markets, dry_run=args.dry_run, rebuild=args.rebuild)
    return 0


if __name__ == "__main__":
    sys.exit(main())
