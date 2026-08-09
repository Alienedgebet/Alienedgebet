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
  /** Full market-factor payload for every fixture, keyed by fixture_id. */
  marketFactors: Record<string, DnaV2FixtureFactors> | undefined;
  /** Preferred join key — exact match against the backend's fixture_id. */
  fixtureId?: string | number;
  /** Fallback join key for pick types with no fixture_id — "Home vs Away". */
  fixtureLabel?: string;
  market: DnaV2MarketKey;
  date: string;
  className?: string;
}

/**
 * Compact, always-first-column DNA factor count — e.g. "9 : 3".
 *
 * Deliberately renders NOTHING else: no percentages, bars, charts, or
 * pillar breakdowns. Every number comes straight from the backend
 * (CORE/dna_v2_market_factors.py) — this component only reads and renders.
 *
 * Fully clickable — routes to the full-screen DNA Analysis page for this
 * exact fixture + market. Because the fixture list and the DNA page share
 * the same `dna-v2:latest` useApi cache (see lib/use-dna-v2.ts), the data
 * is already in memory by the time this is clicked, so the transition is
 * instant.
 */
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
        "inline-flex items-center gap-1 rounded border border-border bg-bg-card px-1.5 py-0.5 font-mono text-2xs font-semibold tabular-nums text-text-primary transition-colors hover:border-accent-indigo hover:text-accent-indigo",
        className
      )}
      aria-label={`DNA factor count: home ${counts.home_count}, away ${counts.away_count}. Open DNA analysis.`}
    >
      <span>{counts.home_count}</span>
      <span className="text-text-dim">:</span>
      <span>{counts.away_count}</span>
    </Link>
  );
}

/**
 * Builds a ready-to-prepend PredictionColumn that renders a DnaCountBadge,
 * joining rows to the backend's market-factor payload by fixture_id.
 * Every market page uses this to keep the DNA column first, consistent,
 * and backed by the exact same server-computed counts.
 */
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

/**
 * Same as createDnaColumn, but for pick types with no fixture_id field —
 * joins by normalized "Home vs Away" fixture label instead.
 */
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
