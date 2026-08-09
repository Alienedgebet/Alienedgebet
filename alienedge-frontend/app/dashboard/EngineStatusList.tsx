"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";
import { getTierClass } from "@/lib/api";
import type { MarketConfig, MarketPick } from "./market-config";

interface EngineRow {
  config: MarketConfig;
  data: MarketPick[];
  isMock: boolean;
}

interface EngineStatusListProps {
  rows: EngineRow[];
}

type PerfTier = "elite" | "strong" | "moderate" | "thin" | "none";

interface Performance {
  tier: PerfTier;
  label: string;
  avgConfidence: number | null;
  eliteCount: number;
}

/**
 * Derives a performance read from the market's own picks — pick volume,
 * average confidence (prob or score), and elite-tier count — instead of
 * a raw request-succeeded/failed connectivity check.
 */
function computePerformance(data: MarketPick[]): Performance {
  if (data.length === 0) {
    return { tier: "none", label: "No signal", avgConfidence: null, eliteCount: 0 };
  }

  const values = data
    .map((p) => p.prob ?? p.score)
    .filter((v): v is number => v != null);
  const avgConfidence = values.length
    ? Math.round((values.reduce((sum, v) => sum + v, 0) / values.length) * 10) / 10
    : null;

  const eliteCount = data.filter((p) => {
    if (!p.tier) return false;
    const cls = getTierClass(p.tier);
    return cls === "tier-diamond" || cls === "tier-fire";
  }).length;

  if (eliteCount > 0 && (avgConfidence ?? 0) >= 70) {
    return { tier: "elite", label: "Elite", avgConfidence, eliteCount };
  }
  if (eliteCount > 0 || (avgConfidence ?? 0) >= 65) {
    return { tier: "strong", label: "Strong", avgConfidence, eliteCount };
  }
  if ((avgConfidence ?? 0) >= 50) {
    return { tier: "moderate", label: "Moderate", avgConfidence, eliteCount };
  }
  return { tier: "thin", label: "Thin", avgConfidence, eliteCount };
}

const TIER_STYLES: Record<PerfTier, { dot: string; text: string }> = {
  elite: { dot: "bg-accent-green animate-live-pulse", text: "text-accent-green" },
  strong: { dot: "bg-accent-cyan", text: "text-accent-cyan" },
  moderate: { dot: "bg-accent-amber", text: "text-accent-amber" },
  thin: { dot: "bg-accent-red/70", text: "text-accent-red" },
  none: { dot: "bg-text-dim/50", text: "text-text-dim" },
};

/**
 * Vertical engine performance panel — each row shows how well that market's
 * engine is actually producing today (pick volume + avg confidence + elite
 * count), not whether its API request happened to succeed.
 */
export function EngineStatusList({ rows }: EngineStatusListProps) {
  const withSignal = rows.filter((r) => r.data.length > 0).length;
  const overallAvg = (() => {
    const values = rows
      .flatMap((r) => r.data.map((p) => p.prob ?? p.score))
      .filter((v): v is number => v != null);
    if (!values.length) return null;
    return Math.round(values.reduce((sum, v) => sum + v, 0) / values.length);
  })();

  return (
    <div className="glass flex flex-1 flex-col overflow-hidden rounded-lg shadow-panel">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold text-text-primary">Engine Performance</h2>
        <span className="font-mono text-2xs text-accent-green">
          {withSignal}/{rows.length} live
          {overallAvg != null ? ` · ${overallAvg}% avg` : ""}
        </span>
      </div>
      <div className="flex-1 divide-y divide-border/60 overflow-y-auto">
        {rows.map(({ config, data, isMock }) => {
          const perf = computePerformance(data);
          const style = TIER_STYLES[perf.tier];
          return (
            <Link
              key={config.key}
              href={config.href}
              prefetch
              className="flex items-center justify-between gap-2 px-4 py-2 text-xs transition-colors hover:bg-bg-elevated/50"
            >
              <span className="flex min-w-0 flex-col">
                <span className="truncate text-text-secondary">{config.label}</span>
                <span className="font-mono text-[0.65rem] text-text-dim">
                  {data.length} pick{data.length === 1 ? "" : "s"}
                  {perf.eliteCount > 0 ? ` · ${perf.eliteCount} elite` : ""}
                  {isMock ? " · Demo" : ""}
                </span>
              </span>
              <span className="flex shrink-0 items-center gap-1.5">
                <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", style.dot)} />
                <span className={cn("font-mono text-2xs whitespace-nowrap", style.text)}>
                  {perf.avgConfidence != null ? `${perf.avgConfidence}%` : perf.label}
                </span>
              </span>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
