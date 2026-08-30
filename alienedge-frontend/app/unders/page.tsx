"use client";

import { useMemo } from "react";
import { TrendingDown } from "lucide-react";
import { specialsApi, type UndersPick } from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
import { useApi } from "@/lib/use-api";
import { useDnaV2 } from "@/lib/use-dna-v2";
import { createDnaColumn } from "@/components/dna/DnaCountBadge";
import { createVerifyColumn } from "@/components/predictions/createVerifyColumn";
import { QuickHistoryStrip } from "@/components/layout/QuickHistoryStrip";
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

  // Under 2.5 (Verify -> DNA -> Rest)
  const u25ColumnsWithVerifyAndDna = useMemo(
    () => [
      createVerifyColumn<UndersPick>(),
      createDnaColumn<UndersPick>(dnaV2?.market_factors, "unders", date),
      ...u25Columns,
    ],
    [dnaV2, date]
  );

  // Under 3.5 (Verify -> DNA -> Rest)
  const u35ColumnsWithVerifyAndDna = useMemo(
    () => [
      createVerifyColumn<UndersPick>(),
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
      className="flex flex-col gap-4 p-3.5 sm:p-5 md:p-6"
    >
      {/* ── 1. SLEEK COMPACT TOP BANNER ──────────────────────────────── */}
      <div className="glass flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-[#0c1220]/90 px-4 py-3 shadow-panel backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-accent-red/30 bg-accent-red/10 shadow-[0_0_12px_rgba(244,63,94,0.2)]">
            <TrendingDown className="h-4 w-4 text-accent-red" />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-text-primary">
              Unders Intelligence
            </h1>
            <p className="text-[11px] text-text-secondary">
              Defensive Under Empire — composite analysis covering Under 2.5 &amp; Under 3.5
            </p>
          </div>
        </div>
      </div>

      {/* ── 2. 5-DAY HISTORY AUDIT STRIP ─────────────────────────────── */}
      <QuickHistoryStrip />

      {/* ── 3. BRANCH 1: Under 2.5 ──────────────────────────────────── */}
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
          columns={u25ColumnsWithVerifyAndDna}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No Under 2.5 picks for this date."
        />
      </div>

      {/* ── 4. BRANCH 2: Under 3.5 ──────────────────────────────────── */}
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
          columns={u35ColumnsWithVerifyAndDna}
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
