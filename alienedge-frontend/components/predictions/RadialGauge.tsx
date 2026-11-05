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

const TRACK_COLOR = "#121a2e";

/**
 * Jewel pairs [light, deep] per confidence band. The thresholds are
 * deliberately identical to getProbColor() / getTrafficLightDot() (75 / 60 /
 * 45) so the gauge can never disagree with the traffic-light dots rendered
 * elsewhere on the same dashboard.
 */
const GEM_COLORS = [
  ["#f43f5e", "#be123c"], // < 45  — deep rose
  ["#f59e0b", "#92400e"], // ≥ 45  — amber
  ["#06b6d4", "#0e7490"], // ≥ 60  — cyan
  ["#22c55e", "#14532d"], // ≥ 75  — emerald
] as const;

function gemColor(value: number): (typeof GEM_COLORS)[number] {
  if (value >= 75) return GEM_COLORS[3];
  if (value >= 60) return GEM_COLORS[2];
  if (value >= 45) return GEM_COLORS[1];
  return GEM_COLORS[0];
}

/**
 * Peak-confidence dial. Every layer — halo lip, track, inner facet, the arc
 * itself, its light edge, the travelling reflection and the apex sparkle —
 * lives in ONE <svg>, so they all share one rotated coordinate space and one
 * layout box (a second sibling <svg> would become a second flex item instead
 * of stacking behind the dial).
 *
 * `overflow-visible` is required: the halo deliberately sits a hair outside
 * the track, and an SVG clips to its viewport by default.
 *
 * The arc is drawn from 12 o'clock and grows clockwise. Because the <svg> is
 * rotated -90°, an un-rotated angle θ renders θ clockwise from the top, so the
 * arc's leading cap — and therefore the sparkle — sits at 2π·(value/100).
 */
export function RadialGauge({
  value,
  label,
  size = 112,
  strokeWidth = 9,
  suffix = "%",
  className,
}: RadialGaugeProps) {
  const finite = Number.isFinite(value) ? value : 0;
  const clamped = Math.min(100, Math.max(0, finite));
  const display = useCountUp(clamped, 700);

  const center = size / 2;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - clamped / 100);
  const [gemLight, gemDeep] = gemColor(clamped);
  const reflectionLength = circumference * 0.34;
  const leadAngle = 2 * Math.PI * (clamped / 100);
  const sparkleX = center + radius * Math.cos(leadAngle);
  const sparkleY = center + radius * Math.sin(leadAngle);

  return (
    <div className={cn("relative flex shrink-0 items-center justify-center", className)} style={{ width: size, height: size }}>
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        aria-hidden
        className="-rotate-90 overflow-visible"
      >
        {/* Halo — hairline jewel lip riding just outside the track. */}
        <circle
          cx={center}
          cy={center}
          r={radius + strokeWidth / 2 + 1.5}
          fill="none"
          stroke={gemDeep}
          strokeWidth={1.5}
          opacity={0.4}
          style={{ filter: `drop-shadow(0 0 6px ${gemDeep}66)` }}
        />

        {/* Track */}
        <circle cx={center} cy={center} r={radius} fill="none" stroke={TRACK_COLOR} strokeWidth={strokeWidth} />

        {/* Inner facet — deep tone beneath the arc, gives the ring its depth. */}
        <circle
          cx={center}
          cy={center}
          r={radius - strokeWidth / 2 - 2}
          fill="none"
          stroke={gemDeep}
          strokeWidth={strokeWidth * 0.9}
          strokeLinecap="round"
          opacity={0.45}
          style={{ filter: `drop-shadow(0 0 5px ${gemDeep}dd)` }}
        />

        {/* Main arc — sweeps up from empty to the value on mount. */}
        <motion.circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke={gemDeep}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: offset }}
          transition={{ duration: 0.7, ease: [0.4, 0, 0.2, 1] }}
          style={{ filter: `drop-shadow(0 0 8px ${gemDeep}cc)` }}
        />

        {/* Light edge — highlight riding the inside of the arc. */}
        <motion.circle
          cx={center}
          cy={center}
          r={radius - strokeWidth / 2 - 1}
          fill="none"
          stroke={gemLight}
          strokeWidth={strokeWidth * 0.5}
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: offset - strokeWidth * 0.7 }}
          transition={{ duration: 0.7, ease: [0.4, 0, 0.2, 1] }}
        />

        {/* Travelling reflection. Keyframes, not a single target: with
            `initial={false}` a lone target has nothing to interpolate, so the
            shimmer would sit frozen. The dash pattern's period is exactly the
            circumference, so 0 → -circumference loops seamlessly. */}
        <motion.circle
          cx={center}
          cy={center}
          r={radius - strokeWidth / 2 - 3}
          fill="none"
          stroke={gemLight}
          strokeWidth={1.2}
          strokeLinecap="round"
          strokeDasharray={`${reflectionLength} ${circumference - reflectionLength}`}
          animate={{ strokeDashoffset: [0, -circumference] }}
          transition={{ duration: 6, repeat: Infinity, ease: "linear" }}
          opacity={0.85}
          style={{ filter: `drop-shadow(0 0 4px ${gemLight}aa)` }}
        />

        {/* Apex sparkle — pinned to the arc's leading cap. */}
        <motion.circle
          cx={sparkleX}
          cy={sparkleY}
          r={2.4}
          fill="#ffffff"
          animate={{ opacity: [0.2, 1, 0.2], scale: [0.7, 1.25, 0.7] }}
          transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }}
          style={{ filter: "drop-shadow(0 0 3px #ffffffdd)" }}
        />
      </svg>

      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-mono text-2xl font-bold leading-none tabular-nums text-text-primary drop-shadow-sm">
          {display.toFixed(0)}
          <span className="text-sm text-text-muted">{suffix}</span>
        </span>
        <span className="mt-1 text-center text-[10px] font-medium uppercase tracking-[0.18em] text-text-secondary drop-shadow-sm">
          {label}
        </span>
      </div>
    </div>
  );
}
