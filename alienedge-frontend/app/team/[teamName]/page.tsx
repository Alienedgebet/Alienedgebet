"use client";

import { Suspense, useMemo } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import { BrainCircuit, ArrowLeft } from "lucide-react";
import {
  teamIntelligenceApi,
  TEAM_INTELLIGENCE_MARKET_LABELS,
  TEAM_INTELLIGENCE_MARKET_ORDER,
  MARKET_SOURCE_PAGE,
  type TeamIntelligencePage,
  type MarketIntelligenceReport,
  type MarketIntelligence,
} from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { useSelectedDate } from "@/lib/date-context";
import { ErrorState } from "@/components/predictions/ErrorState";

/**
 * TEAM INTELLIGENCE PAGE — the drill-down behind every Intelligent Pass
 * Count cell. THE PICK/MARKET IS THE PRIMARY OBJECT: the URL always carries
 * ?market=<key> from the table the user clicked, and this page renders ONLY
 * that market's checks (team + fixture/date + market = the report identity).
 * A URL without ?market= (legacy/direct) falls back to the all-markets view.
 * Display/audit only: everything comes from the SAME cache snapshots the
 * market pages read (zero new backend calls). Nothing here feeds back into
 * predictions, settlement or Verify.
 */

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

/** One market's checks — used by the single-market report AND the legacy view. */
function CheckList({ data }: { data: { checks: MarketIntelligence["checks"] } }) {
  return (
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
              <span className="ml-2 font-mono text-[10px] text-text-muted">
                {formatValue(c.value)}
              </span>
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** THE REPORT CARD — one market, the clicked pick, nothing else. */
function MarketReportCard({ report }: { report: MarketIntelligenceReport }) {
  const score = report.score;
  return (
    <div className="glass rounded-xl border border-white/10 bg-[#0c1220]/90 p-4 shadow-panel backdrop-blur-md">
      <div className="mb-1 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-black uppercase tracking-wider text-text-primary">
            {report.market_label || TEAM_INTELLIGENCE_MARKET_LABELS[report.market] || report.market}
          </h2>
          <p className="text-[11px] text-text-secondary">
            {report.prediction ? `${report.prediction} — ` : ""}
            Intelligent Pass Count
          </p>
        </div>
        {score && (
          <span
            className={`rounded-lg border bg-black/30 px-3 py-1 font-mono text-base font-black tabular-nums ${scoreTone(score.passed, score.total)}`}
            title={`${score.passed} of ${score.total} applicable intelligence checks passed`}
          >
            {score.total === 0 ? "–" : `${score.passed} / ${score.total}`}
          </span>
        )}
      </div>
      <p className="mb-3 text-[11px] text-text-muted">
        {report.fixture || "fixture not found"}
        {report.opponent ? ` · vs ${report.opponent}` : ""} · {report.date}
      </p>
      {report.checks.length > 0 ? (
        <CheckList data={report} />
      ) : (
        <p className="text-[11px] text-text-muted">
          No applicable intelligence checks for this pick on this date.
        </p>
      )}
    </div>
  );
}

/** Legacy all-markets card (only shown for URLs that carry no ?market=). */
function LegacyMarketCard({
  market,
  data,
}: {
  market: string;
  data: MarketIntelligence;
}) {
  return (
    <div className="glass rounded-xl border border-white/10 bg-[#0c1220]/90 p-4 shadow-panel backdrop-blur-md">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-xs font-black uppercase tracking-wider text-text-primary">
          {TEAM_INTELLIGENCE_MARKET_LABELS[market] ?? market}
        </h3>
        <span
          className={`rounded-md border bg-black/30 px-2 py-0.5 font-mono text-xs font-black tabular-nums ${scoreTone(data.passed, data.total)}`}
        >
          {data.total === 0 ? "–" : `${data.passed}/${data.total}`}
        </span>
      </div>
      {data.checks.length > 0 ? (
        <CheckList data={data} />
      ) : (
        <p className="text-[11px] text-text-muted">No applicable checks.</p>
      )}
    </div>
  );
}

function ReportInner() {
  const params = useParams();
  const searchParams = useSearchParams();
  const { date: selectedDate } = useSelectedDate();

  const teamName = decodeURIComponent(
    Array.isArray(params.teamName) ? params.teamName[0] : params.teamName || ""
  );
  const market = searchParams.get("market") || undefined;
  const from = searchParams.get("from");
  const today = new Date().toISOString().slice(0, 10);
  const effectiveDate = searchParams.get("date") || selectedDate || today;

  const { data, loading, error } = useApi<
    TeamIntelligencePage | MarketIntelligenceReport
  >(
    () => teamIntelligenceApi.get(teamName, effectiveDate, market),
    [teamName, effectiveDate, market],
    { cacheKey: `team-intelligence:${teamName}:${effectiveDate}:${market || "all"}` }
  );

  // Back ALWAYS returns to the page the click came from — exactly like the
  // DNA drill-down. Primary mechanism is HISTORY BACK (router.back()): the
  // market page is still mounted in the router stack, so its selected date /
  // tab / filter state and its fetched data are restored instantly with zero
  // re-fetch and zero dependence on URL plumbing. ?from= is only the
  // deep-link fallback for URLs that arrived here directly (new tab / shared
  // link / history already gone): it is decoded and sanitized — it must be a
  // same-origin path with exactly one leading slash (a "//win"-style value
  // would resolve "win" as a hostname — ERR_NAME_NOT_RESOLVED — so it falls
  // back to the market's own page).
  const router = useRouter();
  const backHref = useMemo(() => {
    let target = "";
    if (from) {
      try {
        target = decodeURIComponent(from);
      } catch {
        target = from;
      }
    }
    if (target.startsWith("/") && !target.startsWith("//")) {
      return target;
    }
    const page = (market && MARKET_SOURCE_PAGE[market]) || "/dashboard";
    return effectiveDate ? `${page}?date=${effectiveDate}` : page;
  }, [from, market, effectiveDate]);

  const isSingle = Boolean(market);
  const single = isSingle ? (data as MarketIntelligenceReport | undefined) : undefined;
  const legacy = !isSingle ? (data as TeamIntelligencePage | undefined) : undefined;

  const legacySections = useMemo(() => {
    if (!legacy?.fixture_found) return [];
    const keys = Object.keys(legacy.markets);
    const ordered = [
      ...TEAM_INTELLIGENCE_MARKET_ORDER.filter((k) => keys.includes(k)),
      ...keys.filter((k) => !TEAM_INTELLIGENCE_MARKET_ORDER.includes(k as never)),
    ];
    return ordered
      .map((k) => [k, legacy.markets[k]] as const)
      .filter(([, m]) => m && m.checks.length > 0);
  }, [legacy]);

  const unknownMarket =
    isSingle && !(market && TEAM_INTELLIGENCE_MARKET_LABELS[market]);

  const headerFixture = isSingle
    ? single?.fixture_found
      ? `${single.fixture}${single.opponent ? ` · vs ${single.opponent}` : ""}`
      : `No fixture found for this team on ${effectiveDate}`
    : legacy?.fixture_found
      ? `${legacy.fixture} · ${effectiveDate} · vs ${legacy.opponent || "—"}`
      : `No fixture found for this team on ${effectiveDate}`;

  return (
    <div className="flex flex-col gap-4 p-3.5 sm:p-5 md:p-6">
      {/* ── 1. HEADER — team + THE clicked market ─────────────────────── */}
      <div className="glass flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-[#0c1220]/90 px-4 py-3 shadow-panel backdrop-blur-md">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => {
              // History back restores the originating page exactly as it was
              // (date, tab, filters, scroll) — same mechanism as the DNA
              // drill-down. Only when this report was opened as a fresh
              // deep link (nothing to pop) do we use the sanitized
              // ?from=/market fallback instead.
              if (window.history.length > 1) router.back();
              else window.location.assign(backHref);
            }}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-slate-300 transition-all hover:border-cyan-400 hover:text-white active:scale-95"
            aria-label="Back to the originating page"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-accent-indigo/30 bg-accent-indigo/10 shadow-[0_0_12px_rgba(99,102,241,0.2)]">
            <BrainCircuit className="h-4 w-4 text-accent-indigo" />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-text-primary">
              {teamName}
              {isSingle && single?.market_label
                ? ` — ${single.market_label}`
                : isSingle && market
                  ? ` — ${TEAM_INTELLIGENCE_MARKET_LABELS[market] || market}`
                  : " — Team Intelligence"}
            </h1>
            <p className="text-[11px] text-text-secondary">{headerFixture}</p>
          </div>
        </div>
        {isSingle && single?.fixture_found && single.score && (
          <span
            className={`rounded-lg border bg-black/30 px-3 py-1 font-mono text-sm font-black tabular-nums ${scoreTone(single.score.passed, single.score.total)}`}
            title={`${single.score.passed} of ${single.score.total} applicable checks passed for this pick`}
          >
            {single.score.passed}/{single.score.total}
          </span>
        )}
      </div>

      {/* ── 2. BODY ───────────────────────────────────────────────────── */}
      {loading && (
        <div className="py-10 text-center text-xs text-text-muted">
          Loading intelligence report…
        </div>
      )}
      {!loading && error && (
        <ErrorState message={`Intelligence report unavailable: ${error}`} />
      )}
      {!loading && !error && unknownMarket && (
        <ErrorState message={`Unknown market “${market}”.`} />
      )}
      {!loading && !error && !unknownMarket && data && !data.fixture_found && (
        <ErrorState
          message={`No intelligence found for “${teamName}” on ${effectiveDate}. The team may not have a fixture on this date, or the engines have not produced data for it yet.`}
        />
      )}
      {!loading && !error && !unknownMarket && isSingle && single?.fixture_found && (
        <div className="mx-auto w-full max-w-2xl">
          <MarketReportCard report={single} />
        </div>
      )}
      {!loading && !error && !isSingle && legacySections.length > 0 && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {legacySections.map(([mKey, m]) => (
            <LegacyMarketCard key={mKey} market={mKey} data={m} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function TeamIntelligencePage() {
  return (
    <Suspense
      fallback={
        <div className="py-10 text-center text-xs text-text-muted">
          Loading intelligence report…
        </div>
      }
    >
      <ReportInner />
    </Suspense>
  );
}
