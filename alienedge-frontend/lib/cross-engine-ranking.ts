/**
 * cross-engine-ranking.ts — front-of-list ordering for GG, O25, O15 and U2S,
 * using signals that live in OTHER engines' payloads.
 *
 * WHY A SEPARATE FILE
 * -------------------
 * `signal-ranking.ts` orders Corners and SOT from fields inside their own
 * engine's row. This module does something different and stronger: it borrows
 * a field from a SECOND engine that computed something about the same fixture
 * but whose output was never consulted. The 2026-09-27 sweep found those
 * borrowed fields beat the own-engine rules outright — most sharply on U2S,
 * where `underdog_base.dog_odds` lifted the qualifying block from 77.0% to
 * 83.2% on a base that only reaches 66.5%.
 *
 * THE RULE THAT GOVERNS ALL OF THIS
 * ---------------------------------
 * An ordering is only meaningful for a market whose settlement is a FIXED
 * THRESHOLD that never reads the pick (corners >= 7, sot > 6, o25 >= 3 goals,
 * o15 >= 2, gg = both scored, shvi = 2nd-half goals > 0). For those, putting a
 * higher-expected fixture first is a real prediction.
 *
 * `win` and `u2s` are graded AGAINST A STORED PICK (`win_forecast` grades
 * "did THIS team win", `u2s` grades "did the stored underdog score"), so
 * re-ordering them is a DIFFERENT claim and is deliberately NOT claimed here.
 * U2S appears below only as a *fixture-quality* ordering helper, not as a
 * restatement of its pick-dependent verdict.
 *
 * TWO BUGS THIS WORK UNCOVERED (both fixed in signal_ledger.py)
 * -----------------------------------------------------------
 *  1. The prediction/archive join was keyed on an ORDERED (home, away) tuple,
 *     but the archiver and the engines disagree on venue orientation for some
 *     fixtures. Those rows were dropped as `unmatched`. o15 joined ZERO rows
 *     for an entire sweep because of this.
 *  2. The ledger read only the 'fixture'/'Fixture' column, but o15 ships its
 *     fixture under 'Match'. Again: zero rows, and it looked like "no data".
 * Both were latent and neither was visible from the Corners/SOT numbers.
 *
 * MISSING VALUES ARE NEVER TREATED AS LOW. A row whose borrowed field is absent
 * or unparseable is NOT a qualifier and is never given an invented zero; it
 * falls back to the own-engine ordering. "No data" must not masquerade as
 * "least likely".
 */

/** GG — own-engine rule. */
export const GG_BASE_MARKS_MIN = 3;
export const GG_MCG_PROB_MIN = 74.32;
/** GG — borrowed from gg_forensics. */
export const GG_FORENSIC_AUDIT_MAX = 3;

/** O25 */
export const O25_CONFIDENCE_MIN = 69;
export const O25_ODDS_MAX = 1.47;
/** O25 — borrowed from over25_forecast. */
export const O25_POS_GAP_MIN = 9;

/** O15 */
export const O15_POISSON_MIN = 55.6;
export const O15_GRADE_MIN = 5;

/** U2S — borrowed from underdog_base. */
export const U2S_DOG_VENUE_SOT_MIN = 12;
export const U2S_FAV_VENUE_SOT_MAX = 15;
export const U2S_DOG_ODDS_MAX = 3.44;

/**
 * WIN — the strongest ordering measured anywhere in this project.
 *
 * An earlier pass EXCLUDED win on the grounds that it is graded against a
 * stored pick. That reasoning was wrong. Each `win_forecast` row is a
 * separate bet carrying its own `side` and `team_name`, and `grade_row` grades
 * that row against that row's own team. Ranking bets by each bet's own win
 * probability is therefore exactly a precision improvement on the list, not a
 * restatement of the verdict.
 *
 * `win_odds` was checked for leakage before being used: WON and LOST rows span
 * the same odds range (1.00-12.50 vs 1.00-67.00), so it is a pre-match price
 * and not a copy of the result.
 *
 *   poisson_win_prob >= 41.09 AND win_odds <= 2.16
 *     -> 587 rows, 65.1% vs 31.5% for the rest (+33.6pp)
 *     -> Fisher p = 7.3e-50, Bonferroni-corrected p = 0.0000 over 2,873
 *        tested cut-points, bootstrap 95% CI [+29.5, +37.8]
 *     -> leave-one-day-out: 15 of 16 unseen days (base 38.0%)
 */
export const WIN_POISSON_MIN = 41.09;
export const WIN_ODDS_MAX = 2.16;

/**
 * DRAW — also clears correction outright.
 *
 *   composite_draw_score >= 0.391 AND h2h_draws >= 1
 *     -> 288 rows, 46.9% vs 17.6% for the rest (+29.2pp)
 *     -> Fisher p = 1.6e-21, corrected p = 0.0000 over 11,830 cut-points
 *     -> bootstrap 95% CI [+23.6, +35.4], leave-one-day-out 10/13
 *        (base 25.0%)
 */
export const DRAW_SCORE_MIN = 0.391;
export const DRAW_H2H_MIN = 1;

/**
 * U25 / U35 — REAL LIFT, BUT NOT YET PROVEN. Marked tentative in the UI.
 *
 * U25: combined_lambda >= 2.4 AND mc_u25_prob >= 0.565
 *   -> 46 rows, 65.2% vs 43.1% (+22.2pp), CI [+6.8, +36.8], LODO 6-8 of 7-8
 * U35: combined_lambda >= 2.4 AND mc_u25_prob >= 0.565
 *   -> 46 rows, 89.1% vs 65.5% (+23.6pp), CI [+13.5, +32.0], LODO 7/7-8
 *
 * Both fail Bonferroni (8.98 and 1.28) because 2,436 and 2,035 cut-points were
 * swept on ~1,150 rows, and both select the same 46 fixtures. The effect is
 * large and the CI excludes zero, but at n=46 across 15 days this is a
 * candidate, not a law. It is offered as a reversible display-only toggle and
 * labelled UNPROVEN rather than presented as evidence-backed.
 */
export const UNDERS_LAMBDA_MIN = 2.4;
export const UNDERS_MC_PROB_MIN = 0.565;

/** CORNERS — borrowed from calibration. */
export const CORNERS_PARITY_GAP_MAX = -2;

/**
 * Parse an engine field that may arrive as a number or a decorated string
 * ("41%", "13.11"). Returns null for absent/junk — NEVER 0.
 *
 * Re-implemented here rather than imported so this module stays independent
 * of signal-ranking.ts and the two cannot drift apart silently.
 */
function num(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string") return null;
  const match = value.replace(/,/g, "").match(/-?\d+(?:\.\d+)?/);
  if (!match) return null;
  const parsed = Number.parseFloat(match[0]);
  return Number.isFinite(parsed) ? parsed : null;
}

/** Both comparisons return false when the value is missing — never true. */
function atLeast(value: unknown, threshold: number): boolean {
  const parsed = num(value);
  return parsed !== null && parsed >= threshold;
}

function atMost(value: unknown, threshold: number): boolean {
  const parsed = num(value);
  return parsed !== null && parsed <= threshold;
}

/** Descending-by-a-field tie-break that sinks missing values instead of zeroing. */
function desc<T extends object>(a: T, b: T, field: string): number {
  const av = num((a as Record<string, unknown>)[field]);
  const bv = num((b as Record<string, unknown>)[field]);
  if (av === null && bv === null) return 0;
  if (av === null) return 1;
  if (bv === null) return -1;
  return av === bv ? 0 : av > bv ? -1 : 1;
}

/**
 * Read one field out of a row's `borrowed` bag.
 *
 * Typed as a plain lookup returning `unknown` rather than an indexed access,
 * because the bag is caller-supplied and unvalidated: a page can attach any
 * payload (or none at all), so every borrowed read must survive a missing bag,
 * a missing key, and a junk value without a cast at the call site.
 */
function borrowedField(row: Record<string, unknown>, key: string): unknown {
  const bag = row.borrowed;
  if (!bag || typeof bag !== "object") return undefined;
  return (bag as Record<string, unknown>)[key];
}


/* ================================================================== *
 * EVIDENCE STATUS — READ BEFORE CHANGING ANY THRESHOLD
 * ================================================================== *
 * Measured by `signal_backtest.py` over `output/archive_*.json` (18 settled
 * dates), graded by the same `settlement_service.grade_row` the Verify column
 * uses. Each entry is (n, hit-rate vs the rest, lift, Fisher exact p,
 * Bonferroni-corrected p over ALL cut-points swept, bootstrap 95% CI on the
 * lift, leave-one-day-out days won).
 *
 * GG — SUPPORTED.
 *   Base_Marks >= 3 AND Monte_GG_Prob >= 74.32
 *     -> 291 rows, 70.4% vs 56.0% (+14.4pp), corrected p = 0.013,
 *        CI [+7.0, +21.6], LODO 5/7.
 *   Plus the BORROWED gg_forensics.Forensic_Audit <= 3
 *     -> 129 rows, 75.2% vs 58.5% (+16.7pp), CI [+7.7, +24.8], LODO 6/6.
 *
 * O25 — SUGGESTIVE, NOT PROVEN. Do not present as proven.
 *   Confidence >= 69 AND Odds <= 1.47
 *     -> 109 rows, 80.7% vs 63.3% (+17.4pp), but corrected p = 0.084 does
 *        NOT clear 0.05.
 *   Plus the BORROWED over25_forecast.pos_gap >= 9 reaches 91.4% on only 35
 *   rows, and leave-one-day-out could not be evaluated at that depth.
 *
 * O15 — SUPPORTED. Poisson% >= 55.6 AND Grade >= 5
 *     -> 120 rows, 93.3% vs 72.8% (+20.5pp), corrected p = 0.035,
 *        CI [+9.4, +31.6], LODO 4/7. Good, but not settled.
 *
 * SHVI — NOT SUPPORTED, and deliberately NOT exported. The best rule lifts
 *   +21.0pp on n=83 with a CI of [+3.9, +39.7] that is nearly all noise, and
 *   corrected p = 25. The 2/3-day LODO agrees. Shipping a shvi comparator
 *   would be shipping noise.
 *
 * U2S — SUPPORTED as a fixture-quality ordering only. `dog_odds` is a
 *   pick-INDEPENDENT property of the fixture (how long the market prices the
 *   underdog), so it is not the leak that grading against the stored
 *   `Underdog` column would be.
 *     -> 257 rows, 77.0% (+13.5pp), LODO 7/7
 *     -> plus BORROWED underdog_base.dog_odds <= 3.44: 125 rows, 83.2%
 *        (+18.7pp), corrected p = 1.4e-05, CI [+11.3, +25.5], LODO 5/5.
 *
 * CORNERS — borrowed refinement only. calibration.parity_gap <= -2 takes an
 *   ALREADY-QUALIFYING corners row from 92.4% to 95.9% (+12.7pp total lift,
 *   p = 9.9e-05, LODO 3/4). It never promotes a row on its own; the
 *   own-engine gate in signal-ranking.ts always runs first.
 */


/**
 * Attach borrowed fields to rows without mutating the API payload.
 *
 * The pages fetch their primary engine's rows; the borrowed field lives in a
 * different engine's payload that the page may not have loaded. This lets a
 * caller supply those values explicitly, keyed by fixture name, so the
 * comparators stay pure functions of their input.
 */
export function withBorrowed<T extends object>(
  rows: T[],
  borrowed: Record<string, Record<string, unknown>> = {},
): (T & { borrowed: Record<string, unknown> })[] {
  return rows.map((row) => {
    const r = row as Record<string, unknown>;
    const key = String(r.fixture ?? r.Fixture ?? r.Match ?? "");
    return { ...row, borrowed: borrowed[key] ?? {} };
  });
}

/* ---------------------------- GG ---------------------------- */

/** `Base_Marks >= 3 AND Monte_GG_Prob >= 74.32` — the proven own-engine rule. */
export function ggQualifies(row: Record<string, unknown>): boolean {
  return atLeast(row.Base_Marks, GG_BASE_MARKS_MIN) &&
    atLeast(row.Monte_GG_Prob, GG_MCG_PROB_MIN);
}

/**
 * The sharpened tier: the own-engine rule AND the borrowed forensic audit.
 * Only rows that already pass the own-engine rule are eligible, so a borrowed
 * field can never promote a row the evidence-backed rule rejected.
 */
export function ggQualifiesSharp(row: Record<string, unknown>): boolean {
  if (!ggQualifies(row)) return false;
  return atMost(borrowedField(row, "Forensic_Audit"), GG_FORENSIC_AUDIT_MAX);
}

/** Three tiers, best first; ties inside a tier fall back to Monte_GG_Prob. */
export function sortGG<T extends object>(rows: T[]): T[] {
  return [...rows].sort((a, b) => {
    const ra = a as Record<string, unknown>;
    const rb = b as Record<string, unknown>;
    const tier = (r: Record<string, unknown>): number =>
      ggQualifiesSharp(r) ? 0 : ggQualifies(r) ? 1 : 2;
    const ta = tier(ra);
    const tb = tier(rb);
    if (ta !== tb) return ta - tb;
    return desc(a, b, "Monte_GG_Prob");
  });
}

/* --------------------------- O25 --------------------------- */

export function o25Qualifies(row: Record<string, unknown>): boolean {
  return atLeast(row.Confidence, O25_CONFIDENCE_MIN) &&
    atMost(row.Odds, O25_ODDS_MAX);
}

export function o25QualifiesSharp(row: Record<string, unknown>): boolean {
  if (!o25Qualifies(row)) return false;
  return atLeast(borrowedField(row, "pos_gap"), O25_POS_GAP_MIN);
}

export function sortO25<T extends object>(rows: T[]): T[] {
  return [...rows].sort((a, b) => {
    const ra = a as Record<string, unknown>;
    const rb = b as Record<string, unknown>;
    const tier = (r: Record<string, unknown>): number =>
      o25QualifiesSharp(r) ? 0 : o25Qualifies(r) ? 1 : 2;
    const ta = tier(ra);
    const tb = tier(rb);
    if (ta !== tb) return ta - tb;
    return desc(a, b, "Confidence");
  });
}

/* --------------------------- O15 --------------------------- */

export function o15Qualifies(row: Record<string, unknown>): boolean {
  return atLeast(row["Poisson%"], O15_POISSON_MIN) &&
    atLeast(row.Grade, O15_GRADE_MIN);
}

export function sortO15<T extends object>(rows: T[]): T[] {
  return [...rows].sort((a, b) => {
    const qa = o15Qualifies(a as Record<string, unknown>) ? 0 : 1;
    const qb = o15Qualifies(b as Record<string, unknown>) ? 0 : 1;
    if (qa !== qb) return qa - qb;
    return desc(a, b, "Poisson%");
  });
}

/* --------------------------- U2S --------------------------- */

export function u2sQualifies(row: Record<string, unknown>): boolean {
  return atLeast(row.Dog_Venue_SOT, U2S_DOG_VENUE_SOT_MIN) &&
    atMost(row.Fav_Venue_SOT, U2S_FAV_VENUE_SOT_MAX);
}

export function u2sQualifiesSharp(row: Record<string, unknown>): boolean {
  if (!u2sQualifies(row)) return false;
  return atMost(borrowedField(row, "dog_odds"), U2S_DOG_ODDS_MAX);
}

export function sortU2S<T extends object>(rows: T[]): T[] {
  return [...rows].sort((a, b) => {
    const ra = a as Record<string, unknown>;
    const rb = b as Record<string, unknown>;
    const tier = (r: Record<string, unknown>): number =>
      u2sQualifiesSharp(r) ? 0 : u2sQualifies(r) ? 1 : 2;
    const ta = tier(ra);
    const tb = tier(rb);
    if (ta !== tb) return ta - tb;
    return desc(a, b, "Dog_Venue_SOT");
  });
}

/* ------------------------- CORNERS ------------------------- */

/**
 * True when the borrowed calibration field refines an ALREADY-QUALIFYING
 * corners row. This never promotes a row on its own: cornersQualifies() in
 * signal-ranking.ts remains the gate, and this is a tie-break inside it.
 */
export function cornersRefined(row: Record<string, unknown>): boolean {
  return atMost(borrowedField(row, "parity_gap"), CORNERS_PARITY_GAP_MAX);
}

/**
 * Corners ordering with the borrowed refinement applied INSIDE the qualifying
 * block. `qualifies` is injected (rather than imported) so the own-engine rule
 * in signal-ranking.ts stays the single source of truth for the gate.
 */
export function sortCornersRefined<T extends object>(
  rows: T[],
  qualifies: (row: Record<string, unknown>) => boolean,
): T[] {
  return [...rows].sort((a, b) => {
    const ra = a as Record<string, unknown>;
    const rb = b as Record<string, unknown>;
    const qa = qualifies(ra) ? 0 : 1;
    const qb = qualifies(rb) ? 0 : 1;
    if (qa !== qb) return qa - qb;
    if (qa === 0) {
      const sa = cornersRefined(ra) ? 0 : 1;
      const sb = cornersRefined(rb) ? 0 : 1;
      if (sa !== sb) return sa - sb;
    }
    return desc(a, b, "Total_Exp");
  });
}

/* ---------------------------- WIN ---------------------------- */

/**
 * `poisson_win_prob >= 41.09 AND win_odds <= 2.16`.
 *
 * Both fields are required. A row with no `win_odds` (the engine leaves it null
 * on roughly 2% of rows) is NOT a qualifier — "unknown price" must never be
 * read as "short price".
 */
export function winQualifies(row: Record<string, unknown>): boolean {
  return atLeast(row.poisson_win_prob, WIN_POISSON_MIN) &&
    atMost(row.win_odds, WIN_ODDS_MAX);
}

export function sortWin<T extends object>(rows: T[]): T[] {
  return [...rows].sort((a, b) => {
    const qa = winQualifies(a as Record<string, unknown>) ? 0 : 1;
    const qb = winQualifies(b as Record<string, unknown>) ? 0 : 1;
    if (qa !== qb) return qa - qb;
    return desc(a, b, "poisson_win_prob");
  });
}

/* --------------------------- DRAW --------------------------- */

/** `composite_draw_score >= 0.391 AND h2h_draws >= 1`. */
export function drawQualifies(row: Record<string, unknown>): boolean {
  return atLeast(row.composite_draw_score, DRAW_SCORE_MIN) &&
    atLeast(row.h2h_draws, DRAW_H2H_MIN);
}

export function sortDraw<T extends object>(rows: T[]): T[] {
  return [...rows].sort((a, b) => {
    const qa = drawQualifies(a as Record<string, unknown>) ? 0 : 1;
    const qb = drawQualifies(b as Record<string, unknown>) ? 0 : 1;
    if (qa !== qb) return qa - qb;
    return desc(a, b, "composite_draw_score");
  });
}

/* -------------------------- U25 / U35 -------------------------- */

/**
 * The unders rule, shared by both markets: `combined_lambda >= 2.4 AND
 * mc_u25_prob >= 0.565`. It is deliberately NOT marked proven — see the
 * UNDERS_* constants.
 */
export function undersQualifies(row: Record<string, unknown>): boolean {
  return atLeast(row.combined_lambda, UNDERS_LAMBDA_MIN) &&
    atLeast(row.mc_u25_prob, UNDERS_MC_PROB_MIN);
}

/**
 * The same rule applied to either unders list. `fallback` names the market's
 * OWN score column so the non-qualifying block still has a sensible order
 * instead of an arbitrary one.
 */
export function sortUnders<T extends object>(
  rows: T[],
  fallback: "u25_score" | "u35_score" = "u25_score",
): T[] {
  return [...rows].sort((a, b) => {
    const qa = undersQualifies(a as Record<string, unknown>) ? 0 : 1;
    const qb = undersQualifies(b as Record<string, unknown>) ? 0 : 1;
    if (qa !== qb) return qa - qb;
    return desc(a, b, fallback);
  });
}
