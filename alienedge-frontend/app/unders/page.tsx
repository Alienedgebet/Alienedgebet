"use client";

import { useMemo } from "react";
import { TrendingDown } from "lucide-react";
import { specialsApi, type UndersPick } from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
import { useApi } from "@/lib/use-api";
import { useDnaV2 } from "@/lib/use-dna-v2";
import { createDnaColumn } from "@/components/dna/DnaCountBadge";
import { ChainBranch, TierBadge, ProbCell, type PredictionColumn } from "@/components/predictions";
import { MOCK_UNDERS } from "@/lib/mock-chains";

const u25Columns: PredictionColumn<UndersPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <span className="font-medium text-text-primary">{r.fixture}</span>,
  },
  { key: "tier", header: "U2.5 Tier", render: (r) => (r.u25_tier ? <TierBadge tier={r.u25_tier} /> : "—") },
  { key: "score", header: "U2.5 Score", align: "right", render: (r) => r.u25_score ?? "—" },
  {
    key: "prob",
    header: "MC U2.5 %",
    render: (r) => (r.mc_u25_prob != null ? <ProbCell value={r.mc_u25_prob * 100} showBar={false} /> : "—"),
  },
  { key: "signals", header: "Signals Fired", align: "right", render: (r) => r.u25_signals_fired ?? "—" },
  { key: "lambda", header: "Combined Lambda", align: "right", render: (r) => r.combined_lambda.toFixed(2) },
  {
    key: "gk_home",
    header: "Home GK Wall",
    align: "right",
    render: (r) => r.home_gk_cpg.toFixed(2),
  },
  {
    key: "gk_away",
    header: "Away GK Wall",
    align: "right",
    render: (r) => r.away_gk_cpg.toFixed(2),
  },
  {
    key: "gk_note_h",
    header: "Home GK Note",
    className: "max-w-[140px] truncate",
    render: (r) => r.home_gk_note || "—",
  },
  {
    key: "gk_note_a",
    header: "Away GK Note",
    className: "max-w-[140px] truncate",
    render: (r) => r.away_gk_note || "—",
  },
  {
    key: "fatigue_home",
    header: "Home Fatigue",
    align: "right",
    render: (r) => r.fatigue_home.toFixed(2),
  },
  {
    key: "fatigue_away",
    header: "Away Fatigue",
    align: "right",
    render: (r) => r.fatigue_away.toFixed(2),
  },
];

const u35Columns: PredictionColumn<UndersPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <span className="font-medium text-text-primary">{r.fixture}</span>,
  },
  { key: "tier", header: "U3.5 Tier", render: (r) => (r.u35_tier ? <TierBadge tier={r.u35_tier} /> : "—") },
  { key: "score", header: "U3.5 Score", align: "right", render: (r) => r.u35_score ?? "—" },
  {
    key: "prob",
    header: "MC U3.5 %",
    render: (r) => (r.mc_u35_prob != null ? <ProbCell value={r.mc_u35_prob * 100} showBar={false} /> : "—"),
  },
  { key: "lambda", header: "Combined Lambda", align: "right", render: (r) => r.combined_lambda.toFixed(2) },
  {
    key: "gk_home",
    header: "Home GK Wall",
    align: "right",
    render: (r) => r.home_gk_cpg.toFixed(2),
  },
  {
    key: "gk_away",
    header: "Away GK Wall",
    align: "right",
    render: (r) => r.away_gk_cpg.toFixed(2),
  },
  {
    key: "fatigue_home",
    header: "Home Fatigue",
    align: "right",
    render: (r) => r.fatigue_home.toFixed(2),
  },
  {
    key: "fatigue_away",
    header: "Away Fatigue",
    align: "right",
    render: (r) => r.fatigue_away.toFixed(2),
  },
];

export function UndersMarketPanel({ embedded = false }: { embedded?: boolean }) {
  const { date } = useSelectedDate();
  const { data: dnaV2 } = useDnaV2();
  const result = useApi(() => specialsApi.getUnders(date), [date], {
    fallback: MOCK_UNDERS,
    cacheKey: `unders:${date}`,
  });

  const u25ColumnsWithDna = useMemo(
    () => [
      createDnaColumn<UndersPick>(dnaV2?.market_factors, "unders", date),
      ...u25Columns,
    ],
    [dnaV2, date]
  );
  const u35ColumnsWithDna = useMemo(
    () => [
      createDnaColumn<UndersPick>(dnaV2?.market_factors, "unders", date),
      ...u35Columns,
    ],
    [dnaV2, date]
  );

  // Render-time fallback — same contract as dashboard withFallback / ChainStage.
  const live = result.data;
  const liveHasRows =
    Boolean(live) &&
    ((live!.u25?.length ?? 0) > 0 || (live!.u35?.length ?? 0) > 0);
  const payload = liveHasRows ? live! : MOCK_UNDERS;
  const isMock = !liveHasRows || result.isMock;

  return (
    <div
      data-embedded={embedded || undefined}
      className="flex flex-col gap-4 p-6"
    >
      <div className="glass flex items-center gap-3 rounded-lg p-4 shadow-panel">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-red/15">
          <TrendingDown className="h-5 w-5 text-accent-red" />
        </div>
        <div>
          <h1 className="text-base font-bold text-text-primary">Unders Intelligence</h1>
          <p className="text-xs text-text-secondary">
            Single-code special — one composite response covering both Under 2.5 and Under 3.5 in
            a single engine run.
          </p>
        </div>
      </div>

      <div>
        <ChainBranch
          title="Under 2.5"
          description={
            isMock
              ? "Defensive Under Empire — head 1/2 · Demo"
              : "Defensive Under Empire — head 1/2"
          }
          data={payload.u25}
          loading={result.loading}
          error={null}
          columns={u25ColumnsWithDna}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No Under 2.5 picks for this date."
        />
      </div>

      <div>
        <ChainBranch
          title="Under 3.5"
          description={
            isMock
              ? "Defensive Under Empire — head 2/2 · Demo"
              : "Defensive Under Empire — head 2/2"
          }
          data={payload.u35}
          loading={result.loading}
          error={null}
          columns={u35ColumnsWithDna}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No Under 3.5 picks for this date."
        />
      </div>
    </div>
  );
}

export default function UndersPage() {
  return <UndersMarketPanel />;
}
