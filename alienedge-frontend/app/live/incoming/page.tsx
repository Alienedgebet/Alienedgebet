"use client";

import { useMemo } from "react";
import { AlertTriangle, Handshake, Radio } from "lucide-react";
import {
  getChemistryColor,
  liveApi,
  type LiveAggregatorReport,
  type LiveDangerReport,
  type LiveIncomingPick,
} from "@/lib/api";
import { useApi } from "@/lib/use-api";
import {
  MOCK_LIVE_AGG,
  MOCK_LIVE_DANGER,
  MOCK_LIVE_INCOMING,
} from "@/lib/mock-chains";
import {
  normalizeAggregator,
  normalizeDanger,
  normalizeIncoming,
} from "@/app/live/normalize";
import {
  ChainBranch,
  type PredictionColumn,
} from "@/components/predictions";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * Incoming Live Matches — codes 3→4→5:
 * forensic pick stream → danger audit → master handshake chemistry.
 */

function liveRows<T>(data: T[] | null, loading: boolean, fallback: T[]): T[] {
  if (loading && (!data || data.length === 0)) return fallback;
  if (data && data.length > 0) return data;
  return fallback;
}

function pickLabel(p: LiveIncomingPick["picks"][number]): string {
  if (p.target_name) return `${p.type} · ${p.target_name}`;
  if (p.target_loc) return `${p.type} · ${p.target_loc}`;
  return p.type;
}

const incomingColumns: PredictionColumn<LiveIncomingPick>[] = [
  {
    key: "fixture",
    header: "fixture",
    render: (r) => <span className="font-medium text-text-primary">{r.fixture}</span>,
  },
  {
    key: "fixture_id",
    header: "fixture_id",
    render: (r) => <span className="font-mono text-2xs">{r.fixture_id}</span>,
  },
  {
    key: "picks",
    header: "picks",
    align: "right",
    render: (r) => <span className="font-mono">{r.picks.length}</span>,
  },
  {
    key: "types",
    header: "types",
    className: "max-w-[280px]",
    render: (r) => (
      <span className="line-clamp-2 text-2xs text-text-secondary">
        {r.picks.map(pickLabel).join(" · ") || "—"}
      </span>
    ),
  },
  {
    key: "reason",
    header: "lead_reason",
    className: "max-w-[280px]",
    render: (r) => (
      <span className="line-clamp-2 text-2xs text-text-dim">
        {r.picks[0]?.reason ?? "—"}
      </span>
    ),
  },
];

const dangerColumns: PredictionColumn<LiveDangerReport>[] = [
  {
    key: "fixture",
    header: "fixture",
    render: (r) => <span className="font-medium text-text-primary">{r.fixture}</span>,
  },
  {
    key: "align",
    header: "style_align",
    render: (r) => (
      <span className="font-mono text-2xs text-text-secondary">{r.style_alignment}</span>
    ),
  },
  {
    key: "home",
    header: "home",
    render: (r) => <DangerSideCell side={r.home_team} />,
  },
  {
    key: "away",
    header: "away",
    render: (r) => <DangerSideCell side={r.away_team} />,
  },
  {
    key: "gg",
    header: "gg_chem",
    render: (r) => (
      <span className={cn("font-mono text-2xs", getChemistryColor(r.match_chemistry_list.Gg))}>
        {r.match_chemistry_list.Gg}
      </span>
    ),
  },
];

function DangerSideCell({
  side,
}: {
  side: LiveDangerReport["home_team"];
}) {
  return (
    <span className="flex flex-col gap-0.5">
      <span
        className={cn(
          "font-mono text-2xs font-semibold",
          side.breach ? "text-accent-red" : "text-accent-green"
        )}
      >
        {side.danger_level}
      </span>
      <span className="font-mono text-2xs text-text-dim">
        {side.vulnerability_pct}% · GK {side.gk_leak.toFixed(2)}
      </span>
    </span>
  );
}

function AggregatorCard({ row }: { row: LiveAggregatorReport }) {
  const chem = Object.entries(row.match_chemistry_list);
  return (
    <article className="rounded-xl border border-border/70 bg-bg-elevated/25 shadow-panel">
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-border/60 px-4 py-3">
        <div>
          <p className="font-mono text-2xs text-text-dim">ID {row.fixture_id}</p>
          <h3 className="text-sm font-semibold text-text-primary">{row.fixture}</h3>
        </div>
        <div className="flex flex-wrap gap-1.5 font-mono text-2xs">
          <SyncChip label="H" report={row.danger_report.home} />
          <SyncChip label="A" report={row.danger_report.away} />
        </div>
      </div>

      <div className="border-b border-border/50 px-4 py-2.5">
        <p className="mb-1.5 text-2xs uppercase tracking-wide text-text-dim">
          Incoming ({row.incoming_probabilities.length})
        </p>
        <div className="flex flex-wrap gap-1.5">
          {row.incoming_probabilities.length === 0 ? (
            <span className="font-mono text-2xs text-text-dim">No picks</span>
          ) : (
            row.incoming_probabilities.map((p, i) => {
              const type = String((p as { type?: string }).type ?? "—");
              const target = String(
                (p as { target_name?: string }).target_name ??
                  (p as { target_loc?: string }).target_loc ??
                  ""
              );
              return (
                <span
                  key={`${type}-${i}`}
                  className="rounded border border-border/70 bg-bg-card/40 px-1.5 py-0.5 font-mono text-2xs text-text-secondary"
                >
                  {type}
                  {target ? ` · ${target}` : ""}
                </span>
              );
            })
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 px-4 py-3 sm:grid-cols-4">
        {chem.map(([market, status]) => (
          <div key={market} className="rounded border border-border/50 px-2 py-1.5">
            <p className="text-2xs text-text-dim">{market}</p>
            <p className={cn("font-mono text-xs font-semibold", getChemistryColor(String(status)))}>
              {String(status)}
            </p>
          </div>
        ))}
      </div>
    </article>
  );
}

function SyncChip({
  label,
  report,
}: {
  label: string;
  report: LiveAggregatorReport["danger_report"]["home"];
}) {
  return (
    <span
      className={cn(
        "rounded border px-1.5 py-0.5",
        report.breach
          ? "border-accent-red/40 bg-accent-red/10 text-accent-red"
          : "border-accent-green/30 bg-accent-green/10 text-accent-green"
      )}
    >
      {label}: {report.sync}
      {report.breach ? " · BREACH" : ""}
    </span>
  );
}

export default function LiveIncomingPage() {
  const incoming = useApi(
    () => liveApi.getIncoming().then(normalizeIncoming),
    [],
    { fallback: MOCK_LIVE_INCOMING, cacheKey: "live-incoming-incoming" }
  );
  const danger = useApi(
    () => liveApi.getDanger().then(normalizeDanger),
    [],
    { fallback: MOCK_LIVE_DANGER, cacheKey: "live-incoming-danger" }
  );
  const aggregator = useApi(
    () => liveApi.getAggregator().then(normalizeAggregator),
    [],
    { fallback: MOCK_LIVE_AGG, cacheKey: "live-incoming-aggregator" }
  );

  const incomingRows = liveRows(incoming.data, incoming.loading, MOCK_LIVE_INCOMING);
  const dangerRows = liveRows(danger.data, danger.loading, MOCK_LIVE_DANGER);
  const aggRows = liveRows(aggregator.data, aggregator.loading, MOCK_LIVE_AGG);

  const stats = useMemo(() => {
    const breaches = dangerRows.filter(
      (r) => r.home_team.breach || r.away_team.breach
    ).length;
    const pickCount = incomingRows.reduce((n, r) => n + r.picks.length, 0);
    return {
      fixtures: Math.max(incomingRows.length, dangerRows.length, aggRows.length),
      picks: pickCount,
      breaches,
      handshakes: aggRows.length,
    };
  }, [aggRows.length, dangerRows, incomingRows]);

  return (
    <div className="relative flex flex-col gap-5 p-6">
      <div className="pointer-events-none absolute inset-0 -z-10 bg-hero-glow opacity-70" />

      <section className="relative overflow-hidden rounded-2xl border border-accent-cyan/20 bg-nebula shadow-elevated">
        <div className="relative z-10 px-5 py-3.5 md:px-6">
          <h1 className="text-xl font-extrabold tracking-tight text-text-primary sm:text-2xl">
            Incoming Forensics
          </h1>
          <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-text-secondary">
            Structural pick stream from live lineups, squad danger audit (GK leak / missing stars),
            then master handshake chemistry across GG · Win · O2.5 · Corners · Unders.
          </p>
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent-cyan/15 text-accent-cyan">
            <Radio className="h-4 w-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-text-primary">
              Incoming Forensic Engine
            </h2>
            <p className="text-2xs text-text-dim">
              Rules 1–8 → incoming_predictions.json · {incomingRows.length} fixtures
            </p>
          </div>
        </div>
        <ChainBranch
          title="INCOMING_FEED"
          description="Forensic picks from rules 1–8 with pick type and lead reason"
          data={incomingRows}
          loading={incoming.loading}
          error={incoming.error}
          columns={incomingColumns}
          rowKey={(r) => r.fixture_id}
          emptyMessage="No incoming forensic picks yet."
          isRefetching={incoming.isRefetching}
          defaultOpen
        />
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent-red/15 text-accent-red">
            <AlertTriangle className="h-4 w-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-text-primary">
              Code 4 — Danger Forensic Aggregator
            </h2>
            <p className="text-2xs text-text-dim">
              Vulnerability · GK leak · missing stars · style alignment
            </p>
          </div>
        </div>
        <ChainBranch
          title="DANGER_AUDIT"
          description="Vulnerability audit — GK leak, missing stars, style alignment, match chemistry"
          data={dangerRows}
          loading={danger.loading}
          error={danger.error}
          columns={dangerColumns}
          rowKey={(r) => String(r.fixture_id)}
          emptyMessage="No danger audit profiles yet."
          isRefetching={danger.isRefetching}
          defaultOpen
        />
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent-green/15 text-accent-green">
            <Handshake className="h-4 w-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-text-primary">
              Code 5 — Master Aggregator Handshake
            </h2>
            <p className="text-2xs text-text-dim">
              Incoming + danger → market chemistry list · {aggRows.length} matches
            </p>
          </div>
        </div>
        {aggregator.loading && aggRows.length === 0 ? (
          <Skeleton className="h-48 rounded-xl bg-bg-elevated" />
        ) : (
          <div className="grid gap-3">
            {aggRows.map((row) => (
              <AggregatorCard key={String(row.fixture_id)} row={row} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
