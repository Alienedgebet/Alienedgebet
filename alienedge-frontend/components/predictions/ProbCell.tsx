"use client";

import { getTrafficLightDot, parseProbability } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ProbValue } from "@/components/predictions/ProbValue";
import { ScoreBar } from "@/components/predictions/ScoreBar";

interface ProbCellProps {
  value: string | number;
  suffix?: string;
  max?: number;
  className?: string;
  /** Renders the slim animated score bar beneath the value. Default true. */
  showBar?: boolean;
  /** Optional small caption above the value, e.g. "MC PROB". */
  label?: string;
}

/**
 * Table-cell composite: traffic-light dot + probability value + mini score bar.
 * Drop into a PredictionColumn.render() wherever a bare ProbValue needs the
 * fuller "at a glance" treatment.
 */
export function ProbCell({ value, suffix = "%", max = 100, className, showBar = true, label }: ProbCellProps) {
  const num = parseProbability(value);

  return (
    <div className={cn("flex min-w-[4.5rem] flex-col gap-1", className)}>
      {label && (
        <span className="font-mono text-2xs uppercase tracking-wider text-text-dim">{label}</span>
      )}
      <div className="flex items-center gap-1.5">
        <span
          className={cn("h-1.5 w-1.5 shrink-0 rounded-full", getTrafficLightDot(num))}
        />
        <ProbValue value={value} suffix={suffix} />
      </div>
      {showBar && <ScoreBar score={num} max={max} height={2.5} />}
    </div>
  );
}
