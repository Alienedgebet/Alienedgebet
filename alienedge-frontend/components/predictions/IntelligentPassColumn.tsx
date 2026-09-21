"use client";

import { Suspense } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import type { PredictionColumn } from "@/components/predictions";

/**
 * Intelligent Pass Count — a DISPLAY/AUDIT-only column (never changes the
 * prediction itself). Reads the additive `intelligent_pass_count` object the
 * API already attaches to each row:
 *   { passed: number, total: number, checks: [{name, result, value, threshold}] }
 *
 * UI rules (spec):
 *   • Header is COMPACT, two stacked lines: INTELLIGENT / PASS COUNT.
 *   • Value is the compact "5/7" form (never "5 passes out of 7"); the full
 *     checklist lives in the native title tooltip / the Team Intelligence page.
 *   • Placement: immediately AFTER the DNA column when that market/pick has
 *     DNA, otherwise immediately AFTER Verify. No blank DNA column is ever
 *     added just to make the position uniform.
 *   • Rows without an audit (backend unavailable / display-only stage) render
 *     "–" and take essentially no width.
 * The whole cell is a link to the Team Intelligence page, where every
 * individual check is explained with its real value and threshold.
 */

export interface IntelligentPassData {
  /** The market/pick this audit belongs to (the report's primary identity). */
  market?: string;
  passed: number;
  total: number;
  checks: Array<{
    name: string;
    result: "PASS" | "FAIL" | "NOT_AVAILABLE";
    value?: unknown;
    threshold?: string;
  }>;
}

/** Compact two-line header — INTELLIGENT over PASS COUNT. */
export function IntelligentPassHeader() {
  return (
    <span className="flex flex-col leading-[1.15]">
      <span>Intelligent</span>
      <span>Pass Count</span>
    </span>
  );
}

function tooltipText(d: IntelligentPassData): string {
  const lines = d.checks
    .filter((c) => c.result !== "NOT_AVAILABLE")
    .map((c) => {
      const val =
        c.value === undefined || c.value === null
          ? ""
          : ` (${typeof c.value === "object" ? JSON.stringify(c.value) : String(c.value)})`;
      return `${c.name}: ${c.result}${val}`;
    });
  return lines.length ? lines.join("\n") : "No applicable intelligence";
}

function IntelligentPassCell({
  data,
  team,
  date,
  market,
}: {
  data?: IntelligentPassData | null;
  team?: string;
  date?: string;
  market?: string;
}) {
  if (!data || data.total === 0) {
    return <span className="font-mono text-2xs text-text-dim">–</span>;
  }
  const cls =
    data.passed === data.total
      ? "border-accent-green/40 text-accent-green"
      : data.passed / data.total >= 0.6
        ? "border-amber-500/40 text-amber-300"
        : "border-rose-500/40 text-rose-300";
  return (
    <Suspense
      fallback={
        <span className="font-mono text-[11px] font-black text-text-dim">
          {data.passed}/{data.total}
        </span>
      }
    >
      <ReportLink
        data={data}
        team={team}
        date={date}
        market={market}
        className={cn(cls)}
      />
    </Suspense>
  );
}

/**
 * THE PICK IS THE PRIMARY OBJECT: every click carries the MARKET of the
 * table it came from (?market=…) plus the origin page (?from=…) so the
 * report opens ONLY that market's checks and Back returns to the source.
 */
function ReportLink({
  data,
  team,
  date,
  market,
  className,
}: {
  data: IntelligentPassData;
  team?: string;
  date?: string;
  market?: string;
  className?: string;
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const from = searchParams.toString();
  const marketKey = market || data.market;
  // usePathname() already includes the leading slash — prefixing another
  // produced "//win?date=...", which browsers parse as host "win"
  // (ERR_NAME_NOT_RESOLVED). Normalize instead of prepending.
  const cleanPath = `/${pathname.replace(/^\/+/, "")}`;
  const href = `/team/${encodeURIComponent(team || "")}?date=${date || ""}${
    marketKey ? `&market=${encodeURIComponent(marketKey)}` : ""
  }${from ? `&from=${encodeURIComponent(`${cleanPath}?${from}`)}` : ""}`;
  return (
    <Link
      href={href}
      prefetch
      className={cn(
        "inline-flex items-center justify-center rounded-md border bg-[#0c1526]/90 px-1.5 py-0.5 font-mono text-[11px] font-black tabular-nums shadow-[0_0_8px_rgba(16,185,129,0.12)] transition-all hover:border-cyan-400 hover:text-white active:scale-95",
        className
      )}
      title={`${data.passed}/${data.total} intelligence checks passed\n${tooltipText(data)}\n\nTap to open this pick's intelligence report`}
      aria-label={`Intelligent pass count ${data.passed} of ${data.total}. Open this pick's intelligence report.`}
    >
      {data.passed}/{data.total}
    </Link>
  );
}

/**
 * Column factory. Insert its result into a page's column array at EXACTLY
 * one of two positions (never both):
 *   [ ...verify, createDnaColumn(...), createIntelligentPassColumn(...), ... ]
 *   [ ...verify, createIntelligentPassColumn(...), ... ]
 */
export function createIntelligentPassColumn<T>(
  opts: {
    /** Row's selected team (win Target / the row's own team identity). */
    getTeam?: (r: T) => string | undefined;
    /** Fixture label fallback for rows that carry no team identity. */
    getLabel?: (r: T) => string | undefined;
    /** The market/pick this table represents — REQUIRED for a correct
     * single-market report (e.g. "win", "over25", "gg"). Falls back to the
     * row audit's own `market` tag when omitted. */
    market?: string;
    date: string;
    className?: string;
  } = { date: "" }
): PredictionColumn<T> {
  /**
   * GG-style rows carry only a fixture label ("Jeonbuk Motors vs Gwangju").
   * The team-intelligence endpoint resolves TEAM names, not composite
   * labels — so split the label and pass the HOME side. Both sides of a
   * fixture resolve to the same per-fixture audit.
   */
  const teamFromRow = (r: T): string | undefined => {
    const explicit = opts.getTeam?.(r);
    if (explicit) return explicit;
    const label = opts.getLabel?.(r) || "";
    const home = label.split(/\s+vs\.?\s+/i)[0]?.trim();
    return home || undefined;
  };
  return {
    key: "intelligent_pass_count",
    header: <IntelligentPassHeader />,
    align: "center",
    className: cn("w-14 shrink-0", opts.className),
    render: (r: T) => (
      <IntelligentPassCell
        data={(r as { intelligent_pass_count?: IntelligentPassData | null })
          .intelligent_pass_count}
        team={teamFromRow(r)}
        date={opts.date}
        market={opts.market}
      />
    ),
  };
}
