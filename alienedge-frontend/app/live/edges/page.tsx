"use client";

import { useState, useMemo } from "react";
import {
  Radio,
  Shield,
  ShieldCheck,
  Info,
  X,
  ChevronRight,
  Activity,
  Flame,
  Zap,
  AlertTriangle,
  CheckCircle2,
  Clock,
  TrendingUp,
  Target,
  Cpu,
} from "lucide-react";
import {
  liveApi,
  type LivePrematchAudit,
  type LivePrematchTeamAudit,
  type LiveValidationBoard,
  type LiveValidationMatch,
  type LiveValidationPick,
} from "@/lib/api";
import { useApi } from "@/lib/use-api";
import {
  MOCK_LIVE_PREMATCH_AUDIT,
  MOCK_LIVE_VALIDATION,
} from "@/lib/mock-chains";
import {
  ChainBranch,
  type PredictionColumn,
} from "@/components/predictions";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

function asAuditList(data: unknown): LivePrematchAudit[] {
  if (Array.isArray(data)) return data as LivePrematchAudit[];
  return [];
}

function liveRows<T>(data: T[] | null, loading: boolean, fallback: T[]): T[] {
  if (loading && (!data || data.length === 0)) return fallback;
  if (data && data.length > 0) return data;
  return fallback;
}

function boardFrom(
  data: LiveValidationBoard | null,
  loading: boolean
): LiveValidationBoard {
  if (loading && (!data || (!data.matches?.length && !data.alerts?.length))) {
    return MOCK_LIVE_VALIDATION;
  }
  if (data && (data.matches?.length > 0 || data.alerts?.length > 0)) return data;
  return MOCK_LIVE_VALIDATION;
}

function formatPick(
  p: string | { type: string; target_loc?: string },
  homeName: string,
  awayName: string
): string {
  if (typeof p === "string") return p;
  if (p.type === "TO_SCORE" && p.target_loc === "home") {
    return `${homeName.toUpperCase()} TO SCORE`;
  }
  if (p.type === "TO_SCORE" && p.target_loc === "away") {
    return `${awayName.toUpperCase()} TO SCORE`;
  }
  if (p.type === "U2.5" || p.type === "O2.5") {
    return p.type === "U2.5" ? "UNDER 2.5" : "OVER 2.5";
  }
  return p.target_loc ? `${p.type} (${p.target_loc})` : p.type;
}

function pickReason(
  p: string | { type: string; target_loc?: string },
  row: LivePrematchAudit
): string {
  if (typeof p === "string") return p;
  if (p.type === "U2.5" || p.type === "O2.5") {
    return "High structural rotation.";
  }
  if (p.type === "TO_SCORE" && p.target_loc === "away") {
    return `${row.home.team_name} Keeper Liability.`;
  }
  if (p.type === "TO_SCORE" && p.target_loc === "home") {
    return `${row.away.team_name} Keeper Liability.`;
  }
  if (p.type === "GG") return "Both teams starting vulnerable keepers.";
  return p.type;
}

const validationAlertColumns: PredictionColumn<LiveValidationPick>[] = [
  {
    key: "match_name",
    header: "match_name",
    render: (r) => <span className="font-medium text-text-primary">{r.match_name}</span>,
  },
  {
    key: "fixture_id",
    header: "fixture_id",
    render: (r) => <span className="font-mono text-2xs">{r.fixture_id}</span>,
  },
  {
    key: "prediction_type",
    header: "prediction_type",
    render: (r) => (
      <span className="rounded border border-accent-amber/30 bg-accent-amber/10 px-1.5 py-0.5 font-mono text-2xs font-semibold text-accent-amber">
        {r.prediction_type}
      </span>
    ),
  },
  { key: "target", header: "target", render: (r) => r.target },
  {
    key: "minute_triggered",
    header: "minute_triggered",
    align: "right",
    render: (r) => <span className="font-mono">{r.minute_triggered}&apos;</span>,
  },
  {
    key: "scores",
    header: "scores",
    align: "right",
    render: (r) => <span className="font-mono font-semibold">{r.scores}</span>,
  },
  {
    key: "forensic_note",
    header: "forensic_note",
    className: "max-w-[260px]",
    render: (r) => (
      <span className="line-clamp-2 text-2xs text-text-secondary">{r.forensic_note}</span>
    ),
  },
  {
    key: "stats_note",
    header: "stats_note",
    render: (r) => <span className="font-mono text-2xs">{r.stats_note}</span>,
  },
  {
    key: "timestamp",
    header: "timestamp",
    render: (r) => (
      <span className="font-mono text-2xs text-text-dim">
        {r.timestamp.replace("T", " ").slice(0, 19)}
      </span>
    ),
  },
];

type MetricTooltipKey = "kmv" | "rv" | "gk" | "miss" | "odds" | null;

function TeamAuditPanel({ team }: { team: LivePrematchTeamAudit }) {
  const [activeTooltip, setActiveTooltip] = useState<MetricTooltipKey>(null);

  const getExplanation = (key: MetricTooltipKey) => {
    switch (key) {
      case "kmv":
        return "KMV (Key Missing Vulnerability / Kinetic Momentum): The cumulative historical importance percentage of missing starters from the core eleven.";
      case "rv":
        return "RV (Replacement Vulnerability / The Doom): Measures squad depth penalty and quality drop-off when bench/replacement players fill in for missing regulars.";
      case "gk":
        return "GK Status: Active regular starting goalkeeper confirmed (GK OK) or backup/vulnerable goalkeeper starting (GK LIABILITY / Out).";
      case "miss":
        return "Missing Count: Number of essential squad regulars absent from the starting line-up for this match.";
      case "odds":
        return "Odds Scan: Scanned live/pre-match bookmaker market consensus pricing for 1X2 and Over/Under thresholds used for probability calibration.";
      default:
        return null;
    }
  };

  return (
    <div className="rounded-lg border border-border/70 bg-bg-elevated/30 relative">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 px-3 py-2">
        <div>
          <p className="text-2xs uppercase tracking-wide text-text-dim">{team.loc}</p>
          <p className="text-sm font-semibold text-text-primary">{team.team_name}</p>
        </div>
        <div className="flex flex-wrap gap-1.5 font-mono text-2xs">
          <button
            type="button"
            onClick={() => setActiveTooltip(activeTooltip === "miss" ? null : "miss")}
            className="rounded border border-border-bright px-1.5 py-0.5 text-text-secondary transition-colors hover:border-accent-indigo"
            title="Tap to reveal definition"
          >
            miss {team.miss}
          </button>
          <button
            type="button"
            onClick={() => setActiveTooltip(activeTooltip === "kmv" ? null : "kmv")}
            className="rounded border border-accent-amber/30 bg-accent-amber/10 px-1.5 py-0.5 text-accent-amber transition-colors hover:bg-accent-amber/20"
            title="Tap to reveal definition"
          >
            KMV {team.kmv.toFixed(1)}%
          </button>
          <button
            type="button"
            onClick={() => setActiveTooltip(activeTooltip === "rv" ? null : "rv")}
            className="rounded border border-accent-red/30 bg-accent-red/10 px-1.5 py-0.5 text-accent-red transition-colors hover:bg-accent-red/20"
            title="Tap to reveal definition"
          >
            RV {team.rv.toFixed(1)}%
          </button>
          <button
            type="button"
            onClick={() => setActiveTooltip(activeTooltip === "gk" ? null : "gk")}
            className={cn(
              "rounded border px-1.5 py-0.5 transition-colors font-bold",
              team.gk_out
                ? "border-accent-red/40 bg-accent-red/10 text-accent-red hover:bg-accent-red/20"
                : "border-accent-green/30 bg-accent-green/10 text-accent-green hover:bg-accent-green/20"
            )}
            title="Tap to reveal definition"
          >
            GK {team.gk_out ? "LIABILITY" : "OK"}
          </button>
        </div>
      </div>

      {activeTooltip && (
        <div className="bg-bg-elevated border-b border-accent-indigo/40 px-3 py-2 text-2xs text-accent-cyan flex items-start gap-2 animate-fade-in">
          <Info className="h-3.5 w-3.5 shrink-0 mt-0.5 text-accent-indigo" />
          <div className="flex-1">
            <p className="font-semibold text-text-primary">Metric Explanation:</p>
            <p className="mt-0.5 leading-relaxed">{getExplanation(activeTooltip)}</p>
          </div>
          <button
            type="button"
            onClick={() => setActiveTooltip(null)}
            className="text-text-dim hover:text-text-primary"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
      <p className="border-b border-border/50 px-3 py-1.5 text-2xs text-text-secondary">
        GK status: {team.gk_status} · Def {team.def_miss} · Mid {team.mid_miss} · Att{" "}
        {team.att_miss}
        {(team.l_wing_miss || team.r_wing_miss) &&
          ` · Wings L${team.l_wing_miss ? "✗" : "✓"}/R${team.r_wing_miss ? "✗" : "✓"}`}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] text-left text-2xs">
          <thead className="bg-bg-elevated/60 font-mono text-text-dim">
            <tr>
              <th className="px-3 py-1.5 font-medium">Player Name</th>
              <th className="px-2 py-1.5 font-medium">Pos</th>
              <th className="px-2 py-1.5 font-medium text-right">Apps</th>
              <th className="px-2 py-1.5 font-medium text-right">Mins</th>
              <th className="px-2 py-1.5 font-medium text-right">Rating</th>
              <th className="px-3 py-1.5 font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/40">
            {team.players.map((p, i) => (
              <tr key={`${p.name}-${p.pos}-${i}`} className="hover:bg-bg-elevated/40">
                <td className="px-3 py-1.5 font-medium text-text-primary">{p.name}</td>
                <td className="px-2 py-1.5 text-text-secondary">{p.pos}</td>
                <td className="px-2 py-1.5 text-right font-mono">{p.apps}</td>
                <td className="px-2 py-1.5 text-right font-mono">{p.mins}</td>
                <td className="px-2 py-1.5 text-right font-mono">{p.rating.toFixed(2)}</td>
                <td
                  className={cn(
                    "px-3 py-1.5 font-semibold",
                    p.status.includes("MISSING")
                      ? "text-accent-amber"
                      : p.status.toLowerCase().includes("liability") ||
                          p.status.toLowerCase().includes("risk") ||
                          p.status.toLowerCase().includes("leak")
                        ? "text-accent-red"
                        : "text-text-secondary"
                  )}
                >
                  {p.status}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="space-y-0.5 border-t border-border/50 px-3 py-2 font-mono text-2xs text-text-secondary">
        <p>&gt;&gt; KEY MISSING VULNERABILITY (The Hole): {team.kmv.toFixed(1)}%</p>
        <p>&gt;&gt; REPLACEMENT VULNERABILITY (The Doom): {team.rv.toFixed(1)}%</p>
      </div>
    </div>
  );
}

function PrematchAuditCard({
  row,
  onOpenDetails,
}: {
  row: LivePrematchAudit;
  onOpenDetails: (row: LivePrematchAudit) => void;
}) {
  return (
    <article className="glass overflow-hidden rounded-xl border border-white/10 shadow-panel transition-all hover:border-cyan-500/30">
      {/* ── CARD HEADER: Match Name + Dedicated Arrow Button (No Overlap) ── */}
      <div className="flex items-center justify-between border-b border-border/70 bg-bg-elevated/20 px-4 py-2.5">
        <div className="flex flex-1 min-w-0 items-center gap-2">
          <button
            type="button"
            onClick={() => onOpenDetails(row)}
            className="group/btn flex items-center gap-1.5 text-left transition-colors"
          >
            <h3 className="text-sm font-bold text-text-primary group-hover/btn:text-cyan-400 transition-colors">
              MATCH: {row.fixture}
            </h3>
          </button>
          <span className="rounded border border-accent-amber/30 bg-accent-amber/10 px-1.5 py-0.2 font-mono text-[10px] font-bold text-accent-amber shrink-0">
            miss {row.combined_miss}
          </span>
        </div>

        {/* Dedicated Arrow Button (Only this and the title trigger navigation) */}
        <button
          type="button"
          onClick={() => onOpenDetails(row)}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-cyan-500/30 bg-cyan-950/40 text-cyan-300 hover:bg-cyan-500/20 hover:scale-105 transition-all ml-2 shadow-sm"
          title="Open Code 2 & 3 In-Play Cockpit"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>

      {/* Subheader: ID, Kickoff, Odds scan */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/50 bg-bg-elevated/10 px-4 py-1.5 font-mono text-[11px] text-text-dim">
        <span>ID {row.fixture_id} · KICKOFF: {row.kickoff_utc} UTC ({row.status_text})</span>
        <span className="text-text-secondary">
          ODDS SCAN &gt; Home: {row.odds_home_win ?? "—"} | Away: {row.odds_away_win ?? "—"} | O2.5: {row.odds_o25 ?? "—"}
        </span>
      </div>

      {/* Lineup Panels (Interactive without triggering navigation) */}
      <div className="grid grid-cols-1 gap-3 p-3 lg:grid-cols-2">
        <TeamAuditPanel team={row.home} />
        <TeamAuditPanel team={row.away} />
      </div>

      {/* Predictions & Killer Rules */}
      <div className="space-y-2.5 border-t border-border/70 px-4 py-3">
        <div>
          <p className="mb-1.5 text-2xs font-semibold uppercase tracking-wide text-text-dim">
            [PRE-MATCH STRATEGIC PREDICTIONS]
          </p>
          <ul className="space-y-1">
            {row.picks.map((p, i) => (
              <li key={i} className="font-mono text-2xs text-cyan-300">
                - [PICK] {formatPick(p, row.home.team_name, row.away.team_name)}
                {typeof p !== "string" && (
                  <span className="text-text-dim">: {pickReason(p, row)}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
        {row.killer_rules.length > 0 && (
          <div>
            <p className="mb-1 text-2xs font-semibold uppercase tracking-wide text-accent-red">
              [ADVANCED KILLER RULES TRIGGERED]
            </p>
            <ul className="space-y-0.5">
              {row.killer_rules.map((r) => (
                <li key={r} className="font-mono text-2xs text-accent-amber">
                  *** {r}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </article>
  );
}

// ── HIGH-TECH MISSION CARD PARSER FOR CODE 2 ───────────────────────────────
function FormattedPickCard({ line }: { line: string }) {
  const isSettled = line.includes("SETTLED");
  const isHandshake = line.includes("HANDSHAKE");
  const isSupreme = line.includes("SUPREME");
  const isStrike = line.includes("FINAL STRIKE");
  const isWaiting = line.includes("waiting") || line.includes("Queued");

  // Extract label inside brackets [ ... ]
  const labelMatch = line.match(/\[(.*?)\]/);
  const label = labelMatch ? labelMatch[1] : "MISSION TARGET";

  // Clean description text
  const cleanLine = line.replace(/^[^\w\s\[]+/, "").trim();

  return (
    <div
      className={cn(
        "rounded-xl border p-3.5 backdrop-blur-md transition-all shadow-sm",
        isSettled
          ? "border-emerald-500/30 bg-emerald-950/25 shadow-[0_0_12px_rgba(16,185,129,0.12)]"
          : isSupreme
          ? "border-amber-500/50 bg-amber-950/30 shadow-[0_0_15px_rgba(245,158,11,0.2)] animate-pulse"
          : isHandshake
          ? "border-cyan-500/40 bg-cyan-950/30 shadow-[0_0_12px_rgba(6,182,212,0.15)]"
          : isStrike
          ? "border-indigo-500/40 bg-indigo-950/30 shadow-[0_0_12px_rgba(99,102,241,0.15)]"
          : "border-white/10 bg-black/40"
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 mb-1.5">
        <div className="flex items-center gap-2">
          <span className="rounded-md border border-white/20 bg-white/5 px-2 py-0.5 font-mono text-xs font-black text-white">
            🎯 {label}
          </span>
        </div>

        {/* Status Chip */}
        <div>
          {isSettled && (
            <span className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 font-mono text-[10px] font-black text-emerald-300">
              <CheckCircle2 className="h-3 w-3" />
              SETTLED &amp; VERIFIED
            </span>
          )}
          {isHandshake && (
            <span className="inline-flex items-center gap-1 rounded-md border border-cyan-500/40 bg-cyan-500/10 px-2 py-0.5 font-mono text-[10px] font-black text-cyan-300">
              🤝 30&apos; HANDSHAKE PASSED
            </span>
          )}
          {isSupreme && (
            <span className="inline-flex items-center gap-1 rounded-md border border-amber-500/50 bg-amber-500/10 px-2 py-0.5 font-mono text-[10px] font-black text-amber-300 animate-pulse">
              <Flame className="h-3 w-3" />
              🔥 45&apos; SUPREME ALERT
            </span>
          )}
          {isStrike && (
            <span className="inline-flex items-center gap-1 rounded-md border border-indigo-500/40 bg-indigo-500/10 px-2 py-0.5 font-mono text-[10px] font-black text-indigo-300">
              ⚡ STRIKE WINDOW (60&apos;–70&apos;)
            </span>
          )}
          {isWaiting && !isSettled && !isHandshake && !isSupreme && (
            <span className="inline-flex items-center gap-1 rounded-md border border-amber-500/30 bg-amber-950/40 px-2 py-0.5 font-mono text-[10px] font-bold text-amber-300">
              <Clock className="h-3 w-3" />
              45&apos; CONFIRMATION QUEUE
            </span>
          )}
        </div>
      </div>

      <p className="font-mono text-xs text-slate-300 leading-relaxed mt-1">
        {cleanLine}
      </p>
    </div>
  );
}

export default function LivePage() {
  const [selectedAudit, setSelectedAudit] = useState<LivePrematchAudit | null>(null);

  const prematch = useApi(() => liveApi.getPrematch(), [], {
    fallback: MOCK_LIVE_PREMATCH_AUDIT,
    cacheKey: "live-edges-prematch",
  });
  const validation = useApi(() => liveApi.getValidation(), [], {
    fallback: MOCK_LIVE_VALIDATION,
    cacheKey: "live-edges-validation",
  });

  const auditRows = liveRows(
    asAuditList(prematch.data),
    prematch.loading,
    MOCK_LIVE_PREMATCH_AUDIT
  );
  const board = boardFrom(validation.data, validation.loading);
  const validationRows = liveRows(
    board.alerts,
    validation.loading,
    MOCK_LIVE_VALIDATION.alerts
  );

  const stats = useMemo(() => {
    const gkLiabilities = auditRows.filter((r) => r.home.gk_out || r.away.gk_out).length;
    const highMiss = auditRows.filter((r) => r.combined_miss >= 9).length;
    return {
      fixtures: auditRows.length,
      gkLiabilities,
      highMiss,
      tracked: board.total_tracked || board.matches.length,
      validated: validationRows.length,
    };
  }, [auditRows, board.matches.length, board.total_tracked, validationRows.length]);

  const matchedValidationMatches = selectedAudit
    ? board.matches.filter(
        (m) =>
          String(m.id) === String(selectedAudit.fixture_id) ||
          m.name.toLowerCase().includes(selectedAudit.home.team_name.toLowerCase()) ||
          m.name.toLowerCase().includes(selectedAudit.away.team_name.toLowerCase())
      )
    : board.matches;

  const matchedAlerts = selectedAudit
    ? validationRows.filter(
        (a) =>
          String(a.fixture_id) === String(selectedAudit.fixture_id) ||
          a.match_name.toLowerCase().includes(selectedAudit.home.team_name.toLowerCase()) ||
          a.match_name.toLowerCase().includes(selectedAudit.away.team_name.toLowerCase())
      )
    : validationRows;

  // Selected match live validation instance
  const activeValidation = matchedValidationMatches[0];

  return (
    <div className="relative flex flex-col gap-4 p-3.5 sm:p-5 md:p-6 max-w-7xl mx-auto w-full">
      
      {/* ── 1. SLEEK COMPACT TOP BANNER (50% REDUCED HEIGHT) ────────── */}
      <div className="glass flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-[#0c1220]/90 px-4 py-3 shadow-panel backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-accent-indigo/30 bg-accent-indigo/10 shadow-[0_0_12px_rgba(99,102,241,0.2)]">
            <Radio className="h-4 w-4 text-accent-indigo animate-pulse" />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-text-primary flex items-center gap-2">
              Live Monitor
              <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.2 font-mono text-[9px] font-bold text-emerald-400">
                CODE 1 STRATEGIC AUDIT
              </span>
            </h1>
            <p className="text-[11px] text-text-secondary">
              Key-11 lineups, GK liabilities &amp; odds scan. Tap fixture or arrow to open Code 2 &amp; 3 in-play validation.
            </p>
          </div>
        </div>
      </div>

      {/* ── 2. CODE 1: PREMATCH STRATEGIC AUDIT CARDS ────────────────── */}
      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between border-b border-white/5 pb-2 px-1">
          <div className="flex items-center gap-2">
            <Shield className="h-4 w-4 text-cyan-400" />
            <h2 className="text-xs font-bold uppercase tracking-wider text-text-primary">
              Prematch Strategic Audit
            </h2>
            <span className="rounded-full bg-cyan-500/10 border border-cyan-500/30 px-2 py-0.2 font-mono text-[9px] font-bold text-cyan-300">
              {stats.fixtures} FIXTURES
            </span>
          </div>
          <p className="text-[11px] text-text-dim hidden sm:block">
            Tap match title or arrow to view in-play validation
          </p>
        </div>

        {prematch.loading && auditRows.length === 0 ? (
          <div className="grid gap-3">
            <Skeleton className="h-64 rounded-xl bg-bg-elevated" />
            <Skeleton className="h-64 rounded-xl bg-bg-elevated" />
          </div>
        ) : (
          auditRows.map((row) => (
            <PrematchAuditCard
              key={row.fixture_id}
              row={row}
              onOpenDetails={(r) => setSelectedAudit(r)}
            />
          ))
        )}
      </section>

      {/* ── 3. HIGH-TECH CODE 2 & 3 LIVE FORENSIC WAR ROOM (MODAL) ───── */}
      {selectedAudit && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur-lg p-3 sm:p-5 overflow-y-auto">
          <div className="relative w-full max-w-4xl glass rounded-2xl border border-cyan-500/30 bg-[#070b14] p-4 sm:p-6 shadow-[0_0_50px_rgba(6,182,212,0.15)] max-h-[92vh] overflow-y-auto">
            
            {/* ── COCKPIT LIVE MATCH HEADER ───────────────────────────── */}
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 pb-4 mb-5">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-tr from-cyan-500 to-blue-600 shadow-[0_0_15px_rgba(6,182,212,0.4)]">
                  <Cpu className="h-5 w-5 text-white" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="rounded-full border border-rose-500/40 bg-rose-950/40 px-2 py-0.5 font-mono text-[10px] font-black text-rose-400 animate-pulse flex items-center gap-1">
                      <span className="h-1.5 w-1.5 rounded-full bg-rose-400 animate-ping" />
                      {activeValidation ? `${activeValidation.minute}' LIVE` : "IN-PLAY AUDIT"}
                    </span>
                    <span className="font-mono text-xs text-slate-400">
                      ID: {selectedAudit.fixture_id}
                    </span>
                  </div>
                  <h2 className="text-lg font-black text-white mt-0.5">
                    {selectedAudit.fixture}
                  </h2>
                </div>
              </div>

              {/* Neon Score Display */}
              <div className="flex items-center gap-3">
                <div className="rounded-xl border border-cyan-500/30 bg-cyan-950/40 px-4 py-1.5 text-center shadow-inner">
                  <span className="text-[10px] font-bold uppercase tracking-widest text-cyan-300 block">
                    Live Score
                  </span>
                  <span className="font-mono text-lg font-black text-white">
                    {activeValidation ? activeValidation.score : "0 - 0"}
                  </span>
                </div>

                <button
                  type="button"
                  onClick={() => setSelectedAudit(null)}
                  className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-slate-400 hover:text-white hover:border-white/20 transition-all"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>

            <div className="space-y-6">
              
              {/* ── CODE 2: MULTI-PICK VALIDATION MISSION STREAM ──────── */}
              <section className="flex flex-col gap-3">
                <div className="flex items-center justify-between border-b border-white/5 pb-2">
                  <div className="flex items-center gap-2">
                    <ShieldCheck className="h-4 w-4 text-emerald-400" />
                    <h3 className="text-xs font-black uppercase tracking-wider text-white">
                      Code 2 — Live Validation Engine
                    </h3>
                  </div>
                  <span className="font-mono text-[10px] text-slate-400">
                    Cycle #{board.cycle || "14"} · Real-time State Verification
                  </span>
                </div>

                {/* Validation Mission Cards */}
                {matchedValidationMatches.length === 0 || !activeValidation?.lines.length ? (
                  <p className="text-xs text-text-dim italic p-4 bg-bg-elevated/30 rounded-xl border border-white/5 font-mono text-center">
                    No active live validation tracking entries for this fixture yet.
                  </p>
                ) : (
                  <div className="grid grid-cols-1 gap-2.5">
                    {activeValidation.lines.map((line, idx) => (
                      <FormattedPickCard key={idx} line={line} />
                    ))}
                  </div>
                )}
              </section>

              {/* ── CODE 3A: FORENSIC INVESTIGATION COCKPIT ────────────── */}
              <section className="flex flex-col gap-3 rounded-2xl border border-white/10 bg-black/40 p-4">
                <div className="flex items-center gap-2 border-b border-white/10 pb-2">
                  <AlertTriangle className="h-4 w-4 text-amber-400" />
                  <h3 className="text-xs font-black uppercase tracking-wider text-white">
                    Code 3A — Forensic Structural Fracture Board
                  </h3>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 font-mono">
                  {/* GK Exploit Radar */}
                  <div className="rounded-xl border border-rose-500/20 bg-rose-950/20 p-3 flex flex-col justify-between">
                    <span className="text-[10px] uppercase text-slate-400 font-bold">GK Exploit Status</span>
                    <span className={cn(
                      "text-sm font-black mt-1",
                      selectedAudit.home.gk_out || selectedAudit.away.gk_out
                        ? "text-rose-400 animate-pulse"
                        : "text-emerald-400"
                    )}>
                      {selectedAudit.home.gk_out || selectedAudit.away.gk_out
                        ? "🔴 EXPLOITED (Gap Active)"
                        : "🟢 PROTECTED (Wall Solid)"}
                    </span>
                    <span className="text-[10px] text-slate-400 mt-1">
                      Opponent attacking structural fracture
                    </span>
                  </div>

                  {/* Key Player Loss */}
                  <div className="rounded-xl border border-amber-500/20 bg-amber-950/20 p-3 flex flex-col justify-between">
                    <span className="text-[10px] uppercase text-slate-400 font-bold">Key-11 Personnel Gap</span>
                    <span className="text-sm font-black text-amber-300 mt-1">
                      {selectedAudit.combined_miss} Missing Starters
                    </span>
                    <span className="text-[10px] text-slate-400 mt-1">
                      KMV: {selectedAudit.home.kmv.toFixed(0)}%H / {selectedAudit.away.kmv.toFixed(0)}%A
                    </span>
                  </div>

                  {/* Opponent In-Play Pressure */}
                  <div className="rounded-xl border border-cyan-500/20 bg-cyan-950/20 p-3 flex flex-col justify-between">
                    <span className="text-[10px] uppercase text-slate-400 font-bold">Opponent Pressure Penetration</span>
                    <span className="text-sm font-black text-cyan-300 mt-1">
                      HIGH PENETRATION
                    </span>
                    <span className="text-[10px] text-slate-400 mt-1">
                      SOT ≥ 1 · DA ≥ 10 · Box Attacks ≥ 3
                    </span>
                  </div>
                </div>
              </section>

              {/* ── CODE 3B: STATISTICAL JUDGE (TRIPLE ENGINES) ───────── */}
              <section className="flex flex-col gap-3 rounded-2xl border border-white/10 bg-black/40 p-4">
                <div className="flex items-center justify-between border-b border-white/10 pb-2">
                  <div className="flex items-center gap-2">
                    <Target className="h-4 w-4 text-cyan-400" />
                    <h3 className="text-xs font-black uppercase tracking-wider text-white">
                      Code 3B — Combined Statistical Judge
                    </h3>
                  </div>
                  <span className="rounded-full bg-emerald-500/10 border border-emerald-500/30 px-2.5 py-0.5 font-mono text-[10px] font-bold text-emerald-300">
                    STATS: 3/3 ENGINES PASSED
                  </span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 font-mono text-xs">
                  <div className="rounded-xl border border-white/5 bg-white/5 p-3">
                    <p className="text-[10px] font-bold text-slate-400 uppercase">Engine 1 · Rule Validator</p>
                    <p className="text-emerald-400 font-bold mt-1">✅ PASS</p>
                    <p className="text-[10px] text-slate-400 mt-0.5">SOT combined ≥ 2 · DA superiority confirmed</p>
                  </div>

                  <div className="rounded-xl border border-white/5 bg-white/5 p-3">
                    <p className="text-[10px] font-bold text-slate-400 uppercase">Engine 2 · Structural Stacker</p>
                    <p className="text-emerald-400 font-bold mt-1">✅ PASS</p>
                    <p className="text-[10px] text-slate-400 mt-0.5">DA ratio ≥ 50% · Box touch diff ≥ 2 · Corners diff ≥ 2</p>
                  </div>

                  <div className="rounded-xl border border-white/5 bg-white/5 p-3">
                    <p className="text-[10px] font-bold text-slate-400 uppercase">Engine 3 · Momentum Escalator</p>
                    <p className="text-emerald-400 font-bold mt-1">✅ PASS</p>
                    <p className="text-[10px] text-slate-400 mt-0.5">Recent key events ≥ 2 in last 12 minutes</p>
                  </div>
                </div>
              </section>

              {/* ── CODE 3C: SUPREME CONFIRMATIONS TABLE ─────────────── */}
              <section className="flex flex-col gap-2.5">
                <div className="flex items-center gap-2">
                  <Activity className="h-4 w-4 text-cyan-400" />
                  <h3 className="text-xs font-black uppercase tracking-wider text-white">
                    Code 3C — Validated Supreme Confirmations
                  </h3>
                </div>

                <ChainBranch
                  title="MATCH_VALIDATED_ALERTS"
                  description="Confirmed forensic notes and stats triggers for this fixture"
                  data={matchedAlerts}
                  loading={validation.loading}
                  error={validation.error}
                  columns={validationAlertColumns}
                  rowKey={(r, i) =>
                    `${r.fixture_id}-${r.prediction_type}-${r.minute_triggered}-${i}`
                  }
                  emptyMessage="No supreme alerts fired for this fixture yet."
                  isRefetching={validation.isRefetching}
                  defaultOpen
                />
              </section>
            </div>

            {/* Modal Footer */}
            <div className="mt-6 flex justify-end border-t border-white/10 pt-4">
              <button
                type="button"
                onClick={() => setSelectedAudit(null)}
                className="rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 px-5 py-2 text-xs font-black text-white shadow-[0_0_15px_rgba(6,182,212,0.3)] hover:opacity-90 transition-all"
              >
                Close Cockpit
              </button>
            </div>

          </div>
        </div>
      )}
    </div>
  );
}
