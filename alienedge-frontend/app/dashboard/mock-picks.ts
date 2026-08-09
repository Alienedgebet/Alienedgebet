import type { MarketPick } from "./market-config";

// ============================================================
// DEMO FALLBACK DATA
// Per .cursorrules: "Mock data typed to api.ts interfaces when
// backend unavailable." Used only when a market's live fetch
// errors out or resolves with zero rows — the dashboard never
// silently invents data; every card/row sourced from here is
// tagged with a visible "Demo" badge (see MarketIntelList and
// the Elite Picks feed columns in page.tsx).
//
// Keys match MarketConfig.key for all 11 real markets — see
// market-config.ts for the tree vs. single-code split.
// ============================================================

export const MOCK_PICKS: Record<string, MarketPick[]> = {
  win: [
    { fixture: "Real Madrid vs Alaves", tier: "Category 1", prob: 81.6 },
    { fixture: "Inter vs Salernitana", tier: "Category 1", prob: 76.3 },
    { fixture: "PSG vs Le Havre", tier: "Category 2", prob: 67.9 },
  ],
  gg: [
    { fixture: "Man City vs Arsenal", tier: "Category 1", prob: 78.4 },
    { fixture: "Bayern Munich vs Dortmund", tier: "Category 2", prob: 69.1 },
    { fixture: "Ajax vs PSV", tier: "Category 3", prob: 58.2 },
  ],
  over25: [
    { fixture: "Leverkusen vs Union Berlin", tier: "Category 1", prob: 74.8 },
    { fixture: "Atletico vs Sevilla", tier: "Category 2", prob: 64.5 },
    { fixture: "Benfica vs Porto", tier: "Category 3", prob: 55.1 },
  ],
  over15: [
    { fixture: "Napoli vs Roma", tier: "Tier 1", prob: 88.2, score: 91 },
    { fixture: "Marseille vs Lyon", tier: "Tier 2", prob: 79.4, score: 82 },
  ],
  draw: [
    { fixture: "Juventus vs Milan", tier: "Diamond Lock", prob: 34.2, score: 79 },
    { fixture: "Fenerbahce vs Galatasaray", tier: "Fire Pick", prob: 29.8, score: 71 },
  ],
  unders: [
    { fixture: "Getafe vs Cadiz", tier: "Solid Lean", prob: 71.5, score: 68 },
    { fixture: "Burnley vs Everton", tier: "Playable", prob: 63.2, score: 60 },
  ],
  corners: [
    { fixture: "Newcastle vs Aston Villa", tier: "Tier 1", score: 87 },
    { fixture: "Sevilla vs Villarreal", tier: "Tier 2", score: 74 },
  ],
  sot: [
    { fixture: "Chelsea vs Brentford", tier: "💎 DIAMOND (Stable & High)", prob: 78, score: 10.8 },
    { fixture: "Villarreal vs Girona", tier: "🥈 VALUE PLAY", prob: 61, score: 9.2 },
  ],
  fhvi: [
    { fixture: "Bologna vs Lazio", tier: "🔥 Very explosive FH", score: 11 },
    { fixture: "Betis vs Osasuna", tier: "⚡ Good FH match", score: 8 },
  ],
  shvi: [
    { fixture: "Feyenoord vs AZ Alkmaar", tier: "🔥 Very explosive SH", score: 12 },
    { fixture: "Celtic vs Rangers", tier: "⚡ Good SH match", score: 9 },
  ],
  underdog: [
    { fixture: "Brighton vs Fulham", tier: "Rank 1", prob: 68.5 },
    { fixture: "Valencia vs Alaves", tier: "Rank 2", prob: 54.2 },
  ],
};
