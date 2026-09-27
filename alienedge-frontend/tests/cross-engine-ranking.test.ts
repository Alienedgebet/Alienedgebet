import assert from "node:assert/strict";
import {
  sortGG,
  sortO25,
  sortO15,
  sortU2S,
  sortCornersRefined,
  withBorrowed,
  ggQualifies,
  ggQualifiesSharp,
  o25Qualifies,
  o25QualifiesSharp,
  o15Qualifies,
  u2sQualifies,
  u2sQualifiesSharp,
  cornersRefined,
  dedupeFixtureSides,
  GG_BASE_MARKS_MIN,
  GG_MCG_PROB_MIN,
  GG_FORENSIC_AUDIT_MAX,
  O25_CONFIDENCE_MIN,
  O25_ODDS_MAX,
  O25_POS_GAP_MIN,
  O15_POISSON_MIN,
  O15_GRADE_MIN,
  U2S_DOG_VENUE_SOT_MIN,
  U2S_FAV_VENUE_SOT_MAX,
  U2S_DOG_ODDS_MAX,
  CORNERS_PARITY_GAP_MAX,
} from "../lib/cross-engine-ranking";

let passed = 0;
function check(name: string, fn: () => void) {
  fn();
  passed += 1;
  console.log("  ok  " + name);
}

console.log("cross-engine-ranking");

/* ------------------------- missing data ------------------------- */

check("missing values never qualify (no fabricated zero)", () => {
  assert.equal(ggQualifies({}), false);
  assert.equal(ggQualifies({ Base_Marks: null, Monte_GG_Prob: 90 }), false);
  assert.equal(ggQualifies({ Base_Marks: 5, Monte_GG_Prob: "N/A" }), false);
  assert.equal(o25Qualifies({}), false);
  assert.equal(o15Qualifies({}), false);
  assert.equal(u2sQualifies({}), false);
});

check("an ABSENT borrowed field is unknown, not a pass", () => {
  const own = { Base_Marks: 5, Monte_GG_Prob: 90 };
  assert.equal(ggQualifies(own), true, "own-engine rule still passes");
  assert.equal(
    ggQualifiesSharp(own),
    false,
    "no borrowed data must not be treated as satisfying the borrowed bound",
  );
  assert.equal(
    ggQualifiesSharp({ ...own, borrowed: { Forensic_Audit: "N/A" } }),
    false,
    "unparseable borrowed value is unknown, not zero",
  );
});

check("borrowed comparisons tolerate the engines' string fields", () => {
  assert.equal(
    u2sQualifiesSharp({
      Dog_Venue_SOT: "14", Fav_Venue_SOT: "9", borrowed: { dog_odds: "3.1" },
    }),
    true,
  );
});

/* ------------------ borrowed never promotes a row ------------------ */

check("a borrowed field can never promote a row the own rule rejected", () => {
  const row = {
    Base_Marks: 1, Monte_GG_Prob: 10, borrowed: { Forensic_Audit: 0 },
  };
  assert.equal(ggQualifies(row), false);

check("o25 and u2s honour their documented thresholds", () => {
  assert.equal(
    o25Qualifies({ Confidence: O25_CONFIDENCE_MIN, Odds: O25_ODDS_MAX }), true);
  assert.equal(
    o25Qualifies({ Confidence: O25_CONFIDENCE_MIN - 1, Odds: 1.0 }), false);
  assert.equal(
    o25QualifiesSharp({
      Confidence: 80, Odds: 1.2, borrowed: { pos_gap: O25_POS_GAP_MIN },
    }), true);
  assert.equal(
    u2sQualifies({
      Dog_Venue_SOT: U2S_DOG_VENUE_SOT_MIN, Fav_Venue_SOT: U2S_FAV_VENUE_SOT_MAX,
    }), true);
  assert.equal(
    u2sQualifiesSharp({
      Dog_Venue_SOT: 14, Fav_Venue_SOT: 9, borrowed: { dog_odds: U2S_DOG_ODDS_MAX },
    }), true);
});

check("o15 rule requires BOTH Poisson% and Grade", () => {
  assert.equal(o15Qualifies({ "Poisson%": O15_POISSON_MIN, Grade: O15_GRADE_MIN }), true);
  assert.equal(o15Qualifies({ "Poisson%": 90, Grade: 1 }), false, "Grade alone is not enough");
  assert.equal(o15Qualifies({ "Poisson%": 10, Grade: 9 }), false, "Poisson alone is not enough");
});

/*
 * The comparators read LIVE API rows, where o15's field is the engine's own
 * 'Poisson%'. signal_ledger deliberately RENAMES it to 'Poisson' in the
 * serialised ledger so the column is a valid identifier. The real-data parity
 * test therefore maps between the two; this check locks that mapping so the two
 * sides can never drift apart unnoticed.
 */
check("the ledger's renamed o15 field is the same value as the API's", () => {
  assert.equal(o15Qualifies({ "Poisson%": 60, Grade: 5 }), true);
  assert.equal(o15Qualifies({ Poisson: 60, Grade: 5 }), false,
    "the comparator must NOT read the ledger's renamed column from an API row");
});

/* ---------------------------- ordering ---------------------------- */

check("GG orders: sharpened, then qualifying, then the rest", () => {
  const rows = withBorrowed(
    [
      { Fixture: "rest-high-prob", Base_Marks: 1, Monte_GG_Prob: 95 },
      { Fixture: "qualify", Base_Marks: 4, Monte_GG_Prob: 80 },
      { Fixture: "sharp", Base_Marks: 4, Monte_GG_Prob: 80 },
    ],
    { sharp: { Forensic_Audit: 1 }, qualify: { Forensic_Audit: 9 } },
  );
  const out = sortGG(rows);
  assert.equal(out[0].Fixture, "sharp", "sharpened tier leads");
  assert.equal(out[1].Fixture, "qualify", "then the base qualifying tier");
  assert.equal(out[2].Fixture, "rest-high-prob", "a high prob never promotes a non-qualifier");
  assert.equal(out.length, 3, "no row is ever filtered out");
});

check("U2S ordering puts the borrowed-odds tier first", () => {
  const rows = withBorrowed(
    [
      { Fixture: "base", Dog_Venue_SOT: 14, Fav_Venue_SOT: 9 },
      { Fixture: "sharp", Dog_Venue_SOT: 14, Fav_Venue_SOT: 9 },
      { Fixture: "none", Dog_Venue_SOT: 2, Fav_Venue_SOT: 20 },
    ],
    { sharp: { dog_odds: 2.4 }, base: { dog_odds: 5.0 } },
  );
  const out = sortU2S(rows);
  assert.equal(out[0].Fixture, "sharp");
  assert.equal(out[1].Fixture, "base");
  assert.equal(out[2].Fixture, "none");
});

check("O25 and O15 order qualifying rows into one contiguous top block", () => {
  const o25 = sortO25([
    { Fixture: "no", Confidence: 20, Odds: 1.9 },
    { Fixture: "yes", Confidence: O25_CONFIDENCE_MIN, Odds: 1.4 },
  ]);
  assert.equal(o25[0].Fixture, "yes");
  const o15 = sortO15([
    { Fixture: "no", "Poisson%": 99, Grade: "A" },
    { Fixture: "yes", "Poisson%": O15_POISSON_MIN, Grade: "5" },
  ]);
  assert.equal(o15[0].Fixture, "yes");

/* ------------------------- corners refinement ------------------------- */

check("corners refinement only reorders INSIDE the qualifying block", () => {
  const qualifies = (r: Record<string, unknown>) => r.qualify === true;
  const rows = withBorrowed(
    [
      { Fixture: "qualify-plain", Total_Exp: "9", qualify: true },
      { Fixture: "qualify-refined", Total_Exp: "7", qualify: true },
      { Fixture: "nonqualify-refined", Total_Exp: "30", qualify: false },
    ],
    { "qualify-refined": { parity_gap: -3 }, "nonqualify-refined": { parity_gap: -9 } },
  );
  const out = sortCornersRefined(rows, qualifies);
  assert.equal(out[0].Fixture, "qualify-refined", "refined qualifier leads");
  assert.equal(out[1].Fixture, "qualify-plain");
  assert.equal(out[2].Fixture, "nonqualify-refined", "a non-qualifier is never promoted");
});

check("corners refinement honours the documented bound and missing data", () => {
  assert.equal(cornersRefined({ borrowed: { parity_gap: CORNERS_PARITY_GAP_MAX } }), true);
  assert.equal(cornersRefined({ borrowed: { parity_gap: CORNERS_PARITY_GAP_MAX + 1 } }), false);
  assert.equal(cornersRefined({}), false);
});

/* ---------------------------- withBorrowed ---------------------------- */

check("withBorrowed keys off every fixture column and never mutates", () => {
  const original = [{ Fixture: "A vs B" }];
  const out = withBorrowed(original, { "A vs B": { Forensic_Audit: 1 } });
  assert.deepEqual((out[0] as { borrowed: Record<string, unknown> }).borrowed,
    { Forensic_Audit: 1 });
  assert.deepEqual(original[0], { Fixture: "A vs B" }, "input is untouched");
  const viaMatch = withBorrowed([{ Match: "C vs D" }], { "C vs D": { dog_odds: 2 } });
  assert.deepEqual((viaMatch[0] as { borrowed: Record<string, unknown> }).borrowed,
    { dog_odds: 2 });
  const unknown = withBorrowed([{ Fixture: "Z vs W" }]);
  assert.deepEqual((unknown[0] as { borrowed: Record<string, unknown> }).borrowed, {});
});

/* ------------------------- per-side dedupe ------------------------- */

check("both sides of one fixture collapse to the higher-probability side", () => {
  const out = dedupeFixtureSides([
    { fixture: "A vs B", side: "away", poisson_win_prob: "68.58%" },
    { fixture: "A vs B", side: "home", poisson_win_prob: "5.10%" },
  ]);
  assert.equal(out.length, 1, "a fixture must not appear twice");
  assert.equal(out[0].side, "away", "the side the engine rates higher survives");
});

check("dedupe keeps the first row on a tie, never a reshuffle", () => {
  const out = dedupeFixtureSides([
    { fixture: "A vs B", side: "home", poisson_win_prob: "50%" },
    { fixture: "A vs B", side: "away", poisson_win_prob: "50%" },
  ]);
  assert.equal(out.length, 1);
  assert.equal(out[0].side, "home", "an equal probability keeps the earlier row");
});

check("dedupe preserves the original row order across fixtures", () => {
  const out = dedupeFixtureSides([
    { fixture: "A vs B", side: "home", poisson_win_prob: "10%" },
    { fixture: "C vs D", side: "away", poisson_win_prob: "80%" },
    { fixture: "A vs B", side: "away", poisson_win_prob: "90%" },
  ]);
  assert.deepEqual(out.map((r) => r.fixture), ["A vs B", "C vs D"],
    "the A vs B winner stays in its original slot");
  assert.equal(out[0].side, "away");
});

check("a missing probability does not beat a real one", () => {
  const out = dedupeFixtureSides([
    { fixture: "A vs B", side: "home" },
    { fixture: "A vs B", side: "away", poisson_win_prob: "60%" },
  ]);
  assert.equal(out.length, 1);
  assert.equal(out[0].side, "away", "unknown is not treated as high");
});

check("dedupe is safe on empty input and on rows with no fixture", () => {
  assert.deepEqual(dedupeFixtureSides([]), []);
  const out = dedupeFixtureSides([{ side: "home" }, { side: "away" }]);
  assert.equal(out.length, 1, "rows with no fixture name still collapse, not crash");
});

check("dedupe does not mutate its input", () => {
  const input = [
    { fixture: "A vs B", side: "away", poisson_win_prob: "68.58%" },
    { fixture: "A vs B", side: "home", poisson_win_prob: "5.10%" },
  ];
  dedupeFixtureSides(input);
  assert.equal(input.length, 2, "the caller's array is untouched");
});

check("empty and single-row inputs are safe", () => {
  assert.deepEqual(sortGG([]), []);
  assert.deepEqual(sortO25([]), []);
  assert.deepEqual(sortO15([]), []);
  assert.deepEqual(sortU2S([]), []);
  assert.equal(sortGG([{ Fixture: "solo" }]).length, 1);
  assert.equal(sortCornersRefined([{ Fixture: "solo" }], () => false).length, 1);
});

console.log("\n" + passed + " checks passed");

});

check("missing sort keys sink instead of being read as zero", () => {
  const out = sortO15([
    { Fixture: "missing", Grade: "9" },
    { Fixture: "present", "Poisson%": 56, Grade: "5" },
  ]);
  assert.equal(out[0].Fixture, "present");
  assert.equal(out[1].Fixture, "missing", "a row with no Poisson% is not treated as 0");
});

  assert.equal(ggQualifiesSharp(row), false);
});

check("the sharpened tier is a strict subset of the base tier", () => {
  const base = { Base_Marks: GG_BASE_MARKS_MIN, Monte_GG_Prob: GG_MCG_PROB_MIN };
  assert.equal(ggQualifies(base), true, "exactly at threshold qualifies");
  assert.equal(ggQualifiesSharp(base), false, "but not sharpened without data");
  assert.equal(
    ggQualifiesSharp({ ...base, borrowed: { Forensic_Audit: GG_FORENSIC_AUDIT_MAX } }),
    true,
    "exactly at the borrowed bound sharpens",
  );
  assert.equal(
    ggQualifiesSharp({ ...base, borrowed: { Forensic_Audit: GG_FORENSIC_AUDIT_MAX + 1 } }),
    false,
  );
});
