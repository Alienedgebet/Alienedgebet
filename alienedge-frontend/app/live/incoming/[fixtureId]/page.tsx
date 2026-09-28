"use client";

/**
 * INCOMING FORENSIC DRILL-DOWN
 * ============================
 * /live/incoming/[fixtureId] — why did the incoming feed call this fixture?
 *
 * The Incoming list answers "what did the engine predict"; this page answers
 * "on what evidence", for both teams. It is a join, not a new engine: the
 * endpoint stitches together four artifacts that already exist on disk
 * (incoming picks, the Code 1 key-11 table, the Code 4 danger card, the Code 5
 * chemistry), so opening it costs no provider quota.
 *
 * The player table is deliberately rendered from the SAME `LivePrematchTeamAudit`
 * shape the Live Match page uses, so a team looks identical in both places.
 * The signed impact is shown with its confidence rather than as a bare
 * percentage, because "the number you can see" is now the number that decides
 * the verdict — a claim this page has to be able to substantiate or refute.
 */

import { useCallback, useMemo } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Handshake,
  Info,
  Radio,
  ShieldAlert,
  ShieldCheck,
  Shuffle,
  Users,
  XCircle,
} from "lucide-react";

import { liveApi, type LiveIncomingDetail } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/* ── verdict presentation ─────────────────────────────────────────── */

const VERDICT_STYLE: Record<
  string,
  { label: string; icon: typeof ShieldAlert; className: string }
> = {
  DANGER: {
    label: "DANGER",
    icon: ShieldAlert,
    className: "border-rose-500/60 bg-rose-500/15 text-rose-300",
  },
  BLESSING: {
    label: "BLESSING",
    icon: ShieldCheck,
    className: "border-emerald-500/60 bg-emerald-500/15 text-emerald-300",
  },
  ROTATION: {
    label: "ROTATION",
    icon: Shuffle,
    className: "border-amber-500/50 bg-amber-500/10 text-amber-300",
  },
  UNKNOWN: {
    label: "UNKNOWN",
    icon: Info,
    className: "border-border-bright bg-bg-elevated text-text-secondary",
  },
};

const REGIME_LABEL: Record<string, string> = {
  STRONG_FAVOURITE: "strong favourite",
  MID_FIELD: "even contest",
  BIG_DOG: "big dog",
};

const STRENGTH_RANK: Record<string, number> = {
  Unavailable: 0,
  "Very Weak": 1,
  Weak: 2,
  Balanced: 3,
  Strong: 4,
  "Very Strong": 5,
  Excellent: 6,
  Elite: 7,
};

function strengthClass(grade: string): string {
  const r = STRENGTH_RANK[grade] ?? 0;
  if (r >= 5) return "text-emerald-300 border-emerald-500/40 bg-emerald-500/10";
  if (r === 4) return "text-accent-green border-accent-green/40 bg-accent-green/10";
  if (r === 3) return "text-text-secondary border-border-bright bg-bg-elevated";
  if (r === 2) return "text-amber-300 border-amber-500/40 bg-amber-500/10";
  if (r === 1) return "text-rose-300 border-rose-500/40 bg-rose-500/10";
  return "text-text-dim border-border/60 bg-bg-elevated/50";
}

/** Confidence shown as a fraction plus a word, never as a bare number. */
function confidenceWord(c: number): string {
  if (c >= 0.75) return "strong";
  if (c >= 0.45) return "workable";
  if (c > 0) return "thin";
  return "none";
}

/* ── shared presentational pieces ─────────────────────────────────── */

function Section({
  title,
  icon: Icon,
  right,
  children,
}: {
  title: string;
  icon: typeof Info;
  right?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2.5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent-indigo/15 text-accent-indigo">
            <Icon className="h-3.5 w-3.5" />
          </div>
          <h2 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
            {title}
          </h2>
        </div>
        {right}
      </div>
      {children}
    </section>
  );
}

/**
 * Explicit "we do not have this" state.
 *
 * A missing piece has to say WHY it is missing. A silent blank reads as
 * "nothing to report" when it actually means "this half of the chain has not
 * landed yet", which is the confusion that made this page look broken.
 */
function Unavailable({ what, why }: { what: string; why: string }) {
  return (
    <div className="rounded-lg border border-dashed border-border-bright bg-bg-elevated/30 px-3.5 py-4">
      <p className="text-xs font-semibold text-text-secondary">{what}</p>
      <p className="mt-1 text-2xs leading-relaxed text-text-dim">{why}</p>
    </div>
  );
}

/** A value that is genuinely absent renders as words, never as a number. */
function NotMeasured({ hint }: { hint?: string }) {
  return (
    <span className="font-normal text-text-dim" title={hint}>
      not measured
    </span>
  );
}

const RISK_STYLE: Record<string, string> = {
  FULL_STRENGTH: "border-emerald-500/50 bg-emerald-500/10 text-emerald-300",
  CLEAR: "border-accent-green/40 bg-accent-green/10 text-accent-green",
  ELEVATED: "border-amber-500/50 bg-amber-500/10 text-amber-300",
  HEAVY: "border-rose-500/60 bg-rose-500/15 text-rose-300",
};

function Metric({
  label,
  value,
  hint,
  tone = "flat",
}: {
  label: string;
  /** null means the value was never measured — rendered as words, not 0.0. */
  value: string | null;
  hint?: string;
  tone?: "good" | "bad" | "warn" | "flat";
}) {
  return (
    <div className="rounded-lg border border-border/60 bg-bg-base/40 px-2.5 py-2">
      <p className="text-2xs uppercase tracking-wide text-text-dim">{label}</p>
      <p
        className={cn(
          "mt-0.5 truncate text-xs font-semibold",
          value === null && "font-normal",
          value !== null && tone === "good" && "text-emerald-300",
          value !== null && tone === "bad" && "text-rose-300",
          value !== null && tone === "warn" && "text-amber-300",
          value !== null && tone === "flat" && "text-text-primary"
        )}
        title={value ?? hint}
      >
        {value === null ? <NotMeasured hint={hint} /> : value}
      </p>
      {hint && (
        <p className="mt-0.5 text-2xs leading-snug text-text-dim" title={hint}>
          {hint}
        </p>
      )}
    </div>
  );
}

/* ── both teams, side by side, BEFORE any detail ──────────────────── */

/**
 * The head-to-head strip.
 *
 * Placed above both tables on purpose. The question "is this keeper down?"
 * and "how many are missing?" is a comparison BETWEEN the two sides, and
 * answering it required scrolling past one team's full eleven and then
 * reading the other. Both answers are now adjacent.
 */
function HeadToHead({
  teams,
  fixture,
}: {
  teams: LiveIncomingDetail["teams"];
  fixture: string;
}) {
  const sides: Array<"home" | "away"> = ["home", "away"];
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {sides.map((side) => {
        const t = teams[side];
        if (!t) {
          return (
            <div
              key={side}
              className="rounded-xl border border-dashed border-border-bright bg-bg-elevated/30 px-4 py-3"
            >
              <p className="text-2xs uppercase tracking-wide text-text-dim">
                {side}
              </p>
              <p className="mt-1 text-xs text-text-dim">Not available</p>
            </div>
          );
        }
        const gkOk = t.gk_ok;
        return (
          <div
            key={side}
            className="flex flex-col gap-2.5 rounded-xl border border-border/70 bg-bg-elevated/40 px-4 py-3"
          >
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="text-2xs uppercase tracking-wide text-text-dim">
                  {side}
                </p>
                <p className="text-sm font-semibold text-text-primary">
                  {t.raw?.team_name ?? "Unknown team"}
                </p>
              </div>
              <span
                className={cn(
                  "rounded-lg border px-2 py-0.5 text-2xs font-bold",
                  RISK_STYLE[t.risk] ?? RISK_STYLE.FULL_STRENGTH
                )}
              >
                {t.risk} RISK
              </span>
            </div>

            {/* The two answers that matter, immediately visible. */}
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={cn(
                  "rounded border px-2 py-0.5 text-2xs font-bold",
                  gkOk
                    ? "border-accent-green/50 bg-accent-green/10 text-accent-green"
                    : "border-rose-500/50 bg-rose-500/10 text-rose-300"
                )}
                title={t.gk_status || undefined}
              >
                GK {gkOk ? "OK" : "DOWN"}
              </span>
              <span
                className={cn(
                  "rounded border px-2 py-0.5 text-2xs font-bold",
                  (t.miss ?? 0) >= 4
                    ? "border-rose-500/50 bg-rose-500/10 text-rose-300"
                    : (t.miss ?? 0) >= 2
                    ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
                    : "border-border-bright bg-bg-elevated text-text-secondary"
                )}
              >
                {(t.miss ?? 0) > 0 ? `${t.miss} MISSING` : "FULL STRENGTH"}
              </span>
            </div>

            {t.gk_status && (
              <p className="text-2xs leading-relaxed text-text-secondary">
                {t.gk_status}
              </p>
            )}

            {t.missing_names.length > 0 && (
              <p className="text-2xs leading-relaxed text-text-dim">
                Absent: {t.missing_names.join(", ")}
              </p>
            )}

            {/* The Edge's own percentages, so the header matches the Edge. */}
            <div className="grid grid-cols-3 gap-2">
              <Metric
                label="miss"
                value={String(t.miss ?? 0)}
                hint="key players absent from the XI"
              />
              <Metric
                label="KMV"
                value={
                  typeof t.kmv === "number" ? `${t.kmv.toFixed(1)}%` : null
                }
                hint="Key Missing Vulnerability — the hole left behind"
              />
              <Metric
                label="RV"
                value={
                  typeof t.rv === "number" ? `${t.rv.toFixed(1)}%` : null
                }
                hint="Replacement Vulnerability — the depth penalty"
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ── one team's full detail ────────────────────────────────────────── */

function TeamDetail({
  side,
  team,
  signed,
  picks,
}: {
  side: "home" | "away";
  team?: LiveIncomingDetail["teams"][keyof LiveIncomingDetail["teams"]];
  signed?: LiveIncomingDetail["danger"][keyof LiveIncomingDetail["danger"]];
  picks: LiveIncomingDetail["picks"];
}) {
  const players = team?.players ?? [];
  const teamPicks = picks.filter((p) => p.target_loc === side);
  const hasData = players.length > 0;

  return (
    <div
      id={`side-${side}`}
      className="flex flex-col gap-3 rounded-xl border border-border/70 bg-bg-elevated/40 p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-2xs uppercase tracking-wide text-text-dim">{side}</p>
          <h3 className="text-base font-semibold text-text-primary">
            {team?.raw?.team_name ?? "Unknown team"}
          </h3>
        </div>
        {team && (
          <span
            className={cn(
              "rounded-lg border px-2.5 py-1 text-2xs font-bold",
              RISK_STYLE[team.risk] ?? RISK_STYLE.FULL_STRENGTH
            )}
          >
            {team.risk} RISK · {team.miss} MISSING
          </span>
        )}
      </div>

      {team?.gk_status && (
        <p className="rounded-lg border border-border/60 bg-bg-base/50 px-3 py-2 text-2xs leading-relaxed text-text-secondary">
          <span className="font-semibold text-text-primary">
            GK {team.gk_ok ? "OK" : "DOWN"}:
          </span>{" "}
          {team.gk_status}
        </p>
      )}

      {teamPicks.length > 0 && (
        <ul className="flex flex-col gap-1.5">
          {teamPicks.map((p, i) => (
            <li
              key={`${p.type}-${i}`}
              className="rounded-lg border border-accent-cyan/30 bg-accent-cyan/5 px-3 py-2"
            >
              <p className="text-2xs font-semibold text-accent-cyan">
                {p.type}
                {p.target_name ? ` · ${p.target_name}` : ""}
              </p>
              {p.reason && (
                <p className="mt-0.5 text-2xs leading-relaxed text-text-secondary">
                  {p.reason}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}

      {/* The table, from the same feed the Live Match page renders. */}
      {!hasData ? (
        <Unavailable
          what="No starting XI table for this side"
          why="Code 1 has no published row for this team on the current cycle — most often because the official XI has not been published yet, or the team was unavailable. Nothing is shown rather than filling the table with players who did not start."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-2xs">
            <thead>
              <tr className="border-b border-border/60 text-text-dim">
                <th className="py-1.5 pr-2 font-medium">player</th>
                <th className="py-1.5 pr-2 font-medium">pos</th>
                <th className="py-1.5 pr-2 text-right font-medium">apps</th>
                <th className="py-1.5 pr-2 text-right font-medium">mins</th>
                <th className="py-1.5 pr-2 text-right font-medium">rating</th>
                <th className="py-1.5 font-medium">status</th>
              </tr>
            </thead>
            <tbody>
              {players.map((pl) => {
                const missing = String(pl.status ?? "").startsWith("MISSING");
                return (
                  <tr
                    key={pl.name}
                    className={cn(
                      "border-b border-border/30",
                      missing ? "bg-rose-500/5" : "hover:bg-bg-elevated/50"
                    )}
                  >
                    <td className="py-1.5 pr-2 font-medium text-text-primary">
                      {pl.name}
                    </td>
                    <td className="py-1.5 pr-2 text-text-dim">{pl.pos}</td>
                    <td className="py-1.5 pr-2 text-right font-mono text-text-secondary">
                      {pl.apps}
                    </td>
                    <td className="py-1.5 pr-2 text-right font-mono text-text-secondary">
                      {pl.mins}
                    </td>
                    <td className="py-1.5 pr-2 text-right font-mono text-text-secondary">
                      {typeof pl.rating === "number"
                        ? pl.rating.toFixed(2)
                        : "—"}
                    </td>
                    <td
                      className={cn(
                        "py-1.5 font-medium",
                        missing ? "text-rose-300" : "text-emerald-300"
                      )}
                    >
                      {missing ? "■ MISSING" : "STARTING"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Code 4's signed read, explicitly SECONDARY. */}
      {signed?.signed_verdict && (
        <div className="rounded-lg border border-border/60 bg-bg-base/40 px-3 py-2">
          <p className="text-2xs font-semibold uppercase tracking-wide text-text-dim">
            Signed read (Code 4) — secondary
          </p>
          <p className="mt-1 text-2xs leading-relaxed text-text-secondary">
            {signed.signed_reason}
          </p>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <Metric
              label="net impact"
              value={
                typeof signed.net_impact === "number"
                  ? `${signed.net_impact > 0 ? "+" : ""}${signed.net_impact.toFixed(1)}`
                  : null
              }
              hint="positive = quality lost, negative = upgraded"
              tone={
                (signed.net_impact ?? 0) > 0
                  ? "bad"
                  : (signed.net_impact ?? 0) < 0
                  ? "good"
                  : "flat"
              }
            />
            <Metric
              label="confidence"
              value={
                typeof signed.impact_confidence === "number"
                  ? `${signed.impact_confidence.toFixed(2)} (${confidenceWord(
                      signed.impact_confidence
                    )})`
                  : null
              }
              hint="how much evidence stands behind the number"
              tone={
                (signed.impact_confidence ?? 0) >= 0.45 ? "good" : "warn"
              }
            />
          </div>
        </div>
      )}
    </div>
  );
}

/* ── page ─────────────────────────────────────────────────────────── */

export default function IncomingDetailPage() {
  const params = useParams<{ fixtureId: string }>();
  const fixtureId = params?.fixtureId ?? "";

  const fetcher = useCallback(
    () => liveApi.getIncomingDetail(fixtureId),
    [fixtureId]
  );
  const { data, loading, error, refetch } = useApi<LiveIncomingDetail>(
    fetcher,
    [fixtureId],
    { cacheKey: `incoming-detail:${fixtureId}` }
  );

  const row = data ?? null;
  const teams = row?.teams ?? {};
  const danger = row?.danger ?? {};
  const handshake = row?.handshake ?? null;
  const chemistryEntries = useMemo(
    () => Object.entries(row?.chemistry ?? {}),
    [row?.chemistry]
  );

  if (loading && !row) {
    return (
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 px-4 py-6">
        <Skeleton className="h-8 w-72 rounded-xl bg-bg-elevated" />
        <Skeleton className="h-32 rounded-xl bg-bg-elevated" />
        <Skeleton className="h-64 rounded-xl bg-bg-elevated" />
      </div>
    );
  }

  if (error && !row) {
    return (
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-4 py-10">
        <p className="text-sm font-semibold text-text-primary">
          Could not load this fixture
        </p>
        <p className="max-w-prose text-2xs leading-relaxed text-text-dim">
          {error}
        </p>
        <Link
          href="/live/incoming"
          className="inline-flex w-fit items-center gap-1.5 rounded-lg border border-border-bright px-3 py-1.5 text-2xs text-text-secondary hover:border-accent-indigo"
        >
          <ArrowLeft className="h-3 w-3" /> Back to Incoming
        </Link>
      </div>
    );
  }

  if (!row) return null;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-6">
      {/* ── header ── */}
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1.5">
          <Link
            href="/live/incoming"
            className="inline-flex w-fit items-center gap-1.5 text-2xs text-text-dim hover:text-accent-indigo"
          >
            <ArrowLeft className="h-3 w-3" /> Incoming feed
          </Link>
          <h1 className="text-lg font-semibold text-text-primary">
            {row.fixture}
          </h1>
          <p className="text-2xs text-text-dim">
            fixture {row.fixture_id}
            {row.live && (
              <>
                {" · "}
                <span className="font-mono text-text-secondary">
                  {row.live.score} {row.live.minute}&apos;
                </span>
                <span className="ml-1.5">
                  {row.live.state.replace(/^INPLAY_/, "").replace(/_/g, " ")}
                </span>
              </>
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={refetch}
          className="rounded-lg border border-border-bright px-2.5 py-1 text-2xs text-text-secondary hover:border-accent-indigo"
        >
          Refresh
        </button>
      </header>

      {row.partial && (
        <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-2xs text-amber-200">
          Partial chain:{" "}
          {Object.entries(row.availability)
            .filter(([, ok]) => !ok)
            .map(([k]) => k)
            .join(", ")}{" "}
          not available for this fixture yet. The panels below say so explicitly
          rather than showing an empty card.
        </p>
      )}

      {/* ── BOTH TEAMS FIRST: keeper + missing count, before any table ── */}
      <Section
        title="Both teams at a glance"
        icon={Info}
        right={
          <span className="text-2xs text-text-dim">
            same figures as the Live Match page
          </span>
        }
      >
        <HeadToHead teams={teams} fixture={row.fixture} />
      </Section>

      {/* ── the picks ── */}
      <Section title="What the incoming feed predicted" icon={Radio}>
        {row.picks.length === 0 ? (
          <Unavailable
            what="No picks recorded"
            why="The forensic engine has not written a prediction for this fixture on the current cycle. Rules fire on an official XI, so a fixture whose lineups have not been published yet legitimately has nothing to say."
          />
        ) : (
          <ul className="grid gap-2 sm:grid-cols-2">
            {row.picks.map((p, i) => (
              <li
                key={`${p.type}-${i}`}
                className="rounded-lg border border-accent-cyan/30 bg-accent-cyan/5 px-3 py-2.5"
              >
                <p className="text-2xs font-bold text-accent-cyan">
                  {p.type}
                  {p.target_name ? ` · ${p.target_name}` : ""}
                </p>
                {p.reason && (
                  <p className="mt-1 text-2xs leading-relaxed text-text-secondary">
                    {p.reason}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>

      {/* ── the full tables, one per team ── */}
      <Section title="The starting XI, player by player" icon={Users}>
        {!row.table_available ? (
          <Unavailable
            what="No team evidence for this fixture"
            why="Code 1 holds no published row for this fixture yet, so there is no starting eleven to show."
          />
        ) : (
          <div className="flex flex-col gap-3">
            <TeamDetail
              side="home"
              team={teams.home}
              signed={danger.home}
              picks={row.picks}
            />
            <TeamDetail
              side="away"
              team={teams.away}
              signed={danger.away}
              picks={row.picks}
            />
          </div>
        )}
      </Section>

      {/* ── the handshake ── */}
      <Section title="Do the two engines agree?" icon={Handshake}>
        {!handshake ? (
          <Unavailable
            what="No reconciliation available"
            why="Code 5 could not join this fixture's incoming picks to a danger card, so there is no agreement to report. That is a coverage gap, not a verdict."
          />
        ) : (
          <div className="flex flex-col gap-2.5">
            <div
              className={cn(
                "flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2",
                handshake.status === "CONFLICT" &&
                  "border-amber-500/50 bg-amber-500/10",
                handshake.status === "CORROBORATED" &&
                  "border-emerald-500/50 bg-emerald-500/10",
                handshake.status === "NO_OVERLAP" &&
                  "border-border-bright bg-bg-elevated"
              )}
            >
              {handshake.status === "CONFLICT" ? (
                <AlertTriangle className="h-3.5 w-3.5 text-amber-300" />
              ) : handshake.status === "CORROBORATED" ? (
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-300" />
              ) : (
                <Info className="h-3.5 w-3.5 text-text-dim" />
              )}
              <span className="text-2xs font-semibold text-text-primary">
                {handshake.status}
              </span>
              <span className="text-2xs text-text-secondary">
                {handshake.summary}
              </span>
            </div>

            {handshake.detail.length > 0 && (
              <ul className="flex flex-col gap-1">
                {handshake.detail.map((d, i) => (
                  <li
                    key={`${d.type}-${d.target_name}-${i}`}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/50 bg-bg-base/40 px-2.5 py-1.5"
                  >
                    <span className="text-2xs text-text-secondary">
                      <span className="font-semibold text-text-primary">
                        {d.type}
                      </span>
                      {d.target_name ? ` · ${d.target_name}` : ""}
                      <span className="ml-1.5 text-text-dim">
                        → {d.market} = {d.market_grade}
                      </span>
                    </span>
                    <span
                      className={cn(
                        "flex items-center gap-1 text-2xs font-semibold",
                        d.verdict === "AGREES" && "text-emerald-300",
                        d.verdict === "CONFLICTS" && "text-amber-300",
                        d.verdict === "NEUTRAL" && "text-text-dim"
                      )}
                    >
                      {d.verdict === "AGREES" ? (
                        <CheckCircle2 className="h-3 w-3" />
                      ) : d.verdict === "CONFLICTS" ? (
                        <XCircle className="h-3 w-3" />
                      ) : null}
                      {d.verdict}
                    </span>
                  </li>
                ))}
              </ul>
            )}

            {handshake.coherence_notes.length > 0 && (
              <div className="rounded-lg border border-border/60 bg-bg-elevated/40 px-3 py-2">
                <p className="text-2xs font-semibold uppercase tracking-wide text-text-dim">
                  consistency repairs applied
                </p>
                <ul className="mt-1 flex flex-col gap-0.5">
                  {handshake.coherence_notes.map((n, i) => (
                    <li
                      key={i}
                      className="text-2xs leading-relaxed text-text-dim"
                    >
                      · {n}
                    </li>
                  ))}
                </ul>
                <p className="mt-1.5 text-2xs leading-relaxed text-text-dim">
                  Recorded rather than hidden: these are markets where a naive
                  reading would have contradicted itself.
                </p>
              </div>
            )}
          </div>
        )}
      </Section>

      {/* ── chemistry ── */}
      <Section title="Market chemistry (Code 5)" icon={Shuffle}>
        {chemistryEntries.length === 0 ? (
          <Unavailable
            what="No market grades"
            why="Code 5 has not graded this fixture, or the danger evidence for one side was missing — in which case every market is deliberately marked Unavailable rather than guessed."
          />
        ) : (
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {chemistryEntries.map(([market, grade]) => (
              <div
                key={market}
                className="flex items-center justify-between gap-2 rounded-lg border border-border/60 bg-bg-elevated/40 px-3 py-2"
              >
                <span className="text-2xs text-text-secondary">{market}</span>
                <span
                  className={cn(
                    "rounded border px-2 py-0.5 text-2xs font-semibold",
                    strengthClass(grade)
                  )}
                >
                  {grade}
                </span>
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}
