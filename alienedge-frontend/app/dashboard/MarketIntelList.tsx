"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { TierBadge } from "@/components/predictions/TierBadge";
import { getTrafficLightDot } from "@/lib/api";
import { cn } from "@/lib/utils";
import { DnaCountBadge } from "@/components/dna/DnaCountBadge";
import { VerifyCell } from "@/components/predictions/VerifyCell";
import type { DnaV2FixtureFactors, DnaV2MarketKey } from "@/lib/api";
import type { MarketConfig, MarketPick } from "./market-config";

interface MarketRow {
  config: MarketConfig;
  data: MarketPick[];
  loading: boolean;
  isMock: boolean;
  isRefetching?: boolean;
}

const DNA_SUPPORTED_MARKETS = new Set(["win", "gg", "over25", "over15", "draw", "unders", "corners"]);

export function MarketIntelList({
  rows,
  marketFactors,
  date,
}: {
  rows: MarketRow[];
  marketFactors?: Record<string, DnaV2FixtureFactors>;
  date?: string;
}) {
  return (
    <div className="glass flex h-full flex-col overflow-hidden rounded-xl border border-white/10 shadow-panel">
      
      {/* ── 1. CENTERED SECTION HEADER ────────────────────────── */}
      <div className="flex flex-col items-center justify-center gap-1 border-b border-border/80 bg-[#0d1322]/80 px-4 py-3 backdrop-blur-md">
        <div className="flex items-center gap-2">
          <h2 className="text-base font-black tracking-wide text-white uppercase">
            Market Intelligence
          </h2>
          <span className="rounded-full bg-cyan-500/10 border border-cyan-500/30 px-2 py-0.5 font-mono text-[10px] font-bold text-cyan-300">
            {rows.length} MARKETS
          </span>
        </div>
        <p className="text-[11px] text-text-dim">
          Institutional probability &amp; multi-market forensic signals
        </p>
      </div>

      {/* ── 2. SCROLLABLE TABLE CONTAINER (ULTRA COMPACT) ──────── */}
      <div className="w-full overflow-x-auto scrollbar-none [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <div className="min-w-[440px]">
          
          {/* Table Column Headers (Ultra-Tight Spacing) */}
          {rows.length > 0 && (
            <div className="flex items-center border-b border-border/60 bg-bg-elevated/30 px-2.5 py-1.5 text-[10px] font-bold uppercase tracking-wider text-text-secondary">
              <div className="w-10 shrink-0 font-mono text-center">Verify</div>
              <div className="w-10 shrink-0 font-mono text-center">DNA</div>
              <div className="flex-1 min-w-[130px] font-mono pl-1.5">Market &amp; Fixture</div>
              <div className="w-44 shrink-0 text-right font-mono pr-1.5">Badges &amp; Odds</div>
            </div>
          )}

          {/* Empty Message */}
          {rows.length === 0 ? (
            <div className="flex flex-1 items-center justify-center py-12 text-center text-xs text-text-dim">
              No markets available.
            </div>
          ) : (
            /* Rows */
            <div className="divide-y divide-border/40">
              {rows.map(({ config, data, isMock }) => {
                const top = data[0];
                const dnaKey = DNA_SUPPORTED_MARKETS.has(config.key)
                  ? (config.key as DnaV2MarketKey)
                  : undefined;

                return (
                  <div
                    key={config.key}
                    className="flex items-center px-2.5 py-2 transition-colors hover:bg-bg-elevated/60"
                  >
                    {/* Column 1: VERIFY (Ultra-Compact w-10) */}
                    <div className="flex w-10 shrink-0 items-center justify-center">
                      <VerifyCell data={(top as any)?.verification} />
                    </div>

                    {/* Column 2: DNA (Ultra-Compact w-10) */}
                    <div className="flex w-10 shrink-0 items-center justify-center">
                      {dnaKey && top?.fixture ? (
                        <DnaCountBadge
                          marketFactors={marketFactors}
                          fixtureLabel={top.fixture}
                          market={dnaKey}
                          date={date || ""}
                          className="shrink-0 scale-90"
                        />
                      ) : (
                        <span className="font-mono text-2xs text-text-dim">–</span>
                      )}
                    </div>

                    {/* Column 3: Market & Fixture */}
                    <div className="flex-1 min-w-[130px] pl-1.5 pr-2">
                      <Link
                        href={config.href}
                        prefetch
                        className="group flex flex-col gap-0.5"
                      >
                        <div className="flex flex-wrap items-center gap-1">
                          <span className="text-xs font-bold leading-tight text-text-primary group-hover:text-cyan-400 transition-colors">
                            {config.label}
                          </span>
                          {isMock && (
                            <Badge
                              variant="outline"
                              className="h-3.5 shrink-0 border-accent-amber/40 bg-accent-amber/10 px-1 text-[0.55rem] font-bold text-accent-amber"
                            >
                              Demo
                            </Badge>
                          )}
                        </div>
                        <span className="text-[10.5px] font-semibold text-cyan-400 truncate">
                          {top?.fixture || "No picks today"}
                        </span>
                      </Link>
                    </div>

                    {/* Column 4: Badges & Odds (Ultra-Compact w-44) */}
                    <div className="flex w-44 shrink-0 items-center justify-end gap-1.5 pr-1">
                      {top?.tier && (
                        <div className="flex shrink-0 scale-90 origin-right">
                          <TierBadge tier={top.tier} pulse={false} />
                        </div>
                      )}

                      {top?.prob != null ? (
                        <div className="flex items-center gap-1 whitespace-nowrap font-mono text-[11px] font-bold tabular-nums text-white">
                          <span
                            className={cn(
                              "h-1.5 w-1.5 shrink-0 rounded-full shadow-sm",
                              getTrafficLightDot(top.prob)
                            )}
                          />
                          <span>
                            {top.prob.toFixed(1)}
                            <span className="text-[9px] font-medium text-text-muted">%</span>
                          </span>
                        </div>
                      ) : top?.score != null ? (
                        <span className="font-mono text-[10px] font-bold text-cyan-300">
                          Score {top.score.toFixed(1)}
                        </span>
                      ) : null}

                      {top?.odds != null && top.odds > 0 && (
                        <span className="shrink-0 rounded border border-cyan-500/30 bg-cyan-950/40 px-1 py-0.2 font-mono text-[10px] font-bold text-cyan-300 shadow-sm">
                          @{top.odds.toFixed(2)}
                        </span>
                      )}
                    </div>

                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
