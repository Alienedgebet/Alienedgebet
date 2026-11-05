"use client";

import { getScoreBarVariant } from "@/lib/api";
import { cn } from "@/lib/utils";

interface ScoreBarProps {
  score: number;
  max?: number;
  className?: string;
  /** Track height in px — defaults to the slim 3px table variant. */
  height?: number;
  /** Renders the numeric score to the right of the bar. */
  showValue?: boolean;
}

export function ScoreBar({ score, max = 100, className, height = 3, showValue = false }: ScoreBarProps) {
  const pct = Math.min(100, Math.max(0, (score / max) * 100));
  const variant = getScoreBarVariant(score, max);

  return (
    <div className={cn("flex w-full items-center gap-2", className)}>
      <div
        className="relative w-full overflow-hidden rounded-full bg-bg-elevated"
        style={{ height }}
      >
        <div
          className={cn("h-full rounded-full transition-[width] duration-500 ease-out", variant)}
          style={{ width: `${pct}%` }}
        />
      </div>
      {showValue && (
        <span className="shrink-0 font-mono text-2xs tabular-nums text-text-muted">
          {Math.round(pct)}%
        </span>
      )}
    </div>
  );
}
