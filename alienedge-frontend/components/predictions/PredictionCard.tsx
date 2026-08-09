"use client";

import type { ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { getTrafficLightDot } from "@/lib/api";
import { TierBadge } from "@/components/predictions/TierBadge";
import { ScoreBar } from "@/components/predictions/ScoreBar";
import { useCountUp } from "@/components/predictions/ProbValue";

export interface PredictionCardConfidence {
  value: number;
  max?: number;
  suffix?: string;
}

interface PredictionCardProps {
  /** Kept for call-site compatibility; no longer used for stagger delay. */
  index?: number;
  /** Team names / fixture — the largest, boldest element, read first. */
  title: ReactNode;
  /** Market label (GG, Win, Over 2.5…) — small, secondary, sits left of the tier badge. */
  market?: ReactNode;
  /** Raw tier string — rendered as the single most visually dominant element on the card. */
  tier: string;
  /** Prob% or /100 score — rendered huge, bold, JetBrains Mono, with a thin bar underneath. */
  confidence?: PredictionCardConfidence;
  /** Small, de-emphasized trailing badges (e.g. a "Demo" tag) shown top-right of the title row. */
  meta?: ReactNode;
  className?: string;
}

/**
 * One pick, rendered as a glass card with a fixed visual hierarchy so the
 * strongest pick of the day reads in under two seconds:
 *   1. Team names (large, bold)
 *   2. Market + tier badge, same line — tier is the dominant element
 *   3. Confidence score (huge, bold, mono)
 *   4. Thin confidence bar
 */
export function PredictionCard({
  title,
  market,
  tier,
  confidence,
  meta,
  className,
}: PredictionCardProps) {
  const displayValue = useCountUp(confidence?.value ?? 0, 500);
  const pct = confidence ? Math.min(100, Math.max(0, (confidence.value / (confidence.max ?? 100)) * 100)) : 0;

  return (
    <motion.div
      initial={false}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.15, ease: [0.4, 0, 0.2, 1] }}
      whileHover={{ y: -2 }}
      className={cn(
        "glass group relative flex flex-col gap-3 overflow-hidden rounded-lg p-4 shadow-panel transition-shadow duration-300 hover:shadow-glow",
        className
      )}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-card-shine opacity-0 transition-opacity duration-300 group-hover:opacity-100"
      />

      {/* 1 — team names, large + bold */}
      <div className="flex min-w-0 items-start justify-between gap-2">
        <h3 className="min-w-0 truncate text-base font-bold leading-tight text-text-primary">{title}</h3>
        {meta && <div className="shrink-0">{meta}</div>}
      </div>

      {/* 2 — market + tier, tier is the dominant element */}
      <div className="flex items-center justify-between gap-2">
        {market ? (
          <span className="min-w-0 truncate text-2xs font-medium uppercase tracking-wider text-text-muted">
            {market}
          </span>
        ) : (
          <span />
        )}
        <TierBadge tier={tier} size="lg" />
      </div>

      {/* 3 + 4 — confidence value (huge, mono, bold) + thin bar */}
      {confidence && (
        <div className="mt-1 flex flex-col gap-1.5">
          <div className="flex items-baseline gap-1.5">
            <span className={cn("h-2 w-2 shrink-0 rounded-full", getTrafficLightDot(confidence.value))} />
            <span className="font-mono text-3xl font-bold leading-none tabular-nums text-text-primary">
              {displayValue.toFixed(1)}
            </span>
            <span className="font-mono text-sm font-semibold text-text-muted">
              {confidence.suffix ?? "%"}
            </span>
          </div>
          <ScoreBar score={pct} max={100} height={3} />
        </div>
      )}
    </motion.div>
  );
}

interface PredictionCardItem {
  key: string;
  title: ReactNode;
  market?: ReactNode;
  tier: string;
  confidence?: PredictionCardConfidence;
  meta?: ReactNode;
}

interface PredictionCardGridProps {
  data: PredictionCardItem[];
  emptyMessage?: string;
  className?: string;
}

/** Responsive grid of PredictionCard — the card-view sibling to PredictionTable for the elite-picks feed. */
export function PredictionCardGrid({
  data,
  emptyMessage = "No picks available for this date.",
  className,
}: PredictionCardGridProps) {
  return (
    <AnimatePresence mode="wait">
      {data.length === 0 ? (
        <motion.div
          key="empty"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="flex items-center justify-center py-10 text-center text-xs text-text-dim"
        >
          {emptyMessage}
        </motion.div>
      ) : (
        <motion.div
          key="grid"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className={cn("grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3", className)}
        >
          {data.map((item, i) => (
            <PredictionCard
              key={item.key}
              index={i}
              title={item.title}
              market={item.market}
              tier={item.tier}
              confidence={item.confidence}
              meta={item.meta}
            />
          ))}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
