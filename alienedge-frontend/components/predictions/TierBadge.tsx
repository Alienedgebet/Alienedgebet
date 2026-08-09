"use client";

import { Gem, Flame, CircleCheck, TriangleAlert, Eye, type LucideIcon } from "lucide-react";
import { getTierClass, getTierDotColor, getTierGlow } from "@/lib/api";
import { cn } from "@/lib/utils";

interface TierBadgeProps {
  tier: string;
  className?: string;
  /** Pulses the traffic-light dot — on by default for diamond/fire tiers. */
  pulse?: boolean;
  /** "lg" is for the dominant tier slot on pick cards — bigger text, dot, and always-on glow for hot tiers. Default "sm" for dense table use. */
  size?: "sm" | "lg";
}

/** Each tier gets a distinct glyph instead of shared emoji — reads as an institutional signal, not a chat reaction. */
const TIER_ICON: Record<string, LucideIcon> = {
  "tier-diamond": Gem,
  "tier-fire": Flame,
  "tier-solid": CircleCheck,
  "tier-avoid": TriangleAlert,
  "tier-monitor": Eye,
};

// Raw engine output sometimes leads with a decorative emoji (e.g. "💎 DIAMOND
// (Stable & High)") — the Lucide icon above already carries that meaning, so
// the glyph is stripped for display only. The underlying tier string/data is
// never mutated, only the rendered label.
const EMOJI_PREFIX = /^[\p{Emoji_Presentation}\p{Extended_Pictographic}\uFE0F\u200d]+\s*/u;

function cleanTierLabel(tier: string): string {
  return tier.replace(EMOJI_PREFIX, "").trim();
}

export function TierBadge({ tier, className, pulse = true, size = "sm" }: TierBadgeProps) {
  const tierClass = getTierClass(tier);
  const isHot = tierClass === "tier-diamond" || tierClass === "tier-fire";
  const isLg = size === "lg";
  const Icon = TIER_ICON[tierClass] ?? Eye;
  const label = cleanTierLabel(tier);

  return (
    <span
      className={cn(
        "relative inline-flex items-center overflow-hidden whitespace-nowrap rounded border font-mono font-semibold backdrop-blur-sm transition-transform transition-shadow hover:-translate-y-px hover:scale-[1.03] active:scale-95",
        isLg ? "gap-2 px-2.5 py-1 text-xs" : "gap-1.5 px-1.5 py-0.5 text-2xs",
        tierClass,
        isHot && getTierGlow(tier),
        tierClass === "tier-avoid" && "tier-avoid-hazard",
        tierClass === "tier-monitor" && "tier-monitor-dashed",
        className
      )}
    >
      <span className={cn("relative flex shrink-0", isLg ? "h-2 w-2" : "h-1.5 w-1.5")}>
        {pulse && isHot && (
          <span
            className={cn(
              "absolute inline-flex h-full w-full animate-live-pulse rounded-full opacity-75",
              getTierDotColor(tier)
            )}
          />
        )}
        <span className={cn("relative inline-flex h-full w-full rounded-full", getTierDotColor(tier))} />
      </span>

      <Icon aria-hidden className={cn("relative shrink-0", isLg ? "h-3.5 w-3.5" : "h-3 w-3")} strokeWidth={2.25} />
      <span className="relative">{label}</span>
    </span>
  );
}
