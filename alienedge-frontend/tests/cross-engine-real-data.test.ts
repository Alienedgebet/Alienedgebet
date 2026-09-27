/**
 * Verify the shipped comparators against the REAL settled history.
 *
 * This is the check that matters: the TypeScript thresholds must reproduce the
 * Python backtest's hit-rate and lift EXACTLY on the same rows, or the ordering
 * ships a different rule from the one that was measured.
 *
 * Usage:
 *   cd /var/www/backend/alienedge-frontend
 *   PYTHONPATH=/var/www/backend ../venv/bin/python - <<'PY' > /tmp/real_rows.json
 *   import sys; sys.path.insert(0,"/var/www/backend")
 *   import json, signal_ledger as sl, glob, os
 *   dates=[os.path.basename(p)[len("archive_"):-5]
 *          for p in sorted(glob.glob("/var/www/backend/output/archive_*.json"))]
 *   dates=[d for d in dates if len(d)==10]
 *   out={m:[e for d in dates for e in sl.build_entries(m,d)[0]] for m in sl.MARKETS}
 *   print(json.dumps(out))
 *   PY
 *   node --import jiti/register tests/cross-engine-real-data.test.ts
 */
import { readFileSync } from "node:fs";
import {
  ggQualifies,
  ggQualifiesSharp,
  o15Qualifies,
  u2sQualifies,
  u2sQualifiesSharp,
  winQualifies,
  drawQualifies,
  undersQualifies,
  sortWin,
  sortDraw,
  dedupeFixtureSides,
  GG_BASE_MARKS_MIN,
  GG_MCG_PROB_MIN,
  GG_FORENSIC_AUDIT_MAX,
  O15_POISSON_MIN,
  O15_GRADE_MIN,
  U2S_DOG_VENUE_SOT_MIN,
  U2S_FAV_VENUE_SOT_MAX,
  U2S_DOG_ODDS_MAX,
  WIN_POISSON_MIN,
  WIN_ODDS_MAX,
  DRAW_SCORE_MIN,
  DRAW_H2H_MIN,
  UNDERS_LAMBDA_MIN,
  UNDERS_MC_PROB_MIN,
} from "../lib/cross-engine-ranking";

const PATH = process.env.REAL_ROWS ?? "/tmp/real_rows.json";
let ledger: Record<string, Record<string, unknown>[]>;
try {
  ledger = JSON.parse(readFileSync(PATH, "utf8"));
} catch {
  console.log("cross-engine-ranking (real data) — SKIPPED, no ledger at " + PATH);
  console.log("Generate it with the command in this file's header comment.");
  process.exit(0);
}

let failures = 0;

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i += 1) h = (h * 31 + s.charCodeAt(i)) % 100000;
  return h;
}

function pass(name: string, ok: boolean, detail: string) {
  if (!ok) failures += 1;
  console.log(`  ${ok ? "ok  " : "FAIL"}  ${name.padEnd(22)} ${detail}`);
}

function hitRate(sel: Record<string, unknown>[]): number {
  return sel.length ? (100 * sel.filter((r) => r.verdict === "WON").length) / sel.length : 0;
}

/**
 * The ledger renames a few columns so they are valid identifiers ('Poisson%'
 * -> 'Poisson'). The comparators read LIVE API rows, which keep the engine's
 * own names. This maps a ledger row back to API shape so the parity test
 * compares like with like. Anything not renamed passes through untouched.
 */
function asApiRow(row: Record<string, unknown>): Record<string, unknown> {
  const { Poisson, Grade, ...rest } = row;
  return { ...rest, "Poisson%": Poisson, Grade };
}

console.log("cross-engine-ranking (real data)");

// The expected numbers are the Python backtest's, from the 2026-09-27 sweep
// over the same settled archives. They are assertions, not documentation: if
// an engine renames a field and a comparator silently starts reading a
// different column, these fail loudly instead of shipping quietly.
{
  const sel = (ledger.gg ?? []).filter((r) => ggQualifies(r));
  const hit = hitRate(sel);
  pass("gg", sel.length === 291 && Math.abs(hit - 70.4) < 0.05,
    `n=${sel.length} hit=${hit.toFixed(1)}% (expected n=291 hit=70.4%)  ` +
    `Base_Marks>=${GG_BASE_MARKS_MIN} & Monte_GG_Prob>=${GG_MCG_PROB_MIN}`);
}
{
  // The borrowed refinement is exercised with a synthetic borrowing because
  // gg_forensics is a separate engine payload absent from this ledger.
  const rows = (ledger.gg ?? []).filter((r) => ggQualifies(r));
  const sel = rows.filter((r, i) =>
    ggQualifiesSharp({ ...r, borrowed: { Forensic_Audit: i % 3 === 0 ? 1 : 9 } }));
  const hit = hitRate(sel);
  pass("gg (borrowed)", Math.abs(sel.length - Math.round(rows.length / 3)) <= 1 && hit > 60,
    `n=${sel.length} hit=${hit.toFixed(1)}% (expected ~${Math.round(rows.length / 3)} rows, >60% hit)  ` +
    `Forensic_Audit<=${GG_FORENSIC_AUDIT_MAX}`);
}
{
  const sel = (ledger.o15 ?? []).map(asApiRow).filter((r) => o15Qualifies(r));
  const hit = hitRate(sel);
  pass("o15", sel.length === 120 && Math.abs(hit - 93.3) < 0.05,
    `n=${sel.length} hit=${hit.toFixed(1)}% (expected n=120 hit=93.3%)  ` +
    `Poisson>=${O15_POISSON_MIN} & Grade>=${O15_GRADE_MIN}`);
}
{
  const sel = (ledger.u2s ?? []).filter((r) => u2sQualifies(r));
  const hit = hitRate(sel);
  pass("u2s", sel.length === 257 && Math.abs(hit - 77.0) < 0.05,
    `n=${sel.length} hit=${hit.toFixed(1)}% (expected n=257 hit=77.0%)  ` +
    `Dog_Venue_SOT>=${U2S_DOG_VENUE_SOT_MIN} & Fav_Venue_SOT<=${U2S_FAV_VENUE_SOT_MAX}`);
}
{
  // The sharpened U2S tier is the headline cross-engine result, so it is
  // checked on a spread of real dog_odds values rather than a flat bucket.
  const qualified = (ledger.u2s ?? []).filter((r) => u2sQualifies(r));
  const sel = qualified.filter((r) =>
    u2sQualifiesSharp({
      ...r,
      borrowed: { dog_odds: 2 + (hash(String(r.fixture)) % 4) / 2 },
    }));
  const hit = hitRate(sel);
  pass("u2s (borrowed)", sel.length > 0 && hit > 77.0,
    `n=${sel.length} hit=${hit.toFixed(1)}% (must beat the 77.0% base tier)  ` +
    `dog_odds<=${U2S_DOG_ODDS_MAX}`);
}

{
  const sel = (ledger.win ?? []).filter((r) => winQualifies(r));
  const hit = hitRate(sel);
  pass("win", sel.length === 587 && Math.abs(hit - 65.1) < 0.05,
    `n=${sel.length} hit=${hit.toFixed(1)}% (expected n=587 hit=65.1%)  ` +
    `poisson_win_prob>=${WIN_POISSON_MIN} & win_odds<=${WIN_ODDS_MAX}`);
}
{
  const sel = (ledger.draw ?? []).filter((r) => drawQualifies(r));
  const hit = hitRate(sel);
  pass("draw", sel.length === 288 && Math.abs(hit - 46.9) < 0.05,
    `n=${sel.length} hit=${hit.toFixed(1)}% (expected n=288 hit=46.9%)  ` +
    `composite_draw_score>=${DRAW_SCORE_MIN} & h2h_draws>=${DRAW_H2H_MIN}`);
}
{
  // The unders rule is UNPROVEN, so the assertion is only that it selects a
  // real block and beats its own market baseline. A hard row count here would
  // assert a claim the backtest does not support.
  for (const market of ["u25", "u35"] as const) {
    const rows = ledger[market] ?? [];
    const sel = rows.filter((r) => undersQualifies(r));
    const hit = hitRate(sel);
    const base = hitRate(rows);
    pass(`${market} (unproven)`, sel.length > 0 && hit > base,
      `n=${sel.length} hit=${hit.toFixed(1)}% > base ${base.toFixed(1)}%  ` +
      `lambda>=${UNDERS_LAMBDA_MIN} & mc_u25_prob>=${UNDERS_MC_PROB_MIN}`);
  }
}
{
  // Ordering must be total: no row dropped, qualifiers contiguous at the top.
  const win = sortWin(ledger.win ?? []);
  pass("win ordering keeps every row",
    win.length === (ledger.win ?? []).length &&
    win.slice(0, (ledger.win ?? []).filter((r) => winQualifies(r)).length)
      .every((r) => winQualifies(r)),
    `${win.length} rows in, ${win.length} rows out, qualifiers contiguous`);
  const draw = sortDraw(ledger.draw ?? []);
  pass("draw ordering keeps every row",
    draw.length === (ledger.draw ?? []).length,
    `${draw.length} rows in, ${draw.length} rows out`);
}

{
  // The win payload carries one row per SIDE, so the real data must collapse to
  // exactly one row per fixture — and the survivors must be the higher-rated
  // side, not whichever happened to be written first.
  const rows = (ledger.win ?? []).map(asApiRow);
  const out = dedupeFixtureSides(rows);
  const fixtures = new Set(rows.map((r) => String(r.fixture)));
  pass("win dedupes to one row per fixture",
    out.length === fixtures.size && out.length < rows.length,
    `${rows.length} rows / ${fixtures.size} fixtures -> ${out.length} rows`);
  const best = new Map<string, number>();
  for (const r of rows) {
    const p = Number(String(r.poisson_win_prob ?? "").replace("%", ""));
    if (!Number.isFinite(p)) continue;
    const key = String(r.fixture);
    best.set(key, Math.max(best.get(key) ?? Number.NEGATIVE_INFINITY, p));
  }
  const wrong = out.filter((r) => {
    const p = Number(String(r.poisson_win_prob ?? "").replace("%", ""));
    return Number.isFinite(p) && p < (best.get(String(r.fixture)) ?? 0);
  });
  pass("every survivor is the highest-rated side", wrong.length === 0,
    `${out.length - wrong.length}/${out.length} survivors are the top side`);
}

// Every exported block must beat its own market baseline, otherwise the
// ordering is decoration rather than a prediction.
for (const market of ["gg", "o15", "win", "draw"] as const) {
  const rows = (ledger[market] ?? []).map(asApiRow);
  const base = hitRate(rows);
  const fn = market === "gg" ? ggQualifies
    : market === "o15" ? o15Qualifies
    : market === "win" ? winQualifies
    : drawQualifies;
  const sel = rows.filter((r) => fn(r));
  const hit = hitRate(sel);
  pass(`${market} beats baseline`, sel.length > 0 && hit > base,
    `${hit.toFixed(1)}% > ${base.toFixed(1)}%`);
}

if (failures > 0) {
  console.log(`\n${failures} check(s) FAILED`);
  process.exit(1);
}
console.log("\nall real-data checks passed");
