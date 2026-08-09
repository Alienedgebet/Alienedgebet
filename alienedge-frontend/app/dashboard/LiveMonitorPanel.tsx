"use client";

import Link from "next/link";
import { Bell, ChevronRight, Inbox, Radio, Shield } from "lucide-react";
import { cn } from "@/lib/utils";

const LIVE_LINKS = [
  {
    href: "/live/edges",
    label: "Live Match Edges",
    desc: "Codes 1–2 · strategic audit + validation",
    icon: Shield,
    accent: "text-accent-indigo bg-accent-indigo/15 border-accent-indigo/30",
  },
  {
    href: "/live/incoming",
    label: "Incoming Live Matches",
    desc: "Codes 3–5 · forensics · danger · handshake",
    icon: Inbox,
    accent: "text-accent-cyan bg-accent-cyan/15 border-accent-cyan/30",
  },
  {
    href: "/live/alerts",
    label: "Live Alert Scanner",
    desc: "Code 6 · VIP + free LIVE orchestrator",
    icon: Bell,
    accent: "text-accent-amber bg-accent-amber/15 border-accent-amber/30",
  },
] as const;

/** Dashboard entry to the three live monitor routes — click → instant page. */
export function LiveMonitorPanel() {
  return (
    <div className="glass overflow-hidden rounded-lg shadow-panel">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent-red/15">
            <Radio className="h-3.5 w-3.5 text-accent-red" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-text-primary">Live Monitor</h2>
            <p className="text-2xs text-text-dim">In-play forensics · open a board</p>
          </div>
        </div>
        <span className="inline-flex items-center gap-1 rounded border border-accent-red/30 bg-accent-red/10 px-1.5 py-0.5 text-2xs font-bold text-accent-red">
          <span className="h-1.5 w-1.5 animate-live-pulse rounded-full bg-accent-red" />
          LIVE
        </span>
      </div>

      <div className="grid gap-0 sm:grid-cols-3">
        {LIVE_LINKS.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              prefetch
              className="group flex items-start gap-3 border-b border-border/60 px-4 py-3.5 transition-colors last:border-b-0 hover:bg-bg-elevated/50 sm:border-b-0 sm:border-r sm:last:border-r-0"
            >
              <div
                className={cn(
                  "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border",
                  item.accent
                )}
              >
                <Icon className="h-3.5 w-3.5" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-1 text-xs font-semibold text-text-primary">
                  {item.label}
                  <ChevronRight className="h-3 w-3 text-text-dim opacity-0 transition-opacity group-hover:opacity-100" />
                </p>
                <p className="mt-0.5 text-2xs leading-snug text-text-dim">{item.desc}</p>
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
