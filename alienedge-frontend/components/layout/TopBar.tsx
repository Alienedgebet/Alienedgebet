"use client";

import { useEffect, useState } from "react";
import { Activity, Menu, MessageSquare, Wifi, WifiOff, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import { healthApi } from "@/lib/api";
import { DateSelector } from "@/components/layout/DateSelector";
import { useSidebar } from "@/lib/sidebar-context";
import { useRightPanel } from "@/lib/right-panel-context";

type ApiStatus = "checking" | "online" | "offline";

export function TopBar() {
  const [status, setStatus] = useState<ApiStatus>("checking");
  const { toggle, close: closeSidebar } = useSidebar();
  const { toggle: toggleRightPanel, close: closeRightPanel } = useRightPanel();

  useEffect(() => {
    let live = true;
    healthApi
      .check()
      .then(() => { if (live) setStatus("online"); })
      .catch(() => { if (live) setStatus("offline"); });
    return () => { live = false; };
  }, []);

  return (
    <header
      className={cn(
        "fixed left-0 right-0 top-0 z-[40] md:left-[240px]",
        "flex flex-col border-b border-border/80",
        "bg-[#070b14]/95 backdrop-blur-xl shadow-lg"
      )}
    >
      {/* ── 1. SPECIAL CYAN/NEON BRANDING HEADER ──────────────────────── */}
      <div className="relative flex w-full flex-col items-center justify-center overflow-hidden border-b border-cyan-500/20 bg-gradient-to-r from-[#061e2d] via-[#0b2b3f] to-[#061e2d] py-1.5 shadow-[inset_0_1px_0_rgba(6,182,212,0.2)]">
        
        {/* Subtle Background Glow Line */}
        <div className="absolute inset-x-0 top-0 h-[1px] bg-gradient-to-r from-transparent via-cyan-400 to-transparent opacity-50" />

        {/* ALIENEDGE Title */}
        <div className="flex items-center gap-1.5">
          <Zap className="h-3 w-3 text-cyan-400 fill-cyan-400/30 animate-pulse" />
          <span className="font-black tracking-[0.25em] text-xs sm:text-sm bg-gradient-to-r from-white via-cyan-200 to-cyan-400 bg-clip-text text-transparent drop-shadow-[0_0_8px_rgba(6,182,212,0.6)] uppercase">
            AlienEdge
          </span>
        </div>

        {/* Subtitle Underneath */}
        <span className="select-none text-[8.5px] font-bold uppercase tracking-[0.22em] text-cyan-300/80 drop-shadow-sm">
          Football Intelligence Platform
        </span>
      </div>

      {/* ── 2. CONTROLS & NAVIGATION ROW ─────────────────────────────── */}
      <div className="flex items-center justify-between gap-2 px-3.5 py-2 md:px-6">
        
        {/* Hamburger Menu (Mobile Only) */}
        <button
          type="button"
          onClick={() => {
            closeRightPanel();
            toggle();
          }}
          aria-label="Toggle navigation"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-slate-300 transition-colors hover:border-cyan-500/40 hover:text-white md:hidden"
        >
          <Menu className="h-4 w-4" />
        </button>

        {/* Global Date Selector */}
        <div className="flex-1 flex justify-start sm:justify-center">
          <DateSelector />
        </div>

        {/* Right Section: Status Pill + Drawer Toggle + User Avatar */}
        <div className="flex items-center gap-2">
          
          {/* API Status Pill */}
          <div
            className={cn(
              "flex items-center gap-1.5 rounded-lg border px-2.5 py-1 font-mono text-[11px] font-bold transition-all shadow-sm",
              status === "online"
                ? "border-emerald-500/30 bg-emerald-950/40 text-emerald-400 shadow-[0_0_10px_rgba(16,185,129,0.15)]"
                : status === "offline"
                ? "border-rose-500/30 bg-rose-950/40 text-rose-400 shadow-[0_0_10px_rgba(244,63,94,0.15)]"
                : "border-white/10 bg-white/5 text-slate-400"
            )}
          >
            {status === "online"   && <Wifi className="h-3 w-3 text-emerald-400" />}
            {status === "offline"  && <WifiOff className="h-3 w-3 text-rose-400" />}
            {status === "checking" && <Activity className="h-3 w-3 text-amber-400 animate-pulse" />}
            <span>
              {status === "checking" ? "API…" : status === "online" ? "Online" : "Offline"}
            </span>
            {status === "online" && (
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-ping" />
            )}
          </div>

          {/* War Room / Right Panel Drawer Toggle (Mobile Only) */}
          <button
            type="button"
            onClick={() => {
              closeSidebar();
              toggleRightPanel();
            }}
            aria-label="Toggle War Room panel"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-slate-300 transition-colors hover:border-cyan-500/40 hover:text-white md:hidden"
          >
            <MessageSquare className="h-4 w-4" />
          </button>

          {/* User Avatar */}
          <div className="flex h-8 w-8 cursor-pointer select-none items-center justify-center rounded-lg border border-cyan-500/30 bg-gradient-to-tr from-cyan-950 to-blue-900 text-xs font-bold text-cyan-200 shadow-[0_0_10px_rgba(6,182,212,0.2)] transition-transform hover:scale-105 active:scale-95">
            A
          </div>
        </div>

      </div>
    </header>
  );
}