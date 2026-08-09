"use client";

import { Radar } from "lucide-react";
import { cn } from "@/lib/utils";

interface EngineFeedBarProps {
  totalScanned: number;
  eliteCount: number;
  enginesOnline: number;
  enginesTotal: number;
  peakConfidence: number;
}

/**
 * Top telemetry strip — fully independent from the hero carousel below it.
 * Every number here is real engine output (scanned fixtures, elite count,
 * online engines, peak confidence); there is deliberately no invented
 * financial metric (no "bank growth", no odds vector).
 */
export function EngineFeedBar({
  totalScanned,
  eliteCount,
  enginesOnline,
  enginesTotal,
  peakConfidence,
}: EngineFeedBarProps) {
  return (
    <div className="glass flex flex-wrap items-center gap-x-7 gap-y-3 rounded-xl px-5 py-3.5 shadow-panel md:px-6">
      <div className="flex items-center gap-2.5">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-ae-blue shadow-glow">
          <Radar className="h-4 w-4 text-white" />
        </div>
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wide text-text-primary">Engine Feed</p>
          <p className="text-2xs text-text-dim">Real-time AI analysis &amp; probability engine</p>
        </div>
      </div>

      <div className="ml-auto flex flex-wrap items-center gap-x-6 gap-y-2 font-mono">
        <StatBlock label="Scanning" value={totalScanned.toString()} suffix="fixtures" liveDot />
        <StatBlock label="Elite Picks" value={eliteCount.toString()} suffix="today" accent="text-accent-indigo" />
        <StatBlock label="Engines Online" value={`${enginesOnline}/${enginesTotal}`} accent="text-accent-green" />
        <StatBlock label="Peak Confidence" value={peakConfidence.toFixed(1)} suffix="%" accent="text-accent-cyan" />
      </div>
    </div>
  );
}

function StatBlock({
  label,
  value,
  suffix,
  accent,
  liveDot,
}: {
  label: string;
  value: string;
  suffix?: string;
  accent?: string;
  liveDot?: boolean;
}) {
  return (
    <div className="flex items-center gap-2 border-l border-border/60 pl-4 first:border-l-0 first:pl-0">
      <div className="flex flex-col">
        <span className="flex items-center gap-1.5 text-2xs uppercase tracking-wide text-text-dim">
          {liveDot && <span className="h-1.5 w-1.5 rounded-full bg-accent-green animate-live-pulse" />}
          {label}
        </span>
        <span className={cn("text-sm font-bold tabular-nums", accent ?? "text-text-primary")}>
          {value}
          {suffix && <span className="ml-1 text-2xs font-medium text-text-muted">{suffix}</span>}
        </span>
      </div>
    </div>
  );
}
