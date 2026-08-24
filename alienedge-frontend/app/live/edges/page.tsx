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
              "rounded border px-1.5 py-0.5 transition-colors",
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

function PrematchAuditCard({
  row,
  onOpenDetails,
}: {
  row: LivePrematchAudit;
  onOpenDetails: (row: LivePrematchAudit) => void;
}) {
  return (
    <article
      onClick={() => onOpenDetails(row)}
      className="glass overflow-hidden rounded-xl shadow-panel cursor-pointer transition-all hover:border-accent-indigo/50 hover:shadow-glow group relative"
    >
      <div className="absolute top-3 right-3 flex items-center gap-1 font-mono text-2xs text-accent-cyan opacity-80 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all">
        <span>View Code 2 &amp; 3 Details</span>
        <ChevronRight className="h-4 w-4" />
      </div>

      <div className="border-b border-border/70 px-4 py-3 pr-36">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="mb-1 text-2xs font-bold uppercase tracking-widest text-accent-indigo">
              Stage 1 · Strategic Audit (Tap to open Code 2 &amp; 3)
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

      <div className="grid grid-cols-1 gap-3 p-3 lg:grid-cols-2" onClick={(e) => e.stopPropagation()}>
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

      {/* ── Code 1 ONLY on Main Page ────────────────────────────────────── */}
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
              Console columns persisted · {stats.fixtures} fixtures · Tap any match card to open Code 2 &amp; 3 details
            </p>
          </div>
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

      {/* ── Match Detail Modal / Sub-View for Code 2 and Code 3 ──────────── */}
      {selectedAudit && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-primary/80 backdrop-blur-md p-4 overflow-y-auto">
          <div className="relative w-full max-w-4xl glass rounded-2xl border border-accent-indigo/30 bg-bg-secondary p-6 shadow-2xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-border pb-4 mb-5">
              <div>
                <p className="text-xs font-bold uppercase tracking-widest text-accent-indigo">
                  Match Forensic &amp; Validation Details
                </p>
                <h2 className="text-lg font-bold text-text-primary">
                  {selectedAudit.fixture} (ID: {selectedAudit.fixture_id})
                </h2>
              </div>
              <button
                type="button"
                onClick={() => setSelectedAudit(null)}
                className="flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-bg-elevated text-text-secondary hover:text-text-primary"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-6">
              {/* Code 2 Section */}
              <section className="flex flex-col gap-3">
                <div className="flex items-center gap-3">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-green/15 text-accent-green">
                    <ShieldCheck className="h-4 w-4" />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-text-primary">
                      Code 2 — Live Validation of Code 1 Predictions
                    </h3>
                    <p className="text-2xs text-text-dim">
                      Cycle #{board.cycle || "—"} · Live tracking board for this fixture
                    </p>
                  </div>
                </div>

                {matchedValidationMatches.length === 0 ? (
                  <p className="text-xs text-text-dim italic p-3 bg-bg-elevated/40 rounded-lg">
                    No active live validation tracking entries for this fixture yet.
                  </p>
                ) : (
                  <div className="grid gap-3">
                    {matchedValidationMatches.map((m) => (
                      <ValidationMatchCard key={`${m.id}-${m.minute}`} entry={m} />
                    ))}
                  </div>
                )}
              </section>

              {/* Code 3 Section */}
              <section className="flex flex-col gap-3">
                <div className="flex items-center gap-3">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-cyan/15 text-accent-cyan">
                    <Radio className="h-4 w-4" />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-text-primary">
                      Code 3 — Validated Alerts &amp; Supreme Confirmations
                    </h3>
                    <p className="text-2xs text-text-dim">
                      In-play alerts confirmed at 45&apos; / 30&apos; handshake
                    </p>
                  </div>
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

            <div className="mt-6 flex justify-end">
              <button
                type="button"
                onClick={() => setSelectedAudit(null)}
                className="rounded-lg bg-accent-indigo px-4 py-2 text-xs font-semibold text-white transition-colors hover:bg-accent-indigo/80"
              >
                Close Match Details
              </button>
            </div>
          </div>
        </div>
      )}
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
