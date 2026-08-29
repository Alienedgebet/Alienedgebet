"use client";

import { Radar, Activity, Sparkles, Cpu, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";

interface EngineFeedBarProps {
  totalScanned: number;
  eliteCount: number;
  enginesOnline: number;
  enginesTotal: number;
  peakConfidence: number;
}

export function EngineFeedBar({
  totalScanned,
  eliteCount,
  enginesOnline,
  enginesTotal,
  peakConfidence,
}: EngineFeedBarProps) {
  return (
    <div className="w-full space-y-2.5">
      {/* Top Title & Indicator */}
      <div className="flex items-center justify-between px-1">
        <div className="flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-gradient-to-tr from-cyan-500 to-blue-600 shadow-[0_0_12px_rgba(6,182,212,0.4)]">
            <Radar className="h-3.5 w-3.5 text-white animate-pulse" />
          </div>
          <span className="text-xs font-bold uppercase tracking-wider text-text-primary">
            Engine Feed
          </span>
          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-400 border border-emerald-500/20">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-ping" />
            LIVE
          </span>
        </div>
        <p className="hidden text-[11px] text-text-dim sm:block">
          Real-time AI probability engine
        </p>
      </div>

      {/* Horizontal Scrollable Carousel (Football.com Style) */}
      <div className="flex w-full items-center gap-3 overflow-x-auto pb-1 pt-0.5 scrollbar-none snap-x snap-mandatory [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        
        {/* Card 1: Scanning Fixtures */}
        <StatCard
          icon={<Activity className="h-4 w-4 text-emerald-400" />}
          label="Scanning"
          value={totalScanned.toString()}
          suffix="fixtures"
          badgeColor="border-emerald-500/30 bg-emerald-950/40 text-emerald-300"
          glowColor="shadow-[0_0_15px_rgba(16,185,129,0.12)]"
        />

        {/* Card 2: Elite Picks */}
        <StatCard
          icon={<Sparkles className="h-4 w-4 text-indigo-400" />}
          label="Elite Picks"
          value={eliteCount.toString()}
          suffix="today"
          badgeColor="border-indigo-500/30 bg-indigo-950/40 text-indigo-300"
          glowColor="shadow-[0_0_15px_rgba(99,102,241,0.15)]"
        />

        {/* Card 3: Engines Online */}
        <StatCard
          icon={<Cpu className="h-4 w-4 text-cyan-400" />}
          label="Engines Online"
          value={`${enginesOnline}/${enginesTotal}`}
          suffix="active"
          badgeColor="border-cyan-500/30 bg-cyan-950/40 text-cyan-300"
          glowColor="shadow-[0_0_15px_rgba(6,182,212,0.12)]"
        />

        {/* Card 4: Peak Confidence */}
        <StatCard
          icon={<TrendingUp className="h-4 w-4 text-amber-400" />}
          label="Peak Confidence"
          value={`${peakConfidence.toFixed(1)}%`}
          badgeColor="border-amber-500/30 bg-amber-950/40 text-amber-300"
          glowColor="shadow-[0_0_15px_rgba(245,158,11,0.12)]"
        />

      </div>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  suffix,
  badgeColor,
  glowColor,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  suffix?: string;
  badgeColor: string;
  glowColor: string;
}) {
  return (
    <div
      className={cn(
        "flex min-w-[130px] shrink-0 snap-start items-center gap-2.5 rounded-xl border border-white/10 bg-[#0d1322]/90 backdrop-blur-md px-3.5 py-2.5 transition-all active:scale-95",
        glowColor
      )}
    >
      <div
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border",
          badgeColor
        )}
      >
        {icon}
      </div>
      <div className="flex flex-col min-w-0">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 truncate">
          {label}
        </span>
        <div className="flex items-baseline gap-1">
          <span className="text-sm font-black tabular-nums text-white">
            {value}
          </span>
          {suffix && (
            <span className="text-[10px] font-medium text-slate-400">
              {suffix}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}