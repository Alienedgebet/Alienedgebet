"use client";

import { Suspense, useEffect, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useSelectedDate } from "@/lib/date-context";
import { useApi, type UseApiResult } from "@/lib/use-api";
import { useDnaV2 } from "@/lib/use-dna-v2";
import { getTierClass, type DnaV2MarketKey } from "@/lib/api";
import { isDashboardMarketTab } from "@/lib/dashboard-tabs";
import { RadialGauge } from "@/components/predictions/RadialGauge";
import { EngineFeedBar } from "./EngineFeedBar";
import { HeroCarousel } from "./HeroCarousel";
import { AIMarketAssessment } from "./AIMarketAssessment";
import {
  DASHBOARD_MARKETS,
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
  type MarketPick,
} from "./market-config";
import { MOCK_PICKS } from "./mock-picks";
import { EliteRankList, type EliteRankItem } from "./EliteRankList";
import { EngineStatusList } from "./EngineStatusList";
import { LiveMonitorPanel } from "./LiveMonitorPanel";
import { MarketIntelList } from "./MarketIntelList";

/**
 * Keep rows on screen during fetch. Prefer live data; otherwise seeded mock
 * from useApi fallback. Never return null once a market has anything to show.
 */
function withFallback(
  key: string,
  result: UseApiResult<MarketPick[]>
): { data: MarketPick[]; isMock: boolean } {
  const hasData = (result.data?.length ?? 0) > 0;
  if (hasData) {
    return { data: result.data!, isMock: result.isMock };
  }
  const mock = MOCK_PICKS[key] ?? [];
  return { data: mock, isMock: true };
}

/** Only these 7 of the 11 dashboard markets are covered by DNA Engine V2. */
const DNA_SUPPORTED_MARKET_KEYS = new Set<string>([
  "win",
  "gg",
  "over25",
  "over15",
  "unders",
  "draw",
  "corners",
]);

function DashboardOverview() {
  const { date } = useSelectedDate();
  const { data: dnaV2 } = useDnaV2();

  // Cache key = dashboard + market key + date. Means: leave the dashboard,
  // come back within the TTL window → instant paint from cache instead of
  // re-running all 11 requests (same contract as ChainStage on market pages).
  const win = useApi(() => WIN_MARKET.fetcher(date), [date], {
    fallback: MOCK_PICKS.win,
    cacheKey: `dashboard-win:${date}`,
  });
  const gg = useApi(() => GG_MARKET.fetcher(date), [date], {
    fallback: MOCK_PICKS.gg,
    cacheKey: `dashboard-gg:${date}`,
  });
  const over25 = useApi(() => OVER25_MARKET.fetcher(date), [date], {
    fallback: MOCK_PICKS.over25,
    cacheKey: `dashboard-over25:${date}`,
  });
  const over15 = useApi(() => OVER15_MARKET.fetcher(date), [date], {
    fallback: MOCK_PICKS.over15,
    cacheKey: `dashboard-over15:${date}`,
  });
  const draw = useApi(() => DRAW_MARKET.fetcher(date), [date], {
    fallback: MOCK_PICKS.draw,
    cacheKey: `dashboard-draw:${date}`,
  });
  const unders = useApi(() => UNDERS_MARKET.fetcher(date), [date], {
    fallback: MOCK_PICKS.unders,
    cacheKey: `dashboard-unders:${date}`,
  });
  const corners = useApi(() => CORNERS_MARKET.fetcher(date), [date], {
    fallback: MOCK_PICKS.corners,
    cacheKey: `dashboard-corners:${date}`,
  });
  const sot = useApi(() => SOT_MARKET.fetcher(date), [date], {
    fallback: MOCK_PICKS.sot,
    cacheKey: `dashboard-sot:${date}`,
  });
  const fhvi = useApi(() => FHVI_MARKET.fetcher(date), [date], {
    fallback: MOCK_PICKS.fhvi,
    cacheKey: `dashboard-fhvi:${date}`,
  });
  const shvi = useApi(() => SHVI_MARKET.fetcher(date), [date], {
    fallback: MOCK_PICKS.shvi,
    cacheKey: `dashboard-shvi:${date}`,
  });
  const underdog = useApi(() => UNDERDOG_MARKET.fetcher(date), [date], {
    fallback: MOCK_PICKS.underdog,
    cacheKey: `dashboard-underdog:${date}`,
  });

  const rawResults = [
    win,
    gg,
    over25,
    over15,
    draw,
    unders,
    corners,
    sot,
    fhvi,
    shvi,
    underdog,
  ];

  const marketRows = DASHBOARD_MARKETS.map((config, i) => ({
    config,
    loading: rawResults[i].loading,
    isRefetching: rawResults[i].isRefetching,
    ...withFallback(config.key, rawResults[i]),
  }));

  const totalScanned = marketRows.reduce(
    (sum, m) => sum + (m.data?.length ?? 0),
    0
  );

  const allElite = useMemo(() => {
    const items: EliteRankItem[] = [];
    DASHBOARD_MARKETS.forEach((config, i) => {
      const { data, isMock } = withFallback(config.key, rawResults[i]);
      for (const pick of data) {
        if (!pick.tier) continue;
        const cls = getTierClass(pick.tier);
        if (cls !== "tier-diamond" && cls !== "tier-fire") continue;
        const value = pick.prob ?? pick.score;
        if (value == null) continue;
        items.push({
          key: `${config.key}-${pick.fixture}`,
          rank: 0,
          fixture: pick.fixture,
          market: config.label,
          href: config.href,
          tier: pick.tier,
          value,
          suffix: pick.prob != null ? "%" : "/100",
          isMock,
          odds: pick.odds,
          dnaMarketKey: DNA_SUPPORTED_MARKET_KEYS.has(config.key)
            ? (config.key as DnaV2MarketKey)
            : undefined,
        });
      }
    });
    items.sort((a, b) => b.value - a.value);
    items.forEach((item, i) => (item.rank = i + 1));
    return items;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    win.data,
    win.loading,
    win.isMock,
    gg.data,
    gg.loading,
    gg.isMock,
    over25.data,
    over25.loading,
    over25.isMock,
    over15.data,
    over15.loading,
    over15.isMock,
    draw.data,
    draw.loading,
    draw.isMock,
    unders.data,
    unders.loading,
    unders.isMock,
    corners.data,
    corners.loading,
    corners.isMock,
    sot.data,
    sot.loading,
    sot.isMock,
    fhvi.data,
    fhvi.loading,
    fhvi.isMock,
    shvi.data,
    shvi.loading,
    shvi.isMock,
    underdog.data,
    underdog.loading,
    underdog.isMock,
  ]);

  const peakConfidence = allElite[0]?.value ?? 0;
  const enginesOnline = rawResults.filter((r) => r.error === null).length;

  return (
    <div className="relative flex flex-col gap-4 p-6">
      <div className="pointer-events-none absolute inset-0 -z-10 bg-hero-glow" />

      <EngineFeedBar
        totalScanned={totalScanned}
        eliteCount={allElite.length}
        enginesOnline={enginesOnline}
        enginesTotal={DASHBOARD_MARKETS.length}
        peakConfidence={peakConfidence}
      />

      <HeroCarousel
        peakConfidence={peakConfidence}
        scrollTargetId="elite-picks"
      />

      <LiveMonitorPanel />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div id="elite-picks" className="lg:col-span-2">
          <EliteRankList
            items={allElite}
            emptyMessage="No elite-tier picks yet for this date."
            marketFactors={dnaV2?.market_factors}
            date={date}
          />
        </div>

        <div className="flex flex-col gap-4">
          <div className="glass flex items-center justify-center gap-4 rounded-lg p-4 shadow-panel">
            <RadialGauge value={peakConfidence} label="Peak Confidence" />
            <div className="flex flex-col gap-1 text-2xs text-text-muted">
              <p>
                Strongest signal across every market today, drawn live from each
                engine&apos;s top-of-chain output.
              </p>
            </div>
          </div>

          <EngineStatusList rows={marketRows} />
        </div>
      </div>

      <MarketIntelList rows={marketRows} />

      <AIMarketAssessment />
    </div>
  );
}

/** Old /dashboard?tab=<market> bookmarks → dedicated market routes. */
function LegacyTabRedirect() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tab = searchParams.get("tab");

  useEffect(() => {
    if (tab && isDashboardMarketTab(tab)) {
      router.replace(`/${tab}`);
    }
  }, [tab, router]);

  return null;
}

export default function DashboardPage() {
  return (
    <>
      {/* searchParams Suspense must NOT wrap the command center — that caused
          a blank "Loading…" flash on every sidebar click into /dashboard. */}
      <Suspense fallback={null}>
        <LegacyTabRedirect />
      </Suspense>
      <DashboardOverview />
    </>
  );
}
