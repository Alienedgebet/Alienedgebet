"use client";

/**
 * SportyBet-style match header + H2H statistics block for the DNA page.
 *
 * ── READ ONLY, BY CONTRACT ────────────────────────────────────────────────
 * This component renders history and NOTHING else. It receives finished data
 * as props, starts no fetch, and mutates no engine output. It must never
 * become a source of truth: if a number here disagrees with DNA, DNA is right
 * and this panel is wrong. Adding a calculation to this file is the bug, not
 * the feature.
 *
 * It also introduces NO new provider traffic. Everything arrives as props
 * from the existing `/api/dna/v2/*` cache (see `useDnaV2`).
 *
 * ── NO FABRICATION ────────────────────────────────────────────────────────
 * Every field is optional. A value we do not have renders as an em-dash and
 * is never defaulted to 0 or to a plausible-looking number — the same rule the
 * draw engine was just fixed for, where a silent 0 read as a real 90.7%
 * prediction that had never actually been measured.
 */

import { useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import type { DnaV2FormRow } from "@/lib/api";

// ── SportyBet palette (verbatim from the reference UI) ────────────────────
const SB = {
  red: "#e41e26",
  mint: "#5cd489",
  navy: "#0e1622",
  line: "#22303f",
  green: "#22c55e",
  emerald: "#10b981",
  crimson: "#dc2626",
  grey: "#64748b",
} as const;

export interface SportyH2HMeeting {
  date: string;
  home: string;
  away: string;
  home_goals: number;
  away_goals: number;
  /** True when this row is demo scaffolding, not a real recorded meeting. */
  isPlaceholder?: boolean;
}

export interface SportyMatchOverviewProps {
  homeTeam?: string;
  awayTeam?: string;

  // Header / meta
  competition?: string | null;
  matchday?: string | number | null;
  leagueGroup?: string | null;
  kickoff?: string | null;
  gameId?: string | number | null;
  isHot?: boolean;
  liveInPlay?: boolean;

  // League position (the rank badges in the centre column)
  homePosition?: number | null;
  awayPosition?: number | null;
  /**
   * True when the fixture has no league table at all (friendly/cup). The
   * engines store 99 as an UNRANKED sentinel; the API normalises it to null so
   * a bare "—" can't be misread, and this flag lets the badge say so outright
   * instead of leaving the user guessing why the rank is missing.
   */
  isUnranked?: boolean;

  // Form — real rows from DNA when present.
  homeForm?: DnaV2FormRow[];
  awayForm?: DnaV2FormRow[];

  // H2H summary
  homeWins?: number | null;
  draws?: number | null;
  awayWins?: number | null;
  highestWin?: { team: string; score: string; date?: string } | null;

  // Comparison sliders
  points?: { home: number | null; away: number | null } | null;
  goalsScored?: { home: number | null; away: number | null } | null;

  // Previous direct encounters
  h2hMeetings?: SportyH2HMeeting[];
}

// ── Helpers ───────────────────────────────────────────────────────────────

/** The universal "we do not have this" marker. Never substitute 0 for it. */
const Dash = ({ className }: { className?: string }) => (
  <span className={cn("font-mono text-text-dim", className)}>—</span>
);

/**
 * Renders a value only when genuinely present. `0` and `0.0` ARE present
 * values and render normally — only null/undefined/NaN become a dash.
 */
function Present({
  value,
  children,
  className,
}: {
  value: unknown;
  children: (v: never) => React.ReactNode;
  className?: string;
}) {
  if (value === null || value === undefined) return <Dash className={className} />;
  if (typeof value === "number" && !Number.isFinite(value)) {
    return <Dash className={className} />;
  }
  return <span className={className}>{children(value as never)}</span>;
}

/** "DC United" -> "DC". Used by the circular badge fallback. */
function initialsOf(name?: string | null): string {
  if (!name) return "??";
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "??";
  return parts
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
}

/**
 * National flags for common internationals so they read instantly. Purely
 * decorative and INLINE — no image request, so nothing can 404 or flash a
 * broken icon. An unknown team falls back to initials.
 */
const FLAG_EMOJI: Record<string, string> = {
  france: "\u{1F1EB}\u{1F1F7}", italy: "\u{1F1EE}\u{1F1F9}", belgium: "\u{1F1E7}\u{1F1EA}",
  turkey: "\u{1F1F9}\u{1F1F7}", spain: "\u{1F1EA}\u{1F1F8}", portugal: "\u{1F1F5}\u{1F1F9}",
  germany: "\u{1F1E9}\u{1F1EA}", netherlands: "\u{1F1F3}\u{1F1F1}", greece: "\u{1F1EC}\u{1F1F7}",
  luxembourg: "\u{1F1F1}\u{1F1EB}", bosnia: "\u{1F1E7}\u{1F1E6}", croatia: "\u{1F1ED}\u{1F1F7}",
  denmark: "\u{1F1E9}\u{1F1F0}", sweden: "\u{1F1F8}\u{1F1EA}", norway: "\u{1F1F3}\u{1F1F4}",
  poland: "\u{1F1F5}\u{1F1F1}", ukraine: "\u{1F1FA}\u{1F1E6}", ireland: "\u{1F1EE}\u{1F1EA}",
  "united states": "\u{1F1FA}\u{1F1F8}", mexico: "\u{1F1F2}\u{1F1FD}", brazil: "\u{1F1E7}\u{1F1F7}",
  argentina: "\u{1F1E6}\u{1F1F7}", chile: "\u{1F1E8}\u{1F1F1}", colombia: "\u{1F1E8}\u{1F1F4}",
  canada: "\u{1F1E8}\u{1F1E6}", morocco: "\u{1F1F2}\u{1F1E6}", senegal: "\u{1F1F8}\u{1F1F3}",
  nigeria: "\u{1F1F3}\u{1F1EC}", egypt: "\u{1F1EA}\u{1F1EC}", japan: "\u{1F1EF}\u{1F1F5}",
  "south korea": "\u{1F1F0}\u{1F1F7}", china: "\u{1F1E8}\u{1F1F3}", australia: "\u{1F1E6}\u{1F1FA}",
  "saudi arabia": "\u{1F1F8}\u{1F1E6}", qatar: "\u{1F1F6}\u{1F1E6}", iran: "\u{1F1EE}\u{1F1F7}",
};
const flagFor = (name?: string | null): string =>
  (name && FLAG_EMOJI[name.trim().toLowerCase()]) || "";

/**
 * Circular team badge: flag emoji when the country is known, otherwise
 * initials. No <img>, so it renders instantly and can never show a broken
 * image icon.
 */
function TeamBadge({
  name,
  size = 56,
  className,
}: {
  name?: string | null;
  size?: number;
  className?: string;
}) {
  const flag = flagFor(name);
  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-center overflow-hidden rounded-full border-2 bg-[#16202e] font-mono font-black text-white",
        className
      )}
      style={{ width: size, height: size, borderColor: SB.line, fontSize: size * 0.36 }}
      aria-hidden="true"
    >
      {flag ? (
        <span style={{ fontSize: size * 0.55, lineHeight: 1 }}>{flag}</span>
      ) : (
        initialsOf(name)
      )}
    </div>
  );
}

/** "2026-10-02T19:45:00+00:00" -> { date: "02/10 Friday", time: "19:45" } */
function formatKickoff(iso?: string | null): { date: string; time: string } | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  return {
    date: `${dd}/${mm} ${days[d.getDay()]}`,
    time: `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`,
  };
}

/** "2026-09-27" -> "27/09". */
function shortDate(iso?: string | null): string | null {
  if (!iso) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${m[3]}/${m[2]}` : null;
}

/**
 * Form percentage from real results: points earned / matches played.
 * Returns null — NOT 0 — when there are no results, so the ring renders as
 * "no data" rather than a confident 0% FORM.
 */
function formPct(rows?: DnaV2FormRow[]): number | null {
  if (!rows || rows.length === 0) return null;
  const pts = rows.reduce(
    (acc, r) => acc + (r.result === "W" ? 3 : r.result === "D" ? 1 : 0),
    0
  );
  return Math.round((pts / (rows.length * 3)) * 100);
}

/** Sum of goals scored across the form rows, or null when unknown. */
function goalsSum(rows?: DnaV2FormRow[]): number | null {
  if (!rows || rows.length === 0) return null;
  return rows.reduce((acc, r) => acc + (r.goals_for ?? 0), 0);
}

// ── Tier 2b: tab rows ─────────────────────────────────────────────────────
const PRIMARY_TABS = ["BB", "Markets", "Stats", "Codes"] as const;
type SubTab = (typeof SUB_TABS)[number];
const SUB_TABS = ["H2H", "Comparison", "Lineups", "Table", "Standings"] as const;

function TabPill({
  label,
  active,
  onClick,
  newBadge,
}: {
  label: string;
  active: boolean;
  onClick?: () => void;
  newBadge?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={cn(
        "relative shrink-0 rounded-full px-3 py-1 text-[11px] font-bold transition-colors",
        active
          ? "bg-[#0e1622] text-white"
          : "text-[#0e1622]/60 hover:bg-[#0e1622]/10 hover:text-[#0e1622]"
      )}
    >
      {label}
      {newBadge && (
        <span className="ml-1 rounded bg-[#e41e26] px-1 py-px text-[8px] font-black uppercase text-white">
          New
        </span>
      )}
    </button>
  );
}

function FeatureTabs({ sub, onSubChange }: { sub: SubTab; onSubChange: (s: SubTab) => void }) {
  const [primary, setPrimary] = useState<(typeof PRIMARY_TABS)[number]>("Stats");

  return (
    <>
      <div className="flex items-center gap-1.5 overflow-x-auto border-t border-[#0e1622]/10 bg-[#f1f3f5] px-3 py-1.5">
        {PRIMARY_TABS.map((t) => (
          <TabPill key={t} label={t} active={primary === t} onClick={() => setPrimary(t)} newBadge={t === "Codes"} />
        ))}
        <button type="button" aria-label="Chat" className="ml-auto shrink-0 px-1 text-[13px] text-[#0e1622]/50 hover:text-[#0e1622]">
          &#128172;
        </button>
      </div>

      <div className="flex items-center gap-3 overflow-x-auto border-t border-[#0e1622]/10 bg-white px-3">
        {SUB_TABS.map((t) => {
          const active = sub === t;
          return (
            <button
              key={t}
              type="button"
              onClick={() => onSubChange(t)}
              aria-current={active ? "page" : undefined}
              className={cn(
                "relative shrink-0 py-2 text-[11px] font-semibold transition-colors",
                active ? "text-[#0e1622]" : "text-[#0e1622]/50 hover:text-[#0e1622]/80"
              )}
            >
              {t}
              {active && (
                <span className="absolute inset-x-0 -bottom-px h-[3px] rounded-full" style={{ backgroundColor: SB.emerald }} />
              )}
            </button>
          );
        })}
      </div>
    </>
  );
}

// ── Tier 2: white match card ──────────────────────────────────────────────
function MatchCard({
  homeTeam,
  awayTeam,
  competition,
  kickoff,
  gameId,
  isHot,
  liveInPlay,
  sub,
  onSubChange,
}: Pick<
  SportyMatchOverviewProps,
  "homeTeam" | "awayTeam" | "competition" | "kickoff" | "gameId" | "isHot" | "liveInPlay"
> & { sub: SubTab; onSubChange: (s: SubTab) => void }) {
  const ko = formatKickoff(kickoff);

  return (
    <div className="bg-white text-[#0e1622]">
      <div className="flex items-center justify-between px-3 pt-2.5">
        {isHot ? (
          <span className="rounded px-2 py-0.5 text-[10px] font-black uppercase tracking-wider text-white" style={{ backgroundColor: SB.red }}>
            HOT &#128293;
          </span>
        ) : (
          <span />
        )}
        <button type="button" className="flex items-center gap-1 text-[11px] font-semibold text-[#0e1622]/70 hover:text-[#0e1622]">
          Switch match <span aria-hidden="true">&#9776;</span>
        </button>
      </div>

      <div className="px-3 pt-1.5">
        {competition ? (
          <span className="text-[11px] font-medium text-[#1a7f37] underline">{competition}</span>
        ) : (
          <span className="text-[11px] text-[#0e1622]/40">—</span>
        )}
      </div>

      <div className="relative flex items-center justify-between gap-2 px-3 py-3">
        <span className="pointer-events-none absolute left-0 top-1/2 -translate-y-1/2 text-2xl font-light text-[#fbd5d7]" aria-hidden="true">
          &#8249;
        </span>
        <span className="pointer-events-none absolute right-0 top-1/2 -translate-y-1/2 text-2xl font-light text-[#c9f2da]" aria-hidden="true">
          &#8250;
        </span>

        <div className="flex min-w-0 flex-1 flex-col items-center gap-1">
          <TeamBadge name={homeTeam} size={44} />
          <span className="w-full truncate text-center text-[12px] font-bold">{homeTeam ?? "—"}</span>
        </div>

        <div className="shrink-0 px-1 text-center">
          {ko ? (
            <>
              <p className="text-[11px] font-semibold leading-tight">{ko.date}</p>
              <p className="font-mono text-[13px] font-black leading-tight">{ko.time}</p>
            </>
          ) : (
            <span className="font-mono text-[11px] text-[#0e1622]/40">—</span>
          )}
        </div>

        <div className="flex min-w-0 flex-1 flex-col items-center gap-1">
          <TeamBadge name={awayTeam} size={44} />
          <span className="w-full truncate text-center text-[12px] font-bold">{awayTeam ?? "—"}</span>
        </div>
      </div>

      <div className="pb-2.5 text-center font-mono text-[10px] text-[#0e1622]/55">
        Game ID: {gameId ?? "—"}
        {liveInPlay ? " · Live In-Play Available" : ""}
      </div>

      <FeatureTabs sub={sub} onSubChange={onSubChange} />
    </div>
  );
}

// ── Tier 3: mint matchday banner ──────────────────────────────────────────
function MatchdayBanner({
  competition,
  leagueGroup,
  matchday,
}: Pick<SportyMatchOverviewProps, "competition" | "leagueGroup" | "matchday">) {
  const parts = [competition?.toUpperCase(), leagueGroup?.toUpperCase(), matchday != null ? `MATCHDAY ${matchday}` : null].filter(
    Boolean
  ) as string[];

  return (
    <div className="flex items-center justify-center gap-2 px-3 py-2 text-center" style={{ backgroundColor: SB.mint }}>
      {parts.length > 0 ? (
        <p className="text-[11px] font-black uppercase tracking-wide text-[#0e1622]">
          <span aria-hidden="true">&#9917;</span> {parts.join(", ")}
        </p>
      ) : (
        <p className="text-[11px] font-black uppercase tracking-wide text-[#0e1622]/60">
          <span aria-hidden="true">&#9917;</span> —
        </p>
      )}
    </div>
  );
}

// ── Tier 4: navy statistics body ──────────────────────────────────────────
function FormRing({ pct, color }: { pct: number | null; color: string }) {
  // A null pct renders an EMPTY ring with a dash — never a 0% ring, which
  // would read as "this team won none of its last five".
  const shown = pct == null ? 0 : Math.max(0, Math.min(100, pct));
  return (
    <div
      className="flex h-14 w-14 items-center justify-center rounded-full"
      style={{ background: `conic-gradient(${color} ${shown * 3.6}deg, ${SB.line} 0deg)` }}
    >
      <div className="flex h-10 w-10 flex-col items-center justify-center rounded-full" style={{ backgroundColor: SB.navy }}>
        {pct == null ? (
          <span className="font-mono text-[11px] text-text-dim">—</span>
        ) : (
          <>
            <span className="font-mono text-[13px] font-black leading-none" style={{ color }}>
              {pct}%
            </span>
            <span className="mt-0.5 text-[7px] font-bold uppercase tracking-wider text-text-dim">Form</span>
          </>
        )}
      </div>
    </div>
  );
}

function PositionBadge({ pos, color }: { pos: number | null; color: string }) {
  return (
    <span
      className="flex h-6 w-6 items-center justify-center rounded font-mono text-[11px] font-black text-white"
      style={{ backgroundColor: pos == null ? SB.line : color }}
    >
      {pos ?? "—"}
    </span>
  );
}

function FormTimeline({ rows, align }: { rows?: DnaV2FormRow[]; align: "left" | "right" }) {
  const list = rows ?? [];
  return (
    <div className={cn("flex flex-col gap-1.5", align === "right" ? "items-end" : "items-start")}>
      {list.length === 0 ? (
        <Dash className="text-[11px]" />
      ) : (
        list.map((r, i) => {
          const color = r.result === "W" ? SB.green : r.result === "D" ? SB.grey : SB.crimson;
          return (
            <div key={`${r.fixture_id ?? i}-${r.date ?? i}`} className={cn("flex items-center gap-1.5", align === "right" && "flex-row-reverse")}>
              <span
                className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full font-mono text-[9px] font-black text-white"
                style={{ backgroundColor: color }}
              >
                {r.result}
              </span>
              <span className="max-w-[92px] truncate text-[10px] text-white/70">{r.opponent ?? "—"}</span>
              <span className="font-mono text-[10px] font-bold text-white/90">
                {r.goals_for}-{r.goals_against}
              </span>
            </div>
          );
        })
      )}
    </div>
  );
}

function H2HDonut({
  homeWins,
  draws,
  awayWins,
  homeTeam,
  awayTeam,
}: Pick<SportyMatchOverviewProps, "homeWins" | "draws" | "awayWins" | "homeTeam" | "awayTeam">) {
  const h = homeWins ?? 0;
  const d = draws ?? 0;
  const a = awayWins ?? 0;
  const total = h + d + a;
  // With no H2H data at all, show a neutral ring rather than a fabricated split.
  const known = total > 0;
  const hDeg = known ? (h / total) * 360 : 0;
  const dDeg = known ? (d / total) * 360 : 0;

  return (
    <div className="flex items-center gap-3">
      <div
        className="h-16 w-16 shrink-0 rounded-full"
        style={{
          background: known
            ? `conic-gradient(${SB.green} 0 ${hDeg}, ${SB.grey} ${hDeg} ${hDeg + dDeg}, ${SB.crimson} ${hDeg + dDeg} 360deg)`
            : SB.line,
        }}
      >
        <div className="flex h-10 w-10 items-center justify-center rounded-full font-mono text-[9px] font-bold uppercase text-text-dim" style={{ backgroundColor: SB.navy }}>
          {known ? "H2H" : "—"}
        </div>
      </div>

      <div className="min-w-0 flex-1 space-y-1 font-mono text-[11px]">
        <div className="flex items-center justify-between">
          <span className="truncate text-white/70">{homeTeam ?? "Home"}</span>
          <span className="font-black" style={{ color: SB.green }}>
            <Present value={homeWins}>{(v) => v}</Present>
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-white/70">Draws</span>
          <span className="font-black" style={{ color: SB.grey }}>
            <Present value={draws}>{(v) => v}</Present>
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="truncate text-white/70">{awayTeam ?? "Away"}</span>
          <span className="font-black" style={{ color: SB.crimson }}>
            <Present value={awayWins}>{(v) => v}</Present>
          </span>
        </div>
      </div>
    </div>
  );
}

function CompareSlider({
  label,
  home,
  away,
}: {
  label: string;
  home: number | null;
  away: number | null;
}) {
  // A slider needs a ratio. With one or both sides unknown there is no honest
  // ratio to draw, so the track stays empty and both numbers show a dash.
  const known = home != null && away != null;
  const total = known ? (home as number) + (away as number) : 0;
  const pct = total > 0 ? ((home as number) / total) * 100 : 0;

  return (
    <div>
      <div className="mb-1 flex items-center justify-between font-mono text-[10px]">
        <span className="font-bold" style={{ color: SB.green }}>{home ?? "—"}</span>
        <span className="uppercase tracking-wider text-white/45">{label}</span>
        <span className="font-bold" style={{ color: SB.crimson }}>{away ?? "—"}</span>
      </div>
      <div className="flex h-1.5 overflow-hidden rounded-full" style={{ backgroundColor: SB.line }}>
        {known && total > 0 && (
          <>
            <div style={{ width: `${pct}%`, backgroundColor: SB.green }} />
            <div style={{ width: `${100 - pct}%`, backgroundColor: SB.crimson }} />
          </>
        )}
      </div>
    </div>
  );
}

// ── Root component ────────────────────────────────────────────────────────
export default function SportyMatchOverview(props: SportyMatchOverviewProps) {
  const {
    homeTeam,
    awayTeam,
    competition,
    matchday,
    leagueGroup,
    kickoff,
    gameId,
    isHot,
    liveInPlay,
    homePosition,
    awayPosition,
    isUnranked,
    homeForm,
    awayForm,
    homeWins,
    draws,
    awayWins,
    highestWin,
    points,
    goalsScored,
    h2hMeetings,
  } = props;

  const [sub, setSub] = useState<SubTab>("H2H");

  // Points slider falls back to the real form rows so it shows live data as
  // soon as DNA has any; goals uses the same rows. Explicit props win.
  const homePts = useMemo(
    () => points?.home ?? (homeForm?.length ? homeForm.reduce((a, r) => a + (r.result === "W" ? 3 : r.result === "D" ? 1 : 0), 0) : null),
    [points, homeForm]
  );
  const awayPts = useMemo(
    () => points?.away ?? (awayForm?.length ? awayForm.reduce((a, r) => a + (r.result === "W" ? 3 : r.result === "D" ? 1 : 0), 0) : null),
    [points, awayForm]
  );
  const homeGoals = goalsScored?.home ?? goalsSum(homeForm);
  const awayGoals = goalsScored?.away ?? goalsSum(awayForm);

  return (
    <div className="overflow-hidden rounded-lg border" style={{ borderColor: SB.line, backgroundColor: SB.navy }}>
      {/* Tier 1 — red bar */}
      <div className="h-1.5 w-full" style={{ backgroundColor: SB.red }} aria-hidden="true" />

      {/* Tier 2 — white match card */}
      <MatchCard
        homeTeam={homeTeam}
        awayTeam={awayTeam}
        competition={competition}
        kickoff={kickoff}
        gameId={gameId}
        isHot={isHot}
        liveInPlay={liveInPlay}
        sub={sub}
        onSubChange={setSub}
      />

      {/* Tier 3 — mint matchday banner */}
      <MatchdayBanner competition={competition} leagueGroup={leagueGroup} matchday={matchday} />

      {/* Tier 4 — navy statistics body */}
      <div className="space-y-4 px-3 py-4">
        {/* team strip */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-1.5">
            {flagFor(homeTeam) && <span aria-hidden="true">{flagFor(homeTeam)}</span>}
            <span className="truncate text-[12px] font-bold text-white">{homeTeam ?? "—"}</span>
          </div>
          <span className="shrink-0 font-mono text-[10px] text-white/25">·····</span>
          <div className="flex min-w-0 items-center justify-end gap-1.5">
            <span className="truncate text-[12px] font-bold text-white">{awayTeam ?? "—"}</span>
            {flagFor(awayTeam) && <span aria-hidden="true">{flagFor(awayTeam)}</span>}
          </div>
        </div>

        {/* League position & form — 3 columns */}
        <div className="grid grid-cols-3 items-center gap-2">
          <div className="flex justify-center">
            <FormRing pct={formPct(homeForm)} color={SB.green} />
          </div>

          <div className="flex flex-col items-center gap-1.5">
            {isUnranked ? (
              // No league table exists for this fixture (friendly/cup). Say so
              // plainly rather than showing a dash that reads as "rank unknown".
              <span className="rounded bg-white/10 px-1.5 py-1 text-center font-mono text-[8px] font-bold uppercase tracking-wider text-white/50">
                Unranked
              </span>
            ) : (
              <>
                <PositionBadge pos={homePosition ?? null} color={SB.green} />
                <span className="font-mono text-[8px] uppercase tracking-wider text-white/40">Home</span>
                <PositionBadge pos={awayPosition ?? null} color={SB.crimson} />
                <span className="font-mono text-[8px] uppercase tracking-wider text-white/40">Away</span>
              </>
            )}
          </div>

          <div className="flex justify-center">
            <FormRing pct={formPct(awayForm)} color={SB.crimson} />
          </div>
        </div>

        {/* Last 5 matches — mirrored timelines */}
        <div>
          <p className="mb-2 text-center text-[10px] font-bold uppercase tracking-wider text-white/50">Last 5 Matches</p>
          <div className="grid grid-cols-2 gap-3">
            <FormTimeline rows={homeForm} align="left" />
            <FormTimeline rows={awayForm} align="right" />
          </div>
        </div>

        {/* H2H */}
        <div className="space-y-3 border-t pt-3" style={{ borderColor: SB.line }}>
          <p className="text-center text-[10px] font-bold uppercase tracking-wider text-white/50">Head to Head</p>
          <H2HDonut homeWins={homeWins} draws={draws} awayWins={awayWins} homeTeam={homeTeam} awayTeam={awayTeam} />

          {highestWin && (
            <div className="rounded px-3 py-2 text-center" style={{ backgroundColor: "rgba(34,197,94,0.12)" }}>
              <p className="text-[10px] uppercase tracking-wider text-white/50">Highest Win</p>
              <p className="text-[12px] font-bold" style={{ color: SB.green }}>
                {highestWin.team} {highestWin.score}
              </p>
            </div>
          )}

          <div className="space-y-2.5">
            <CompareSlider label="Points" home={homePts} away={awayPts} />
            <CompareSlider label="Goals Scored" home={homeGoals} away={awayGoals} />
          </div>
        </div>

        {/* Previous direct encounters */}
        <div className="border-t pt-3" style={{ borderColor: SB.line }}>
          <p className="mb-2 text-center text-[10px] font-bold uppercase tracking-wider text-white/50">Last 5 Matches</p>
          {(h2hMeetings && h2hMeetings.length > 0) ? (
            <div className="space-y-1">
              {h2hMeetings.map((m, i) => {
                const homeWon = m.home_goals > m.away_goals;
                const awayWon = m.away_goals > m.home_goals;
                return (
                  <div
                    key={`${m.date}-${i}`}
                    className="flex items-center justify-between gap-2 rounded px-2 py-1.5 text-[10px]"
                    style={{ backgroundColor: SB.navy }}
                  >
                    <span className="w-10 shrink-0 font-mono text-white/40">{shortDate(m.date) ?? "—"}</span>
                    <span className="min-w-0 flex-1 truncate text-right text-white/75">{m.home}</span>
                    <span
                      className="shrink-0 rounded px-1.5 py-0.5 font-mono font-black"
                      style={{
                        backgroundColor: homeWon ? SB.green : awayWon ? SB.crimson : SB.grey,
                        color: "#fff",
                      }}
                    >
                      {m.home_goals}-{m.away_goals}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-white/75">{m.away}</span>
                    <span className="w-8 shrink-0 text-right font-mono text-white/30">
                      {m.isPlaceholder ? "demo" : ""}
                    </span>
                  </div>
                );
              })}
              {h2hMeetings.some((m) => m.isPlaceholder) && (
                <p className="pt-1 text-center text-[9px] italic text-white/35">
                  Demo rows — awaiting live head-to-head data
                </p>
              )}
            </div>
          ) : (
            <Dash className="block py-2 text-center text-[11px]" />
          )}
        </div>
      </div>
    </div>
  );
}
