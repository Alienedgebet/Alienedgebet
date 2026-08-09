"use client";

import { useMemo } from "react";
import { Radio, Shield, ShieldCheck } from "lucide-react";
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
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * Live Monitor — Stage 1 strategic audit first (console columns),
 * then Stage 2 validation board of those same stage-1 picks.
 */

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

function TeamAuditPanel({ team }: { team: LivePrematchTeamAudit }) {
  return (
    <div className="rounded-lg border border-border/70 bg-bg-elevated/30">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 px-3 py-2">
        <div>
          <p className="text-2xs uppercase tracking-wide text-text-dim">{team.loc}</p>
          <p className="text-sm font-semibold text-text-primary">{team.team_name}</p>
        </div>
        <div className="flex flex-wrap gap-1.5 font-mono text-2xs">
          <span className="rounded border border-border-bright px-1.5 py-0.5 text-text-secondary">
            miss {team.miss}
          </span>
          <span className="rounded border border-accent-amber/30 bg-accent-amber/10 px-1.5 py-0.5 text-accent-amber">
            KMV {team.kmv.toFixed(1)}%
          </span>
          <span className="rounded border border-accent-red/30 bg-accent-red/10 px-1.5 py-0.5 text-accent-red">
            RV {team.rv.toFixed(1)}%
          </span>
          <span
            className={cn(
              "rounded border px-1.5 py-0.5",
              team.gk_out
                ? "border-accent-red/40 bg-accent-red/10 text-accent-red"
                : "border-accent-green/30 bg-accent-green/10 text-accent-green"
            )}
          >
            GK {team.gk_out ? "LIABILITY" : "OK"}
          </span>
        </div>
      </div>
      <p className="border-b border-border/50 px-3 py-1.5 text-2xs text-text-secondary">
        GK status: {team.gk_status} · Def {team.def_miss} · Mid {team.mid_miss} · Att{" "}
        {team.att_miss}
        {(team.l_wing_miss || team.r_wing_miss) &&
          ` · Wings L${team.l_wing_miss ? "✗" : "✓"}/R${team.r_wing_miss ? "✗" : "✓"}`}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-left text-2xs">
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
                    "px-3 py-1.5",
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

function PrematchAuditCard({ row }: { row: LivePrematchAudit }) {
  return (
    <article className="glass overflow-hidden rounded-xl shadow-panel">
      <div className="border-b border-border/70 px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="mb-1 text-2xs font-bold uppercase tracking-widest text-accent-indigo">
              Stage 1 · Strategic Audit
            </p>
            <h3 className="text-sm font-semibold text-text-primary">
              MATCH: {row.fixture}
            </h3>
            <p className="mt-0.5 font-mono text-2xs text-text-dim">
              ID {row.fixture_id} · KICKOFF: {row.kickoff_utc} UTC ({row.status_text})
            </p>
          </div>
          <span className="rounded border border-accent-amber/30 bg-accent-amber/10 px-1.5 py-0.5 font-mono text-2xs text-accent-amber">
            combined miss {row.combined_miss}
          </span>
        </div>
        <p className="mt-2 font-mono text-2xs text-text-secondary">
          ODDS SCAN &gt; Home: {row.odds_home_win ?? "—"} | Away: {row.odds_away_win ?? "—"} | O2.5:{" "}
          {row.odds_o25 ?? "—"}
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3 p-3 lg:grid-cols-2">
        <TeamAuditPanel team={row.home} />
        <TeamAuditPanel team={row.away} />
      </div>

      <div className="space-y-3 border-t border-border/70 px-4 py-3">
        <div>
          <p className="mb-2 text-2xs font-semibold uppercase tracking-wide text-text-dim">
            [PRE-MATCH STRATEGIC PREDICTIONS]
          </p>
          <ul className="space-y-1">
            {row.picks.map((p, i) => (
              <li key={i} className="font-mono text-2xs text-accent-cyan">
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

function ValidationMatchCard({ entry }: { entry: LiveValidationMatch }) {
  return (
    <article className="rounded-xl border border-border/70 bg-bg-elevated/25 shadow-panel">
      <div className="border-b border-border/60 px-4 py-2.5">
        <p className="text-sm font-semibold text-text-primary">
          🏟️ {entry.name}
        </p>
        <p className="mt-0.5 font-mono text-2xs text-text-dim">
          Min {entry.minute}&apos; · Score {entry.score} · ID {entry.id}
        </p>
      </div>
      <div className="space-y-1 px-4 py-3 font-mono text-2xs">
        {entry.lines.length === 0 ? (
          <p className="text-text-dim">No picks active for this match.</p>
        ) : (
          entry.lines.map((line, i) => (
            <p
              key={i}
              className={cn(
                "whitespace-pre-wrap text-text-secondary",
                line.includes("SUPREME") && "text-accent-amber",
                line.includes("SETTLED") && "text-accent-green",
                line.includes("HANDSHAKE") && "text-accent-cyan",
                line.includes("FINAL STRIKE") && "text-accent-indigo"
              )}
            >
              {line.trimStart()}
            </p>
          ))
        )}
      </div>
    </article>
  );
}

export default function LivePage() {
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

  const anyMock = prematch.isMock || validation.isMock;

  return (
    <div className="relative flex flex-col gap-5 p-6">
      <div className="pointer-events-none absolute inset-0 -z-10 bg-hero-glow opacity-80" />

      <div className="glass flex flex-wrap items-center gap-x-7 gap-y-3 rounded-xl px-5 py-3.5 shadow-panel">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-red/20 shadow-glow-red">
            <Radio className="h-4 w-4 text-accent-red" />
          </div>
          <div>
            <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-text-primary">
              Live Monitor
              <span className="inline-flex items-center gap-1 rounded border border-accent-red/30 bg-accent-red/10 px-1.5 py-0.5 text-2xs font-bold text-accent-red">
                <span className="h-1.5 w-1.5 animate-live-pulse rounded-full bg-accent-red" />
                LIVE
              </span>
              {anyMock && (
                <Badge
                  variant="outline"
                  className="h-4 border-accent-amber/30 px-1 text-[0.6rem] text-accent-amber"
                >
                  Demo
                </Badge>
              )}
            </p>
            <p className="text-2xs text-text-dim">
              Code 1 audit → Code 2 validates those same predictions in-play
            </p>
          </div>
        </div>
        <div className="ml-auto flex flex-wrap gap-x-6 font-mono text-sm">
          <FeedStat label="Audits" value={String(stats.fixtures)} />
          <FeedStat label="GK liabilities" value={String(stats.gkLiabilities)} accent="text-accent-red" />
          <FeedStat label="Tracked" value={String(stats.tracked)} accent="text-accent-cyan" />
          <FeedStat label="Supreme" value={String(stats.validated)} accent="text-accent-green" />
        </div>
      </div>

      <section className="relative overflow-hidden rounded-2xl border border-accent-indigo/20 bg-nebula shadow-elevated">
        <div className="relative z-10 px-6 py-7 md:px-8">
          <p className="mb-2 inline-flex items-center gap-1.5 rounded-full border border-accent-indigo/40 bg-accent-indigo/10 px-2.5 py-1 text-2xs font-bold uppercase tracking-[0.14em] text-accent-indigo">
            Master Engine A · Strategic Audit
          </p>
          <h1 className="text-3xl font-extrabold tracking-tight text-text-primary sm:text-4xl">
            Live Monitor
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-secondary">
            Code 1 prints the full key-11 board (Player · Pos · Apps · Mins · Rating · Status),
            KMV / RV holes, GK liability, odds scan, strategic picks and killer rules. Code 2 then
            tracks those same picks live (monitoring → 30&apos; handshake → 45&apos; supreme).
          </p>
        </div>
      </section>

      {/* ── Stage 1 first ─────────────────────────────────────────────────── */}
      <section className="flex flex-col gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent-indigo/15 text-accent-indigo">
            <Shield className="h-4 w-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-text-primary">
              Code 1 — Prematch Strategic Audit
            </h2>
            <p className="text-2xs text-text-dim">
              Console columns persisted · {stats.fixtures} fixtures · picks also written to
              live_predictions.json for code 2
            </p>
          </div>
        </div>
        {prematch.loading && auditRows.length === 0 ? (
          <div className="grid gap-3">
            <Skeleton className="h-64 rounded-xl bg-bg-elevated" />
            <Skeleton className="h-64 rounded-xl bg-bg-elevated" />
          </div>
        ) : (
          auditRows.map((row) => <PrematchAuditCard key={row.fixture_id} row={row} />)
        )}
      </section>

      {/* ── Stage 2 — validation board then fired alerts ──────────────────── */}
      <section className="flex flex-col gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent-green/15 text-accent-green">
            <ShieldCheck className="h-4 w-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-text-primary">
              Code 2 — Live Validation of Code 1 Predictions
            </h2>
            <p className="text-2xs text-text-dim">
              VALIDATION BOARD · Cycle #{board.cycle || "—"} · Live {board.total_live} · Tracked{" "}
              {board.total_tracked}
            </p>
          </div>
        </div>

        {validation.loading && board.matches.length === 0 ? (
          <Skeleton className="h-40 rounded-xl bg-bg-elevated" />
        ) : (
          <div className="grid gap-3">
            {board.matches.map((m) => (
              <ValidationMatchCard key={`${m.id}-${m.minute}`} entry={m} />
            ))}
          </div>
        )}

        <ChainBranch
          title="VALIDATED_ALERTS — 45' supreme confirmations"
          description="In-play alerts confirmed at 45' — forensic note, stats note, minute triggered"
          data={validationRows}
          loading={validation.loading}
          error={validation.error}
          columns={validationAlertColumns}
          rowKey={(r, i) =>
            `${r.fixture_id}-${r.prediction_type}-${r.minute_triggered}-${i}`
          }
          emptyMessage="No supreme alerts yet — code 2 validates code 1 picks once matches go live."
          isRefetching={validation.isRefetching}
          defaultOpen
        />
      </section>
    </div>
  );
}

function FeedStat({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: string;
}) {
  return (
    <div className="border-l border-border/60 pl-4 first:border-l-0 first:pl-0">
      <p className="text-2xs uppercase tracking-wide text-text-dim">{label}</p>
      <p className={cn("font-bold tabular-nums", accent ?? "text-text-primary")}>{value}</p>
    </div>
  );
}
