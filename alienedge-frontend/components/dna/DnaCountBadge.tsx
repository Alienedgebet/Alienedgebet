"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";
import type { DnaV2FixtureFactors, DnaV2MarketKey } from "@/lib/api";
import type { PredictionColumn } from "@/components/predictions";

function normalizeFixtureLabel(label: string): string {
  return label.trim().toLowerCase().replace(/\s+/g, " ");
}

function findEntryByLabel(
  marketFactors: Record<string, DnaV2FixtureFactors> | undefined,
  label: string | undefined
): DnaV2FixtureFactors | undefined {
  if (!marketFactors || !label) return undefined;
  const normalized = normalizeFixtureLabel(label);
  return Object.values(marketFactors).find(
    (entry) => normalizeFixtureLabel(entry.fixture) === normalized
  );
}

interface DnaCountBadgeProps {
  marketFactors: Record<string, DnaV2FixtureFactors> | undefined;
  fixtureId?: string | number;
  fixtureLabel?: string;
  market: DnaV2MarketKey;
  date: string;
  className?: string;
}

export function DnaCountBadge({
  marketFactors,
  fixtureId,
  fixtureLabel,
  market,
  date,
  className,
}: DnaCountBadgeProps) {
  const fixtureKey = fixtureId != null ? String(fixtureId) : undefined;
  const entry =
    (fixtureKey ? marketFactors?.[fixtureKey] : undefined) ??
    findEntryByLabel(marketFactors, fixtureLabel);
  const counts = entry?.markets?.[market];
  const resolvedId = fixtureKey ?? entry?.fixture_id;

  if (!resolvedId || !counts) {
    return <span className="font-mono text-2xs text-text-dim">–</span>;
  }

  return (
    <Link
      href={`/dna/${market}/${resolvedId}?date=${date}`}
      prefetch
      className={cn(
        "inline-flex items-center justify-center gap-1 rounded-md border border-cyan-500/30 bg-[#0c1526]/90 px-1.5 py-0.5 font-mono text-[11px] font-black tabular-nums text-cyan-200 shadow-[0_0_8px_rgba(6,182,212,0.15)] transition-all hover:border-cyan-400 hover:bg-cyan-500/20 hover:text-white active:scale-95",
        className
      )}
      title="Tap to open full Tactical DNA analysis"
      aria-label={`DNA count: home ${counts.home_count}, away ${counts.away_count}. Open DNA analysis.`}
    >
      <span>{counts.home_count}</span>
      <span className="text-cyan-400/60 font-medium">:</span>
      <span>{counts.away_count}</span>
    </Link>
  );
}

export function createDnaColumn<T extends { fixture_id: string | number }>(
  marketFactors: Record<string, DnaV2FixtureFactors> | undefined,
  market: DnaV2MarketKey,
  date: string
): PredictionColumn<T> {
  return {
    key: "dna_v2",
    header: "DNA",
    render: (r) => (
      <DnaCountBadge
        marketFactors={marketFactors}
        fixtureId={r.fixture_id}
        market={market}
        date={date}
      />
    ),
  };
}

export function createDnaColumnByLabel<T>(
  marketFactors: Record<string, DnaV2FixtureFactors> | undefined,
  market: DnaV2MarketKey,
  date: string,
  getLabel: (row: T) => string
): PredictionColumn<T> {
  return {
    key: "dna_v2",
    header: "DNA",
    render: (r) => (
      <DnaCountBadge
        marketFactors={marketFactors}
        fixtureLabel={getLabel(r)}
        market={market}
        date={date}
      />
    ),
  };
}
