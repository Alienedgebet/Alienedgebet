/**
 * signal-ranking.ts — front-of-list ordering for the Corners and SOT markets.
 *
 * WHY THIS EXISTS
 * ---------------
 * Verification for both markets is a FIXED threshold on the combined match
 * total that never reads the pick (corners: total_corners >= 7, sot:
 * total_sot > 6). So the only thing an ordering can do is surface matches
 * with a higher expected total first. That is what these comparators do.
 *
 * EVIDENCE STATUS — READ BEFORE CHANGING ANY THRESHOLD
 * ----------------------------------------------------
 * These are backtested numbers, and they are NOT equally trustworthy. Both
 * were measured by `signal_backtest.py` against the settled archives
 * (output/archive_*.json), graded by the same settlement_service.grade_row
 * the Verify column uses. Re-run it before trusting any of this:
 *
 *   python3 signal_backtest.py --market sot
 *   python3 signal_backtest.py --market corners
 *
 * SOT — SUPPORTED, but not proven.
 *   Consistency >= 48 AND Proj_SOT >= 9.3 -> 49/51 = 96.1%
 *   vs 81.5% baseline (+19.6pp), Fisher exact p = 0.00136 (survives a
 *   Bonferroni correction over 36 tested cut-points), bootstrap 95% CI on
 *   the lift [+10.9, +27.8] pp, and it beat the rest of the list on 5 of 7
 *   leave-one-day-out days. n=51 and p clears Bonferroni by a hair, so treat
 *   this as the best available ordering, not a proven law.
 *
 * CORNERS — SUPPORTED via a compound rule (U2.5% + squad availability),
 *   not via Total_Exp.
 *   `Total_Exp` on its own scored AUC 0.488 (worse than a coin flip) across 667
 *   rows, and its top-10 hit 70% against an 85.6% baseline. That is NOT the
 *   signal. The signal is `U2.5% <= 48.8 AND at most one side wounded`
 *   -> 247 rows at 92.7% vs 81.5% for the rest, p = 0.000037 (survives
 *   Bonferroni over 404 cut-points), 10 of 11 leave-one-day-out days, and a
 *   bootstrap 95% CI on the lift of [+6.5, +16.2] pp. See the
 *   CORNERS_U25_MAX block below for why the U2.5 side is INVERTED.
 *
 *   Cup/friendly fixtures were checked separately: the rule holds on
 *   league-only (12/12) and cup/friendly (5/5) alike, so it is applied to
 *   every row rather than used to partition the list.
 *
 * MISSING VALUES ARE NEVER TREATED AS LOW. A row whose signal is missing or
 * unparseable sorts to the end with its peers; it is never given an invented
 * zero, which would silently rank "no data" as "least likely".
 */

export const SOT_CONSISTENCY_MIN = 48;
export const SOT_PROJ_MIN = 9.3;

/**
 * Corners thresholds — the ordering the full-history backtest supports.
 *
 * THE EVIDENCE (n=673 settled rows / 16 days, graded by the same
 * settlement_service.grade_row the Verify column uses):
 *
 *   U2.5% <= 48.8  AND  at most one side wounded
 *     -> 247 rows, 92.7% pass vs 81.5% for the rest (+11.3pp)
 *     -> Fisher exact p = 0.000037, survives a Bonferroni correction
 *        across 404 tested cut-points
 *     -> leave-one-day-out: beats the rest of the list on 10 of 11 days,
 *        mean margin +14.0pp
 *     -> bootstrap 95% CI on the lift [+6.5, +16.2] pp, P(lift>0) = 100%
 *     -> holds on league-only (12/12) AND cup/friendly (5/5) fixtures
 *
 * WHY THE U2.5 SIDE IS INVERTED: the market wins on the COMBINED corner
 * count (>= 7), and a low under-2.5-goals probability is the engine's proxy
 * for an open, high-event game. A high U2.5% means a cagey, low-event game
 * that produces fewer corners, so LOW U2.5% is the good side. Scoring this
 * the naive way (treating higher as better) is the single easiest way to
 * ship this rule inverted.
 *
 * U2.5% is only weakly correlated with Total_Exp (r = -0.20), so it is a
 * genuinely separate signal rather than a rescaling of the projection.
 */
export const CORNERS_U25_MAX = 48.8;
export const CORNERS_MAX_WOUNDED = 1;

function numeric(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string") return null;
  const match = value.replace(/,/g, "").match(/-?\d+(?:\.\d+)?/);
  if (!match) return null;
  const parsed = Number.parseFloat(match[0]);
  return Number.isFinite(parsed) ? parsed : null;
}

type SortDirection = 1 | -1;

/**
 * Descending by one field; rows missing it sink to the bottom, stably.
 *
 * Generic over `T extends object` rather than `Record<string, unknown>` on
 * purpose: the API's pick interfaces (CornerAggregatorPick, SOTPick) are
 * declared as `interface`, so they have no index signature and would not
 * satisfy a Record constraint. Reading a field off them is done through this
 * one narrow cast, which is why it lives here and not at the call site.
 */
function byField<T extends object>(field: string, direction: SortDirection = 1) {
  return (a: T, b: T): number => {
    const av = numeric((a as Record<string, unknown>)[field]);
    const bv = numeric((b as Record<string, unknown>)[field]);
    if (av === null && bv === null) return 0;
    if (av === null) return 1;
    if (bv === null) return -1;
    if (av === bv) return 0;
    // DESCENDING for the default direction=1: the comparator must report
    // "a after b" when a's signal is the higher one. Negating here is the
    // whole contract — getting it backwards silently yields ascending order.
    return av > bv ? -direction : direction;
  };
}

/**
 * SOT: matches the backtested combination first, then everything else by
 * Proj_SOT. The two groups are never merged, so the qualifying block stays a
 * contiguous run at the top instead of being diluted by a couple of very
 * high-projection rows that failed the consistency check.
 */
export function sortSOT<T extends object>(rows: T[]): T[] {
  const qualifies = (r: T): boolean => sotQualifies(r as Record<string, unknown>);
  return [...rows].sort((a, b) => {
    const qa = qualifies(a) ? 0 : 1;
    const qb = qualifies(b) ? 0 : 1;
    if (qa !== qb) return qa - qb;
    return byField<T>("Proj_SOT")(a, b);
  });
}

export function sotQualifies(row: Record<string, unknown>): boolean {
  const c = numeric(row.Consistency);
  const p = numeric(row.Proj_SOT);
  return c !== null && p !== null && c >= SOT_CONSISTENCY_MIN && p >= SOT_PROJ_MIN;
}

/**
 * Corners rows carry a decorated injury flag ('🩸 YES' / '❌ NO'). Returns the
 * number of wounded sides, or null when a side has no flag at all — an absent
 * flag must NOT be read as "healthy", or a match with missing injury data
 * would silently pass the wounded-side test.
 */
export function countWounded(row: Record<string, unknown>): number | null {
  let total = 0;
  for (const key of ["Home_Wounded", "Away_Wounded"]) {
    const raw = row[key];
    if (raw === null || raw === undefined || String(raw).trim() === "") return null;
    const text = String(raw).toUpperCase();
    if (text.includes("YES")) total += 1;
    else if (!text.includes("NO")) return null;   // unrecognised -> unknown
  }
  return total;
}

/** True when the row satisfies the backtested Corners rule. */
export function cornersQualifies(row: Record<string, unknown>): boolean {
  const u25 = numeric(row["U2.5%"]);
  const wounded = countWounded(row);
  if (u25 === null || wounded === null) return false;
  return u25 <= CORNERS_U25_MAX && wounded <= CORNERS_MAX_WOUNDED;
}

/**
 * Corners: qualifying rows first, then everything else by projected volume.
 *
 * The rest are ordered by Total_Exp DESC purely as a tie-break within the
 * non-qualifying block. Total_Exp is NOT itself evidence-backed (AUC 0.488 on
 * its own), so it must never be allowed to promote a non-qualifying row above
 * a qualifying one — hence the two groups are kept strictly separate.
 */
export function sortCorners<T extends object>(rows: T[]): T[] {
  const ok = (r: T): boolean => cornersQualifies(r as Record<string, unknown>);
  return [...rows].sort((a, b) => {
    const qa = ok(a) ? 0 : 1;
    const qb = ok(b) ? 0 : 1;
    if (qa !== qb) return qa - qb;
    return byField<T>("Total_Exp")(a, b);
  });
}
