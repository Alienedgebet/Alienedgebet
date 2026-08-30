"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { TierBadge } from "@/components/predictions/TierBadge";
import { getTrafficLightDot } from "@/lib/api";
import { cn } from "@/lib/utils";
import { DnaCountBadge } from "@/components/dna/DnaCountBadge";
import { VerifyCell, type VerificationData } from "@/components/predictions/VerifyCell";
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
  odds?: number;
  dnaMarketKey?: DnaV2MarketKey;
  verification?: VerificationData;
}

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
      <div className="flex flex-col items-center justify-center gap-1 border-b border-border/80 bg-[#0d1322]/80 px-4 py-3 backdrop-blur-md">
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

      {/* ── 2. SCROLLABLE TABLE CONTAINER (ULTRA COMPACT) ──────── */}
      <div className="w-full overflow-x-auto scrollbar-none [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <div className="min-w-[440px]">
          
          {/* Table Column Headers (Ultra-Tight Spacing) */}
          {items.length > 0 && (
            <div className="flex items-center border-b border-border/60 bg-bg-elevated/30 px-2.5 py-1.5 text-[10px] font-bold uppercase tracking-wider text-text-secondary">
              <div className="w-10 shrink-0 font-mono text-center">Verify</div>
              <div className="w-10 shrink-0 font-mono text-center">DNA</div>
              <div className="flex-1 min-w-[130px] font-mono pl-1.5">Match &amp; Market</div>
              <div className="w-44 shrink-0 text-right font-mono pr-1.5">Badges &amp; Odds</div>
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
                  className="flex items-center px-2.5 py-2 transition-colors hover:bg-bg-elevated/60"
                >
                  {/* Column 1: VERIFY (Ultra-Compact w-10) */}
                  <div className="flex w-10 shrink-0 items-center justify-center">
                    <VerifyCell data={item.verification} />
                  </div>

                  {/* Column 2: DNA (Ultra-Compact w-10) */}
                  <div className="flex w-10 shrink-0 items-center justify-center">
                    {item.dnaMarketKey ? (
                      <DnaCountBadge
                        marketFactors={marketFactors}
                        fixtureLabel={item.fixture}
                        market={item.dnaMarketKey}
                        date={date}
                        className="shrink-0 scale-90"
                      />
                    ) : (
                      <span className="font-mono text-2xs text-text-dim">–</span>
                    )}
                  </div>

                  {/* Column 3: Match & Market */}
                  <div className="flex-1 min-w-[130px] pl-1.5 pr-2">
                    <Link
                      href={item.href}
                      prefetch
                      className="group flex flex-col gap-0.5"
                    >
                      <div className="flex flex-wrap items-center gap-1">
                        <span className="text-xs font-bold leading-tight text-text-primary group-hover:text-cyan-400 transition-colors">
                          {item.fixture}
                        </span>
                        {item.isMock && (
                          <Badge
                            variant="outline"
                            className="h-3.5 shrink-0 border-accent-amber/40 bg-accent-amber/10 px-1 text-[0.55rem] font-bold text-accent-amber"
                          >
                            Demo
                          </Badge>
                        )}
                      </div>
                      <span className="text-[10.5px] font-semibold text-cyan-400">
                        {item.market}
                      </span>
                    </Link>
                  </div>

                  {/* Column 4: Badges & Odds (Ultra-Compact w-44) */}
                  <div className="flex w-44 shrink-0 items-center justify-end gap-1.5 pr-1">
                    <div className="flex shrink-0 scale-90 origin-right">
                      <TierBadge tier={item.tier} pulse={false} />
                    </div>

                    <div className="flex items-center gap-1 whitespace-nowrap font-mono text-[11px] font-bold tabular-nums text-white">
                      <span
                        className={cn(
                          "h-1.5 w-1.5 shrink-0 rounded-full shadow-sm",
                          getTrafficLightDot(item.value)
                        )}
                      />
                      <span>
                        {item.value.toFixed(1)}
                        <span className="text-[9px] font-medium text-text-muted">
                          {item.suffix}
                        </span>
                      </span>
                    </div>

                    {item.odds != null && item.odds > 0 && (
                      <span className="shrink-0 rounded border border-cyan-500/30 bg-cyan-950/40 px-1 py-0.2 font-mono text-[10px] font-bold text-cyan-300 shadow-sm">
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
