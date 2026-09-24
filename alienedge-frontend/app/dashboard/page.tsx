"use client";

import { Suspense, useEffect, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useSelectedDate } from "@/lib/date-context";
import { useApi, DEMO_MODE_ENABLED, type UseApiResult } from "@/lib/use-api";
import { useDnaV2 } from "@/lib/use-dna-v2";
import { marketCacheKey, type DnaV2MarketKey } from "@/lib/api";
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
  UNDERDOG_2_SOURCE,
  OVER15_INTELLIGENCE_SOURCE,
  OVER25_JUDGES_SOURCE,
  ELITE_PICK_SOURCES,
  selectTopSourceRows,
  type MarketPick,
} from "./market-config";
import { MOCK_PICKS } from "./mock-picks";
import { EliteRankList, type EliteRankItem } from "./EliteRankList";
import { EngineStatusList } from "./EngineStatusList";
import { LiveMonitorPanel } from "./LiveMonitorPanel";
import { MarketIntelList } from "./MarketIntelList";

function withFallback(
  key: string,
  result: UseApiResult<MarketPick[]>
): { data: MarketPick[]; isMock: boolean } {
  const hasData = (result.data?.length ?? 0) > 0;
  if (hasData) {
    return { data: result.data!, isMock: result.isMock };
  }
  if (DEMO_MODE_ENABLED) {
    // D. Demo explicitly enabled → demo rows, clearly flagged.
    const mock = MOCK_PICKS[key] ?? [];
    return { data: mock, isMock: true };
  }
  // B/C. Real empty or API failure — NEVER substitute fake picks
  // automatically. The empty/error states below handle both honestly.
  return { data: [], isMock: false };
}

const ELITE_DNA_MARKET_KEYS: Partial<Record<string, DnaV2MarketKey>> = {
  corner_intelligence: "corners",
  over15_intelligence: "over15",
};

function DashboardOverview() {
  const { date } = useSelectedDate();
  const { data: dnaV2 } = useDnaV2();

  // 60s auto-refresh: verdicts (PENDING → IN_PLAY → WON/LOST) must appear
  // without a manual re-navigation. Cheap for the API — market reads for an
  // archived date never touch SportMonks, and the in-play feed fetch is
  // shared and disk-cached (2-min TTL) behind all twelve endpoints.
  const REFRESH_MS = 60_000;

  const win = useApi(() => WIN_MARKET.fetcher(date), [date], {
    fallback: MOCK_PICKS.win,
    cacheKey: marketCacheKey(WIN_MARKET.key, date),
    refreshMs: REFRESH_MS,
  });
  const gg = useApi(() => GG_MARKET.fetcher(date), [date], {
    fallback: MOCK_PICKS.gg,
    cacheKey: marketCacheKey(GG_MARKET.key, date),
    refreshMs: REFRESH_MS,
  });
  const over25 = useApi(() => OVER25_MARKET.fetcher(date), [date], {
    fallback: MOCK_PICKS.over25,
    cacheKey: marketCacheKey(OVER25_MARKET.key, date),
    refreshMs: REFRESH_MS,
  });
  const over15 = useApi(() => OVER15_MARKET.fetcher(date), [date], {
    fallback: MOCK_PICKS.over15,
    cacheKey: marketCacheKey(OVER15_MARKET.key, date),
    refreshMs: REFRESH_MS,
  });
  const draw = useApi(() => DRAW_MARKET.fetcher(date), [date], {
    fallback: MOCK_PICKS.draw,
    cacheKey: marketCacheKey(DRAW_MARKET.key, date),
    refreshMs: REFRESH_MS,
  });
  const unders = useApi(() => UNDERS_MARKET.fetcher(date), [date], {
    fallback: MOCK_PICKS.unders,
    cacheKey: marketCacheKey(UNDERS_MARKET.key, date),
    refreshMs: REFRESH_MS,
  });
  const corners = useApi(() => CORNERS_MARKET.fetcher(date), [date], {
    fallback: MOCK_PICKS.corners,
    cacheKey: marketCacheKey(CORNERS_MARKET.key, date),
    refreshMs: REFRESH_MS,
  });
  const sot = useApi(() => SOT_MARKET.fetcher(date), [date], {
    fallback: MOCK_PICKS.sot,
    cacheKey: marketCacheKey(SOT_MARKET.key, date),
    refreshMs: REFRESH_MS,
  });
  const fhvi = useApi(() => FHVI_MARKET.fetcher(date), [date], {
    fallback: MOCK_PICKS.fhvi,
    cacheKey: marketCacheKey(FHVI_MARKET.key, date),
    refreshMs: REFRESH_MS,
  });
  const shvi = useApi(() => SHVI_MARKET.fetcher(date), [date], {
    fallback: MOCK_PICKS.shvi,
    cacheKey: marketCacheKey(SHVI_MARKET.key, date),
    refreshMs: REFRESH_MS,
  });
  const underdog = useApi(() => UNDERDOG_MARKET.fetcher(date), [date], {
    fallback: MOCK_PICKS.underdog,
    cacheKey: marketCacheKey(UNDERDOG_MARKET.key, date),
    refreshMs: REFRESH_MS,
  });

  // Elite Picks has its own source adapters. These do not replace the
  // dashboard market grid above; they only add the requested ranked feeds.
  const underdog2 = useApi(() => UNDERDOG_2_SOURCE.fetcher(date), [date], {
    cacheKey: marketCacheKey(UNDERDOG_2_SOURCE.key, date),
    refreshMs: REFRESH_MS,
  });
  const over15Intelligence = useApi(
    () => OVER15_INTELLIGENCE_SOURCE.fetcher(date),
    [date],
    {
      cacheKey: marketCacheKey(OVER15_INTELLIGENCE_SOURCE.key, date),
      refreshMs: REFRESH_MS,
    },
  );
  const over25Judges = useApi(() => OVER25_JUDGES_SOURCE.fetcher(date), [date], {
    cacheKey: marketCacheKey(OVER25_JUDGES_SOURCE.key, date),
    refreshMs: REFRESH_MS,
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
    stale: rawResults[i].stale,
    ...withFallback(config.key, rawResults[i]),
  }));

  const totalScanned = marketRows.reduce(
    (sum, m) => sum + (m.data?.length ?? 0),
    0
  );

  // The grid above still shows all 11 dashboard markets. Elite Picks uses
  // only the requested source list, with an independent top-five cap per source.
  const eliteResults = useMemo(
    () => [
      underdog2,
      shvi,
      fhvi,
      sot,
      corners,
      over15Intelligence,
      fhvi, // Over 2.5 Intelligence 2 intentionally uses the same FHVI feed.
      over25Judges,
    ],
    [
      underdog2,
      shvi,
      fhvi,
      sot,
      corners,
      over15Intelligence,
      over25Judges,
    ],
  );

  const allElite = useMemo(() => {
    const items: EliteRankItem[] = [];
    ELITE_PICK_SOURCES.forEach((source, sourceIndex) => {
      const { data, isMock } = withFallback(source.key, eliteResults[sourceIndex]);
      for (const selected of selectTopSourceRows(source, data)) {
        const { pick, value, sourceRank } = selected;
        items.push({
          key: `${source.key}-${sourceRank}-${pick.fixture}`,
          rank: 0,
          sourceRank,
          fixture: pick.fixture,
          market: source.label,
          href: source.href,
          tier: pick.tier || source.label,
          value,
          suffix: source.suffix,
          isMock,
          odds: pick.odds,
          verification: pick.verification,
          dnaMarketKey: ELITE_DNA_MARKET_KEYS[source.key],
        });
      }
    });
    // Preserve source order and each source's own rank. Values from different
    // engines have different units, so a global mixed-value sort is misleading.
    items.forEach((item, i) => (item.rank = i + 1));
    return items;
  }, [eliteResults]);

  const peakConfidence = allElite.length
    ? Math.max(...allElite.map((item) => item.value))
    : 0;
  const enginesOnline = rawResults.filter(
    (r) => r.error === null || (r.data?.length ?? 0) > 0
  ).length;

  return (
    <div className="relative flex w-full flex-col gap-4 overflow-x-hidden p-4 sm:p-6">
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
          <div className="glass flex w-full flex-col items-center gap-4 rounded-lg p-4 text-center shadow-panel sm:flex-row sm:justify-center sm:text-left">
            <RadialGauge value={peakConfidence} label="Peak Confidence" />
            <div className="flex min-w-0 flex-col gap-1 text-2xs text-text-muted">
              <p>
                Strongest signal across every market today, drawn live from each
                engine&apos;s top-of-chain output.
              </p>
            </div>
          </div>

          <EngineStatusList rows={marketRows} />
        </div>
      </div>

      {/* ── MARKET INTEL WITH DNA FACTORS & DATE CONNECTED ──────────── */}
      <MarketIntelList
        rows={marketRows}
        marketFactors={dnaV2?.market_factors}
        date={date}
      />

      <AIMarketAssessment />
    </div>
  );
}

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
      <Suspense fallback={null}>
        <LegacyTabRedirect />
      </Suspense>
      <DashboardOverview />
    </>
  );
}
