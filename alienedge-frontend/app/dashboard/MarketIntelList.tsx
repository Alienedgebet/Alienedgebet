"use client";

import Link from "next/link";
import { AlertTriangle, ChevronRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { TierBadge } from "@/components/predictions/TierBadge";
import { ProbCell } from "@/components/predictions/ProbCell";
import { ScoreBar } from "@/components/predictions/ScoreBar";
import { cn } from "@/lib/utils";
import type { MarketConfig, MarketPick } from "./market-config";

interface MarketRow {
  config: MarketConfig;
  data: MarketPick[];
  loading: boolean;
  isMock: boolean;
  isRefetching?: boolean;
}

/** Cycles through the design system's accent palette so rows stay distinct. */
const ACCENTS = [
  { bg: "bg-accent-indigo/15", text: "text-accent-indigo" },
  { bg: "bg-accent-cyan/15", text: "text-accent-cyan" },
  { bg: "bg-accent-green/15", text: "text-accent-green" },
  { bg: "bg-accent-amber/15", text: "text-accent-amber" },
  { bg: "bg-accent-purple/15", text: "text-accent-purple" },
  { bg: "bg-accent-blue/15", text: "text-accent-blue" },
];

/**
 * Market Intelligence — static list paint. Seeded rows show immediately;
 * soft dim only while background revalidation runs.
 */
export function MarketIntelList({ rows }: { rows: MarketRow[] }) {
  return (
    <div className="glass overflow-hidden rounded-lg shadow-panel">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
        <h2 className="min-w-0 truncate text-sm font-semibold text-text-primary">
          Market Intelligence
        </h2>
        <span className="shrink-0 font-mono text-2xs text-text-dim">
          {rows.length} markets
        </span>
      </div>

      <div className="divide-y divide-border/60">
        {rows.map(({ config, data, isMock }, index) => {
          const accent = ACCENTS[index % ACCENTS.length];
          const top = data[0];
          const Icon = config.icon;
          const count = data.length;

          return (
            <Link key={config.key} href={config.href} prefetch className="block w-full">
              <div className="group flex w-full flex-wrap items-center gap-3 px-4 py-3 transition-colors hover:bg-bg-elevated/40">
                <div
                  className={cn(
                    "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
                    accent.bg
                  )}
                >
                  <Icon className={cn("h-4 w-4", accent.text)} />
                </div>

                {/* Left side — market title + badges on top, match name below */}
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-semibold text-text-primary">
                      {config.label}
                    </span>
                    {top?.tier && <TierBadge tier={top.tier} pulse={false} className="shrink-0" />}
                    {isMock && (
                      <Badge
                        variant="outline"
                        className="h-4 shrink-0 border-accent-amber/30 px-1 text-[0.6rem] text-accent-amber"
                      >
                        Demo
                      </Badge>
                    )}
                  </div>
                  {top ? (
                    <p className="mt-1 truncate text-xs text-text-secondary">{top.fixture}</p>
                  ) : (
                    <p className="mt-1 text-xs text-text-dim">No picks today</p>
                  )}
                </div>

                {/* Right side — probability + bookmaker odds, right-aligned, no overlap */}
                <div className="flex shrink-0 items-center gap-2">
                  {!top ? (
                    <AlertTriangle className="h-3.5 w-3.5 text-text-dim" />
                  ) : top.prob != null ? (
                    <>
                      <ProbCell value={top.prob} showBar={false} />
                      {top.odds != null && top.odds > 0 && (
                        <span className="rounded bg-accent-indigo/15 px-1 py-0.5 font-mono text-2xs font-semibold text-accent-cyan">
                          @{top.odds.toFixed(2)}
                        </span>
                      )}
                    </>
                  ) : top.score != null ? (
                    <div className="w-16">
                      <ScoreBar score={top.score} showValue />
                    </div>
                  ) : null}
                </div>

                <span className="hidden w-14 shrink-0 text-right font-mono text-2xs text-text-dim sm:block">
                  {count} picks
                </span>

                <ChevronRight className="h-3.5 w-3.5 shrink-0 text-text-dim transition-transform duration-150 group-hover:translate-x-0.5 group-hover:text-text-muted" />
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
