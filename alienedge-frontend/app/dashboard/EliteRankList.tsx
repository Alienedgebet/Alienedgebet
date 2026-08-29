"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { TierBadge } from "@/components/predictions/TierBadge";
import { getTrafficLightDot } from "@/lib/api";
import { cn } from "@/lib/utils";
import { DnaCountBadge } from "@/components/dna/DnaCountBadge";
import type { DnaV2FixtureFactors, DnaV2MarketKey } from "@/lib/api";

export interface EliteRankItem {
  key: string;
  rank: number;
  fixture: string;
  market: string;
  href: string;
  tier: string;
  value: number;
  suffix: string;
  isMock: boolean;
  /** Bookmaker odds for this pick — displayed next to probability when available. */
  odds?: number;
  /** Present only for the 7 markets the DNA v2 engine covers (win/gg/over25/over15/unders/draw/corners). */
  dnaMarketKey?: DnaV2MarketKey;
}

const RANK_ACCENT: Record<number, string> = {
  1: "bg-accent-indigo/20 text-accent-indigo border-accent-indigo/30",
  2: "bg-accent-cyan/15 text-accent-cyan border-accent-cyan/30",
  3: "bg-accent-amber/15 text-accent-amber border-accent-amber/30",
};

export function EliteRankList({
  items,
  emptyMessage,
  marketFactors,
  date,
}: {
  items: EliteRankItem[];
  emptyMessage: string;
  marketFactors?: Record<string, DnaV2FixtureFactors>;
  date: string;
}) {
  return (
    <div className="glass flex h-full flex-col overflow-hidden rounded-xl border border-white/10 shadow-panel">
      
      {/* ── 1. CENTERED SECTION HEADER ────────────────────────── */}
      <div className="flex flex-col items-center justify-center gap-1 border-b border-border/80 bg-[#0d1322]/80 px-4 py-3.5 backdrop-blur-md">
        <div className="flex items-center gap-2">
          <h2 className="text-base font-black tracking-wide text-white uppercase">
            Today&apos;s Elite Picks
          </h2>
          <span className="rounded-full bg-cyan-500/10 border border-cyan-500/30 px-2 py-0.5 font-mono text-[10px] font-bold text-cyan-300">
            {items.length} TOTAL
          </span>
        </div>
        <p className="text-[11px] text-text-dim">
          Highest ranked AI probability &amp; market intelligence
        </p>
      </div>

      {/* ── 2. SCROLLABLE / MOVABLE TABLE CONTAINER ────────────── */}
      <div className="w-full overflow-x-auto scrollbar-none [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <div className="min-w-[560px]">
          
          {/* Table Column Titles */}
          {items.length > 0 && (
            <div className="flex items-center border-b border-border/60 bg-bg-elevated/30 px-4 py-2 text-[10px] font-bold uppercase tracking-wider text-text-secondary">
              <div className="w-24 shrink-0 font-mono">DNA / #</div>
              <div className="flex-1 min-w-[200px] font-mono">Match &amp; Market</div>
              <div className="w-64 shrink-0 text-right font-mono pr-2">Badges &amp; Odds</div>
            </div>
          )}

          {/* Empty Message */}
          {items.length === 0 ? (
            <div className="flex flex-1 items-center justify-center py-12 text-center text-xs text-text-dim">
              {emptyMessage}
            </div>
          ) : (
            /* Rows */
            <div className="divide-y divide-border/40">
              {items.map((item) => (
                <div
                  key={item.key}
                  className="flex items-center px-4 py-3 transition-colors hover:bg-bg-elevated/60"
                >
                  {/* Column 1: DNA & Rank Number */}
                  <div className="flex w-24 shrink-0 items-center gap-2.5">
                    <span
                      className={cn(
                        "flex h-6 w-6 shrink-0 items-center justify-center rounded font-mono text-xs font-bold shadow-sm",
                        RANK_ACCENT[item.rank]
                          ? cn("border", RANK_ACCENT[item.rank])
                          : "bg-bg-elevated text-text-muted border border-border"
                      )}
                    >
                      {item.rank}
                    </span>

                    <div className="flex flex-col">
                      {item.dnaMarketKey ? (
                        <DnaCountBadge
                          marketFactors={marketFactors}
                          fixtureLabel={item.fixture}
                          market={item.dnaMarketKey}
                          date={date}
                          className="shrink-0"
                        />
                      ) : (
                        <span className="font-mono text-2xs text-text-dim">–</span>
                      )}
                    </div>
                  </div>

                  {/* Column 2: Match & Market (Ample room, no clipping) */}
                  <div className="flex-1 min-w-[200px] pr-4">
                    <Link
                      href={item.href}
                      prefetch
                      className="group flex flex-col gap-0.5"
                    >
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="text-xs font-bold leading-snug text-text-primary group-hover:text-cyan-400 transition-colors">
                          {item.fixture}
                        </span>
                        {item.isMock && (
                          <Badge
                            variant="outline"
                            className="h-4 shrink-0 border-accent-amber/40 bg-accent-amber/10 px-1 text-[0.6rem] font-bold text-accent-amber"
                          >
                            Demo
                          </Badge>
                        )}
                      </div>
                      <span className="text-[11px] font-semibold text-cyan-400">
                        {item.market}
                      </span>
                    </Link>
                  </div>

                  {/* Column 3: Badges, Confidence & Odds (Dedicated spacious width) */}
                  <div className="flex w-64 shrink-0 items-center justify-end gap-2.5">
                    {/* Badge */}
                    <div className="flex shrink-0">
                      <TierBadge tier={item.tier} pulse={false} />
                    </div>

                    {/* Confidence % */}
                    <div className="flex items-center gap-1.5 whitespace-nowrap font-mono text-xs font-bold tabular-nums text-white">
                      <span
                        className={cn(
                          "h-2 w-2 shrink-0 rounded-full shadow-sm",
                          getTrafficLightDot(item.value)
                        )}
                      />
                      <span>
                        {item.value.toFixed(1)}
                        <span className="text-2xs font-medium text-text-muted">
                          {item.suffix}
                        </span>
                      </span>
                    </div>

                    {/* Odds */}
                    {item.odds != null && item.odds > 0 && (
                      <span className="shrink-0 rounded-md border border-cyan-500/30 bg-cyan-950/40 px-1.5 py-0.5 font-mono text-2xs font-bold text-cyan-300 shadow-sm">
                        @{item.odds.toFixed(2)}
                      </span>
                    )}
                  </div>

                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}