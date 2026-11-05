"use client";

import { useEffect, useState } from "react";
import { getProbColor, parseProbability } from "@/lib/api";
import { cn } from "@/lib/utils";

interface ProbValueProps {
  value: string | number;
  suffix?: string;
  className?: string;
}

/**
 * Lightweight count-up used by PredictionCard / RadialGauge.
 * Kept separate from ProbValue (static table cells) so tables stay cheap.
 */
export function useCountUp(target: number, durationMs = 500): number {
  const [value, setValue] = useState(0);

  useEffect(() => {
    let frame = 0;
    const start = performance.now();
    const from = 0;
    const to = Number.isFinite(target) ? target : 0;

    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const eased = 1 - (1 - t) * (1 - t);
      setValue(from + (to - from) * eased);
      if (t < 1) frame = requestAnimationFrame(tick);
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, durationMs]);

  return value;
}

/**
 * Static probability text — count-up + entrance motion previously ran one
 * rAF loop and a framer controller per cell across every table on a page.
 */
export function ProbValue({ value, suffix = "%", className }: ProbValueProps) {
  const target = parseProbability(value);
  const isElite = target >= 75;

  return (
    <span
      className={cn(
        "font-mono text-sm font-semibold tabular-nums",
        getProbColor(target),
        isElite && "drop-shadow-[0_0_6px_rgba(34,197,94,0.45)]",
        className
      )}
    >
      {target.toFixed(1)}
      {suffix}
    </span>
  );
}
