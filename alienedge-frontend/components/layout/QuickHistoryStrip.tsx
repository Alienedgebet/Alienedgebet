"use client";

import { useSelectedDate } from "@/lib/date-context";
import { cn } from "@/lib/utils";
import { History, Calendar } from "lucide-react";

export function QuickHistoryStrip() {
  const { date, setDate } = useSelectedDate();

  const getDateOffset = (offsetDays: number) => {
    const d = new Date();
    d.setDate(d.getDate() - offsetDays);
    return d.toISOString().split("T")[0];
  };

  const buttons = [
    { label: "Today", value: getDateOffset(0), badge: "LIVE" },
    { label: "Yesterday", value: getDateOffset(1), badge: "AUDIT" },
    { label: "2 Days Ago", value: getDateOffset(2) },
    { label: "3 Days Ago", value: getDateOffset(3) },
    { label: "4 Days Ago", value: getDateOffset(4) },
    { label: "5 Days Ago", value: getDateOffset(5) },
  ];

  return (
    <div className="flex w-full items-center justify-between gap-3 overflow-x-auto rounded-xl border border-white/10 bg-[#090e1a]/90 p-2 shadow-panel backdrop-blur-md scrollbar-none">
      <div className="flex items-center gap-2 px-2 shrink-0">
        <History className="h-4 w-4 text-cyan-400" />
        <span className="text-xs font-black uppercase tracking-wider text-slate-300">
          Track Record Audit:
        </span>
      </div>

      <div className="flex items-center gap-2 shrink-0">
        {buttons.map((b) => {
          const isActive = date === b.value;
          return (
            <button
              key={b.value}
              onClick={() => setDate(b.value)}
              className={cn(
                "flex items-center gap-1.5 rounded-lg border px-3 py-1.5 font-mono text-xs font-bold transition-all active:scale-95",
                isActive
                  ? "border-cyan-400 bg-gradient-to-r from-cyan-500/20 to-blue-600/20 text-cyan-200 shadow-[0_0_15px_rgba(6,182,212,0.3)]"
                  : "border-white/5 bg-white/5 text-slate-400 hover:border-white/20 hover:text-white"
              )}
            >
              <Calendar className="h-3 w-3" />
              <span>{b.label}</span>
              {b.badge && (
                <span
                  className={cn(
                    "ml-1 rounded px-1 py-0.2 text-[9px] font-black uppercase tracking-wider",
                    b.badge === "LIVE"
                      ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                      : "bg-cyan-500/20 text-cyan-300 border border-cyan-500/30"
                  )}
                >
                  {b.badge}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
