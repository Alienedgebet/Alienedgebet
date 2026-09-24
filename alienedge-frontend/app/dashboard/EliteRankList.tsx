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
import {
  VerifyCell,
  type VerificationData,
} from "@/components/predictions/VerifyCell";
import type { DnaV2FixtureFactors, DnaV2MarketKey } from "@/lib/api";

export interface EliteRankItem {
  key: string;
  rank: number;
  sourceRank: number;
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

// ── Final numeric render boundary ──────────────────────────────────────
// Every value that reaches `.toFixed()` must first be guaranteed to be a
// finite number. Values are normalized once at the market-config adapter
// boundary; this is the defense-in-depth guard at the actual render site
// so a stray string/null/NaN can never crash the dashboard again.
const FALLBACK_CELL = "–";

function safeFixed(value: unknown, digits: number): string | null {
  const n = toFiniteNumber(value);
  return n != null ? n.toFixed(digits) : null;
}

function safeNumeric(value: unknown): number {
  return toFiniteNumber(value) ?? 0;
}

/**
 * Today's Elite Picks — rendered through the SAME real <table> component
 * every market page uses (PredictionTable). A real <td> grows to fit its
 * content and the container scrolls horizontally, so the full raw tier text
 * ("CATEGORY 4: LOCK BUT LOW CONFIDENCE", …) can never paint over the
 * fixture column the way the old fixed-width flexbox row did.
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
  const columns: PredictionColumn<EliteRankItem>[] = [
    {
      key: "verify",
      header: "Verify",
      align: "center",
      className: "w-10",
      render: (it) => <VerifyCell data={it.verification} />,
    },
    {
      key: "dna",
      header: "DNA",
      align: "center",
      className: "w-10",
      render: (it) =>
        it.dnaMarketKey ? (
          <DnaCountBadge
            marketFactors={marketFactors}
            fixtureLabel={it.fixture}
            market={it.dnaMarketKey}
            date={date}
            className="shrink-0 scale-90"
          />
        ) : (
          <span className="font-mono text-2xs text-text-dim">–</span>
        ),
    },
    {
      key: "match",
      header: "Match & Market",
      className: "min-w-[150px]",
      render: (it) => (
        <Link
          href={it.href}
          prefetch
          className="group flex flex-col gap-0.5 py-0.5"
        >
          <div className="flex flex-wrap items-center gap-1">
            <span className="text-xs font-bold leading-tight text-text-primary transition-colors group-hover:text-cyan-400">
              {it.fixture}
            </span>
            {it.isMock && (
              <Badge
                variant="outline"
                className="h-3.5 shrink-0 border-accent-amber/40 bg-accent-amber/10 px-1 text-[0.55rem] font-bold text-accent-amber"
              >
                Demo
              </Badge>
            )}
          </div>
          <span className="text-[10.5px] font-semibold text-cyan-400">
            #{it.sourceRank} · {it.market}
          </span>
        </Link>
      ),
    },
    {
      key: "badges",
      header: "Badges & Odds",
      align: "right",
      className: "whitespace-nowrap",
      render: (it) => (
        <div className="flex items-center justify-end gap-1.5 py-0.5">
          <div className="flex shrink-0 scale-90 origin-right">
            <TierBadge tier={it.tier} pulse={false} />
          </div>
          <div className="flex items-center gap-1 whitespace-nowrap font-mono text-[11px] font-bold tabular-nums text-white">
            <span
              className={cn(
                "h-1.5 w-1.5 shrink-0 rounded-full shadow-sm",
                getTrafficLightDot(safeNumeric(it.value))
              )}
            />
            <span>
              {safeFixed(it.value, 1) ?? FALLBACK_CELL}
              <span className="text-[9px] font-medium text-text-muted">
                {it.suffix}
              </span>
            </span>
          </div>
          {safeFixed(it.odds, 2) != null && safeNumeric(it.odds) > 0 && (
            <span className="shrink-0 rounded border border-cyan-500/30 bg-cyan-950/40 px-1 py-0.2 font-mono text-[10px] font-bold text-cyan-300 shadow-sm">
              @{safeFixed(it.odds, 2)}
            </span>
          )}
        </div>
      ),
    },
  ];

  return (
    <div className="glass flex h-full flex-col overflow-hidden rounded-xl border border-white/10 shadow-panel">
      {/* ── CENTERED SECTION HEADER (unchanged identity) ─────────────── */}
      <div className="flex flex-col items-center justify-center gap-1 border-b border-border/80 bg-[#0d1322]/80 px-4 py-3 backdrop-blur-md">
        <div className="flex items-center gap-2">
          <h2 className="text-base font-black uppercase tracking-wide text-white">
            Today&apos;s Elite Picks
          </h2>
          <span className="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2 py-0.5 font-mono text-[10px] font-bold text-cyan-300">
            {items.length} TOTAL
          </span>
        </div>
        <p className="text-[11px] text-text-dim">
          Up to five source-ranked picks per configured intelligence engine
        </p>
      </div>

      {/* ── REAL TABLE — grows + scrolls sideways, never overlaps ────── */}
      <div className="flex-1">
        <PredictionTable
          columns={columns}
          data={items}
          rowKey={(it) => it.key}
          emptyMessage={emptyMessage}
        />
      </div>
    </div>
  );
}
