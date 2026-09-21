"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { BrainCircuit, ArrowLeft } from "lucide-react";
import {
  teamIntelligenceApi,
  TEAM_INTELLIGENCE_MARKET_ORDER,
  type TeamIntelligencePage,
  type MarketIntelligence,
} from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { useSelectedDate } from "@/lib/date-context";
import { ErrorState } from "@/components/predictions/ErrorState";

/**
 * TEAM INTELLIGENCE PAGE — the drill-down behind every Intelligent Pass
 * Count cell. Display/audit only: it renders the per-check PASS/FAIL/
 * NOT_AVAILABLE detail the evaluator already computed from the SAME cache
 * snapshots the market pages read (zero new backend calls). Nothing on this
 * page feeds back into predictions, settlement or Verify.
 */

const MARKET_LABELS: Record<string, string> = {
  win: "Win",
  win_psychology: "Win Psychology",
  gg: "GG / BTTS Supreme",
  gg_precision: "GG Precision",
  over25: "Over 2.5",
  over15: "Over 1.5",
  corners: "Corners",
  draw: "Draw",
  unders: "Under 2.5",
  u2s: "Underdog-to-Score",
  fhvi: "FHVI",
  shvi: "SHVI",
};

function scoreTone(passed: number, total: number): string {
  if (total === 0) return "text-text-dim border-white/10";
  if (passed === total) return "text-accent-green border-accent-green/40";
  if (passed / total >= 0.6) return "text-amber-300 border-amber-500/40";
  return "text-rose-300 border-rose-500/40";
}

function checkTone(result: string): string {
  if (result === "PASS") return "text-accent-green";
  if (result === "FAIL") return "text-rose-300";
  return "text-text-dim";
}

function formatValue(value: unknown): string {
  if (value === undefined || value === null) return "";
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => `${k} ${String(v)}`)
      .join(" · ");
  }
  return String(value);
}

function MarketCard({
  market,
  data,
}: {
  market: string;
  data: MarketIntelligence;
}) {
  const tone = scoreTone(data.passed, data.total);
  return (
    <div className="glass rounded-xl border border-white/10 bg-[#0c1220]/90 p-4 shadow-panel backdrop-blur-md">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-xs font-black uppercase tracking-wider text-text-primary">
          {MARKET_LABELS[market] ?? market}
        </h3>
        <span
          className={`rounded-md border bg-black/30 px-2 py-0.5 font-mono text-xs font-black tabular-nums ${tone}`}
        >
          {data.total === 0 ? "–" : `${data.passed}/${data.total}`}
        </span>
      </div>
      <ul className="flex flex-col gap-1.5">
        {data.checks.map((c) => (
          <li
            key={c.name}
            className="flex items-baseline justify-between gap-3 border-b border-white/5 pb-1.5 last:border-0 last:pb-0"
          >
            <span className="text-[11px] text-text-secondary">{c.name}</span>
            <span className="shrink-0 text-right">
              <span
                className={`font-mono text-[11px] font-black ${checkTone(c.result)}`}
              >
                {c.result === "NOT_AVAILABLE" ? "N/A" : c.result}
              </span>
              {c.result !== "NOT_AVAILABLE" && formatValue(c.value) && (
                <span className="ml-2 font-mono text-[10px] text-text-dim">
                  {formatValue(c.value)}
                </span>
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function TeamIntelligencePage() {
  const params = useParams<{ teamName: string }>();
  const search = useSearchParams();
  const teamName = decodeURIComponent(String(params?.teamName ?? ""));
  // The Intelligent Pass cell links carry ?date=…; fall back to the
  // globally selected date (DateSelector / QuickHistoryStrip).
  const urlDate = search.get("date");
  const { date } = useSelectedDate();
  const effectiveDate = urlDate || date;

  const { data, loading, error } = useApi<TeamIntelligencePage>(
    () => teamIntelligenceApi.get(teamName, effectiveDate),
    [teamName, effectiveDate],
    { cacheKey: `team-intelligence:${teamName}:${effectiveDate}` }
  );

  const sections = useMemo(() => {
    if (!data?.fixture_found) return [];
    const keys = Object.keys(data.markets);
    const ordered = [
      ...TEAM_INTELLIGENCE_MARKET_ORDER.filter((k) => keys.includes(k)),
      ...keys.filter((k) => !TEAM_INTELLIGENCE_MARKET_ORDER.includes(k as never)),
    ];
    return ordered
      .map((k) => [k, data.markets[k]] as const)
      .filter(([, m]) => m && m.checks.length > 0);
  }, [data]);

  const totalPassed = sections.reduce((acc, [, m]) => acc + m.passed, 0);
  const totalChecks = sections.reduce((acc, [, m]) => acc + m.total, 0);

  return (
    <div className="flex flex-col gap-4 p-3.5 sm:p-5 md:p-6">
      {/* ── 1. HEADER ────────────────────────────────────────────────── */}
      <div className="glass flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-[#0c1220]/90 px-4 py-3 shadow-panel backdrop-blur-md">
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-slate-300 transition-all hover:border-cyan-400 hover:text-white active:scale-95"
            aria-label="Back to dashboard"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-accent-indigo/30 bg-accent-indigo/10 shadow-[0_0_12px_rgba(99,102,241,0.2)]">
            <BrainCircuit className="h-4 w-4 text-accent-indigo" />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-text-primary">
              {teamName} — Team Intelligence
            </h1>
            <p className="text-[11px] text-text-secondary">
              {data?.fixture_found
                ? `${data.fixture} · ${effectiveDate} · vs ${data.opponent || "—"}`
                : `No fixture found for this team on ${effectiveDate}`}
            </p>
          </div>
        </div>
        {data?.fixture_found && (
          <span
            className={`rounded-lg border bg-black/30 px-3 py-1 font-mono text-sm font-black tabular-nums ${scoreTone(totalPassed, totalChecks)}`}
            title={`${totalPassed} of ${totalChecks} intelligence checks passed across all markets`}
          >
            {totalPassed}/{totalChecks}
          </span>
        )}
      </div>

      {/* ── 2. BODY ──────────────────────────────────────────────────── */}
      {loading && (
        <div className="py-10 text-center text-xs text-text-muted">
          Loading team intelligence…
        </div>
      )}
      {!loading && error && (
        <ErrorState message={`Team intelligence unavailable: ${error}`} />
      )}
      {!loading && !error && data && !data.fixture_found && (
        <ErrorState
          message={`No intelligence found for “${teamName}” on ${effectiveDate}. The team may not have a fixture on this date, or the engines have not produced data for it yet.`}
        />
      )}
      {!loading && !error && data?.fixture_found && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {sections.map(([market, m]) => (
            <MarketCard key={market} market={market} data={m} />
          ))}
        </div>
      )}
    </div>
  );
}
