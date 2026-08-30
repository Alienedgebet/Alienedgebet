"use client";

import { useEffect, useState } from "react";
import { Bell, Flame, CheckCircle, Activity, Radio, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { useSelectedDate } from "@/lib/date-context";
import { QuickHistoryStrip } from "@/components/layout/QuickHistoryStrip";

export interface LiveAlertRecord {
  f_id: string;
  fixture: string;
  time: string;
  minute: number;
  level: "🔥 PREMIUM" | "✅ STANDARD" | "📊 MONITOR" | string;
  confidence: number;
  msg: string;
  session?: string;
  user_id?: string;
  rule_id?: string;
  rule_label?: string;
}

const MOCK_LIVE_ALERTS: LiveAlertRecord[] = [
  {
    f_id: "fx_901",
    fixture: "Arsenal vs Liverpool",
    time: new Date().toISOString(),
    minute: 45,
    level: "🔥 PREMIUM",
    confidence: 88.5,
    msg: "Arsenal vs Liverpool — 45' Verified Handshake. Chaos: 7.4 | H-xG: 1.62 A-xG: 0.90 | Pressure: 62% Home",
    rule_label: "VIP 45' Handshake Engine",
  },
  {
    f_id: "fx_902",
    fixture: "Real Madrid vs Alaves",
    time: new Date().toISOString(),
    minute: 34,
    level: "🔥 PREMIUM",
    confidence: 82.0,
    msg: "Real Madrid Dominance Surge — 8 SOT, 14 Box Attacks, High xG Slope (+0.45)",
    rule_label: "Home Dominance Spike",
  },
  {
    f_id: "fx_903",
    fixture: "Bayern Munich vs Stuttgart",
    time: new Date().toISOString(),
    minute: 68,
    level: "✅ STANDARD",
    confidence: 64.0,
    msg: "Second-Half BTTS Trigger — Away substitute threat active, Chaos Index: 5.8",
    rule_label: "2H Volatility Special",
  },
  {
    f_id: "fx_904",
    fixture: "Napoli vs Roma",
    time: new Date().toISOString(),
    minute: 22,
    level: "📊 MONITOR",
    confidence: 45.0,
    msg: "Early Momentum Build — High corner acceleration (4 corners in 6 mins)",
    rule_label: "Corner Surge Tracker",
  },
];

export default function LiveAlertScannerPage() {
  const { date } = useSelectedDate();
  const [alerts, setAlerts] = useState<LiveAlertRecord[]>(MOCK_LIVE_ALERTS);
  const [filterLevel, setFilterLevel] = useState<"ALL" | "PREMIUM" | "STANDARD" | "MONITOR">("ALL");
  const [refreshing, setRefreshing] = useState(false);

  const handleRefresh = () => {
    setRefreshing(true);
    setTimeout(() => {
      setRefreshing(false);
    }, 600);
  };

  const filteredAlerts = alerts.filter((a) => {
    if (filterLevel === "PREMIUM") return a.level.includes("PREMIUM");
    if (filterLevel === "STANDARD") return a.level.includes("STANDARD");
    if (filterLevel === "MONITOR") return a.level.includes("MONITOR");
    return true;
  });

  return (
    <div className="flex flex-col gap-4 p-3.5 sm:p-5 md:p-6 max-w-7xl mx-auto w-full">
      {/* ── 1. COMPACT TOP BANNER ──────────────────────────────── */}
      <div className="glass flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-[#0c1220]/90 px-4 py-3 shadow-panel backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-amber-500/30 bg-amber-950/20 shadow-[0_0_12px_rgba(245,158,11,0.2)]">
            <Bell className="h-4 w-4 text-amber-400 animate-pulse" />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-text-primary flex items-center gap-2">
              Live Alert Scanner
              <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.2 font-mono text-[9px] font-bold text-emerald-400">
                LIVE ORCHESTRATOR
              </span>
            </h1>
            <p className="text-[11px] text-text-secondary">
              Real-time Code 6 forensic triggers, 45&apos; AI verification gates &amp; custom alert streams
            </p>
          </div>
        </div>

        <button
          onClick={handleRefresh}
          className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs font-bold text-slate-300 hover:text-white transition-all active:scale-95"
        >
          <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin text-cyan-400")} />
          <span className="hidden sm:inline">Refresh</span>
        </button>
      </div>

      {/* ── 2. 5-DAY HISTORY AUDIT STRIP ─────────────────────────────── */}
      <QuickHistoryStrip />

      {/* ── 3. FILTER PILLS BAR ──────────────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 pb-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            onClick={() => setFilterLevel("ALL")}
            className={cn(
              "rounded-lg border px-3 py-1.5 text-xs font-bold transition-all",
              filterLevel === "ALL"
                ? "border-cyan-400 bg-cyan-500/10 text-cyan-300 shadow-[0_0_10px_rgba(6,182,212,0.2)]"
                : "border-white/10 bg-white/5 text-slate-400 hover:text-white"
            )}
          >
            All Alerts ({alerts.length})
          </button>
          <button
            onClick={() => setFilterLevel("PREMIUM")}
            className={cn(
              "flex items-center gap-1 rounded-lg border px-3 py-1.5 text-xs font-bold transition-all",
              filterLevel === "PREMIUM"
                ? "border-amber-500/50 bg-amber-950/50 text-amber-300 shadow-[0_0_10px_rgba(245,158,11,0.2)]"
                : "border-white/10 bg-white/5 text-slate-400 hover:text-white"
            )}
          >
            <Flame className="h-3 w-3 text-amber-400" />
            🔥 Premium (≥50%)
          </button>
          <button
            onClick={() => setFilterLevel("STANDARD")}
            className={cn(
              "flex items-center gap-1 rounded-lg border px-3 py-1.5 text-xs font-bold transition-all",
              filterLevel === "STANDARD"
                ? "border-emerald-500/50 bg-emerald-950/50 text-emerald-300 shadow-[0_0_10px_rgba(16,185,129,0.2)]"
                : "border-white/10 bg-white/5 text-slate-400 hover:text-white"
            )}
          >
            <CheckCircle className="h-3 w-3 text-emerald-400" />
            ✅ Standard (≥30%)
          </button>
          <button
            onClick={() => setFilterLevel("MONITOR")}
            className={cn(
              "flex items-center gap-1 rounded-lg border px-3 py-1.5 text-xs font-bold transition-all",
              filterLevel === "MONITOR"
                ? "border-indigo-500/50 bg-indigo-950/50 text-indigo-300 shadow-[0_0_10px_rgba(99,102,241,0.2)]"
                : "border-white/10 bg-white/5 text-slate-400 hover:text-white"
            )}
          >
            <Activity className="h-3 w-3 text-indigo-400" />
            📊 Monitor
          </button>
        </div>

        <span className="text-[11px] font-mono text-slate-400">
          Showing {filteredAlerts.length} triggered signals
        </span>
      </div>

      {/* ── 4. LIVE ALERTS STREAM CARDS ──────────────────────────────── */}
      <div className="flex flex-col gap-3">
        {filteredAlerts.map((alert, idx) => {
          const isPremium = alert.level.includes("PREMIUM");
          const isStandard = alert.level.includes("STANDARD");

          return (
            <div
              key={idx}
              className={cn(
                "glass relative flex flex-col gap-2 rounded-xl border p-4 shadow-xl backdrop-blur-md transition-all hover:border-cyan-500/40",
                isPremium
                  ? "border-amber-500/30 bg-[#0d1322]/90 shadow-[0_0_15px_rgba(245,158,11,0.08)]"
                  : isStandard
                  ? "border-emerald-500/30 bg-[#0d1322]/90 shadow-[0_0_15px_rgba(16,185,129,0.08)]"
                  : "border-white/10 bg-[#0d1322]/90"
              )}
            >
              {/* Header Row: Fixture, Minute Badge, Tier & Conf */}
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/5 pb-2">
                <div className="flex items-center gap-2">
                  <span className="rounded-md border border-amber-500/40 bg-amber-950/40 px-2 py-0.5 font-mono text-xs font-black text-amber-300">
                    {alert.minute}&apos;
                  </span>
                  <h3 className="text-sm font-black text-white">{alert.fixture}</h3>
                </div>

                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "rounded-md border px-2 py-0.5 text-[10px] font-black tracking-wide",
                      isPremium
                        ? "border-amber-500/40 bg-amber-950/40 text-amber-300"
                        : isStandard
                        ? "border-emerald-500/40 bg-emerald-950/40 text-emerald-300"
                        : "border-indigo-500/40 bg-indigo-950/40 text-indigo-300"
                    )}
                  >
                    {alert.level}
                  </span>

                  <span className="font-mono text-xs font-bold text-emerald-400">
                    {alert.confidence}% Conf
                  </span>
                </div>
              </div>

              {/* Message Content */}
              <p className="text-xs font-mono text-slate-300 leading-relaxed">
                {alert.msg}
              </p>

              {/* Footer: Rule tag + Timestamp */}
              <div className="flex items-center justify-between border-t border-white/5 pt-2 text-[10px] font-mono text-slate-400">
                <span>
                  Source: <strong className="text-cyan-300">{alert.rule_label || "Code 6 Engine"}</strong>
                </span>
                <span>{new Date(alert.time).toLocaleTimeString()} UTC</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
