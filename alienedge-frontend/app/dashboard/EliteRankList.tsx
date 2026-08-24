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

/**
 * Dense ranked list — clean 3-column architecture:
 * 1. DNA & Rank Score Column
 * 2. Match & Market Column (full wrapped team names, no truncation)
 * 3. Badges & Odds Column (tier badges, prob %, and odds)
 */
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
    <div className="glass flex h-full flex-col overflow-hidden rounded-lg shadow-panel">
      <div className="flex w-full items-center justify-between gap-2 border-b border-border px-4 py-3">
        <h2 className="min-w-0 text-sm font-bold text-text-primary">
          Today&apos;s Elite Picks
        </h2>
        <span className="shrink-0 font-mono text-2xs text-text-dim">
          {items.length} total
        </span>
      </div>

      {items.length > 0 && (
        <div className="grid grid-cols-12 items-center gap-2 border-b border-border/60 px-4 py-2 text-2xs font-semibold uppercase tracking-wider text-text-secondary">
          <div className="col-span-3 sm:col-span-2 font-mono">
            DNA / #
          </div>
          <div className="col-span-5 sm:col-span-6 font-mono">
            Match & Market
          </div>
          <div className="col-span-4 sm:col-span-4 text-right font-mono">
            Badges & Odds
          </div>
        </div>
      )}

      {items.length === 0 ? (
        <div className="flex flex-1 items-center justify-center py-10 text-center text-xs text-text-dim">
          {emptyMessage}
        </div>
      ) : (
        <div className="divide-y divide-border/60">
          {items.map((item) => (
            <div
              key={item.key}
              className="grid grid-cols-12 items-center gap-2 px-4 py-3 transition-colors hover:bg-bg-elevated/40"
            >
              {/* Column 1: DNA & Rank Number */}
              <div className="col-span-3 sm:col-span-2 flex items-center gap-2">
                <span
                  className={cn(
                    "flex h-6 w-6 shrink-0 items-center justify-center rounded font-mono text-xs font-bold",
                    RANK_ACCENT[item.rank]
                      ? cn("border", RANK_ACCENT[item.rank])
                      : "bg-bg-elevated text-text-muted"
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

              {/* Column 2: Match & Market Column (No truncation, allows 2-line wrap) */}
              <div className="col-span-5 sm:col-span-6 min-w-0 pr-2">
                <Link
                  href={item.href}
                  prefetch
                  className="group flex flex-col gap-0.5"
                >
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-xs font-semibold leading-snug text-text-primary group-hover:text-accent-indigo transition-colors break-words">
                      {item.fixture}
                    </span>
                    {item.isMock && (
                      <Badge
                        variant="outline"
                        className="h-4 shrink-0 border-accent-amber/30 px-1 text-[0.6rem] text-accent-amber"
                      >
                        Demo
                      </Badge>
                    )}
                  </div>
                  <span className="text-2xs font-medium text-accent-cyan/90">
                    {item.market}
                  </span>
                </Link>
              </div>

              {/* Column 3: Badges & Odds Column (Tier, Prob, Odds) */}
              <div className="col-span-4 sm:col-span-4 flex flex-col items-end justify-center gap-1 sm:flex-row sm:items-center sm:justify-end sm:gap-2.5">
                <div className="flex shrink-0">
                  <TierBadge tier={item.tier} pulse={false} />
                </div>

                <div className="flex flex-wrap items-center justify-end gap-1.5 whitespace-nowrap font-mono text-xs font-bold tabular-nums text-text-primary">
                  <span
                    className={cn(
                      "h-1.5 w-1.5 shrink-0 rounded-full",
                      getTrafficLightDot(item.value)
                    )}
                  />
                  <span>
                    {item.value.toFixed(1)}
                    <span className="text-2xs font-medium text-text-muted">
                      {item.suffix}
                    </span>
                  </span>
                  {item.odds != null && item.odds > 0 && (
                    <span className="rounded bg-accent-indigo/15 border border-accent-indigo/30 px-1 py-0.5 text-2xs font-semibold text-accent-cyan">
                      @{item.odds.toFixed(2)}
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
