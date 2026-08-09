import type { AxiosResponse } from "axios";
import {
  ggApi,
  winApi,
  over25Api,
  over15Api,
  cornersApi,
  specialsApi,
  underdogApi,
  parseProbability,
} from "@/lib/api";
import {
  Zap,
  Trophy,
  TrendingUp,
  Flame,
  CornerUpRight,
  Scale,
  TrendingDown,
  Crosshair,
  Hourglass,
  TimerReset,
  Swords,
  type LucideIcon,
} from "lucide-react";

// ============================================================
// DASHBOARD MARKET ADAPTERS
// Normalizes each chain's flagship endpoint down to a common
// { fixture, tier?, prob?, score? } shape so the dashboard grid
// and Elite Convergence feed can render all 11 markets generically
// without touching engine math. Assumes each engine already
// returns picks best-first (consistent with the rest of the app).
//
// The 11 markets split into two architectural families:
//   - Tree markets (Win, GG/BTTS, Over 2.5, Over 1.5, Corners,
//     Underdog to Score): Normal -> Psychology/Audit -> Aggregator
//     chain. The fetcher below always points at the top-of-chain
//     aggregator endpoint (the "elite" output), not a mid-chain head.
//   - Single-code specials (Draw, Unders, SOT, FHVI, SHVI): one
//     engine, no psychology/aggregator siblings.
//
// NOTE: the "SH Master" family (sh_gg_winner, sh_master_vortex,
// sh_8goal_aggregator — typed as `shMasterApi` in lib/api.ts) is
// NOT one of the 11 user-facing picks. Per product decision it is
// surfaced as supplementary panels on the dedicated /shvi page,
// not as its own dashboard market card.
// ============================================================

export interface MarketPick {
  fixture: string;
  tier?: string;
  prob?: number;
  score?: number;
}

export interface MarketConfig {
  key: string;
  label: string;
  href: string;
  icon: LucideIcon;
  fetcher: (date: string) => Promise<AxiosResponse<MarketPick[]>>;
}

function mapResponse<T>(
  promise: Promise<AxiosResponse<T>>,
  map: (data: T) => MarketPick[]
): Promise<AxiosResponse<MarketPick[]>> {
  return promise.then((res) => ({ ...res, data: map(res.data) }));
}

// ── Tree markets (Normal -> Psychology/Audit -> Aggregator) ────────────────

export const WIN_MARKET: MarketConfig = {
  key: "win",
  label: "Win",
  href: "/win",
  icon: Trophy,
  fetcher: (date) =>
    mapResponse(winApi.getApex(date), (res) =>
      res.map((p) => ({
        fixture: p.Fixture,
        tier: p.Category,
        prob: p.Monte_Win_Prob,
      }))
    ),
};

export const GG_MARKET: MarketConfig = {
  key: "gg",
  label: "GG / BTTS",
  href: "/gg",
  icon: Zap,
  // Supreme is the top-of-chain VIP aggregator (Category + Monte_GG_Prob) —
  // the actual "elite" output, not the mid-chain precision head.
  fetcher: (date) =>
    mapResponse(ggApi.getSupreme(date), (res) =>
      res.map((p) => ({
        fixture: p.Fixture,
        tier: p.Category,
        prob: p.Monte_GG_Prob,
      }))
    ),
};

export const OVER25_MARKET: MarketConfig = {
  key: "over25",
  label: "Over 2.5",
  href: "/over25",
  icon: TrendingUp,
  fetcher: (date) =>
    mapResponse(over25Api.getApex(date), (res) =>
      res.map((p) => ({
        fixture: p.Fixture,
        tier: p.Category,
        prob: p.Super_Monte_Prob,
      }))
    ),
};

export const OVER15_MARKET: MarketConfig = {
  key: "over15",
  label: "Over 1.5",
  href: "/over15",
  icon: Flame,
  fetcher: (date) =>
    mapResponse(over15Api.getApex(date), (res) =>
      res.map((p) => ({
        fixture: p.Fixture,
        tier: p.Tier,
        prob: parseProbability(p.Base_Poisson),
        score: p.Score,
      }))
    ),
};

export const CORNERS_MARKET: MarketConfig = {
  key: "corners",
  label: "Corners",
  href: "/corners",
  icon: CornerUpRight,
  fetcher: (date) =>
    mapResponse(cornersApi.getAggregator(date), (res) =>
      res.map((p) => ({
        fixture: p.Fixture,
        tier: p.Tier,
        score: p.Master_Score,
      }))
    ),
};

export const UNDERDOG_MARKET: MarketConfig = {
  key: "underdog",
  label: "Underdog to Score",
  href: "/underdog",
  icon: Swords,
  fetcher: (date) =>
    mapResponse(underdogApi.getApex(date), (res) =>
      res.map((p) => ({
        fixture: p.Fixture,
        tier: p.Rank,
        prob: parseProbability(p.Monte_UD_Prob),
      }))
    ),
};

// ── Single-code specials (no psychology/aggregator siblings) ───────────────

export const DRAW_MARKET: MarketConfig = {
  key: "draw",
  label: "Draw",
  href: "/draw",
  icon: Scale,
  fetcher: (date) =>
    mapResponse(specialsApi.getDraw(date), (res) =>
      res.draws.map((p) => ({
        fixture: p.fixture,
        tier: p.tier,
        prob: p.mc_draw_prob * 100,
        score: p.composite_draw_score,
      }))
    ),
};

export const UNDERS_MARKET: MarketConfig = {
  key: "unders",
  label: "Unders",
  href: "/unders",
  icon: TrendingDown,
  fetcher: (date) =>
    mapResponse(specialsApi.getUnders(date), (res) =>
      res.u25.map((p) => ({
        fixture: p.fixture,
        tier: p.u25_tier,
        prob: p.mc_u25_prob != null ? p.mc_u25_prob * 100 : undefined,
        score: p.u25_score,
      }))
    ),
};

export const SOT_MARKET: MarketConfig = {
  key: "sot",
  label: "SOT",
  href: "/sot",
  icon: Crosshair,
  fetcher: (date) =>
    mapResponse(specialsApi.getSOT(date), (res) =>
      res.map((p) => ({
        fixture: p.Fixture,
        tier: p.Verdict,
        prob: parseProbability(p["Poisson_Over_8.5"]),
        score: p.Proj_SOT,
      }))
    ),
};

export const FHVI_MARKET: MarketConfig = {
  key: "fhvi",
  label: "FHVI",
  href: "/fhvi",
  icon: Hourglass,
  fetcher: (date) =>
    mapResponse(specialsApi.getFHVI(date), (res) =>
      res.map((p) => ({
        fixture: p.fixture,
        tier: p.fhvi_label,
        score: p.fhvi_score,
      }))
    ),
};

export const SHVI_MARKET: MarketConfig = {
  key: "shvi",
  label: "SHVI",
  href: "/shvi",
  icon: TimerReset,
  fetcher: (date) =>
    mapResponse(specialsApi.getSHVI(date), (res) =>
      res.map((p) => ({
        fixture: p.fixture,
        tier: p.shvi_label,
        score: p.shvi_score,
      }))
    ),
};

/** Grid render order — must stay in sync with the useApi() calls in app/dashboard/page.tsx. */
export const DASHBOARD_MARKETS: MarketConfig[] = [
  WIN_MARKET,
  GG_MARKET,
  OVER25_MARKET,
  OVER15_MARKET,
  DRAW_MARKET,
  UNDERS_MARKET,
  CORNERS_MARKET,
  SOT_MARKET,
  FHVI_MARKET,
  SHVI_MARKET,
  UNDERDOG_MARKET,
];
