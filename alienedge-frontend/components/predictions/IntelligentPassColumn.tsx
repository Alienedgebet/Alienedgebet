"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  getIntelligentPass,
  type IntelligentPassResult,
} from "@/lib/api";

/** Shape of a prediction table column (matches components/predictions). */
export interface PredictionColumn<T> {
  key: string;
  header: string;
  className?: string;
  align?: "left" | "center" | "right";
  render: (row: T) => React.ReactNode;
}

function resultColor(result: string): string {
  switch (result) {
    case "PASS":
      return "text-accent-green border-accent-green/20 bg-accent-green/10";
    case "FAIL":
      return "text-accent-red border-accent-red/20 bg-accent-red/10";
    default:
      return "text-text-muted border-muted/30 bg-muted/50";
  }
}

function resultLabel(result: string): string {
  switch (result) {
    case "PASS":
      return "PASS";
    case "FAIL":
      return "FAIL";
    default:
      return "N/A";
  }
}

/**
 * Single cell: fetches the Intelligent Pass result for one team+fixture+market
 * and renders a clickable badge showing PASS / FAIL / N/A + count.
 */
function IntelligentPassCell({
  team,
  label,
  market,
  date,
}: {
  team: string;
  label: string;
  market: string;
  date: string;
}) {
  const router = useRouter();
  const [result, setResult] = useState<IntelligentPassResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const mounted = useRef(true);

  const fetchPass = useCallback(async () => {
    if (!team) {
      setLoading(false);
      return;
    }
    try {
      setError(false);
      const data = await getIntelligentPass(team, date, market, {
        label,
      });
      if (mounted.current) setResult(data);
    } catch {
      if (mounted.current) setError(true);
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, [team, label, market, date]);

  useEffect(() => {
    mounted.current = true;
    setLoading(true);
    fetchPass();
    return () => {
      mounted.current = false;
    };
  }, [fetchPass]);

  const handleClick = useCallback(() => {
    const params = new URLSearchParams({ date, market });
    if (label) params.set("label", label);
    router.push(`/team/${encodeURIComponent(team)}?${params.toString()}`);
  }, [router, team, date, market, label]);

  if (loading) {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-md border border-muted/30 bg-muted/50 px-2 py-0.5 text-[10px] font-semibold text-text-muted animate-pulse"
        title="Intelligent Pass — loading"
      >
        ⏳ IP
      </span>
    );
  }

  if (error || !result) {
    return (
      <button
        onClick={handleClick}
        className="inline-flex items-center gap-1 rounded-md border border-destructive/30 bg-destructive/10 px-2 py-0.5 text-[10px] font-semibold text-destructive hover:bg-destructive/20 transition"
        title="Intelligent Pass — unavailable"
      >
        N/A
      </button>
    );
  }

  const pass = result.pass_count;
  const total = result.total;
  const allPass = total > 0 && pass === total;
  const anyFail = result.checks.some((c) => c.result === "FAIL");
  const cellResult = anyFail ? "FAIL" : allPass ? "PASS" : "N/A";

  return (
    <button
      onClick={handleClick}
      className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-0.5 text-[10px] font-bold transition hover:opacity-90 ${resultColor(cellResult)}`}
      title={`Intelligent Pass — ${market}: ${pass}/${total} checks passed
${result.checks.map((c) => `\n• ${c.name}: ${c.result} (${c.source})`).join("")}
Click to view the ${market} report for ${team}.`}
    >
      <span className="font-mono">{pass}/{total}</span>
      <span className={resultLabel(cellResult) === "PASS" ? "text-current font-semibold" : "text-current"}>{resultLabel(cellResult)}</span>
    </button>
  );
}

/**
 * Factory: builds a PredictionColumn that shows the Intelligent Pass Count for
 * one market. Every row (team + fixture) gets its own count; clicking carries
 * the market identity to /team/{team}?date=&market=.
 *
 * Usage:
 *   createIntelligentPassColumn<UndersPick>({
 *     market: "unders",
 *     getLabel: (r) => r.fixture,
 *     date,
 *   })
 *
 * If getTeam is provided it identifies the evaluated team; otherwise the
 * label/fixture is used as the team identity (fixture-level markets like
 * Unders).
 */
export function createIntelligentPassColumn<T>({
  market,
  getLabel,
  getTeam,
  date,
}: {
  market: string;
  getLabel: (row: T) => string;
  getTeam?: (row: T) => string;
  date: string;
}): PredictionColumn<T> {
  return {
    key: `intelligent_pass_${market}`,
    header: "Intelligent Pass",
    className: "w-[72px]",
    render: (row) => {
      const team = getTeam ? getTeam(row) : getLabel(row);
      const label = getLabel(row);
      return (
        <IntelligentPassCell
          team={team}
          label={label}
          market={market}
          date={date}
        />
      );
    },
  };
}
