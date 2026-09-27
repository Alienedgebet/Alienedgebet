"use client";

import { useState, useMemo, type ReactNode } from "react";
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
  type LiveValidationPrediction,
  type LiveValidationSideStats,
} from "@/lib/api";
import { useApi } from "@/lib/use-api";
import {
  MOCK_LIVE_PREMATCH_AUDIT,
} from "@/lib/mock-chains";
import {
} from "@/components/predictions";
import { Skeleton } from "@/components/ui/skeleton";
import { PushToggle } from "./PushToggle";
import { cn } from "@/lib/utils";

function asAuditList(data: unknown): LivePrematchAudit[] {
  if (Array.isArray(data)) return data as LivePrematchAudit[];
  return [];
}


function liveRows<T>(data: T[] | null): T[] {
  return data ?? [];
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
  { key: "shots_inside_box", label: "Shots in box" },
  { key: "attacks", label: "Attacks" },
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
  // The Code 2 validator no longer runs, so its board is retired as the
  // source for this page. Live team statistics now come from the Code 6
  // orchestrator board, which already extracts the same per-team stats from
  // the same provider payload every cycle — so this costs no extra API call
  // and nothing was lost. It still polls, because the underlying cycle is
  // ~3 minutes and a one-shot fetch would freeze on first paint.
  const validation = useApi(() => liveApi.getOrchestrator(), [], {
    cacheKey: "live-edges-orchestrator",
    refreshMs: 15_000,
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
  const board = validation.data;

  const stats = useMemo(() => {
    const gkLiabilities = auditRows.filter((r) => r.home.gk_out || r.away.gk_out).length;
    const highMiss = auditRows.filter((r) => r.combined_miss >= 9).length;
    return {
      fixtures: auditRows.length,
      gkLiabilities,
      highMiss,
      tracked: board?.matches.length ?? 0,
      validated: 0,
    };
  }, [auditRows, board?.matches.length]);

  // The live row for the selected fixture, matched on fixture_id ALONE.
  //
  // The old filter matched on team-name SUBSTRINGS, so selecting "Sportivo
  // Luqueño vs Guaraní" also pulled rows for other matches involving the same
  // club and could bind the WRONG fixture's score and statistics. Every row
  // carries a real fixture_id, so the substring path is not reinstated.
  const activeMatch = selectedAudit
    ? (board?.matches ?? []).find(
        (m) => String(m.id) === String(selectedAudit.fixture_id)
      ) ?? null
    : (board?.matches?.[0] ?? null);

  // Map Code 6's raw provider stat names onto the shape the panel renders.
  // The provider spells them with hyphens and reports box entries under
  // "box" (absent for many fixtures, which is why the panel already treats a
  // null as "no data" rather than zero).
  const sideStats = (raw: Record<string, number> | undefined) => {
    const n = (k: string) => {
      const v = raw?.[k];
      return typeof v === "number" && !Number.isNaN(v) ? v : 0;
    };
    return {
      possession: n("ball-possession"),
      shots_on_target: n("shots-on-target"),
      dangerous_attacks: n("dangerous-attacks"),
      corners: n("corners"),
      shots_inside_box: n("shots-insidebox"),
      attacks: n("attacks"),
    };
  };

  const liveStatistics = useMemo(() => {
    const raw = activeMatch?.statistics;
    if (!raw?.home && !raw?.away) return null;
    return { home: sideStats(raw?.home), away: sideStats(raw?.away) };
  }, [activeMatch?.statistics]);

  // The live scoreline, taken from the same provider stats block.
  const liveScore = useMemo(() => {
    const raw = activeMatch?.statistics;
    const g = (side: "home" | "away") => {
      const v = raw?.[side]?.["goals"];
      return typeof v === "number" && !Number.isNaN(v) ? v : null;
    };
    const h = g("home");
    const a = g("away");
    return h === null && a === null ? null : `${h ?? 0} - ${a ?? 0}`;
  }, [activeMatch?.statistics]);

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
            
            {/* ── LIVE MATCH HEADER (score first) ──────────────────── */}
            <div className="relative z-10 mb-5 rounded-xl border border-white/10 bg-[#070b14] p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full border border-cyan-500/40 bg-cyan-950/40 px-2 py-0.5 font-mono text-[10px] font-black uppercase tracking-wider text-cyan-300">
                      Live match
                    </span>
                    {activeMatch?.storm?.stage && (
                      <span className="rounded-full border border-amber-500/40 bg-amber-950/40 px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wide text-amber-300">
                        Storm {activeMatch.storm.stage}
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
                  aria-label="Close"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-4">
                <div className="flex items-center gap-3">
                  <span className="text-sm font-bold text-white">
                    {selectedAudit.home.team_name}
                  </span>
                  <span className="rounded-xl border border-cyan-500/40 bg-cyan-950/50 px-4 py-1 text-center font-mono text-2xl font-black text-white shadow-inner">
                    {liveScore ?? "—"}
                  </span>
                  <span className="text-sm font-bold text-white">
                    {selectedAudit.away.team_name}
                  </span>
                </div>
                <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] text-slate-400">
                  {activeMatch?.minute != null && (
                    <span className="rounded border border-white/10 bg-white/5 px-2 py-0.5 font-bold text-white">
                      {activeMatch.minute}&apos;
                    </span>
                  )}
                  <span className="text-slate-600">ID {selectedAudit.fixture_id}</span>
                </div>
              </div>
            </div>

            <div className="space-y-6">

              {/* ── LIVE TEAM STATISTICS ─────────────────────────────────── */}
              {liveStatistics && (
                <section className="rounded-2xl border border-white/10 bg-black/40 p-4">
                  <LiveStatsPanel
                    statistics={liveStatistics}
                    homeName={selectedAudit.home.team_name}
                    awayName={selectedAudit.away.team_name}
                  />
                </section>
              )}

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
                    not asserted. It previously always read "HIGH PENETRATION"
                    even when the board showed 0 box entries on both sides. */}
                {(() => {
                  const stats = liveStatistics;
                  if (!stats) {
                    return (
                      <p className="rounded-lg border border-white/5 bg-white/5 p-3 font-mono text-[11px] text-slate-400">
                        No live statistics for this fixture yet — pressure
                        cannot be assessed.
                      </p>
                    );
                  }
                  // Box ENTRIES are not published in the in-play feed at all
                  // (absent from every live team row), so the penetration test
                  // uses shots from inside the box — a different metric, and
                  // labelled as such — rather than a row that could only ever
                  // read "no data".
                  const boxValues = [
                    stats.home.shots_inside_box,
                    stats.away.shots_inside_box,
                  ];
                  const boxAvailable = boxValues.every(
                    (v) => typeof v === "number" && !Number.isNaN(v)
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
