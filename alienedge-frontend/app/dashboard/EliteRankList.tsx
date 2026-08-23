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
 * Dense ranked list — static paint (no opacity:0 mount). Instant on nav.
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
        <h2 className="min-w-0 truncate text-sm font-bold text-text-primary">
          Today's Elite Picks
        </h2>
        <span className="shrink-0 font-mono text-2xs text-text-dim">
          {items.length} total
        </span>
      </div>

      {items.length > 0 && (
        <div className="hidden items-center gap-3 border-b border-border/60 px-4 py-2 sm:flex">
          <span className="w-[38px] shrink-0 text-center font-mono text-2xs font-semibold uppercase tracking-wider text-text-secondary">
            DNA
          </span>
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <span className="h-6 w-6 shrink-0 text-center font-mono text-2xs font-semibold uppercase tracking-wider text-text-secondary">
              #
            </span>
            <span className="min-w-0 flex-1 font-mono text-2xs font-semibold uppercase tracking-wider text-text-secondary">
              Fixture
            </span>
            <span className="w-24 shrink-0 text-center font-mono text-2xs font-semibold uppercase tracking-wider text-text-secondary">
              Tier
            </span>
            <span className="min-w-[7rem] shrink-0 text-right font-mono text-2xs font-semibold uppercase tracking-wider text-text-secondary">
              Prob / Odds
            </span>
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
              className="flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-bg-elevated/40"
            >
              {/* DNA count — first element, separate clickable target so it
                  doesn't nest inside the fixture Link below. */}
              {item.dnaMarketKey ? (
                <DnaCountBadge
                  marketFactors={marketFactors}
                  fixtureLabel={item.fixture}
                  market={item.dnaMarketKey}
                  date={date}
                  className="shrink-0"
                />
              ) : (
                <span className="w-[38px] shrink-0" />
              )}

              <Link
                href={item.href}
                prefetch
                className="flex min-w-0 flex-1 items-center gap-3"
              >
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

                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate text-xs font-semibold text-text-primary">
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
                  <span className="text-2xs text-text-dim">{item.market}</span>
                </div>

                {/* Right side — tier + prob/odds stack vertically on small
                    screens so they never collide with the fixture text */}
                <div className="flex shrink-0 flex-col items-end gap-1.5 sm:flex-row sm:items-center sm:gap-3">
                  <span className="flex w-fit shrink-0 justify-center sm:w-24">
                    <TierBadge tier={item.tier} pulse={false} />
                  </span>

                  <div className="flex min-w-[7rem] shrink-0 flex-wrap items-center justify-end gap-1.5 whitespace-nowrap font-mono text-sm font-bold tabular-nums text-text-primary">
                    <span
                      className={cn(
                        "h-1.5 w-1.5 shrink-0 rounded-full",
                        getTrafficLightDot(item.value)
                      )}
                    />
                    {item.value.toFixed(1)}
                    <span className="text-2xs font-medium text-text-muted">
                      {item.suffix}
                    </span>
                    {item.odds != null && item.odds > 0 && (
                      <span className="ml-1 rounded bg-accent-indigo/15 px-1 py-0.5 text-2xs font-semibold text-accent-cyan">
                        @{item.odds.toFixed(2)}
                      </span>
                    )}
                  </div>
                </div>
              </Link>
             </div>
          ))}
        </div>
      )}
    </div>
  );
}
