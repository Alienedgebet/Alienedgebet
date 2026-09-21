"use client";

import Link from "next/link";
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
}: {
  data?: IntelligentPassData | null;
  team?: string;
  date?: string;
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
    <Link
      href={`/team/${encodeURIComponent(team || "")}?date=${date || ""}`}
      prefetch
      className={cn(
        "inline-flex items-center justify-center rounded-md border bg-[#0c1526]/90 px-1.5 py-0.5 font-mono text-[11px] font-black tabular-nums shadow-[0_0_8px_rgba(16,185,129,0.12)] transition-all hover:border-cyan-400 hover:text-white active:scale-95",
        cls
      )}
      title={`${data.passed}/${data.total} intelligence checks passed\n${tooltipText(data)}\n\nTap to open Team Intelligence`}
      aria-label={`Intelligent pass count ${data.passed} of ${data.total}. Open team intelligence.`}
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
    date: string;
    className?: string;
  } = { date: "" }
): PredictionColumn<T> {
  return {
    key: "intelligent_pass_count",
    header: <IntelligentPassHeader />,
    align: "center",
    className: cn("w-14 shrink-0", opts.className),
    render: (r: T) => (
      <IntelligentPassCell
        data={(r as { intelligent_pass_count?: IntelligentPassData | null })
          .intelligent_pass_count}
        team={opts.getTeam?.(r) ?? opts.getLabel?.(r)}
        date={opts.date}
      />
    ),
  };
}
