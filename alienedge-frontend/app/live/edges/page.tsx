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
  AlertTriangle,
} from "lucide-react";
import {
  liveApi,
  type LivePrematchAudit,
  type LivePrematchTeamAudit,
  type LiveValidationBoard,
  type LiveValidationPick,
  type LiveValidationPrediction,
  type LiveValidationSideStats,
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
import { PushToggle } from "./PushToggle";
import { cn } from "@/lib/utils";

function asAuditList(data: unknown): LivePrematchAudit[] {
  if (Array.isArray(data)) return data as LivePrematchAudit[];
  return [];
}

const EMPTY_VALIDATION_BOARD: LiveValidationBoard = {
  cycle: 0,
  total_live: 0,
  total_tracked: 0,
  matches: [],
  alerts: [],
};

function liveRows<T>(data: T[] | null): T[] {
  return data ?? [];
}

function boardFrom(data: LiveValidationBoard | null): LiveValidationBoard {
  return data ?? EMPTY_VALIDATION_BOARD;
}

// ── CODE 1 PRESENTATION HELPERS (frontend only — no engine change) ────────
// Code 1 deliberately does NOT render its own pre-match picks. The `picks`
// array stays on the payload and is still handed to Code 2 unchanged through
// `onOpenDetails` → `setSelectedAudit`, so only the disclosure is removed.

type RiskLevel = "clear" | "elevated" | "heavy";

/**
 * A side carrying more than 3 missing key players is treated as heavy risk so
 * the user can see at a glance which team must be taken seriously.
 * 0–1 missing = clear, 2–3 = elevated, 4+ = heavy.
 */
function missingRisk(count: number): RiskLevel {
  if (count > 3) return "heavy";
  if (count >= 2) return "elevated";
  return "clear";
}

const RISK_LABEL: Record<RiskLevel, string> = {
  clear: "STRENGTH INTACT",
  elevated: "ELEVATED RISK",
  heavy: "HEAVY RISK",
};

const RISK_BADGE_CLASS: Record<RiskLevel, string> = {
  clear: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  elevated: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  heavy: "border-rose-500/60 bg-rose-500/15 text-rose-300",
};

const RISK_RAIL_CLASS: Record<RiskLevel, string> = {
  clear: "border-l-emerald-500/40",
  elevated: "border-l-amber-500/60",
  heavy: "border-l-rose-500",
};

const RISK_BORDER_CLASS: Record<RiskLevel, string> = {
  clear: "border-border/70",
  elevated: "border-amber-500/30",
  heavy: "border-rose-500/40",
};

/** Plain-English read of a team's pre-match risk so metrics need no decoding. */
function teamRiskSummary(team: LivePrematchTeamAudit): string {
  const miss = team.miss ?? 0;
  const level = missingRisk(miss);
  const gk = team.gk_out
    ? "Goalkeeper down — goal is exposed"
    : "Goalkeeper secure";
  if (level === "heavy") {
    return `${miss} key players missing — heavy risk. ${gk}. Treat this side as compromised for the rest of the match.`;
  }
  if (level === "elevated") {
    return `${miss} key players missing — moderate risk, weakened structure. ${gk}.`;
  }
  return miss === 1
    ? `1 key player missing — watch for a drop in intensity. ${gk}.`
    : `Full-strength spine — no key players missing. ${gk}.`;
}

/** Render an odds value, or an explicit dash when the feed had none. */
function oddsCell(value: number | null | undefined): string {
  return value === null || value === undefined || Number.isNaN(value)
    ? "—"
    : String(value);
}

const validationAlertColumns: PredictionColumn<LiveValidationPick>[] = [
  {
    key: "match_name",
    header: "match_name",
    render: (r) => <span className="font-medium text-text-primary">{r.match_name}</span>,
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

  // Defensive accessors for potentially-missing fields on stale/old audit rows
  const _loc = team.loc ?? "unknown";
  const _teamName = team.team_name ?? "?";
  const _miss = team.miss ?? 0;
  const _kmv = team.kmv ?? 0;
  const _rv = team.rv ?? 0;
  const _gkOut = team.gk_out ?? false;
  const _gkStatus = team.gk_status ?? "";
  const _defMiss = team.def_miss ?? 0;
  const _midMiss = team.mid_miss ?? 0;
  const _attMiss = team.att_miss ?? 0;
  const _lWingMiss = team.l_wing_miss ?? false;
  const _rWingMiss = team.r_wing_miss ?? false;
  const _players = team.players ?? [];
  const risk = missingRisk(_miss);

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
    <div
      className={cn(
        "relative overflow-hidden rounded-lg border border-l-2 bg-bg-elevated/30",
        RISK_RAIL_CLASS[risk],
        RISK_BORDER_CLASS[risk]
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 px-3 py-2">
        <div>
          <p className="text-2xs uppercase tracking-wide text-text-dim">{_loc}</p>
          <p className="text-sm font-semibold text-text-primary">{_teamName}</p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 font-mono text-2xs">
          <span
            className={cn(
              "rounded border px-1.5 py-0.5 font-bold",
              RISK_BADGE_CLASS[risk]
            )}
            title={
              _miss > 3
                ? "More than 3 key players missing — heavy risk"
                : "Key player absence level"
            }
          >
            {RISK_LABEL[risk]}
          </span>
          <button
            type="button"
            onClick={() => setActiveTooltip(activeTooltip === "miss" ? null : "miss")}
            className={cn(
              "rounded border px-1.5 py-0.5 transition-colors",
              risk === "heavy"
                ? "border-rose-500/60 bg-rose-500/15 font-bold text-rose-300 hover:bg-rose-500/25"
                : risk === "elevated"
                  ? "border-amber-500/40 bg-amber-500/10 text-amber-300 hover:bg-amber-500/20"
                  : "border-border-bright text-text-secondary hover:border-accent-indigo"
            )}
            title="Tap to reveal definition"
          >
            miss {_miss}
          </button>
          <button
            type="button"
            onClick={() => setActiveTooltip(activeTooltip === "kmv" ? null : "kmv")}
            className="rounded border border-accent-amber/30 bg-accent-amber/10 px-1.5 py-0.5 text-accent-amber transition-colors hover:bg-accent-amber/20"
            title="Tap to reveal definition"
          >
            KMV {_kmv.toFixed(1)}%
          </button>
          <button
            type="button"
            onClick={() => setActiveTooltip(activeTooltip === "rv" ? null : "rv")}
            className="rounded border border-accent-red/30 bg-accent-red/10 px-1.5 py-0.5 text-accent-red transition-colors hover:bg-accent-red/20"
            title="Tap to reveal definition"
          >
            RV {_rv.toFixed(1)}%
          </button>
          <button
            type="button"
            onClick={() => setActiveTooltip(activeTooltip === "gk" ? null : "gk")}
            className={cn(
              "rounded border px-1.5 py-0.5 transition-colors font-bold",
              _gkOut
                ? "border-accent-red/40 bg-accent-red/10 text-accent-red hover:bg-accent-red/20"
                : "border-accent-green/30 bg-accent-green/10 text-accent-green hover:bg-accent-green/20"
            )}
            title="Tap to reveal definition"
          >
            GK {_gkOut ? "LIABILITY" : "OK"}
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
        GK status: {_gkStatus} · Def {_defMiss} · Mid {_midMiss} · Att{" "}
        {_attMiss}
        {(_lWingMiss || _rWingMiss) &&
          ` · Wings L${_lWingMiss ? "✗" : "✓"}/R${_rWingMiss ? "✗" : "✓"}`}
      </p>
      <p
        className={cn(
          "border-b border-border/50 px-3 py-1.5 text-2xs leading-relaxed",
          risk === "heavy"
            ? "bg-rose-500/10 font-semibold text-rose-200"
            : risk === "elevated"
              ? "bg-amber-500/5 text-amber-200/90"
              : "text-text-secondary"
        )}
      >
        {teamRiskSummary(team)}
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
            {_players.map((p, i) => {
              const isMissing = p.status.includes("MISSING");
              return (
              <tr
                key={`${p.name}-${p.pos}-${i}`}
                className={cn(
                  "hover:bg-bg-elevated/40",
                  isMissing && "bg-rose-500/10"
                )}
              >
                <td className="px-3 py-1.5 font-medium text-text-primary">{p.name}</td>
                <td className="px-2 py-1.5 text-text-secondary">{p.pos}</td>
                <td className="px-2 py-1.5 text-right font-mono">{p.apps}</td>
                <td className="px-2 py-1.5 text-right font-mono">{p.mins}</td>
                <td className="px-2 py-1.5 text-right font-mono">{p.rating.toFixed(2)}</td>
                <td
                  className={cn(
                    "px-3 py-1.5 font-semibold",
                    isMissing
                      ? "text-rose-400"
                      : p.status.toLowerCase().includes("liability") ||
                          p.status.toLowerCase().includes("risk") ||
                          p.status.toLowerCase().includes("leak")
                        ? "text-accent-red"
                        : "text-text-secondary"
                  )}
                >
                  {isMissing && (
                    <span className="mr-1 font-mono font-black" aria-hidden="true">
                      ■
                    </span>
                  )}
                  {p.status}
                </td>
              </tr>
              );
            })}
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

/**
 * Pre-match vs live odds comparison.
 *
 * No live-odds feed exists in the system today — every odds call in the
 * engines is `/odds/pre-match/fixtures/{id}`. The live column therefore reads
 * optional `live_odds_*` fields and shows an explicit "not available" state
 * when they are absent, rather than a blank or a stale pre-match number. If a
 * live feed is ever wired into the same payload, this block renders real
 * values and a shortened/drifted indicator with no further frontend work.
 */
function OddsComparisonBlock({ row }: { row: LivePrematchAudit }) {
  const markets: Array<{
    label: string;
    pre: number | null | undefined;
    live: number | null | undefined;
  }> = [
    { label: "HOME", pre: row.odds_home_win, live: row.live_odds_home_win },
    { label: "AWAY", pre: row.odds_away_win, live: row.live_odds_away_win },
    { label: "O2.5", pre: row.odds_o25, live: row.live_odds_o25 },
  ];
  const hasLiveOdds = markets.some(
    (m) => m.live !== null && m.live !== undefined
  );

  return (
    <div className="border-b border-border/50 px-4 py-2.5">
      <div className="mb-1.5 flex items-center justify-between">
        <p className="text-2xs font-semibold uppercase tracking-wide text-text-dim">
          Odds comparison
        </p>
        {!hasLiveOdds && (
          <span className="font-mono text-[10px] uppercase text-amber-300/80">
            live odds — not available
          </span>
        )}
      </div>

      <div className="grid grid-cols-3 gap-2">
        {markets.map((m) => {
          const hasLive = m.live !== null && m.live !== undefined;
          const shift =
            hasLive && m.pre !== null && m.pre !== undefined
              ? (m.live as number) - (m.pre as number)
              : null;
          return (
            <div
              key={m.label}
              className="rounded-md border border-border/60 bg-bg-elevated/30 px-2 py-1.5"
            >
              <p className="font-mono text-[10px] uppercase tracking-wide text-text-dim">
                {m.label}
              </p>
              <p className="mt-0.5 flex items-baseline gap-1.5 font-mono">
                <span className="text-sm font-bold text-text-primary">
                  {oddsCell(m.pre)}
                </span>
                <span className="text-[9px] uppercase text-text-dim">pre</span>
              </p>
              <p className="mt-0.5 flex items-baseline gap-1.5 font-mono">
                {hasLive ? (
                  <>
                    <span className="text-sm font-bold text-cyan-300">
                      {oddsCell(m.live)}
                    </span>
                    {shift !== null && Math.abs(shift) >= 0.01 && (
                      <span
                        className={cn(
                          "text-[9px] font-bold",
                          shift < 0 ? "text-emerald-400" : "text-slate-400"
                        )}
                        title="Shorter odds = more money backing this market"
                      >
                        {shift < 0 ? "▲ SHORTENED" : "▼ DRIFTED"}
                      </span>
                    )}
                  </>
                ) : (
                  <span className="font-mono text-[10px] uppercase text-text-dim">
                    live n/a
                  </span>
                )}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── CODE 2 PRESENTATION ───────────────────────────────────────────────────
// The gate reports one of four states instead of a pass/fail, so the UI
// colour-codes the verdict instead of implying everything passed.

type VerdictTone = "good" | "bad" | "wait" | "flat";

const STAGE_STYLE: Record<string, string> = {
  MONITORING: "border-white/15 bg-white/5 text-slate-300",
  SUPPORTED: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  UNLIKELY: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  VOID: "border-slate-500/40 bg-slate-500/10 text-slate-300",
  TRIGGERED: "border-amber-500/50 bg-amber-500/10 text-amber-300",
  SETTLED: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
};

// The 45' locked verdict vocabulary. "REJECTED" is deliberately absent: it
// asserted a certainty the engine does not have, and on live football it was
// being produced from a weak engine reading. VOID is the arithmetic case
// (3+ goals already scored) and is styled neutral because it is a fact about
// the scoreline, not a judgement about the prediction.
const LEDGER_VERDICT_STYLE: Record<string, { label: string; tone: VerdictTone }> = {
  LIKELY: { label: "LIKELY", tone: "good" },
  UNLIKELY: { label: "UNLIKELY", tone: "wait" },
  VOID: { label: "VOID", tone: "flat" },
  UNCLEAR: { label: "UNCLEAR", tone: "flat" },
  FINAL_APPROVED: { label: "LIKELY", tone: "good" },
  PRE_APPROVED: { label: "LIKELY (PRE)", tone: "good" },
  // The 30' checkpoint is an OBSERVATION, not a verdict.
  SUPPORTING: { label: "SUPPORTING", tone: "good" },
  AGAINST: { label: "AGAINST", tone: "wait" },
  APPROVED_WATCH: { label: "LIKELY", tone: "good" },
  TRIGGERED: { label: "TRIGGERED", tone: "wait" },
  PRE_REJECTED: { label: "UNLIKELY (PRE)", tone: "wait" },
  FINAL_REJECTED: { label: "UNLIKELY", tone: "wait" },
  WON: { label: "WON", tone: "good" },
  LOST: { label: "LOST", tone: "bad" },
};

// PHASE 2 — a live-only read's own styling. Deliberately muted and distinct
// from the verdict colours: a read is an observation, not a judgement.
const READ_STATE_STYLE: Record<string, string> = {
  ON_TRACK: "border-sky-500/30 bg-sky-500/10 text-sky-300",
  AT_RISK: "border-orange-500/30 bg-orange-500/10 text-orange-300",
  DEAD: "border-slate-500/40 bg-slate-500/10 text-slate-400",
  UNCLEAR: "border-white/15 bg-white/5 text-slate-300",
};

// The 30' -> 45' comparison: how the match MOVED between the two checkpoints.
const COMPARISON_STYLE: Record<string, string> = {
  STRENGTHENED: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  HELD: "border-white/15 bg-white/5 text-slate-300",
  WEAKENED: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  COLLAPSED: "border-rose-500/30 bg-rose-500/10 text-rose-300",
  NO_BASELINE: "border-white/10 bg-white/[0.03] text-slate-500",
};

type MonitorRow = {
  n: number;
  market: string;
  state: string;
  kind: "pick" | "read";
  comparison?: string;
  comparisonNote?: string;
};

/**
 * The per-match list of predictions Code 2 is monitoring and verifying.
 * Numbered, with the 30'→45' comparison beside each state. A live-only read is
 * tagged so it can never be mistaken for a Code 1 prematch prediction.
 */
function MonitorListTable({ rows }: { rows: MonitorRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[440px] text-left font-mono text-[11px]">
        <thead className="text-[9px] uppercase tracking-wide text-slate-500">
          <tr>
            <th className="w-8 py-1 pr-2 font-medium">#</th>
            <th className="py-1 pr-2 font-medium">Market</th>
            <th className="py-1 pr-2 font-medium">State</th>
            <th className="py-1 font-medium">30&apos;&rarr;45&apos;</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={`${r.market}-${r.n}`}
              className="border-t border-white/5 align-top"
            >
              <td className="py-1 pr-2 font-bold text-slate-500">{r.n}</td>
              <td className="py-1 pr-2">
                <span
                  className={cn(
                    "rounded border px-1.5 py-0.5 text-[10px] font-bold",
                    r.kind === "pick"
                      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                      : "border-white/15 bg-white/5 text-slate-300"
                  )}
                  title={
                    r.kind === "pick"
                      ? "Code 1 prematch prediction, validated by Code 2"
                      : "Live-only read — no prematch pick from Code 1"
                  }
                >
                  {displayMarketLabel(r.market)}
                </span>
              </td>
              <td className="py-1 pr-2">
                <span
                  className={cn(
                    "rounded border px-1.5 py-0.5 text-[10px] font-bold",
                    r.kind === "read"
                      ? READ_STATE_STYLE[r.state] ??
                        "border-white/15 bg-white/5 text-slate-300"
                      : "border-white/20 bg-white/5 text-slate-200"
                  )}
                >
                  {r.kind === "read"
                    ? r.state.replace("_", " ")
                    : (LEDGER_VERDICT_STYLE[r.state]?.label ?? r.state)}
                </span>
              </td>
              <td className="py-1">
                {r.comparison ? (
                  <span
                    className={cn(
                      "rounded border px-1.5 py-0.5 text-[10px] font-bold",
                      COMPARISON_STYLE[r.comparison] ??
                        "border-white/15 bg-white/5 text-slate-400"
                    )}
                    title={r.comparisonNote}
                  >
                    {r.comparison.replace("_", " ")}
                  </span>
                ) : (
                  <span className="text-slate-600">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LedgerVerdictChip({ verdict }: { verdict?: string | null }) {
  if (!verdict) return null;
  const style = LEDGER_VERDICT_STYLE[verdict] ?? {
    label: verdict,
    tone: "flat" as VerdictTone,
  };
  return (
    <span
      className={cn(
        "rounded-md border px-2 py-0.5 font-mono text-[10px] font-black",
        VERDICT_TONE_CLASS[style.tone]
      )}
      title={`45' locked verdict: ${verdict}`}
    >
      {style.label}
    </span>
  );
}

// DISPLAY-ONLY SAFETY LABEL. Prematch Under 2.5 is shown to users as
// "Under 3.5" so they are not handed the tightest line. This is a LABEL ONLY:
// the engine still tracks and settles the real 2.5, so a match finishing 2-1
// is still recorded as a loss for the true line. Nothing here changes the
// engine, the pick type, or the settlement maths.
const DISPLAY_LABEL: Record<string, string> = {
  "UNDER_2.5": "UNDER 3.5",
  "U2_5": "UNDER 3.5",
  "U2.5": "UNDER 3.5",
};

// `UNDER 2.5` and `under 2.5` both normalise to UNDER_2.5 above, and the
// backend label may carry a target suffix such as "UNDER_2.5 (match)".
function displayMarketLabel(label: string): string {
  if (!label) return label;
  const key = label.toUpperCase().replace(/\s+/g, "_");
  if (DISPLAY_LABEL[key]) return DISPLAY_LABEL[key];
  // Preserve any "(home)"/"(away)" target suffix on team-side markets.
  const targetMatch = key.match(/^([A-Z0-9_.]+)\s*\((.+)\)$/);
  if (targetMatch) {
    const base = DISPLAY_LABEL[targetMatch[1]];
    if (base) return `${base} (${targetMatch[2]})`;
  }
  return label;
}

const VERDICT_STYLE: Record<string, { label: string; tone: VerdictTone }> = {
  SUPPORTED: { label: "SUPPORTED", tone: "good" },
  CONTRADICTED: { label: "CONTRADICTED", tone: "bad" },
  INSUFFICIENT_DATA: { label: "NEED MORE DATA", tone: "wait" },
  NEUTRAL: { label: "NEUTRAL", tone: "flat" },
  SETTLED: { label: "SETTLED", tone: "good" },
};

const VERDICT_TONE_CLASS: Record<VerdictTone, string> = {
  good: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  bad: "border-rose-500/40 bg-rose-500/10 text-rose-300",
  wait: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  flat: "border-white/15 bg-white/5 text-slate-300",
};

const PREDICTION_STATUS_STYLE: Record<string, string> = {
  SETTLED: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  TRIGGERED: "border-amber-500/50 bg-amber-500/10 text-amber-300",
  STRIKE_WINDOW: "border-indigo-500/40 bg-indigo-500/10 text-indigo-300",
  QUEUED: "border-cyan-500/40 bg-cyan-500/10 text-cyan-300",
  MONITORING: "border-white/15 bg-white/5 text-slate-300",
  WAITING: "border-white/15 bg-white/5 text-slate-300",
};

function VerdictChip({ state }: { state?: string }) {
  const style = VERDICT_STYLE[state ?? ""] ?? {
    label: "UNKNOWN",
    tone: "flat" as VerdictTone,
  };
  return (
    <span
      className={cn(
        "rounded-md border px-2 py-0.5 font-mono text-[10px] font-bold",
        VERDICT_TONE_CLASS[style.tone]
      )}
    >
      {style.label}
    </span>
  );
}

function PredictionLifecycleCard({
  prediction,
}: {
  prediction: LiveValidationPrediction;
}) {
  const settled = prediction.status === "SETTLED";
  return (
    <div
      className={cn(
        "rounded-xl border bg-black/40 p-3",
        settled
          ? "border-emerald-500/30"
          : prediction.status === "TRIGGERED"
            ? "border-amber-500/40"
            : "border-white/10"
      )}
    >
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono text-xs font-black text-white">
          {displayMarketLabel(prediction.label)}
        </span>
        <div className="flex flex-wrap items-center gap-1.5">
          {/* The authoritative verdict: the 60' final validation where one
              exists, otherwise the 45' verdict. LIKELY / UNLIKELY / VOID /
              UNCLEAR. */}
          <LedgerVerdictChip verdict={prediction.verdict} />
          {/* Honesty flags. A verdict recorded after its window closed is
              labelled as such rather than presented as a live reading. */}
          {prediction.backfilled && (
            <span
              className="rounded-md border border-slate-500/40 bg-slate-500/10 px-2 py-0.5 font-mono text-[10px] font-bold text-slate-300"
              title="Recorded after the checkpoint window closed"
            >
              BACKFILLED
            </span>
          )}
          {(prediction.late_45 || prediction.late_60) && !prediction.backfilled && (
            <span
              className="rounded-md border border-white/15 bg-white/5 px-2 py-0.5 font-mono text-[10px] font-bold text-slate-300"
              title="The checkpoint window was missed; the verdict was recorded late"
            >
              LATE
            </span>
          )}
          {prediction.trigger_only && (
            <span
              className="rounded-md border border-indigo-500/40 bg-indigo-500/10 px-2 py-0.5 font-mono text-[10px] font-bold text-indigo-300"
              title="Past 60' with a final validation — this market may only trigger now"
            >
              TRIGGER-ONLY
            </span>
          )}
          {/* Lifecycle stage is the primary read: it says where this
              prediction is in its live validation, one at a time. */}
          {prediction.stage && (
            <span
              className={cn(
                "rounded-md border px-2 py-0.5 font-mono text-[10px] font-black",
                STAGE_STYLE[prediction.stage] ?? STAGE_STYLE.MONITORING
              )}
              title={prediction.stage_note}
            >
              {prediction.stage}
            </span>
          )}
          {!settled && <VerdictChip state={prediction.signal} />}
          <span
            className={cn(
              "rounded-md border px-2 py-0.5 font-mono text-[10px] font-bold",
              PREDICTION_STATUS_STYLE[prediction.status] ??
                PREDICTION_STATUS_STYLE.MONITORING
            )}
          >
            {prediction.status.replace("_", " ")}
          </span>
        </div>
      </div>

      {prediction.stage_note && (
        <p className="mb-2 font-mono text-[11px] text-slate-400">
          {prediction.stage_note}
        </p>
      )}

      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-[11px] sm:grid-cols-3">
        {!settled && (
          <>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-slate-500">Forensic</dt>
              <dd>
                <VerdictChip state={prediction.forensic} />
              </dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-slate-500">Statistics</dt>
              <dd>
                <VerdictChip state={prediction.statistics} />
              </dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-slate-500">Engines</dt>
              <dd className="text-slate-300">{prediction.stats_label ?? "—"}</dd>
            </div>
          </>
        )}
        <div className="flex items-center justify-between gap-2">
          <dt className="text-slate-500">Trigger</dt>
          <dd className="text-slate-300">
            {prediction.trigger_minute != null
              ? `${prediction.trigger_minute}'`
              : "—"}
          </dd>
        </div>
        <div className="flex items-center justify-between gap-2">
          <dt className="text-slate-500">Score at trigger</dt>
          <dd className="text-slate-300">{prediction.score_at_trigger ?? "—"}</dd>
        </div>
        <div className="flex items-center justify-between gap-2">
          <dt className="text-slate-500">Final score</dt>
          <dd className="text-slate-300">{prediction.final_score ?? "—"}</dd>
        </div>
      </dl>

      {prediction.settlement && (
        <p className="mt-2 border-t border-white/10 pt-2 font-mono text-[11px] font-bold text-emerald-300">
          Settlement: {prediction.settlement}
        </p>
      )}
    </div>
  );
}

// Only the numeric statistics are rendered as a home/away comparison.
// `box_available` is a boolean flag on the same object and is intentionally
// not part of this list.
const LIVE_STAT_ROWS: Array<{
  key: Exclude<keyof LiveValidationSideStats, "box_available">;
  label: string;
  suffix?: string;
}> = [
  { key: "possession", label: "Possession", suffix: "%" },
  { key: "shots_on_target", label: "Shots on target" },
  { key: "dangerous_attacks", label: "Dangerous attacks" },
  { key: "corners", label: "Corners" },
  { key: "box_entries", label: "Box entries" },
];

function LiveStatsPanel({
  statistics,
  homeName,
  awayName,
}: {
  statistics?: { home: LiveValidationSideStats; away: LiveValidationSideStats };
  homeName: string;
  awayName: string;
}) {
  if (!statistics) return null;
  // `box_entries` is null when the provider did not supply it, so a plain
  // `> 0` comparison is invalid. Treat null as "no data", not as zero.
  const num = (v: number | null | undefined) =>
    typeof v === "number" && !Number.isNaN(v) ? v : 0;
  const hasData = LIVE_STAT_ROWS.some(
    (r) => num(statistics.home[r.key]) > 0 || num(statistics.away[r.key]) > 0
  );

  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-2">
        <h4 className="text-2xs font-bold uppercase tracking-wider text-slate-300">
          Live team statistics
        </h4>
        {!hasData && (
          <span className="font-mono text-[10px] uppercase text-slate-500">
            awaiting provider statistics
          </span>
        )}
      </div>
      <table className="w-full font-mono text-[11px]">
        <thead className="text-[10px] uppercase text-slate-500">
          <tr>
            <th className="py-1 text-left font-medium">{homeName}</th>
            <th className="py-1 text-center font-medium">Statistic</th>
            <th className="py-1 text-right font-medium">{awayName}</th>
          </tr>
        </thead>
        <tbody>
          {LIVE_STAT_ROWS.map((row) => {
            const homeRaw = statistics.home[row.key];
            const awayRaw = statistics.away[row.key];
            const homeMissing =
              homeRaw === null || homeRaw === undefined;
            const awayMissing =
              awayRaw === null || awayRaw === undefined;
            // A missing stat never "leads" — otherwise an absent value would
            // render as 0 and look like the other side was winning.
            const lead =
              homeMissing || awayMissing || homeRaw === awayRaw
                ? ""
                : num(homeRaw) > num(awayRaw)
                  ? "home"
                  : "away";
            return (
              <tr key={row.key} className="border-t border-white/5">
                <td
                  className={cn(
                    "py-1 font-bold",
                    lead === "home" ? "text-cyan-300" : "text-slate-400"
                  )}
                >
                  {homeMissing
                    ? "n/a"
                    : `${num(homeRaw)}${row.suffix ?? ""}`}
                </td>
                <td className="py-1 text-center text-slate-500">{row.label}</td>
                <td
                  className={cn(
                    "py-1 text-right font-bold",
                    lead === "away" ? "text-cyan-300" : "text-slate-400"
                  )}
                >
                  {awayMissing
                    ? "n/a"
                    : `${num(awayRaw)}${row.suffix ?? ""}`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
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
  const combinedRisk = missingRisk(row.combined_miss ?? 0);
  const status = (row.status_text ?? "").toUpperCase();
  const isLive = status.includes("LIVE");
  const isFinished = status.includes("FINISH") || /\bFT\b/.test(status);

  return (
    <article className="glass overflow-hidden rounded-xl border border-white/10 shadow-panel transition-all hover:border-cyan-500/30">
      {/* ── CARD HEADER: Match + Status + Risk + Arrow ──────────────────── */}
      <div className="flex items-center justify-between gap-2 border-b border-border/70 bg-bg-elevated/20 px-4 py-2.5">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => onOpenDetails(row)}
            className="group/btn flex items-center gap-1.5 text-left transition-colors"
          >
            <h3 className="text-sm font-bold text-text-primary transition-colors group-hover/btn:text-cyan-400">
              {row.fixture}
            </h3>
          </button>

          <span
            className={cn(
              "shrink-0 rounded border px-1.5 py-0.2 font-mono text-[10px] font-bold",
              isLive
                ? "border-rose-500/40 bg-rose-950/40 text-rose-300"
                : isFinished
                  ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                  : "border-white/15 bg-white/5 text-slate-300"
            )}
          >
            {row.status_text || "UNKNOWN"}
          </span>

          <span
            className={cn(
              "shrink-0 rounded border px-1.5 py-0.2 font-mono text-[10px] font-bold",
              RISK_BADGE_CLASS[combinedRisk]
            )}
            title="Combined key-player absence across both teams"
          >
            {RISK_LABEL[combinedRisk]} · {row.combined_miss} MISSING
          </span>
        </div>

        <button
          type="button"
          onClick={() => onOpenDetails(row)}
          className="ml-2 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-cyan-500/30 bg-cyan-950/40 text-cyan-300 shadow-sm transition-all hover:scale-105 hover:bg-cyan-500/20"
          title="Open Code 2 live validation"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>

      {/* ── PURPOSE STRIP: Code 1 contract + fixture meta ──────────────── */}
      <div className="border-b border-border/50 bg-bg-elevated/10 px-4 py-1.5">
        <div className="flex flex-wrap items-center justify-between gap-2 text-[11px]">
          <span className="font-semibold uppercase tracking-wide text-cyan-300/90">
            Code 1 · Pre-match evidence
          </span>
          <span className="text-text-dim">
            Predictions are intentionally not shown here — select the fixture
            to open the Code 2 validator.
          </span>
        </div>
        <div className="mt-0.5 flex flex-wrap items-center justify-between gap-2 font-mono text-[10px] text-text-dim">
          <span>KICKOFF {row.kickoff_utc} UTC</span>
          <span className="text-text-dim/60">ID {row.fixture_id}</span>
        </div>
      </div>

      {/* ── RISK STRIP: per-team absence severity ──────────────────────── */}
      <div className="grid grid-cols-1 gap-2 border-b border-border/50 px-4 py-2 sm:grid-cols-2">
        {(["home", "away"] as const).map((side) => {
          const team = row[side];
          const level = missingRisk(team?.miss ?? 0);
          return (
            <div
              key={side}
              className={cn(
                "flex items-center justify-between gap-2 rounded-md border px-2.5 py-1.5 text-2xs",
                RISK_BADGE_CLASS[level]
              )}
            >
              <span className="truncate font-semibold text-text-primary">
                {team?.team_name ?? (side === "home" ? "HOME" : "AWAY")}
              </span>
              <span className="shrink-0 font-mono font-bold">
                {team?.gk_out ? "GK DOWN" : "GK OK"} · {team?.miss ?? 0} MISSING
              </span>
            </div>
          );
        })}
      </div>

      {/* ── ODDS COMPARISON: PRE-MATCH vs LIVE ──────────────────────────── */}
      <OddsComparisonBlock row={row} />

      {/* Lineup Panels (Interactive without triggering navigation) */}
      <div className="grid grid-cols-1 gap-3 p-3 lg:grid-cols-2">
        <TeamAuditPanel team={row.home} />
        <TeamAuditPanel team={row.away} />
      </div>
    </article>
  );
}

export default function LivePage() {
  const [selectedAudit, setSelectedAudit] = useState<LivePrematchAudit | null>(null);

  // Code 1 must keep refreshing. Without an interval the prematch panel is
  // fetched exactly once on mount, so the board FREEZES on first paint — the
  // other half of "it stops". A live match's audit can change every cycle
  // (~2.5-3.5 min), so a 20s poll is well inside the useful window.
  const prematch = useApi(() => liveApi.getPrematch(), [], {
    fallback: MOCK_LIVE_PREMATCH_AUDIT,
    cacheKey: "live-edges-prematch",
    refreshMs: 20_000,
  });
  // Code 2 must stay live while the cockpit is open. Without a refresh
  // interval the modal could show 0-0 at 24' long after the match moved on,
  // because the board is only fetched once on mount.
  const validation = useApi(() => liveApi.getValidation(), [], {
    fallback: MOCK_LIVE_VALIDATION,
    cacheKey: "live-edges-validation",
    refreshMs: selectedAudit ? 15_000 : 0,
  });

  // Code 1 render filter — the FINAL guard against a finished match appearing.
  //
  // Stage 1 already refuses to admit a finished fixture, and the audit rows
  // carry explicit `is_finished` / `state` flags, but the old card only used
  // `isFinished` to tint a badge and rendered EVERY row regardless. Filtering
  // here means a stale cached payload or a row written by an older build can
  // never put a completed match back on the pre-match board.
  const auditRows = liveRows(asAuditList(prematch.data)).filter((row) => {
    if (row.is_finished) return false;
    const state = (row.state ?? "").toString().toUpperCase();
    if (state === "FINISHED") return false;
    const status = (row.status_text ?? "").toUpperCase();
    if (status.includes("FINISH") || /\bFT\b/.test(status)) return false;
    return true;
  });
  const board = boardFrom(validation.data);
  const validationRows = liveRows(board.alerts);

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

  // Code 3C must match on fixture_id ALONE.
  //
  // The old filter matched on team-name SUBSTRINGS:
  //     m.name.includes(home.team_name) || m.name.includes(away.team_name)
  // "Sportivo Luqueño" plays in three different fixtures, so selecting
  // "Sportivo Luqueño vs Guaraní" (19745716) also pulled in alerts belonging to
  // "Olimpia vs Sportivo Luqueño" and "Sportivo Luqueño vs Deportivo Recoleta",
  // and `activeValidation = matched[0]` could then bind the WRONG fixture's
  // score, minute and statistics. Every alert carries a real fixture_id, so the
  // substring path is removed entirely rather than merely deprioritised.
  const matchedValidationMatches = selectedAudit
    ? board.matches.filter(
        (m) => String(m.id) === String(selectedAudit.fixture_id)
      )
    : board.matches;

  const matchedAlerts = selectedAudit
    ? validationRows.filter(
        (a) => String(a.fixture_id) === String(selectedAudit.fixture_id)
      )
    : validationRows;

  // When no live row exists for the selected fixture we say so explicitly
  // instead of borrowing another match's score/minute/statistics.
  const activeValidation = matchedValidationMatches[0] ?? null;

  // PHASE 2: the live-only read for a fixture Code 1 did not pick. Sourced from
  // the SAME matched row as the predictions, so it can never be borrowed from
  // another fixture — the cross-fixture leakage bug this board already had.
  const activeLiveRead = activeValidation?.live_read ?? null;

  // The structured prediction list is Code 2's primary output. Older boards
  // written before the contract change carry no `predictions` array, so fall
  // back to an empty list rather than rendering a misleading empty state.
  // Memoised on its own so the tally below has a stable dependency: `?? []`
  // creates a NEW array every render otherwise, which would recompute the
  // headline counts on every paint.
  const activePredictions: LiveValidationPrediction[] = useMemo(
    () => activeValidation?.predictions ?? [],
    [activeValidation]
  );

  // Counts for the Code 2 headline.
  //
  // PHASE 1 FIX: settled picks were previously counted in the `default`
  // branch and reported as "Awaiting 45'", so a match whose predictions had
  // all finished at full time displayed LIKELY 0 / UNLIKELY 0 / VOID 0 /
  // AWAITING 4 — the exact screen that made Code 2 look broken. A settled pick
  // is DECIDED, not awaiting anything, and is now counted on its own.
  const predictionTally = useMemo(() => {
    let likely = 0;
    let unlikely = 0;
    let voided = 0;
    let settled = 0;
    let awaiting = 0;
    for (const p of activePredictions) {
      if (p.status === "SETTLED") {
        settled++;
        continue;
      }
      switch (p.verdict) {
        case "LIKELY":
        case "FINAL_APPROVED":
          likely++;
          break;
        case "UNLIKELY":
        case "FINAL_REJECTED":
          unlikely++;
          break;
        case "VOID":
          voided++;
          break;
        default:
          // UNCLEAR, a 30' pre-verdict, or no verdict yet.
          awaiting++;
      }
    }
    return {
      total: activePredictions.length,
      likely,
      unlikely,
      void: voided,
      settled,
      awaiting,
    };
  }, [activePredictions]);

  // THE PREDICTIONS CODE 2 IS MONITORING — scoped to the SELECTED match.
  //
  // This was previously a flat index across every live match, shown at the top
  // of the page. The user rejected that: "code i dont need the board list even
  // if its need it its should be on individusl team section or pages not in
  // general its not convinet like that so the best mean is for code 2 to have
  // the list of prematch prediction its want to monitor and verify at the top
  // of its individual page".
  //
  // So the list now lives on the individual match page and shows only that
  // match's predictions. A live-only read is included but tagged, so a read
  // can never be mistaken for a Code 1 pick.
  const monitorList = useMemo(() => {
    const rows: Omit<MonitorRow, "n">[] = [];

    for (const p of activePredictions) {
      if (p.status === "SETTLED") continue;
      rows.push({
        market: p.label,
        state: p.verdict ?? p.status ?? "MONITORING",
        kind: "pick",
        comparison: p.comparison_30_45,
        comparisonNote: p.comparison_note,
      });
    }
    if (activeLiveRead) {
      rows.push({
        market: "UNDER 2.5 (live read)",
        state: activeLiveRead.read,
        kind: "read",
      });
    }
    return rows.map((r, i) => ({ ...r, n: i + 1 }));
  }, [activePredictions, activeLiveRead]);

  const pickCount = monitorList.filter((r) => r.kind === "pick").length;
  const readCount = monitorList.filter((r) => r.kind === "read").length;

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
                Live Match Edges
                <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.2 font-mono text-[9px] font-bold text-emerald-400">
                  CODE 1 EVIDENCE
                </span>
              </h1>
              <p className="text-[11px] text-text-secondary">
                Code 1 reveals pre-match evidence only — key-player gaps, goalkeeper
                liability and market odds. It does not show predictions. Open a
                fixture to reach the Code 2 live validator.
              </p>
          </div>
        </div>
      </div>

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between border-b border-white/5 pb-2 px-1">
          <div className="flex items-center gap-2">
            <Shield className="h-4 w-4 text-cyan-400" />
            <h2 className="text-xs font-bold uppercase tracking-wider text-text-primary">
              Code 1 — Pre-Match Evidence
            </h2>
            <span className="rounded-full bg-cyan-500/10 border border-cyan-500/30 px-2 py-0.2 font-mono text-[9px] font-bold text-cyan-300">
              {stats.fixtures} FIXTURES
            </span>
          </div>
          <p className="text-[11px] text-text-dim hidden sm:block">
            Evidence only, no predictions. Use it to read each side&apos;s risk, then
            open the fixture for Code 2 validation.
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
            
            {/* ── CODE 2: STICKY LIVE MATCH HEADER (score first) ─────── */}
            {/* Header is a normal block, not a sticky element with negative
                margins: the negative offsets clipped the first line of text
                when the modal was scrolled. */}
            <div className="relative z-10 mb-5 rounded-xl border border-white/10 bg-[#070b14] p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full border border-cyan-500/40 bg-cyan-950/40 px-2 py-0.5 font-mono text-[10px] font-black uppercase tracking-wider text-cyan-300">
                      Code 2 — Live Validator
                    </span>
                    {activeValidation?.status && (
                      <span className="rounded-full border border-white/15 bg-white/5 px-2 py-0.5 font-mono text-[10px] font-bold text-slate-300">
                        {activeValidation.status}
                      </span>
                    )}
                  </div>
                  <h2 className="mt-1 text-lg font-black text-white">
                    {selectedAudit.fixture}
                  </h2>
                </div>

                <button
                  type="button"
                  onClick={() => setSelectedAudit(null)}
                  className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-slate-400 transition-all hover:border-white/20 hover:text-white"
                  aria-label="Close cockpit"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              {/* Score and minute are the primary visual element. */}
              <div className="mt-3 flex flex-wrap items-center gap-4">
                <div className="flex items-center gap-3">
                  <span className="text-sm font-bold text-white">
                    {selectedAudit.home.team_name}
                  </span>
                  <span className="rounded-xl border border-cyan-500/40 bg-cyan-950/50 px-4 py-1 text-center font-mono text-2xl font-black text-white shadow-inner">
                    {activeValidation?.score_parts?.display ??
                      activeValidation?.score ??
                      "0 - 0"}
                  </span>
                  <span className="text-sm font-bold text-white">
                    {selectedAudit.away.team_name}
                  </span>
                </div>
                <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] text-slate-400">
                  {activeValidation?.minute != null && (
                    <span className="rounded border border-white/10 bg-white/5 px-2 py-0.5 font-bold text-white">
                      {activeValidation.minute}&apos;
                    </span>
                  )}
                  {activeValidation?.period && (
                    <span>{activeValidation.period}</span>
                  )}
                  {activeValidation?.updated_at && (
                    <span className="text-slate-500">
                      data {activeValidation.updated_at.slice(11, 19)} UTC
                    </span>
                  )}
                  <span className="text-slate-600">ID {selectedAudit.fixture_id}</span>
                </div>
              </div>
            </div>

            <div className="space-y-6">

              {/* ── CODE 2 TOP SECTION: what is being validated ──────────── */}
              {/* The user asked for a headline that states plainly which
                  prematch predictions are awaiting validation or already
                  voided, so the board never reads as empty or ambiguous. */}
              <section className="flex flex-col gap-2.5 rounded-2xl border border-emerald-500/20 bg-emerald-950/10 p-3.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="flex items-center gap-2 text-[11px] font-black uppercase tracking-wider text-emerald-300">
                    <ShieldCheck className="h-4 w-4" />
                    Prematch probabilistic predictions — validation status
                  </h3>
                  <span className="font-mono text-[10px] text-slate-400">
                    locked at 45&apos; · cycle #{board.cycle || "—"}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
                  {(
                    [
                      ["Tracked", predictionTally.total, "text-white"],
                      ["Likely", predictionTally.likely, "text-emerald-300"],
                      ["Unlikely", predictionTally.unlikely, "text-amber-300"],
                      ["Void", predictionTally.void, "text-slate-300"],
                      ["Settled", predictionTally.settled, "text-cyan-300"],
                      ["Awaiting", predictionTally.awaiting, "text-slate-400"],
                    ] as const
                  ).map(([label, value, cls]) => (
                    <div
                      key={label}
                      className="rounded-lg border border-white/10 bg-black/30 px-2.5 py-2"
                    >
                      <p className="font-mono text-[9px] uppercase tracking-wide text-slate-400">
                        {label}
                      </p>
                      <p className={cn("font-mono text-lg font-black", cls)}>
                        {value}
                      </p>
                    </div>
                  ))}
                </div>
                {predictionTally.total === 0 && (
                  <p className="font-mono text-[11px] italic text-slate-400">
                    No prematch predictions reached this fixture yet. Code 1
                    emits a pick only when a structural condition fires, so a
                    clean match sheet produces nothing to validate.
                  </p>
                )}
              </section>

              {/* ── THE PREDICTIONS CODE 2 IS MONITORING (this match) ────── */}
              {/* Scoped to the individual match page, not the page as a whole.
                  The user asked for "the list of prematch prediction its want
                  to monitor and verify at the top of its individual page". */}
              <section className="flex flex-col gap-2.5 rounded-2xl border border-emerald-500/20 bg-emerald-950/10 p-3.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="flex items-center gap-2 text-[11px] font-black uppercase tracking-wider text-emerald-300">
                    <ShieldCheck className="h-4 w-4" />
                    Prematch predictions — monitored &amp; verified
                  </h3>
                  <div className="flex items-center gap-1.5 font-mono text-[10px]">
                    <span className="rounded border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.5 text-emerald-300">
                      {pickCount} PICK{pickCount === 1 ? "" : "S"}
                    </span>
                    {readCount > 0 && (
                      <span className="rounded border border-white/15 bg-white/5 px-1.5 py-0.5 text-slate-300">
                        {readCount} READ
                      </span>
                    )}
                    <span className="text-slate-400">
                      cycle #{board.cycle || "—"}
                    </span>
                  </div>
                </div>

                {monitorList.length === 0 ? (
                  <p className="rounded-lg border border-white/5 bg-white/5 p-3 text-center font-mono text-[11px] italic text-slate-400">
                    Code 1 attached no prediction to this fixture, and the match
                    has not passed 30&apos; yet — so there is nothing for Code 2
                    to monitor here.
                  </p>
                ) : (
                  <MonitorListTable rows={monitorList} />
                )}
              </section>

              {/* ── CODE 2: PREDICTION LIFECYCLE (main objective) ─────── */}
              <section className="flex flex-col gap-3">
                <div className="flex items-center justify-between border-b border-white/5 pb-2">
                  <div className="flex items-center gap-2">
                    <ShieldCheck className="h-4 w-4 text-emerald-400" />
                    <h3 className="text-xs font-black uppercase tracking-wider text-white">
                      Predictions for this match
                    </h3>
                  </div>
                  <span className="font-mono text-[10px] text-slate-400">
                    Cycle #{board.cycle || "—"} ·{" "}
                    {activePredictions.length} tracked
                    {validation.isRefetching ? " · refreshing…" : ""}
                  </span>
                </div>

                {activePredictions.length === 0 ? (
                  <p className="rounded-xl border border-white/5 bg-bg-elevated/30 p-4 text-center font-mono text-xs italic text-text-dim">
                    {activeLiveRead
                      ? "Code 1 attached no prediction to this fixture, so there is nothing to validate. Code 2 is still reading the match live — see below."
                      : "No predictions are attached to this fixture yet. Code 2 validates whatever Code 1 hands it once picks exist."}
                  </p>
                ) : (
                  <div className="grid grid-cols-1 gap-2.5">
                    {activePredictions.map((prediction) => (
                      <PredictionLifecycleCard
                        key={prediction.key}
                        prediction={prediction}
                      />
                    ))}
                  </div>
                )}

                {/* PHASE 2 — the live-only read, shown in its OWN block so it
                    can never be mistaken for a validated Code 1 prediction. It
                    is an observation from the live statistics, not a bet. */}
                {activeLiveRead && (
                  <div className="mt-3 rounded-xl border border-sky-500/25 bg-sky-950/20 p-3">
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                      <span className="font-mono text-xs font-black text-sky-200">
                        Live read — no Code 1 pick
                      </span>
                      <span
                        className={cn(
                          "rounded-md border px-2 py-0.5 font-mono text-[10px] font-black",
                          READ_STATE_STYLE[activeLiveRead.read] ??
                            "border-white/15 bg-white/5 text-slate-300"
                        )}
                      >
                        {activeLiveRead.read.replace("_", " ")}
                      </span>
                    </div>
                    <p className="font-mono text-[11px] text-slate-300">
                      {activeLiveRead.stage_note}
                    </p>
                    <p className="mt-2 font-mono text-[10px] italic leading-relaxed text-slate-500">
                      This is an observation from the live statistics only.
                      Code 1 attached no prematch prediction to this fixture, so
                      there is nothing to validate. It is not a bet and carries
                      no verdict.
                    </p>
                  </div>
                )}
              </section>

              {/* ── CODE 2: LIVE TEAM STATISTICS ────────────────────────── */}
              {activeValidation?.statistics && (
                <section className="rounded-2xl border border-white/10 bg-black/40 p-4">
                  <LiveStatsPanel
                    statistics={activeValidation.statistics}
                    homeName={selectedAudit.home.team_name}
                    awayName={selectedAudit.away.team_name}
                  />
                </section>
              )}

              {/* ── CODE 2: VALIDATION DETAIL (raw board log) ───────────── */}
              {activeValidation?.lines?.length ? (
                <section className="flex flex-col gap-2">
                  <h3 className="text-2xs font-bold uppercase tracking-wider text-slate-400">
                    Cycle detail
                  </h3>
                  <div className="rounded-xl border border-white/5 bg-black/30 p-3 font-mono text-[11px] leading-relaxed text-slate-400">
                    {activeValidation.lines.map((line, idx) => (
                      <p key={idx} className="whitespace-pre-wrap">
                        {line.trim()}
                      </p>
                    ))}
                  </div>
                </section>
              ) : null}

              {/* ── MATCH ALERTS (opt-in push) ─────────────────────────── */}
              <PushToggle />

              {/* ── CODE 3A: FORENSIC INVESTIGATION COCKPIT ────────────── */}
              <section className="flex flex-col gap-3 rounded-2xl border border-white/10 bg-black/40 p-4">
                <div className="flex items-center gap-2 border-b border-white/10 pb-2">
                  <AlertTriangle className="h-4 w-4 text-amber-400" />
                  <h3 className="text-xs font-black uppercase tracking-wider text-white">
                    Code 3A — Forensic Structural Fracture Board
                  </h3>
                </div>

                {/* Goalkeeper exposure is reported PER TEAM. The previous
                    version collapsed both sides into a single "EXPLOITED"
                    verdict with no indication of which goalkeeper was at risk. */}
                <div className="grid grid-cols-1 gap-3 font-mono sm:grid-cols-2">
                  {(
                    [
                      ["Home", selectedAudit.home],
                      ["Away", selectedAudit.away],
                    ] as const
                  ).map(([side, team]) => {
                    const gkDown = Boolean(team?.gk_out);
                    return (
                      <div
                        key={side}
                        className={cn(
                          "rounded-xl border p-3",
                          gkDown
                            ? "border-rose-500/30 bg-rose-950/20"
                            : "border-emerald-500/20 bg-emerald-950/10"
                        )}
                      >
                        <p className="text-[10px] font-bold uppercase text-slate-400">
                          {side} — {team?.team_name ?? "?"}
                        </p>
                        <p
                          className={cn(
                            "mt-1 text-sm font-black",
                            gkDown ? "text-rose-400" : "text-emerald-400"
                          )}
                        >
                          {gkDown ? "🔴 GK EXPOSED" : "🟢 GK PROTECTED"}
                        </p>
                        <p className="mt-1 text-[10px] text-slate-400">
                          {team?.gk_status || "No goalkeeper note"}
                        </p>
                        <p className="mt-1 text-[10px] text-slate-400">
                          Missing key players:{" "}
                          <span
                            className={cn(
                              "font-bold",
                              (team?.miss ?? 0) > 3
                                ? "text-rose-400"
                                : "text-slate-300"
                            )}
                          >
                            {team?.miss ?? 0}
                          </span>{" "}
                          · KMV {Number(team?.kmv ?? 0).toFixed(0)}%
                        </p>
                      </div>
                    );
                  })}
                </div>

                {/* Pressure is COMPUTED from the live statistics shown above,
                    not asserted. This panel previously always read
                    "HIGH PENETRATION" even when the board showed 0 box
                    entries on both sides. */}
                {(() => {
                  const stats = activeValidation?.statistics;
                  if (!stats) {
                    return (
                      <p className="rounded-lg border border-white/5 bg-white/5 p-3 font-mono text-[11px] text-slate-400">
                        No live statistics for this fixture yet — pressure
                        cannot be assessed.
                      </p>
                    );
                  }
                  const boxValues = [
                    stats.home.box_entries,
                    stats.away.box_entries,
                  ];
                  const boxAvailable = boxValues.every(
                    (v) => v !== null && v !== undefined
                  );
                  const levels = [
                    {
                      label: "Shots on target",
                      value: Math.max(
                        stats.home.shots_on_target,
                        stats.away.shots_on_target
                      ),
                      // Mirrors the engine's Engine 1 bar (combined SOT > 3,
                      // i.e. 4+). Keeping these in sync is what stops the panel
                      // contradicting the real verdicts again.
                      need: 4,
                    },
                    {
                      label: "Dangerous attacks",
                      value: Math.max(
                        stats.home.dangerous_attacks,
                        stats.away.dangerous_attacks
                      ),
                      need: 10,
                    },
                    {
                      label: "Box entries",
                      value: boxAvailable
                        ? Math.max(
                            Number(boxValues[0]),
                            Number(boxValues[1])
                          )
                        : null,
                      need: 3,
                    },
                  ];
                  const met = levels.filter(
                    (l) => l.value !== null && l.value >= l.need
                  );
                  const verdict =
                    met.length >= 2
                      ? { text: "HIGH PRESSURE", cls: "text-rose-300" }
                      : met.length === 1
                        ? { text: "MODERATE PRESSURE", cls: "text-amber-300" }
                        : { text: "LOW PRESSURE", cls: "text-slate-400" };
                  return (
                    <div className="rounded-xl border border-cyan-500/20 bg-cyan-950/20 p-3 font-mono">
                      <p className="text-[10px] font-bold uppercase text-slate-400">
                        Combined attacking pressure (best side)
                      </p>
                      <p className={cn("mt-1 text-sm font-black", verdict.cls)}>
                        {verdict.text}
                      </p>
                      <ul className="mt-1.5 space-y-0.5 text-[10px] text-slate-400">
                        {levels.map((l) => (
                          <li key={l.label}>
                            {l.value === null
                              ? `${l.label}: unavailable`
                              : `${l.label} ${l.value} ${l.value >= l.need ? "≥" : "<"} ${l.need} ${l.value >= l.need ? "✅" : "❌"}`}
                          </li>
                        ))}
                      </ul>
                    </div>
                  );
                })()}
              </section>

              {/* CODE 3B REMOVED.
                  The user asked for this table to go. It duplicated the
                  per-prediction Forensic / Statistics / Engines rows already
                  rendered inside each prediction card above, and its footnote
                  ("passes only when forensic AND statistics both read
                  SUPPORTED") described the OLD gate — which was precisely the
                  rule that made a match-level Under 2.5 impossible to approve.
                  The 45' verdict chip on each card is now the single source of
                  truth, so a second summary table can only contradict it. */}

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
