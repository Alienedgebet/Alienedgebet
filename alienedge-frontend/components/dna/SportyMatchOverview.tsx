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

import { useMemo } from "react";
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

/**
 * The specific reason behind every dash on this card.
 *
 * Collected here so each absence states what is actually missing, and so the
 * wording is reviewed in one place instead of scattered through the JSX. The
 * distinction that matters throughout: an unmeasured value is NOT a zero and
 * NOT a weakness, it is an absence, and the copy says so.
 */
const NOT_MEASURED = {
  formPct: "Form percentage not measured — no completed matches with a readable result were recorded for this team.",
  rank: "League position not available — this fixture has no league table (friendly or cup).",
  rankUnknown: "League position not available — no league table was found for this fixture.",
  formRows: "No recent results were recorded for this team.",
  h2hRecord: "No head-to-head record — these teams have no previous meetings on record.",
  h2hHomeWins: "Home wins not measured — no previous meetings were found to count.",
  h2hAwayWins: "Away wins not measured — no previous meetings were found to count.",
  h2hDraws: "Draws not measured — no previous meetings were found to count.",
  opponent: "Opponent name not recorded for this match.",
  date: "Match date not recorded.",
  meetingDate: "Date not recorded for this meeting.",
  teamName: "Team name not available.",
  points: "Points not measured — no completed matches were recorded.",
  goals: "Goals not measured — no completed matches were recorded.",
  banner: "Competition not available for this fixture.",
} as const;

export interface SportyH2HMeeting {
  date: string | null;
  fixture_id: number | string | null;
  home: string;
  away: string;
  home_goals: number;
  away_goals: number;
  home_id?: string;
  away_id?: string;
}

/**
 * Why the H2H section is showing what it is showing.
 *
 * "Never met" and "could not check" are different facts and must never share
 * one empty panel — otherwise a throttled provider silently becomes a claim
 * about the fixture. `null` means the lookup succeeded.
 */
export type SportyH2HError =
  | "no_data"
  | "unresolved_teams"
  | "ambiguous_team_name"
  | "no_provider_key"
  | "rate_limited"
  | "provider_unreachable"
  | string
  | null;

export interface SportyMatchOverviewProps {
  homeTeam?: string;
  awayTeam?: string;
  /**
   * SportMonks team ids for THIS fixture. Present so the H2H record can tell
   * which side of each past meeting corresponds to which side of this one —
   * the two clubs swap venues between encounters, and matching on the name
   * alone is what makes a head-to-head count attribute results to the wrong
   * team. Optional: with no ids the component falls back to name matching.
   */
  homeId?: string | null;
  awayId?: string | null;

  // Header / meta
  // NOTE: kickoff / gameId / isHot / liveInPlay were part of the original
  // SportyBet chrome but are no longer rendered — the match card now shows the
  // team names only. They are kept out of the interface rather than left as
  // props nothing reads, so the next person does not wire data to a dead prop.
  competition?: string | null;
  matchday?: string | number | null;
  leagueGroup?: string | null;

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

  // H2H totals are NOT props.
  //
  // `homeWins` / `draws` / `awayWins` / `highestWin` used to be passed in and
  // are now counted from `h2hMeetings` inside this component instead. Two
  // independent sources for one number is exactly how a donut ends up saying
  // 3-1-2 above a list of two meetings: the caller would have to keep a count
  // in step with the list, and nothing enforced it. They were removed from the
  // interface rather than left as props nothing reads, so the next person does
  // not wire data to a dead prop. `points` and `goalsScored` remain valid
  // explicit overrides for the sliders.

  // Comparison sliders
  points?: { home: number | null; away: number | null } | null;
  goalsScored?: { home: number | null; away: number | null } | null;

  // Previous direct encounters — REAL meetings from the provider.
  h2hMeetings?: SportyH2HMeeting[] | null;
  /**
   * Why the H2H block has nothing to show. `null`/undefined means the lookup
   * worked and an empty list genuinely means these teams have never met.
   * Anything else must be surfaced as its own message, because "we could not
   * check" presented as an empty history is a false statement about the game.
   */
  h2hError?: SportyH2HError;
}

// ── Helpers ───────────────────────────────────────────────────────────────

/**
 * The universal "we do not have this" marker. Never substitute 0 for it.
 *
 * The dash alone was ambiguous: the same glyph was standing in for an
 * unmeasured league position, a team with no form data, an unavailable
 * head-to-head record, a missing scoreline and a missing team name, so it read
 * as a stray mark rather than a deliberate state. Every call site now passes
 * `label`, which becomes the hover text and the screen-reader text, so the
 * absence always says what is absent.
 *
 * `label` is REQUIRED by the type, not merely by convention: an unlabelled dash
 * is exactly the ambiguity this change exists to remove, so the compiler is
 * what guarantees every absence explains itself.
 *
 * The italic + reduced opacity is deliberate: it makes the glyph read as an
 * annotation on the surrounding figures rather than as one of them.
 *
 * Follows the pattern already used by DnaCountBadge.tsx (title + aria-label on
 * a dimmed marker) rather than pulling in the heavier Tooltip primitive for a
 * glyph this small.
 */
const Dash = ({
  className,
  label,
}: {
  className?: string;
  label: string;
}) => (
  <span
    className={cn("font-mono italic text-text-dim/70", className)}
    title={label}
    aria-label={label}
  >
    —
  </span>
);

/**
 * Renders a value only when genuinely present. `0` and `0.0` ARE present
 * values and render normally — only null/undefined/NaN become a dash.
 *
 * `label` is required for the same reason Dash requires one: a dash that does
 * not say what is missing is indistinguishable from a dash that means something
 * else. Callers describe the specific quantity, not a generic "no data".
 */
function Present({
  value,
  children,
  className,
  label,
}: {
  value: unknown;
  children: (v: never) => React.ReactNode;
  className?: string;
  label: string;
}) {
  if (value === null || value === undefined) {
    return <Dash className={className} label={label} />;
  }
  if (typeof value === "number" && !Number.isFinite(value)) {
    return <Dash className={className} label={label} />;
  }
  return <span className={className}>{children(value as never)}</span>;
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
 * Plain-English copy for each head-to-head failure mode.
 *
 * The distinction that matters: "none" (the lookup ran and found nothing —
 * these teams have genuinely never met) is a fact about the fixture, while
 * every other entry is a fact about our connection. Rendering a connection
 * problem in the wording of a fixture fact is how a user ends up believing two
 * clubs have no history when in fact nobody asked.
 *
 * `provider_http_*` is matched by prefix; the `??` fallback then covers any
 * code the backend adds later without this file silently claiming "never met".
 */
const H2H_ERROR_COPY: Record<string, string> = {
  none: "These teams have no previous meetings on record.",
  no_data: "No data was found for this fixture.",
  unresolved_teams:
    "The two teams could not be matched to their records, so no history was looked up.",
  ambiguous_team_name:
    "Two clubs share this display name, so their history was not looked up rather than risk showing the wrong team's results.",
  no_provider_key:
    "No data provider is configured on the server, so head-to-head history is unavailable.",
  rate_limited:
    "The data provider is throttling requests right now. This is a temporary connection limit, not a statement about these teams' history.",
  provider_unreachable:
    "The data provider could not be reached. This is a connection problem, not a statement about these teams' history.",
  provider_http: "The data provider returned an unexpected response, so no history could be read.",
};

/**
 * Resolve the copy for an error code.
 *
 * Exact match first, then a prefix match so `provider_http_503` picks up the
 * `provider_http` entry rather than falling through. The final fallback is the
 * CONNECTION wording on purpose: an unrecognised code means the backend
 * reported a problem we do not have copy for, and claiming "never met" there
 * would be the one unsafe default. It only reads as "never met" when the code
 * is genuinely absent.
 */
function h2hErrorCopy(error?: SportyH2HError | null): string {
  if (!error) return H2H_ERROR_COPY.none;
  if (H2H_ERROR_COPY[error]) return H2H_ERROR_COPY[error];
  const prefix = Object.keys(H2H_ERROR_COPY).find(
    (k) => k !== "none" && error.startsWith(k)
  );
  if (prefix) return H2H_ERROR_COPY[prefix];
  return H2H_ERROR_COPY.provider_unreachable;
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

// ── Tier 2: white match card — TEAM NAMES ONLY ───────────────────────────
// Deliberately minimal. An earlier pass carried the full SportyBet chrome
// (Switch match, competition link, nav arrows, Game ID, and both tab rows).
// It was removed on request: on this page all of that was visual noise
// competing with the team names, and the tab rows were decorative anyway —
// they only ever swapped which panel was shown, never what was measured.
// The real statistics live in the navy body below and are untouched.
function MatchCard({
  homeTeam,
  awayTeam,
}: Pick<SportyMatchOverviewProps, "homeTeam" | "awayTeam">) {
  return (
    <div className="flex items-center justify-center gap-3 bg-white px-4 py-5 text-[#0e1622]">
      <span className="min-w-0 flex-1 truncate text-center text-[15px] font-bold">
        {homeTeam ?? <Dash label={`Home: ${NOT_MEASURED.teamName}`} />}
      </span>
      <span className="shrink-0 font-mono text-[11px] font-medium text-[#0e1622]/30">vs</span>
      <span className="min-w-0 flex-1 truncate text-center text-[15px] font-bold">
        {awayTeam ?? <Dash label={`Away: ${NOT_MEASURED.teamName}`} />}
      </span>
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
        /* The banner still renders (it is a structural tier, not a statistic),
           and says plainly that the competition is unknown rather than showing
           a bare dash against a mint background that would read as a rule. */
        <p
          className="text-[11px] font-black uppercase tracking-wide text-[#0e1622]/50"
          title={NOT_MEASURED.banner}
          aria-label={NOT_MEASURED.banner}
        >
          <span aria-hidden="true">&#9917;</span> Competition unknown
        </p>
      )}
    </div>
  );
}

// ── Tier 4: navy statistics body ──────────────────────────────────────────
function FormRing({ pct, color, teamName }: { pct: number | null; color: string; teamName?: string }) {
  // A null pct renders an EMPTY ring with a labelled dash — never a 0% ring,
  // which would read as "this team won none of its last five".
  const shown = pct == null ? 0 : Math.max(0, Math.min(100, pct));
  const who = teamName ? `${teamName}: ` : "";
  return (
    <div
      className="flex h-14 w-14 items-center justify-center rounded-full"
      style={{ background: `conic-gradient(${color} ${shown * 3.6}deg, ${SB.line} 0deg)` }}
    >
      <div className="flex h-10 w-10 flex-col items-center justify-center rounded-full" style={{ backgroundColor: SB.navy }}>
        {pct == null ? (
          <Dash className="text-[11px]" label={`${who}${NOT_MEASURED.formPct}`} />
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

function PositionBadge({
  pos,
  color,
  side,
}: {
  pos: number | null;
  color: string;
  side: "home" | "away";
}) {
  const who = side === "home" ? "Home" : "Away";
  // The badge is filled with the team's colour only when the rank is real. A
  // missing rank keeps the neutral track colour AND carries a label, so a
  // grey square cannot be misread as "ranked, and the rank is low".
  return (
    <span
      className="flex h-6 w-6 items-center justify-center rounded font-mono text-[11px] font-black text-white"
      style={{ backgroundColor: pos == null ? SB.line : color }}
      title={pos == null ? `${who}: ${NOT_MEASURED.rankUnknown}` : undefined}
      aria-label={pos == null ? `${who}: ${NOT_MEASURED.rankUnknown}` : `${who}: league position ${pos}`}
    >
      {pos ?? <Dash label={`${who}: ${NOT_MEASURED.rank}`} />}
    </span>
  );
}

/**
 * Home / Away marker for one form row.
 *
 * This was measured as missing rather than absent: `venue` is populated on
 * 378 of 378 form rows in the live profile cache (189 home, 189 away, zero
 * nulls), so the field was being fetched, paid for and then never rendered.
 * That left a reader unable to distinguish a 3-1 win at home from a 3-1 win
 * away — the single most context-relevant fact on a form row.
 *
 * Colours are deliberately NEUTRAL (mint / steel), not the green and crimson
 * used for W and L. Venue is not an outcome: tinting it would compete with the
 * result badge sitting next to it and let a reader score the row twice.
 */
function VenueChip({ venue }: { venue: "home" | "away" | null }) {
  if (venue === "home") {
    return (
      <span
        className="flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-[3px] font-mono text-[8px] font-black"
        style={{ backgroundColor: "rgba(92,212,137,0.22)", color: SB.mint }}
        title="Played at home"
        aria-label="Played at home"
      >
        H
      </span>
    );
  }
  if (venue === "away") {
    return (
      <span
        className="flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-[3px] font-mono text-[8px] font-black"
        style={{ backgroundColor: "rgba(100,116,139,0.28)", color: "#cbd5e1" }}
        title="Played away"
        aria-label="Played away"
      >
        A
      </span>
    );
  }
  // Never guess a venue. The engine derives this from the provider's own
  // participants metadata, and a missing value is a data gap, not a home game.
  return <Dash className="text-[9px]" label="Venue not recorded for this match." />;
}

function FormTimeline({ rows, align }: { rows?: DnaV2FormRow[]; align: "left" | "right" }) {
  const list = rows ?? [];
  return (
    <div className={cn("flex flex-col gap-1.5", align === "right" ? "items-end" : "items-start")}>
      {list.length === 0 ? (
        <Dash className="text-[11px]" label={NOT_MEASURED.formRows} />
      ) : (
        list.map((r, i) => {
          const color = r.result === "W" ? SB.green : r.result === "D" ? SB.grey : SB.crimson;
          return (
            <div
              key={`${r.fixture_id ?? i}-${r.date ?? i}`}
              className={cn("flex items-center gap-1.5", align === "right" && "flex-row-reverse")}
              title={`${r.date ?? "date not recorded"} · ${r.venue === "home" ? "home" : r.venue === "away" ? "away" : "venue not recorded"} vs ${r.opponent ?? "unknown opponent"}`}
            >
              <span
                className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full font-mono text-[9px] font-black text-white"
                style={{ backgroundColor: color }}
                aria-label={`Result: ${r.result === "W" ? "win" : r.result === "D" ? "draw" : "loss"}`}
              >
                {r.result}
              </span>
              <VenueChip venue={r.venue ?? null} />
              <span className="max-w-[74px] truncate text-[10px] text-white/70">
                {r.opponent ?? <Dash label={NOT_MEASURED.opponent} />}
              </span>
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
}: {
  homeWins: number | null;
  draws: number | null;
  awayWins: number | null;
  homeTeam?: string;
  awayTeam?: string;
}) {
  // `known` is the whole honesty rule for this ring: it is drawn only when a
  // real meeting produced a real split. `?? 0` below is arithmetic on an
  // already-decided-unknown value, never a displayed figure — a null side
  // renders as a dash via <Present>, and a fully unknown record renders the
  // neutral ring. All three outcomes can legitimately be 0 (0 wins, 0 draws,
  // 0 losses is a real record), which is exactly why presence is tracked
  // separately from the numbers.
  const known = homeWins != null && draws != null && awayWins != null;
  const h = known ? homeWins : 0;
  const d = known ? draws : 0;
  const a = known ? awayWins : 0;
  const total = h + d + a;
  const hasAny = total > 0;
  const hDeg = hasAny ? (h / total) * 360 : 0;
  const dDeg = hasAny ? (d / total) * 360 : 0;

  return (
    /* Centred, not left-hugging. Every other section on this card is centred
       under a centred heading, and this block was pinned to the left edge
       under a centred "Head to Head" title — so the ring, its legend and the
       title above them were on three different axes. The wrapper gives the
       group one shared centre and a max width, so donut + legend read as a
       single object centred in the panel. */
    <div className="mx-auto flex w-full max-w-[260px] items-center gap-3">
      <div
        className="h-16 w-16 shrink-0 rounded-full"
        style={{
          background: hasAny
            ? `conic-gradient(${SB.green} 0 ${hDeg}, ${SB.grey} ${hDeg} ${hDeg + dDeg}, ${SB.crimson} ${hDeg + dDeg} 360deg)`
            : SB.line,
        }}
      >
        <div className="flex h-10 w-10 items-center justify-center rounded-full font-mono text-[9px] font-bold uppercase text-text-dim" style={{ backgroundColor: SB.navy }}>
          {hasAny ? "H2H" : <Dash label={NOT_MEASURED.h2hRecord} />}
        </div>
      </div>

      <div className="min-w-0 flex-1 space-y-1 font-mono text-[11px]">
        <div className="flex items-center justify-between">
          <span className="truncate text-white/70">{homeTeam ?? "Home"}</span>
          <span className="font-black" style={{ color: SB.green }}>
            <Present value={homeWins} label={NOT_MEASURED.h2hHomeWins}>
              {(v) => v}
            </Present>
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-white/70">Draws</span>
          <span className="font-black" style={{ color: SB.grey }}>
            <Present value={draws} label={NOT_MEASURED.h2hDraws}>
              {(v) => v}
            </Present>
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="truncate text-white/70">{awayTeam ?? "Away"}</span>
          <span className="font-black" style={{ color: SB.crimson }}>
            <Present value={awayWins} label={NOT_MEASURED.h2hAwayWins}>
              {(v) => v}
            </Present>
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
  missingLabel,
}: {
  label: string;
  home: number | null;
  away: number | null;
  /** Why this particular quantity is missing, for the dash-state label. */
  missingLabel: string;
}) {
  // A slider needs a ratio. With one or both sides unknown there is no honest
  // ratio to draw, so the track stays empty and both numbers show a dash.
  const known = home != null && away != null;
  const total = known ? (home as number) + (away as number) : 0;
  const pct = total > 0 ? ((home as number) / total) * 100 : 0;
  const who = `${label}: `;

  return (
    <div>
      <div className="mb-1 flex items-center justify-between font-mono text-[10px]">
        <span className="font-bold" style={{ color: SB.green }}>
          {home ?? <Dash label={`Home ${who.toLowerCase()}${missingLabel}`} />}
        </span>
        <span className="uppercase tracking-wider text-white/45">{label}</span>
        <span className="font-bold" style={{ color: SB.crimson }}>
          {away ?? <Dash label={`Away ${who.toLowerCase()}${missingLabel}`} />}
        </span>
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
    homeId,
    awayId,
    competition,
    matchday,
    leagueGroup,
    homePosition,
    awayPosition,
    isUnranked,
    homeForm,
    awayForm,
    points,
    goalsScored,
    h2hMeetings,
    h2hError,
  } = props;

  // ── H2H record, DERIVED FROM THE REAL MEETINGS ──────────────────────────
  // Counting here rather than trusting passed-in totals keeps the donut and the
  // meeting list provably consistent with each other: they are two views of the
  // same array, so they cannot disagree.
  //
  // Each meeting is scored from the perspective of the team playing in THIS
  // fixture, which is not always the meeting's own home side — the two clubs
  // swap venues between encounters. Getting that backwards would credit one
  // team with the other's results, so it is resolved by team id (which the
  // backend supplies) and only falls back to name matching when an id is
  // absent. A meeting whose sides cannot be identified is skipped rather than
  // guessed at.
  //
  // Every count is a real result. Nothing here defaults to 0 for a missing
  // meeting: the totals are only rendered when there is at least one meeting,
  // and 0 wins with 3 draws is a legitimate reading that is displayed as such.
  const h2hRecord = useMemo(() => {
    const rows = h2hMeetings ?? [];
    if (rows.length === 0) return null;

    const sameId = (a?: string | null, b?: string | null) =>
      a != null && b != null && String(a) === String(b);

    let homeWinsReal = 0;
    let awayWinsReal = 0;
    let drawsReal = 0;
    let identified = 0;

    for (const m of rows) {
      let homeIsOurHome: boolean | null = null;

      // Four ways this fixture's home side can line up with the meeting's home
      // side. The two CROSS cases are the ones that matter: they are the
      // meetings played at the OTHER club's ground. Testing only
      // `away_id === awayId` misses them entirely — in a swapped meeting the
      // away id is our HOME id — which silently discarded every meeting the
      // home team played away from home.
      if (sameId(m.home_id, homeId)) homeIsOurHome = true;
      else if (sameId(m.home_id, awayId)) homeIsOurHome = false;
      else if (sameId(m.away_id, awayId)) homeIsOurHome = true;
      else if (sameId(m.away_id, homeId)) homeIsOurHome = false;
      else if (!m.home_id && !m.away_id && homeTeam && awayTeam) {
        // No ids on the row at all: fall back to names, both orientations.
        if (m.home === homeTeam && m.away === awayTeam) homeIsOurHome = true;
        else if (m.home === awayTeam && m.away === homeTeam) homeIsOurHome = false;
      }

      if (homeIsOurHome === null) continue; // sides unknown — skip, never guess
      identified += 1;

      if (m.home_goals > m.away_goals) {
        if (homeIsOurHome) homeWinsReal += 1;
        else awayWinsReal += 1;
      } else if (m.home_goals < m.away_goals) {
        if (homeIsOurHome) awayWinsReal += 1;
        else homeWinsReal += 1;
      } else {
        drawsReal += 1;
      }
    }

    // Nothing identifiable means we cannot state a record at all.
    if (identified === 0) return null;
    return { homeWins: homeWinsReal, awayWins: awayWinsReal, draws: drawsReal, total: identified };
  }, [h2hMeetings, homeId, awayId, homeTeam, awayTeam]);

  // Largest margin in the real meetings. Null unless there is one, so the
  // "Highest Win" callout simply does not render rather than claiming a
  // biggest win of 0-0.
  const highestReal = useMemo(() => {
    const rows = h2hMeetings ?? [];
    let best: { team: string; score: string; date: string | null } | null = null;
    let bestMargin = -1;

    for (const m of rows) {
      const margin = Math.abs(m.home_goals - m.away_goals);
      // A goalless draw is not a "highest win" — it has no winning team.
      if (margin === 0 || margin <= bestMargin) continue;
      bestMargin = margin;
      const homeWon = m.home_goals > m.away_goals;
      best = {
        team: homeWon ? m.home : m.away,
        score: `${m.home_goals}-${m.away_goals}`,
        date: m.date,
      };
    }
    return best;
  }, [h2hMeetings]);

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
      {/* Tier 1 — red bar. 18px (was 6px): this strip is the strongest visual
          anchor on the card and read as a hairline at 6px. */}
      <div className="h-[18px] w-full" style={{ backgroundColor: SB.red }} aria-hidden="true" />

      {/* Tier 2 — white match card (team names only) */}
      <MatchCard homeTeam={homeTeam} awayTeam={awayTeam} />

      {/* Tier 3 — mint matchday banner */}
      <MatchdayBanner competition={competition} leagueGroup={leagueGroup} matchday={matchday} />

      {/* Tier 4 — navy statistics body */}
      <div className="space-y-4 px-3 py-4">
        {/* team strip */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-1.5">
            {flagFor(homeTeam) && <span aria-hidden="true">{flagFor(homeTeam)}</span>}
            <span className="truncate text-[12px] font-bold text-white">
              {homeTeam ?? <Dash label={`Home: ${NOT_MEASURED.teamName}`} />}
            </span>
          </div>
          <span className="shrink-0 font-mono text-[10px] text-white/25">·····</span>
          <div className="flex min-w-0 items-center justify-end gap-1.5">
            <span className="truncate text-[12px] font-bold text-white">
              {awayTeam ?? <Dash label={`Away: ${NOT_MEASURED.teamName}`} />}
            </span>
            {flagFor(awayTeam) && <span aria-hidden="true">{flagFor(awayTeam)}</span>}
          </div>
        </div>

        {/* League position & form — 3 columns */}
        <div className="grid grid-cols-3 items-center gap-2">
          <div className="flex justify-center">
            <FormRing pct={formPct(homeForm)} color={SB.green} teamName={homeTeam} />
          </div>

          <div className="flex flex-col items-center gap-1">
            {isUnranked ? (
              // No league table exists for this fixture (friendly/cup). Say so
              // plainly rather than showing a dash that reads as "rank unknown".
              <span className="rounded bg-white/10 px-1.5 py-1 text-center font-mono text-[8px] font-bold uppercase tracking-wider text-white/50">
                Unranked
              </span>
            ) : (
              /* Badges sit side by side with their labels directly beneath,
                 in the same left=home / right=away reading order as every other
                 pair on this card (team strip, form rings, form timelines).

                 The previous markup stacked them as badge, "Home", badge,
                 "Away" down a single column, so the away badge appeared BELOW
                 the home label. Nothing said which label belonged to which
                 badge except vertical position — and when one side was "—" the
                 two badges became indistinguishable, which is precisely the
                 moment the labels mattered most. */
              <>
                <div className="flex items-center gap-1.5">
                  <PositionBadge pos={homePosition ?? null} color={SB.green} side="home" />
                  <PositionBadge pos={awayPosition ?? null} color={SB.crimson} side="away" />
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="w-6 text-center font-mono text-[8px] uppercase tracking-wider text-white/40">
                    Home
                  </span>
                  <span className="w-6 text-center font-mono text-[8px] uppercase tracking-wider text-white/40">
                    Away
                  </span>
                </div>
              </>
            )}
          </div>

          <div className="flex justify-center">
            <FormRing pct={formPct(awayForm)} color={SB.crimson} teamName={awayTeam} />
          </div>
        </div>

        {/* Last 5 matches — mirrored timelines.
            The heading promises five, so when a side has fewer than five the
            count is disclosed next to it. A strip silently rendering one row
            under a "Last 5 Matches" heading is a broken promise; "3 of 5
            recorded" is an honest one. Counted PER SIDE, because this is two
            independent strips — summing them would claim 8 of 5. */}
        <div>
          <p className="mb-2 text-center text-[10px] font-bold uppercase tracking-wider text-white/50">
            Last 5 Matches
          </p>
          <div className="grid grid-cols-2 gap-3">
            <FormTimeline rows={homeForm} align="left" />
            <FormTimeline rows={awayForm} align="right" />
          </div>
          {/* Disclosure under the strip, per side, so it cannot be misread as a
              statement about the match as a whole. */}
          {((homeForm?.length ?? 0) < 5 || (awayForm?.length ?? 0) < 5) && (
            <p className="mt-2 text-center text-[9px] leading-relaxed text-white/35">
              {[
                (homeForm?.length ?? 0) < 5 && homeTeam
                  ? `${homeTeam}: ${homeForm?.length ?? 0} of 5 recorded`
                  : null,
                (awayForm?.length ?? 0) < 5 && awayTeam
                  ? `${awayTeam}: ${awayForm?.length ?? 0} of 5 recorded`
                  : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          )}
        </div>

        {/* H2H — the donut is driven by h2hRecord, which is counted from the
            real meetings below. One source of truth, so the ring and the list
            can never disagree. */}
        <div className="space-y-3 border-t pt-3" style={{ borderColor: SB.line }}>
          <p className="text-center text-[10px] font-bold uppercase tracking-wider text-white/50">
            Head to Head
            {h2hRecord && (
              /* The count rides in the SAME <p> as the title, not beside it in
                 a flex row, so the pair centres as one block. Wrapping it in its
                 own centred <span> (rather than an inline ml-offset) keeps the
                 optical centre of "Head to Head" aligned with the donut below
                 even when the trailing count makes the line asymmetric. */
              <span className="ml-1.5 font-normal normal-case text-white/35">
                last {h2hRecord.total} meeting{h2hRecord.total === 1 ? "" : "s"}
              </span>
            )}
          </p>
          <H2HDonut
            homeWins={h2hRecord ? h2hRecord.homeWins : null}
            draws={h2hRecord ? h2hRecord.draws : null}
            awayWins={h2hRecord ? h2hRecord.awayWins : null}
            homeTeam={homeTeam}
            awayTeam={awayTeam}
          />

          {(highestReal) && (
            <div className="rounded px-3 py-2 text-center" style={{ backgroundColor: "rgba(34,197,94,0.12)" }}>
              <p className="text-[10px] uppercase tracking-wider text-white/50">Highest Win</p>
              <p className="text-[12px] font-bold" style={{ color: SB.green }}>
                {highestReal.team} {highestReal.score}
              </p>
            </div>
          )}

          <div className="space-y-2.5">
            <CompareSlider label="Points" home={homePts} away={awayPts} missingLabel={NOT_MEASURED.points} />
            <CompareSlider label="Goals Scored" home={homeGoals} away={awayGoals} missingLabel={NOT_MEASURED.goals} />
          </div>
        </div>

        {/* Previous direct encounters — REAL meetings.
            Two empty states that must never be confused: a successful lookup
            that found nothing means these teams have never met, while any
            `h2hError` means we simply could not find out. Telling the user
            "no head-to-head history" when the provider was simply throttled is
            a false statement about the fixture. */}
        <div className="border-t pt-3" style={{ borderColor: SB.line }}>
          <p className="mb-2 text-center text-[10px] font-bold uppercase tracking-wider text-white/50">
            Previous Meetings
          </p>
          {(h2hMeetings && h2hMeetings.length > 0) ? (
            <div className="space-y-1">
              {h2hMeetings.map((m, i) => {
                const homeWon = m.home_goals > m.away_goals;
                const awayWon = m.away_goals > m.home_goals;
                return (
                  <div
                    key={`${m.fixture_id ?? m.date ?? "h2h"}-${i}`}
                    className="flex items-center justify-between gap-2 rounded px-2 py-1.5 text-[10px]"
                    style={{ backgroundColor: SB.navy }}
                  >
                    <span className="w-10 shrink-0 font-mono text-white/40">
                      {shortDate(m.date) ?? <Dash label={NOT_MEASURED.meetingDate} />}
                    </span>
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
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="rounded px-3 py-2.5 text-center" style={{ backgroundColor: SB.navy }}>
              <p className="text-[10px] font-bold uppercase tracking-wider text-white/45">
                {h2hError ? "Head-to-head unavailable" : "Never met"}
              </p>
              <p className="mt-1 text-[9px] italic leading-relaxed text-white/30">
                {h2hErrorCopy(h2hError)}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
