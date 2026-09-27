import assert from "node:assert/strict";
import {
  sortSOT,
  sortCorners,
  sotQualifies,
  cornersQualifies,
  countWounded,
  SOT_CONSISTENCY_MIN,
  SOT_PROJ_MIN,
  CORNERS_U25_MAX,
  CORNERS_MAX_WOUNDED,
} from "../lib/signal-ranking";

let passed = 0;
function check(name: string, fn: () => void) {
  fn();
  passed += 1;
  console.log("  ok  " + name);
}

console.log("signal-ranking");

check("numeric parsing tolerates the engines' string fields", () => {
  assert.equal(sotQualifies({ Consistency: "52%", Proj_SOT: "9.4" }), true);
  assert.equal(sotQualifies({ Consistency: 52, Proj_SOT: 9.4 }), true);
});

check("missing values never qualify (no fabricated zero)", () => {
  assert.equal(sotQualifies({ Consistency: null, Proj_SOT: 12 }), false);
  assert.equal(sotQualifies({ Consistency: 90, Proj_SOT: undefined }), false);
  assert.equal(sotQualifies({ Consistency: "N/A", Proj_SOT: "9.9" }), false);
  assert.equal(sotQualifies({}), false);
});

check("both conditions are required at the documented thresholds", () => {
  const at = (c: number, p: number) => ({ Consistency: c, Proj_SOT: p });
  assert.equal(sotQualifies(at(SOT_CONSISTENCY_MIN, SOT_PROJ_MIN)), true, "exactly at threshold qualifies");
  assert.equal(sotQualifies(at(SOT_CONSISTENCY_MIN - 1, SOT_PROJ_MIN)), false, "just below Consistency fails");
  assert.equal(sotQualifies(at(SOT_CONSISTENCY_MIN, SOT_PROJ_MIN - 0.1)), false, "just below Proj_SOT fails");
});

check("qualifying rows form one contiguous block at the top", () => {
  const rows = [
    { Fixture: "loser-high-proj", Consistency: "10%", Proj_SOT: 14 },
    { Fixture: "qualify-2", Consistency: "60%", Proj_SOT: 9.5 },
    { Fixture: "mid", Consistency: "30%", Proj_SOT: 11 },
    { Fixture: "qualify-1", Consistency: "55%", Proj_SOT: 9.4 },
  ];
  const out = sortSOT(rows);
  assert.deepEqual(
    out.slice(0, 2).map((r) => r.Fixture),
    ["qualify-2", "qualify-1"],
    "a high-projection non-qualifier must not outrank a qualifier",
  );
  assert.equal(sotQualifies(out[0]), true);
  assert.equal(sotQualifies(out[1]), true);
});

check("within each block, order is by Proj_SOT descending", () => {
  const out = sortSOT([
    { Fixture: "a", Consistency: "10%", Proj_SOT: 8 },
    { Fixture: "b", Consistency: "10%", Proj_SOT: 12 },
  ]);
  assert.deepEqual(out.map((r) => r.Fixture), ["b", "a"]);
});

check("input array is not mutated", () => {
  const rows = [
    { Fixture: "a", Consistency: "10%", Proj_SOT: 8 },
    { Fixture: "b", Consistency: "60%", Proj_SOT: 9.4 },
  ];
  const copy = [...rows];
  sortSOT(rows);
  assert.deepEqual(rows, copy, "sortSOT must not sort in place");
});

check("corners sort is by Total_Exp descending, nulls last", () => {
  const out = sortCorners([
    { Fixture: "mid", Total_Exp: "9", "U2.5%": "90", Home_Wounded: "🩸 YES", Away_Wounded: "🩸 YES" },
    { Fixture: "high", Total_Exp: "13.11", "U2.5%": "90", Home_Wounded: "🩸 YES", Away_Wounded: "🩸 YES" },
    { Fixture: "none", Total_Exp: null, "U2.5%": "90", Home_Wounded: "🩸 YES", Away_Wounded: "🩸 YES" },
    { Fixture: "junk", Total_Exp: "N/A", "U2.5%": "90", Home_Wounded: "🩸 YES", Away_Wounded: "🩸 YES" },
    { Fixture: "low", Total_Exp: "5.2", "U2.5%": "90", Home_Wounded: "🩸 YES", Away_Wounded: "🩸 YES" },
  ]);
  assert.deepEqual(
    out.map((r) => r.Fixture),
    ["high", "mid", "low", "none", "junk"],
  );
});

check("wounded count reads the engine's decorated flags", () => {
  assert.equal(countWounded({ Home_Wounded: "🩸 YES", Away_Wounded: "❌ NO" }), 1);
  assert.equal(countWounded({ Home_Wounded: "🩸 YES", Away_Wounded: "🩸 YES" }), 2);
  assert.equal(countWounded({ Home_Wounded: "❌ NO", Away_Wounded: "❌ NO" }), 0);
});

check("an ABSENT injury flag is unknown, not 'healthy'", () => {
  // Reading a missing flag as healthy would let matches with no injury data
  // pass the wounded-side test on false information.
  assert.equal(countWounded({ Home_Wounded: "🩸 YES", Away_Wounded: null }), null);
  assert.equal(countWounded({ Home_Wounded: undefined, Away_Wounded: "❌ NO" }), null);
  assert.equal(countWounded({ Home_Wounded: "", Away_Wounded: "❌ NO" }), null);
  assert.equal(cornersQualifies({ "U2.5%": "20", Home_Wounded: "🩸 YES", Away_Wounded: null }), false);
});

check("corners rule honours the documented thresholds", () => {
  const row = (u25: string, hw: string, aw: string) => ({
    "U2.5%": u25, Home_Wounded: hw, Away_Wounded: aw,
  });
  assert.equal(cornersQualifies(row(String(CORNERS_U25_MAX), "🩸 YES", "❌ NO")), true, "at threshold, one wounded side qualifies");
  assert.equal(cornersQualifies(row(String(CORNERS_U25_MAX), "🩸 YES", "🩸 YES")), false, "two wounded sides fails");
  assert.equal(cornersQualifies(row("95", "❌ NO", "❌ NO")), false, "high U2.5% fails");
  assert.equal(
    cornersQualifies(row(String(CORNERS_U25_MAX + 0.1), "❌ NO", "❌ NO")),
    false,
    "just above the U2.5 cut fails",
  );
  assert.equal(cornersQualifies({ "U2.5%": "N/A", Home_Wounded: "❌ NO", Away_Wounded: "❌ NO" }), false);
});

check("corners qualifying rows form one contiguous block at the top", () => {
  const out = sortCorners([
    { Fixture: "huge-proj-nonqual", Total_Exp: "30", "U2.5%": "88", Home_Wounded: "🩸 YES", Away_Wounded: "🩸 YES" },
    { Fixture: "qualify", Total_Exp: "8", "U2.5%": "30", Home_Wounded: "❌ NO", Away_Wounded: "❌ NO" },
    { Fixture: "other-nonqual", Total_Exp: "20", "U2.5%": "77", Home_Wounded: "🩸 YES", Away_Wounded: "🩸 YES" },
  ]);
  assert.equal(out[0].Fixture, "qualify", "a huge projection must not outrank a qualifier");
  assert.equal(out.length, 3, "no row is ever filtered out");
});

check("empty and single-row inputs are safe", () => {
  assert.deepEqual(sortSOT([]), []);
  assert.deepEqual(sortCorners([]), []);
  const one = [{ Fixture: "solo", Total_Exp: "9" }];
  assert.equal(sortCorners(one).length, 1);
});

console.log("\n" + passed + " checks passed");
