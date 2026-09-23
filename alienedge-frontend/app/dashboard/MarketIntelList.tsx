"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { TierBadge } from "@/components/predictions/TierBadge";
import {
  PredictionTable,
  type PredictionColumn,
} from "@/components/predictions";
import { getTrafficLightDot, toFiniteNumber } from "@/lib/api";
import { cn } from "@/lib/utils";
import { DnaCountBadge } from "@/components/dna/DnaCountBadge";
import { VerifyCell } from "@/components/predictions/VerifyCell";
import type { DnaV2FixtureFactors, DnaV2MarketKey } from "@/lib/api";
import type { MarketConfig, MarketPick } from "./market-config";
import { FixtureRiskTag } from "@/components/FixtureRiskTag";

interface MarketRow {
  config: MarketConfig;
  data: MarketPick[];
  loading: boolean;
  isMock: boolean;
  isRefetching?: boolean;
}

const DNA_SUPPORTED_MARKETS = new Set([
  "win", "gg", "over25", "over15", "draw", "unders", "corners",
]);

// ── Final numeric render boundary ──────────────────────────────────────
// Same defense-in-depth guard as EliteRankList: values are normalized at
// the market-config adapter boundary, and this render-site guard makes a
// stray string/null/NaN impossible to crash the dashboard with.
const FALLBACK_CELL = "–";

function safeFixed(value: unknown, digits: number): string | null {
  const n = toFiniteNumber(value);
  return n != null ? n.toFixed(digits) : null;
}

function safeNumeric(value: unknown): number {
  return toFiniteNumber(value) ?? 0;
}

/**
 * Market Intelligence — rendered through the SAME real <table> component
 * every market page uses (PredictionTable). A real <td> grows to fit its
 * content and the container scrolls horizontally, so long raw tier text
 * can never paint over the fixture column the way the old fixed-width
 * flexbox row did.
 */
export function MarketIntelList({
  rows,
  marketFactors,
  date,
}: {
  rows: MarketRow[];
  marketFactors?: Record<string, DnaV2FixtureFactors>;
  date?: string;
}) {
  const columns: PredictionColumn<MarketRow>[] = [
    {
      key: "verify",
      header: "Verify",
      align: "center",
      className: "w-10",
      render: (row) => <VerifyCell data={row.data[0]?.verification} />,
    },
    {
      key: "dna",
      header: "DNA",
      align: "center",
      className: "w-10",
      render: (row) => {
        const top = row.data[0];
        const dnaKey = DNA_SUPPORTED_MARKETS.has(row.config.key)
          ? (row.config.key as DnaV2MarketKey)
          : undefined;
        return dnaKey && top?.fixture ? (
          <DnaCountBadge
            marketFactors={marketFactors}
            fixtureLabel={top.fixture}
            market={dnaKey}
            date={date || ""}
            className="shrink-0 scale-90"
          />
        ) : (
          <span className="font-mono text-2xs text-text-dim">–</span>
        );
      },
    },
    {
      key: "match",
      header: "Market & Fixture",
      className: "min-w-[150px]",
      render: (row) => {
        const { config, isMock } = row;
        const top = row.data[0];
        return (
          <Link
            href={config.href}
            prefetch
            className="group flex flex-col gap-0.5 py-0.5"
          >
            <div className="flex flex-wrap items-center gap-1">
              <span className="text-xs font-bold leading-tight text-text-primary transition-colors group-hover:text-cyan-400">
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
            <FixtureRiskTag
              row={top}
              label={top?.fixture || "No picks today"}
              className="text-[10.5px] font-semibold text-cyan-400"
            />
          </Link>
        );
      },
    },
    {
      key: "badges",
      header: "Badges & Odds",
      align: "right",
      className: "whitespace-nowrap",
      render: (row) => {
        const top = row.data[0];
        return (
          <div className="flex items-center justify-end gap-1.5 py-0.5">
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
                    getTrafficLightDot(safeNumeric(top.prob))
                  )}
                />
                <span>
                  {safeFixed(top.prob, 1) ?? FALLBACK_CELL}
                  <span className="text-[9px] font-medium text-text-muted">%</span>
                </span>
              </div>
            ) : top?.score != null ? (
              <span className="whitespace-nowrap font-mono text-[10px] font-bold text-cyan-300">
                Score {safeFixed(top.score, 1) ?? FALLBACK_CELL}
              </span>
            ) : null}
            {top?.odds != null && safeNumeric(top.odds) > 0 && (
              <span className="shrink-0 rounded border border-cyan-500/30 bg-cyan-950/40 px-1 py-0.2 font-mono text-[10px] font-bold text-cyan-300 shadow-sm">
                @{safeFixed(top.odds, 2)}
              </span>
            )}
          </div>
        );
      },
    },
  ];

  return (
    <div className="glass flex h-full flex-col overflow-hidden rounded-xl border border-white/10 shadow-panel">
      {/* ── CENTERED SECTION HEADER (unchanged identity) ─────────────── */}
      <div className="flex flex-col items-center justify-center gap-1 border-b border-border/80 bg-[#0d1322]/80 px-4 py-3 backdrop-blur-md">
        <div className="flex items-center gap-2">
          <h2 className="text-base font-black tracking-wide text-white uppercase">
            Market Intelligence
          </h2>
          <span className="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2 py-0.5 font-mono text-[10px] font-bold text-cyan-300">
            {rows.length} MARKETS
          </span>
        </div>
        <p className="text-[11px] text-text-dim">
          Institutional probability &amp; multi-market forensic signals
        </p>
      </div>

      {/* ── REAL TABLE — grows + scrolls sideways, never overlaps ────── */}
      <div className="flex-1">
        <PredictionTable
          columns={columns}
          data={rows}
          rowKey={(r) => r.config.key}
          emptyMessage="No markets available."
        />
      </div>
    </div>
  );
}
