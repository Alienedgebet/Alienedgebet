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
  XCircle,
} from "lucide-react";

import {
  liveApi,
  type LiveIncomingDetail,
  type LivePrematchTeamAudit,
} from "@/lib/api";
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
 * The page is a drill-down, so a missing piece has to say WHY it is missing.
 * A silent blank would read as "nothing to report" when it actually means "the
 * evidence for this half of the chain has not landed yet", which is the exact
 * confusion that made the old feed look like it had opinions it did not have.
 */
function Unavailable({ what, why }: { what: string; why: string }) {
  return (
    <div className="rounded-lg border border-dashed border-border-bright bg-bg-elevated/30 px-3.5 py-4">
      <p className="text-xs font-semibold text-text-secondary">{what}</p>
      <p className="mt-1 text-2xs leading-relaxed text-text-dim">{why}</p>
    </div>
  );
}

function Metric({
  label,
  value,
  hint,
  tone = "flat",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "good" | "bad" | "warn" | "flat";
}) {
  return (
    <div className="rounded-lg border border-border/60 bg-bg-base/40 px-2.5 py-2">
      <p className="text-2xs uppercase tracking-wide text-text-dim">{label}</p>
      <p
        className={cn(
          "mt-0.5 truncate text-xs font-semibold",
          tone === "good" && "text-emerald-300",
          tone === "bad" && "text-rose-300",
          tone === "warn" && "text-amber-300",
          tone === "flat" && "text-text-primary"
        )}
        title={value}
      >
        {value}
      </p>
      {hint && (
        <p className="mt-0.5 text-2xs leading-snug text-text-dim" title={hint}>
          {hint}
        </p>
      )}
    </div>
  );
}

/* ── the team block (table + signed impact) ───────────────────────── */

function TeamBlock({
  side,
  team,
  danger,
  picks,
}: {
  side: "home" | "away";
  team?: LivePrematchTeamAudit;
  danger?: LiveIncomingDetail["danger"][keyof LiveIncomingDetail["danger"]];
  picks: LiveIncomingDetail["picks"];
}) {
  const verdict = danger?.verdict ?? "UNKNOWN";
  const style = VERDICT_STYLE[verdict] ?? VERDICT_STYLE.UNKNOWN;
  const Icon = style.icon;
  const players = team?.players ?? [];
  const teamPicks = picks.filter((p) => p.target_loc === side);

  return (
    <div
      id={`side-${side}`}
      className="flex flex-col gap-3 rounded-xl border border-border/70 bg-bg-elevated/40 p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-2xs uppercase tracking-wide text-text-dim">{side}</p>
          <h3 className="text-base font-semibold text-text-primary">
            {team?.team_name ?? danger?.team_name ?? "Unknown team"}
          </h3>
          {danger?.formation && danger.formation !== "N/A" && (
            <p className="mt-0.5 font-mono text-2xs text-text-dim">
              formation {danger.formation}
              {danger.style?.label ? ` · ${danger.style.label} style` : ""}
            </p>
          )}
        </div>
        <span
          className={cn(
            "flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-2xs font-bold",
            style.className
          )}
        >
          <Icon className="h-3.5 w-3.5" />
          {style.label}
        </span>
      </div>

      {/* WHY — the sentence that justifies the badge. */}
      {danger?.verdict_reason && (
        <p className="rounded-lg border border-border/60 bg-bg-base/50 px-3 py-2 text-2xs leading-relaxed text-text-secondary">
          {danger.verdict_reason}
        </p>
      )}

      {/* The signed numbers, with the confidence that produced them. */}
      {typeof danger?.net_impact === "number" && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Metric
            label="net impact"
            value={`${danger.net_impact > 0 ? "+" : ""}${danger.net_impact.toFixed(1)}`}
            hint={
              typeof danger.quality_lost === "number" &&
              typeof danger.replacement_credit === "number"
                ? `lost ${danger.quality_lost.toFixed(1)} of quality, replaced with ${danger.replacement_credit.toFixed(1)}`
                : undefined
            }
            tone={
              danger.net_impact > 0
                ? "bad"
                : danger.net_impact < 0
                ? "good"
                : "flat"
            }
          />
          <Metric
            label="confidence"
            value={
              typeof danger.impact_confidence === "number"
                ? danger.impact_confidence.toFixed(2)
                : "—"
            }
            hint={
              typeof danger.impact_confidence === "number"
                ? `${confidenceWord(danger.impact_confidence)} evidence`
                : undefined
            }
            tone={(danger.impact_confidence ?? 0) >= 0.45 ? "good" : "warn"}
          />
          <Metric
            label="market read"
            value={
              danger.regime
                ? (REGIME_LABEL[danger.regime] ?? danger.regime)
                : "—"
            }
            hint="how the market prices this side"
          />
          <Metric
            label="goalkeeper"
            value={
              danger.gk_verdict ??
              (danger.gk_leak != null ? "unrated" : "—")
            }
            hint={danger.gk_note}
            tone={
              danger.gk_verdict === "DANGER"
                ? "bad"
                : danger.gk_verdict === "BLESSING"
                ? "good"
                : "flat"
            }
          />
        </div>
      )}

      {/* Picks that name this side. */}
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

      {/* The key-11 table — same shape as the Live Match page. */}
      {players.length === 0 ? (
        <Unavailable
          what="No starting XI table for this side"
          why={
            danger?.data_available === false
              ? "The engines have no historical squad data for this team yet, so there is no key eleven to compare the lineup against. Nothing is being hidden — there is genuinely nothing measured."
              : "Code 1 has not published an official XI for this side, or the team was unavailable on the last cycle. The engine refuses to substitute the bench for a starting eleven, so the table stays empty rather than being filled with players who did not start."
          }
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
                      {pl.status}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* The absent, with the quality evidence that now drives the verdict. */}
      {danger?.missing_details && danger.missing_details.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <p className="text-2xs font-semibold uppercase tracking-wide text-text-dim">
            Absent key players — and what they were worth
          </p>
          <ul className="flex flex-col gap-1">
            {danger.missing_details.map((m) => (
              <li
                key={m.name}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/50 bg-bg-base/40 px-2.5 py-1.5"
              >
                <span className="text-2xs font-medium text-text-primary">
                  {m.name}
                  <span className="ml-1.5 text-text-dim">{m.pos}</span>
                </span>
                <span className="font-mono text-2xs text-text-secondary">
                  {typeof m.rating === "number" ? (
                    <>
                      rating {m.rating.toFixed(2)} · {m.apps ?? 0} apps ·{" "}
                      {m.mins ?? 0} min
                      <span
                        className={cn(
                          "ml-1.5 font-semibold",
                          m.rating >= 6.8 ? "text-rose-300" : "text-emerald-300"
                        )}
                      >
                        {m.rating >= 6.8 ? "▲ above typical" : "▼ below typical"}
                      </span>
                    </>
                  ) : (
                    <span className="text-text-dim">no rating on record</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
          <p className="text-2xs leading-relaxed text-text-dim">
            A player rated above 6.80 leaving is damage; one rated below it is
            either neutral or an upgrade. That sign — not the headcount — is what
            sets the badge.
          </p>
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
        <Skeleton className="h-40 rounded-xl bg-bg-elevated" />
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

      {/* ── both teams ── */}
      <Section
        title="The evidence, per team"
        icon={Info}
        right={
          <span className="text-2xs text-text-dim">
            table + keeper + signed impact
          </span>
        }
      >
        {!row.table_available && !row.danger_available ? (
          <Unavailable
            what="No team evidence for this fixture"
            why="Neither the Code 1 starting-XI table nor the Code 4 danger card holds a row for this fixture. The engines agree there is nothing measured yet."
          />
        ) : (
          <div className="flex flex-col gap-3">
            <TeamBlock
              side="home"
              team={teams.home}
              danger={danger.home}
              picks={row.picks}
            />
            <TeamBlock
              side="away"
              team={teams.away}
              danger={danger.away}
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
                  These are recorded rather than hidden: they are markets where a
                  naive reading would have contradicted itself.
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
