/**
 * Typed demo payload for DNA Engine V2 — same contract as lib/mock-chains.ts.
 * Used only when /api/dna/v2/latest is unreachable (e.g. this frontend is
 * deployed on Vercel but the Python backend isn't hosted publicly, or is
 * only running on a local machine). Every DNA badge/page rendered from this
 * data is a deterministic, clearly-fake demo dataset — it never claims to
 * be real DNA output, and it mirrors the exact response shape the real
 * /api/dna/v2/* endpoints return so swapping in live data later requires
 * zero frontend changes.
 *
 * Fixture ids/names are intentionally aligned with lib/mock-chains.ts and
 * app/dashboard/mock-picks.ts so the DNA badge lights up on every page's
 * existing demo rows instead of showing "–" everywhere when the API is down.
 */
import type {
  DnaV2Clash,
  DnaV2Factor,
  DnaV2FixtureFactors,
  DnaV2MarketCount,
  DnaV2MarketKey,
  DnaV2Profile,
  DnaV2Response,
} from "@/lib/api";

// ── Deterministic per-team profile generator ────────────────────────────────
// Same team name always yields the same numbers (stable across re-renders/
// deploys), without hand-typing ~25 full profile objects.

function hashName(name: string): number {
  let h = 0;
  for (let i = 0; i < name.length; i++) {
    h = (h * 31 + name.charCodeAt(i)) & 0x7fffffff;
  }
  return h || 1;
}

function seededRandom(seed: number): () => number {
  let s = seed;
  return () => {
    s = (s * 1103515245 + 12345) & 0x7fffffff;
    return s / 0x7fffffff;
  };
}

const ARCHETYPES = [
  "Elite Dominator (WIN/OVER)",
  "Balanced",
  "Box Predator (OVER/GG)",
  "High-Friction Chaos (GG/OVER)",
  "Possession Controller (DRAW/UNDER)",
];
const LINE_HEIGHTS = ["High", "Medium", "Low"] as const;
const SHOT_QUALITIES = ["Elite Box Threat", "Balanced Attacker", "Long Range Dependent"] as const;
const TRANSITION_STYLES = ["High Press / Fast Transition", "Structured Recovery", "Passive / Reactive"] as const;

const profileCache = new Map<string, DnaV2Profile>();

function buildProfile(name: string): DnaV2Profile {
  const cached = profileCache.get(name);
  if (cached) return cached;

  const rand = seededRandom(hashName(name));
  const pick = <T,>(arr: readonly T[]): T => arr[Math.floor(rand() * arr.length)];
  const range = (min: number, max: number) => Math.round((min + rand() * (max - min)) * 10) / 10;

  const profile: DnaV2Profile = {
    team_name: name,
    Archetype: pick(ARCHETYPES),
    Market_Power_Scores: {
      Corner_Power: range(40, 90),
      Goal_Intent: range(40, 95),
      BTTS_Friction: range(30, 85),
      Win_Dominance: range(35, 92),
      Box_Dominance: range(35, 90),
    },
    Tactical_DNA: {
      Tempo: range(35, 88),
      Line_Height: pick(LINE_HEIGHTS),
      Risk_Appetite: rand() > 0.5 ? "High" : "Low",
      Verticality: rand() > 0.5 ? "Direct" : "Horizontal",
      Shot_Quality: pick(SHOT_QUALITIES),
      Transition_Style: pick(TRANSITION_STYLES),
      Transition_Score: range(30, 90),
    },
    Raw_Audit_Metrics: {
      Avg_Corners: range(3.5, 7.5),
      Estimated_Crosses: range(12, 26),
      Estimated_Blocks: range(2, 6),
      Dangerous_Attacks: range(28, 62),
      Passing_Control: range(65, 90),
      Big_Chances_Created: range(0.8, 3.4),
      Shots_Insidebox: range(3.5, 9.5),
      Shots_Outsidebox: range(2, 6.5),
      Inside_Shot_Ratio_Pct: range(45, 82),
      Tackles_Avg: range(12, 22),
      Interceptions_Avg: range(8, 16),
      Own_Pass_Quality_Pct: range(68, 91),
      Opp_Pass_Acc_Allowed: range(65, 85),
      Opp_Dangerous_Attacks: range(24, 50),
      Resistance_Score: range(35, 88),
    },
  };

  profileCache.set(name, profile);
  return profile;
}

// ── Market factor definitions — mirrors CORE/dna_v2_market_factors.py ──────

interface FactorDef {
  name: string;
  /**
   * May return null. Schema v3 lets any stat be "never measured", so the mock
   * must be able to model that too — a getter typed as plain `number` cannot
   * represent a data gap and would quietly paper over it.
   */
  get: (p: DnaV2Profile) => number | null;
  invert?: boolean;
}

const MARKET_FACTOR_DEFS: Record<DnaV2MarketKey, FactorDef[]> = {
  win: [
    { name: "Win Dominance", get: (p) => p.Market_Power_Scores.Win_Dominance },
    { name: "Resistance", get: (p) => p.Raw_Audit_Metrics.Resistance_Score },
    { name: "Passing Control", get: (p) => p.Raw_Audit_Metrics.Passing_Control },
    { name: "Own Pass Quality", get: (p) => p.Raw_Audit_Metrics.Own_Pass_Quality_Pct },
    { name: "Tackles", get: (p) => p.Raw_Audit_Metrics.Tackles_Avg },
    { name: "Interceptions", get: (p) => p.Raw_Audit_Metrics.Interceptions_Avg },
    { name: "Tempo", get: (p) => p.Tactical_DNA.Tempo },
    { name: "Transition", get: (p) => p.Tactical_DNA.Transition_Score },
  ],
  gg: [
    { name: "BTTS Friction", get: (p) => p.Market_Power_Scores.BTTS_Friction },
    { name: "Goal Intent", get: (p) => p.Market_Power_Scores.Goal_Intent },
    { name: "Box Dominance", get: (p) => p.Market_Power_Scores.Box_Dominance },
    { name: "Big Chances Created", get: (p) => p.Raw_Audit_Metrics.Big_Chances_Created },
    { name: "Shots Insidebox", get: (p) => p.Raw_Audit_Metrics.Shots_Insidebox },
    { name: "Dangerous Attacks", get: (p) => p.Raw_Audit_Metrics.Dangerous_Attacks },
  ],
  over25: [
    { name: "Goal Intent", get: (p) => p.Market_Power_Scores.Goal_Intent },
    { name: "Box Dominance", get: (p) => p.Market_Power_Scores.Box_Dominance },
    { name: "Big Chances Created", get: (p) => p.Raw_Audit_Metrics.Big_Chances_Created },
    { name: "Shots Insidebox", get: (p) => p.Raw_Audit_Metrics.Shots_Insidebox },
    { name: "Dangerous Attacks", get: (p) => p.Raw_Audit_Metrics.Dangerous_Attacks },
    { name: "Inside Shot Ratio", get: (p) => p.Raw_Audit_Metrics.Inside_Shot_Ratio_Pct },
  ],
  over15: [
    { name: "Goal Intent", get: (p) => p.Market_Power_Scores.Goal_Intent },
    { name: "Box Dominance", get: (p) => p.Market_Power_Scores.Box_Dominance },
    { name: "Big Chances Created", get: (p) => p.Raw_Audit_Metrics.Big_Chances_Created },
    { name: "Shots Insidebox", get: (p) => p.Raw_Audit_Metrics.Shots_Insidebox },
    { name: "Dangerous Attacks", get: (p) => p.Raw_Audit_Metrics.Dangerous_Attacks },
    { name: "Inside Shot Ratio", get: (p) => p.Raw_Audit_Metrics.Inside_Shot_Ratio_Pct },
  ],
  unders: [
    { name: "Resistance", get: (p) => p.Raw_Audit_Metrics.Resistance_Score },
    { name: "Win Dominance", get: (p) => p.Market_Power_Scores.Win_Dominance },
    { name: "Interceptions", get: (p) => p.Raw_Audit_Metrics.Interceptions_Avg },
    { name: "Tackles", get: (p) => p.Raw_Audit_Metrics.Tackles_Avg },
    { name: "Own Pass Quality", get: (p) => p.Raw_Audit_Metrics.Own_Pass_Quality_Pct },
    { name: "BTTS Friction", get: (p) => p.Market_Power_Scores.BTTS_Friction, invert: true },
  ],
  draw: [
    { name: "Win Dominance", get: (p) => p.Market_Power_Scores.Win_Dominance },
    { name: "BTTS Friction", get: (p) => p.Market_Power_Scores.BTTS_Friction },
    { name: "Tempo", get: (p) => p.Tactical_DNA.Tempo },
    { name: "Passing Control", get: (p) => p.Raw_Audit_Metrics.Passing_Control },
    { name: "Resistance", get: (p) => p.Raw_Audit_Metrics.Resistance_Score },
  ],
  corners: [
    { name: "Corner Power", get: (p) => p.Market_Power_Scores.Corner_Power },
    { name: "Avg Corners", get: (p) => p.Raw_Audit_Metrics.Avg_Corners },
    { name: "Estimated Crosses", get: (p) => p.Raw_Audit_Metrics.Estimated_Crosses },
    { name: "Estimated Blocks", get: (p) => p.Raw_Audit_Metrics.Estimated_Blocks },
  ],
};

// Schema v4: the same 95% noise floors as CORE/dna_v2_market_factors.py.
// Kept in sync deliberately — a demo page that awarded factors on sub-noise
// gaps would misrepresent what the real engine now does.
const MIN_MARGIN: Record<string, number> = {
  "Win Dominance": 7.2,
  "Corner Power": 5.0,
  "BTTS Friction": 5.0,
  "Passing Control": 5.05,
  Tackles: 4.14,
  Interceptions: 2.92,
  Tempo: 4.14,
  Transition: 10.8,
  "Avg Corners": 2.25,
  "Estimated Crosses": 2.0,
  "Estimated Blocks": 2.0,
  "Big Chances Created": 1.25,
  "Shots Insidebox": 2.94,
  "Goal Intent": 5.0,
  "Box Dominance": 5.0,
};

function compareFactor(home: DnaV2Profile, away: DnaV2Profile, def: FactorDef): DnaV2Factor {
  const h = def.get(home);
  const a = def.get(away);

  // Mirrors CORE/dna_v2_market_factors.py: an unknown value on either side
  // makes the factor undecided and awards it to nobody. It is never coerced
  // to 0, which is precisely the behaviour that produced phantom factor wins.
  const floor = MIN_MARGIN[def.name] ?? 0;
  if (h === null || a === null) {
    return {
      name: def.name,
      home_value: h === null ? null : Math.round(h * 10) / 10,
      away_value: a === null ? null : Math.round(a * 10) / 10,
      winner: "unknown",
      difference: null,
      min_margin: floor,
      reason: "unmeasured",
    };
  }

  // A gap smaller than the noise floor is "undecided", not a win. Same rule,
  // same reason: `h > a` awarded the factor on any gap at all.
  const signed = def.invert ? a - h : h - a;
  const difference = Math.abs(signed);
  if (difference < floor) {
    return {
      name: def.name,
      home_value: Math.round(h * 10) / 10,
      away_value: Math.round(a * 10) / 10,
      winner: "undecided",
      difference: Math.round(difference * 10) / 10,
      min_margin: floor,
      reason: "within_noise",
    };
  }

  return {
    name: def.name,
    home_value: Math.round(h * 10) / 10,
    away_value: Math.round(a * 10) / 10,
    winner: signed > 0 ? "home" : "away",
    difference: Math.round(difference * 10) / 10,
    min_margin: floor,
    reason: "decided",
  };
}

function buildMarkets(home: DnaV2Profile, away: DnaV2Profile): Record<DnaV2MarketKey, DnaV2MarketCount> {
  const result = {} as Record<DnaV2MarketKey, DnaV2MarketCount>;
  (Object.keys(MARKET_FACTOR_DEFS) as DnaV2MarketKey[]).forEach((key) => {
    const factors = MARKET_FACTOR_DEFS[key].map((def) => compareFactor(home, away, def));
    const unknownCount = factors.filter((f) => f.winner === "unknown").length;
    const undecidedCount = factors.filter((f) => f.winner === "undecided").length;
    const homeCount = factors.filter((f) => f.winner === "home").length;
    const awayCount = factors.filter((f) => f.winner === "away").length;
    result[key] = {
      home_count: homeCount,
      away_count: awayCount,
      unknown_count: unknownCount,
      undecided_count: undecidedCount,
      decided_count: homeCount + awayCount,
      comparable_count: factors.length - unknownCount,
      factors,
    };
  });
  return result;
}

const CLASH_PILLARS = ["Corner_Power", "Goal_Intent", "BTTS_Friction", "Win_Dominance", "Box_Dominance"] as const;

function buildClash(fixtureId: string, home: DnaV2Profile, away: DnaV2Profile): DnaV2Clash {
  const pillarClash = {} as DnaV2Clash["pillar_clash"];
  let homeEdges = 0;
  let awayEdges = 0;

  CLASH_PILLARS.forEach((pillar) => {
    const h = home.Market_Power_Scores[pillar];
    const a = away.Market_Power_Scores[pillar];

    // Schema v3: a pillar can be unmeasurable. It is recorded as "Unknown" and
    // scores for neither side rather than being treated as a 0.
    if (h === null || a === null) {
      pillarClash[pillar] = {
        home_score: h,
        away_score: a,
        difference: null,
        edge: "Unknown",
        margin: "Unknown",
      };
      return;
    }

    const diff = Math.round((h - a) * 10) / 10;
    const edge = diff > 5 ? home.team_name : diff < -5 ? away.team_name : "Neutral";
    if (diff > 5) homeEdges += 1;
    if (diff < -5) awayEdges += 1;
    pillarClash[pillar] = {
      home_score: h,
      away_score: a,
      difference: diff,
      edge,
      margin: Math.abs(diff) > 5 ? "Clear" : "Tight",
    };
  });

  // Schema v4: Box_Dominance is nullable (unknown, not zero). Averaging with a
  // null would coerce it to 0 and invent a combined figure out of an
  // unmeasured pillar, so an unmeasured side yields null here — mirroring
  // `_mean2` in the engine.
  const meanNullable = (a: number | null, b: number | null): number | null =>
    a == null || b == null ? null : Math.round(((a + b) / 2) * 10) / 10;

  const combinedBox = meanNullable(
    home.Market_Power_Scores.Box_Dominance,
    away.Market_Power_Scores.Box_Dominance
  );
  const combinedGoal = Math.round(((home.Market_Power_Scores.Goal_Intent + away.Market_Power_Scores.Goal_Intent) / 2) * 10) / 10;

  return {
    fixture: `${home.team_name} vs ${away.team_name}`,
    home_team: home.team_name,
    away_team: away.team_name,
    fixture_id: fixtureId,
    fixture_date: "demo",
    pillar_clash: pillarClash,
    home_pillar_edges: homeEdges,
    away_pillar_edges: awayEdges,
    overall_structural_edge:
      homeEdges > awayEdges + 1 ? home.team_name : awayEdges > homeEdges + 1 ? away.team_name : "Contested",
    combined_box_dominance: combinedBox,
    combined_goal_intent: combinedGoal,
    // An unmeasured combined Box Dominance yields UNKNOWN, mirroring the
    // engine's `_cmp_signal`. Deciding "LEAN OVER" from a null would invent a
    // directional lean out of missing data.
    market_signals: {
      Over_Under:
        combinedBox == null
          ? "UNKNOWN"
          : combinedBox > 65
            ? "LEAN OVER"
            : combinedBox < 45
              ? "LEAN UNDER"
              : "NEUTRAL",
      GG_NoGG: combinedBox == null ? "UNKNOWN" : combinedBox > 60 ? "LEAN GG" : "NEUTRAL",
      Corners: home.Market_Power_Scores.Corner_Power > 70 || away.Market_Power_Scores.Corner_Power > 70 ? "HIGH CORNERS" : "AVERAGE",
    },
  };
}

// ── Demo fixture roster ──────────────────────────────────────────────────
// Ids/names mirror lib/mock-chains.ts and app/dashboard/mock-picks.ts so
// the DNA badge lights up on the existing demo rows across every page.

const DEMO_FIXTURES: Array<{ id: string; home: string; away: string }> = [
  { id: "demo-w1", home: "Real Madrid", away: "Alaves" },
  { id: "demo-w2", home: "Liverpool", away: "Burnley" },
  { id: "demo-w3", home: "Bayer Leverkusen", away: "Augsburg" },
  { id: "demo-w4", home: "Inter", away: "Salernitana" },
  { id: "demo-w5", home: "PSG", away: "Le Havre" },
  { id: "demo-gg1", home: "Man City", away: "Arsenal" },
  { id: "demo-gg2", home: "Bayern Munich", away: "Dortmund" },
  { id: "demo-gg3", home: "Ajax", away: "PSV" },
  { id: "demo-o25a", home: "Leverkusen", away: "Union Berlin" },
  { id: "demo-o25b", home: "Ajax", away: "Feyenoord" },
  { id: "demo-o25c", home: "Celtic", away: "Rangers" },
  { id: "demo-o25d", home: "Atletico", away: "Sevilla" },
  { id: "demo-o25e", home: "Benfica", away: "Porto" },
  { id: "demo-o15p1", home: "Napoli", away: "Roma" },
  { id: "demo-o15p2", home: "PSG", away: "Lyon" },
  { id: "demo-o15p3", home: "Marseille", away: "Lyon" },
  { id: "demo-u1", home: "Getafe", away: "Cadiz" },
  { id: "demo-u2", home: "Burnley", away: "Everton" },
  { id: "demo-u3", home: "Metz", away: "Clermont" },
  { id: "demo-u35-1", home: "Getafe", away: "Cadiz" },
  { id: "demo-u35-2", home: "Burnley", away: "Everton" },
  { id: "demo-u35-3", home: "Udinese", away: "Empoli" },
  { id: "demo-d1", home: "Juventus", away: "Milan" },
  { id: "demo-d2", home: "Fenerbahce", away: "Galatasaray" },
  { id: "demo-c-agg1", home: "Newcastle", away: "Aston Villa" },
  { id: "demo-c-agg2", home: "Sevilla", away: "Villarreal" },
];

const dnaProfiles: Record<string, DnaV2Profile> = {};
const fixtureClashes: DnaV2Clash[] = [];
const marketFactors: Record<string, DnaV2FixtureFactors> = {};

DEMO_FIXTURES.forEach(({ id, home, away }, index) => {
  const homeProfile = buildProfile(home);
  const awayProfile = buildProfile(away);

  dnaProfiles[`demo-team-${index}-home`] = homeProfile;
  dnaProfiles[`demo-team-${index}-away`] = awayProfile;

  fixtureClashes.push(buildClash(id, homeProfile, awayProfile));

  marketFactors[id] = {
    fixture_id: id,
    fixture: `${home} vs ${away}`,
    home_team: home,
    away_team: away,
    markets: buildMarkets(homeProfile, awayProfile),
  };
});

export const MOCK_DNA_V2: DnaV2Response = {
  dna_profiles: dnaProfiles,
  fixture_clashes: fixtureClashes,
  market_factors: marketFactors,
};
