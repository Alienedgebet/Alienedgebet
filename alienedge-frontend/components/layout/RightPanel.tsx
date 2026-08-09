"use client";

import { useState } from "react";
import {
  Crown,
  Lock,
  MessageSquare,
  Send,
  Shield,
  TrendingUp,
  X,
} from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { getProbColor, getTierEmoji } from "@/lib/api";
import { useRightPanel } from "@/lib/right-panel-context";

// ── Mock types ────────────────────────────────────────────────────────────────
// Replaced in Phase 13 with real types from socialApi in lib/api.ts

interface WarRoomMessage {
  id: string;
  user: string;
  accuracy: number;
  market: "GG" | "O2.5" | "Win" | "Draw" | "SH" | "Corner";
  time: string;
  message: string;
}

interface LeaderboardEntry {
  rank: number;
  user: string;
  accuracy: number;
  totalPicks: number;
  streak: number;
  tier: string;
}

// ── Mock data ─────────────────────────────────────────────────────────────────

const MOCK_WAR_ROOM: WarRoomMessage[] = [
  {
    id: "1",
    user: "Cerberus",
    accuracy: 71,
    market: "GG",
    time: "2m",
    message:
      "GG on Man City vs Arsenal — DNA + H2H convergence. BTTS venue 78%, H2H 71%. Tier 1 lock.",
  },
  {
    id: "2",
    user: "AlphaHunt",
    accuracy: 68,
    market: "O2.5",
    time: "5m",
    message:
      "Over 2.5 Valencia — council 8/9, Poisson 74%. Combined lambda 2.91. Clean add.",
  },
  {
    id: "3",
    user: "Forensix",
    accuracy: 65,
    market: "Draw",
    time: "9m",
    message:
      "Draw alert PSG vs Lyon — DMI 0.82, both no-win last 4, parity gap 2. Watching.",
  },
  {
    id: "4",
    user: "SH_Oracle",
    accuracy: 62,
    market: "SH",
    time: "14m",
    message:
      "2H GG Atletico confirmed. SH pressure 78, late threat HIGH, SH master T1.",
  },
  {
    id: "5",
    user: "VaultBreaker",
    accuracy: 59,
    market: "Win",
    time: "18m",
    message:
      "Win forecast Benfica — parity 12, form W4/5, h2h dominant 3/5. Low risk.",
  },
  {
    id: "6",
    user: "EdgeMapper",
    accuracy: 57,
    market: "Corner",
    time: "23m",
    message:
      "Corner catalyst on Dortmund — home pressure 8.2 exp, wounded beast flag home. Tier 2.",
  },
];

const MOCK_LEADERBOARD: LeaderboardEntry[] = [
  { rank: 1, user: "Cerberus",     accuracy: 71.4, totalPicks: 312, streak: 7, tier: "diamond"  },
  { rank: 2, user: "AlphaHunt",    accuracy: 68.2, totalPicks: 248, streak: 4, tier: "diamond"  },
  { rank: 3, user: "Forensix",     accuracy: 65.8, totalPicks: 190, streak: 2, tier: "fire"     },
  { rank: 4, user: "SH_Oracle",    accuracy: 63.1, totalPicks: 175, streak: 5, tier: "fire"     },
  { rank: 5, user: "VaultBreaker", accuracy: 59.7, totalPicks: 143, streak: 1, tier: "solid"    },
  { rank: 6, user: "Meridian",     accuracy: 57.3, totalPicks: 120, streak: 0, tier: "solid"    },
  { rank: 7, user: "EdgeMapper",   accuracy: 55.9, totalPicks: 105, streak: 3, tier: "solid"    },
  { rank: 8, user: "ZonePress",    accuracy: 54.1, totalPicks:  98, streak: 0, tier: "monitor"  },
];

// ── Style maps ────────────────────────────────────────────────────────────────

const MARKET_STYLE: Record<WarRoomMessage["market"], string> = {
  GG:     "border-accent-cyan/25   bg-accent-cyan/10   text-accent-cyan",
  "O2.5": "border-accent-indigo/25 bg-accent-indigo/10 text-accent-indigo",
  Win:    "border-accent-green/25  bg-accent-green/10  text-accent-green",
  Draw:   "border-accent-amber/25  bg-accent-amber/10  text-accent-amber",
  SH:     "border-accent-purple/25 bg-accent-purple/10 text-accent-purple",
  Corner: "border-accent-blue/25   bg-accent-blue/10   text-accent-blue",
};

const RANK_STYLE: Record<number, string> = {
  1: "bg-accent-indigo/20 text-accent-indigo",
  2: "bg-accent-cyan/15   text-accent-cyan",
  3: "bg-accent-amber/15  text-accent-amber",
};

// ── Root panel ────────────────────────────────────────────────────────────────

export function RightPanel() {
  const [tab, setTab] = useState<"warroom" | "leaderboard">("warroom");
  const { mobileOpen, close } = useRightPanel();

  return (
    <>
      {/* Mobile backdrop — tap to close. Desktop never renders this (panel is always docked, not an overlay). */}
      {mobileOpen && (
        <div
          aria-hidden
          className="fixed inset-0 z-[54] bg-black/60 md:hidden"
          onClick={close}
        />
      )}

      <aside
        className={cn(
          "fixed inset-y-0 right-0 top-[56px] z-[55] flex h-[calc(100vh-56px)] w-[85vw] max-w-[320px] flex-col border-l border-border bg-bg-primary",
          "transition-transform duration-200 ease-ae-ease",
          mobileOpen ? "translate-x-0" : "translate-x-full",
          "md:w-[320px] md:translate-x-0"
        )}
      >
        {/* Tab switcher */}
        <div className="flex shrink-0 items-center border-b border-border">
          <div className="flex flex-1">
            {(
              [
                { id: "warroom",     label: "War Room",    icon: MessageSquare },
                { id: "leaderboard", label: "Leaderboard", icon: Crown         },
              ] as const
            ).map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                className={cn(
                  "flex flex-1 items-center justify-center gap-1.5 border-b-2 py-3 text-xs font-medium transition-colors",
                  tab === id
                    ? "border-accent-indigo text-text-primary"
                    : "border-transparent text-text-muted hover:text-text-secondary"
                )}
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
              </button>
            ))}
          </div>
          {/* Close — mobile drawer only, panel is always visible on desktop */}
          <button
            type="button"
            onClick={close}
            aria-label="Close panel"
            className="mx-2 flex h-7 w-7 shrink-0 items-center justify-center rounded border border-border text-text-muted transition-colors hover:border-border-bright hover:text-text-primary md:hidden"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>

        {tab === "warroom" ? <WarRoomTab /> : <LeaderboardTab />}
      </aside>
    </>
  );
}

// ── War Room tab ──────────────────────────────────────────────────────────────

function WarRoomTab() {
  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Access gate notice */}
      <div className="flex shrink-0 items-center gap-2 border-b border-border bg-bg-elevated/30 px-3 py-2">
        <Lock className="h-3 w-3 shrink-0 text-accent-amber" />
        <p className="text-2xs text-text-muted">
          Post requires{" "}
          <span className="font-medium text-accent-amber">accuracy &gt; 55%</span>
        </p>
      </div>

      {/* Message feed */}
      <ScrollArea className="flex-1">
        <div className="divide-y divide-border/40">
          {MOCK_WAR_ROOM.map((msg) => (
            <div
              key={msg.id}
              className="px-3 py-3 transition-colors hover:bg-bg-elevated/20"
            >
              {/* Message header */}
              <div className="mb-1.5 flex items-center gap-2">
                <span className="text-xs font-semibold text-text-primary">
                  {msg.user}
                </span>
                <span className={cn("font-mono text-2xs", getProbColor(msg.accuracy))}>
                  {msg.accuracy}%
                </span>
                <div className="ml-auto flex items-center gap-1.5">
                  <span
                    className={cn(
                      "rounded border px-1.5 py-0.5 text-2xs font-medium",
                      MARKET_STYLE[msg.market]
                    )}
                  >
                    {msg.market}
                  </span>
                  <span className="text-2xs text-text-dim">{msg.time}</span>
                </div>
              </div>
              {/* Message body */}
              <p className="text-xs leading-relaxed text-text-secondary">
                {msg.message}
              </p>
            </div>
          ))}
        </div>
      </ScrollArea>

      {/* Compose — disabled until Phase 13 auth */}
      <div className="shrink-0 border-t border-border p-3">
        <div className="flex cursor-not-allowed items-center gap-2 rounded border border-border bg-bg-elevated px-3 py-2 opacity-40">
          <Shield className="h-3.5 w-3.5 text-text-dim" />
          <span className="flex-1 text-xs text-text-dim">Sign in to post…</span>
          <Send className="h-3.5 w-3.5 text-text-dim" />
        </div>
        <p className="mt-1.5 text-center font-mono text-2xs text-text-dim">
          Social layer · Phase 13
        </p>
      </div>
    </div>
  );
}

// ── Leaderboard tab ───────────────────────────────────────────────────────────

function LeaderboardTab() {
  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Sub-header */}
      <div className="flex shrink-0 items-center justify-between border-b border-border bg-bg-elevated/30 px-3 py-2">
        <div className="flex items-center gap-1.5">
          <TrendingUp className="h-3.5 w-3.5 text-accent-green" />
          <span className="text-2xs font-semibold uppercase tracking-wider text-text-secondary">
            Ranked by accuracy
          </span>
        </div>
        <span className="font-mono text-2xs text-text-dim">min 50 picks</span>
      </div>

      {/* Entries */}
      <ScrollArea className="flex-1">
        <div className="divide-y divide-border/40">
          {MOCK_LEADERBOARD.map((entry) => (
            <div
              key={entry.rank}
              className="flex items-center gap-2.5 px-3 py-2.5 transition-colors hover:bg-bg-elevated/20"
            >
              {/* Rank badge */}
              <div
                className={cn(
                  "flex h-6 w-6 shrink-0 items-center justify-center rounded font-mono text-xs font-bold",
                  RANK_STYLE[entry.rank] ?? "bg-bg-elevated text-text-muted"
                )}
              >
                {entry.rank}
              </div>

              {/* User info */}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="truncate text-xs font-semibold text-text-primary">
                    {entry.user}
                  </span>
                  <span className="text-xs">{getTierEmoji(entry.tier)}</span>
                </div>
                <div className="mt-0.5 flex items-center gap-2">
                  <span className="font-mono text-2xs text-text-muted">
                    {entry.totalPicks} picks
                  </span>
                  {entry.streak > 0 && (
                    <span className="text-2xs text-accent-amber">
                      🔥 {entry.streak}
                    </span>
                  )}
                </div>
              </div>

              {/* Accuracy */}
              <span
                className={cn(
                  "font-mono text-sm font-bold",
                  getProbColor(entry.accuracy)
                )}
              >
                {entry.accuracy.toFixed(1)}%
              </span>
            </div>
          ))}
        </div>
      </ScrollArea>

      <div className="shrink-0 border-t border-border p-3 text-center">
        <p className="font-mono text-2xs text-text-dim">Social backend · Phase 13</p>
      </div>
    </div>
  );
}
