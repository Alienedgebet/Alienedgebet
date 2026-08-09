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
  get: (p: DnaV2Profile) => number;
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

function compareFactor(home: DnaV2Profile, away: DnaV2Profile, def: FactorDef): DnaV2Factor {
  const h = def.get(home);
  const a = def.get(away);
  const winner: DnaV2Factor["winner"] = def.invert
    ? h < a
      ? "home"
      : a < h
        ? "away"
        : "neutral"
    : h > a
      ? "home"
      : a > h
        ? "away"
        : "neutral";
  return {
    name: def.name,
    home_value: Math.round(h * 10) / 10,
    away_value: Math.round(a * 10) / 10,
    winner,
  };
}

function buildMarkets(home: DnaV2Profile, away: DnaV2Profile): Record<DnaV2MarketKey, DnaV2MarketCount> {
  const result = {} as Record<DnaV2MarketKey, DnaV2MarketCount>;
  (Object.keys(MARKET_FACTOR_DEFS) as DnaV2MarketKey[]).forEach((key) => {
    const factors = MARKET_FACTOR_DEFS[key].map((def) => compareFactor(home, away, def));
    result[key] = {
      home_count: factors.filter((f) => f.winner === "home").length,
      away_count: factors.filter((f) => f.winner === "away").length,
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

  const combinedBox = Math.round(((home.Market_Power_Scores.Box_Dominance + away.Market_Power_Scores.Box_Dominance) / 2) * 10) / 10;
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
    market_signals: {
      Over_Under: combinedBox > 65 ? "LEAN OVER" : combinedBox < 45 ? "LEAN UNDER" : "NEUTRAL",
      GG_NoGG: combinedBox > 60 ? "LEAN GG" : "NEUTRAL",
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
