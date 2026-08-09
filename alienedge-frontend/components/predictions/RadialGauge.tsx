"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { useCountUp } from "@/components/predictions/ProbValue";

interface RadialGaugeProps {
  /** 0-100 */
  value: number;
  label: string;
  size?: number;
  strokeWidth?: number;
  suffix?: string;
  className?: string;
}

const TRACK_COLOR = "#1a2540";

/** Semantic traffic-light stroke matching getProbColor()'s thresholds — kept local since it drives an SVG stroke, not a text class. */
function strokeForValue(value: number): string {
  if (value >= 75) return "#22c55e";
  if (value >= 60) return "#06b6d4";
  if (value >= 45) return "#f59e0b";
  return "#ef4444";
}

/**
 * Lightweight hand-rolled SVG radial gauge — no charting library dependency,
 * so it renders reliably regardless of bundler/version quirks. Animates the
 * arc fill and the centered number together on mount/update.
 */
export function RadialGauge({ value, label, size = 108, strokeWidth = 8, suffix = "%", className }: RadialGaugeProps) {
  const clamped = Math.min(100, Math.max(0, value));
  const display = useCountUp(clamped, 700);
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - clamped / 100);
  const color = strokeForValue(clamped);

  return (
    <div className={cn("relative flex items-center justify-center", className)} style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={TRACK_COLOR} strokeWidth={strokeWidth} />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={false}
          animate={{ strokeDashoffset: offset }}
          transition={{ duration: 0.45, ease: [0.4, 0, 0.2, 1] }}
          style={{ filter: `drop-shadow(0 0 6px ${color}80)` }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-mono text-2xl font-bold leading-none tabular-nums text-text-primary">
          {display.toFixed(0)}
          <span className="text-sm text-text-muted">{suffix}</span>
        </span>
        <span className="mt-1 text-center text-2xs font-medium uppercase tracking-wider text-text-muted">
          {label}
        </span>
      </div>
    </div>
  );
}
