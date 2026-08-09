"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { TierBadge } from "@/components/predictions/TierBadge";
import { getTrafficLightDot } from "@/lib/api";
import { cn } from "@/lib/utils";

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
}: {
  items: EliteRankItem[];
  emptyMessage: string;
}) {
  return (
    <div className="glass flex h-full flex-col overflow-hidden rounded-lg shadow-panel">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold text-text-primary">
          Today&apos;s Elite Picks
        </h2>
        <span className="font-mono text-2xs text-text-dim">
          {items.length} total
        </span>
      </div>

      {items.length === 0 ? (
        <div className="flex flex-1 items-center justify-center py-10 text-center text-xs text-text-dim">
          {emptyMessage}
        </div>
      ) : (
        <div className="divide-y divide-border/60">
          {items.map((item) => (
            <Link
              key={item.key}
              href={item.href}
              prefetch
              className="flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-bg-elevated/40"
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

              <TierBadge tier={item.tier} pulse={false} />

              <div className="flex w-16 shrink-0 items-center justify-end gap-1.5 font-mono text-sm font-bold tabular-nums text-text-primary">
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
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
