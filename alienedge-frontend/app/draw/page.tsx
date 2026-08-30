"use client";

import { useMemo } from "react";
import { Scale } from "lucide-react";
import { specialsApi, type DrawPick } from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
import { useApi } from "@/lib/use-api";
import { useDnaV2 } from "@/lib/use-dna-v2";
import { createDnaColumn } from "@/components/dna/DnaCountBadge";
import { createVerifyColumn } from "@/components/predictions/createVerifyColumn";
import { QuickHistoryStrip } from "@/components/layout/QuickHistoryStrip";
import { ChainBranch, TierBadge, ProbCell, type PredictionColumn } from "@/components/predictions";
import { MOCK_DRAW } from "@/lib/mock-chains";

const drawColumns: PredictionColumn<DrawPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <span className="font-medium text-text-primary">{r.fixture}</span>,
  },
  { key: "tier", header: "Tier", render: (r) => <TierBadge tier={r.tier} /> },
  {
    key: "prob",
    header: "MC Draw %",
    render: (r) => <ProbCell value={r.mc_draw_prob * 100} showBar={false} />,
  },
  {
    key: "poisson",
    header: "Poisson Draw %",
    align: "right",
    render: (r) => <span className="font-mono text-text-muted">{(r.poisson_draw_prob * 100).toFixed(1)}%</span>,
  },
  { key: "odds", header: "Draw Odds", align: "right", render: (r) => r.draw_odds.toFixed(2) },
  { key: "dmi", header: "DMI", align: "right", render: (r) => r.dmi },
  { key: "parity", header: "Parity", align: "right", render: (r) => r.parity },
  { key: "value", header: "Value Edge", align: "right", render: (r) => r.value_edge },
  {
    key: "likely",
    header: "Most Likely Score",
    render: (r) => (
      <span>
        {r.most_likely_draw_score}{" "}
        <span className="text-text-dim">({r.most_likely_draw_pct}%)</span>
      </span>
    ),
  },
  {
    key: "draws",
    header: "Draws (H/A/H2H)",
    align: "right",
    render: (r) => `${r.home_draws}/${r.away_draws}/${r.h2h_draws}`,
  },
];

export default function DrawPage() {
  const { date } = useSelectedDate();
  const { data: dnaV2 } = useDnaV2();
  const result = useApi(() => specialsApi.getDraw(date), [date], {
    fallback: MOCK_DRAW,
    cacheKey: `draw:${date}`,
  });

  // Verify -> DNA -> Rest (Used across all 3 draw branches)
  const drawColumnsWithVerifyAndDna = useMemo(
    () => [
      createVerifyColumn<DrawPick>(),
      createDnaColumn<DrawPick>(dnaV2?.market_factors, "draw", date),
      ...drawColumns,
    ],
    [dnaV2, date]
  );

  const live = result.data;
  const liveHasRows =
    Boolean(live) &&
    ((live!.draws?.length ?? 0) > 0 ||
      (live!.parity_list?.length ?? 0) > 0 ||
      (live!.amateurs_list?.length ?? 0) > 0);
  const payload = liveHasRows ? live! : MOCK_DRAW;
  const isMock = !liveHasRows || result.isMock;

  return (
    <div className="flex flex-col gap-4 p-3.5 sm:p-5 md:p-6">
      {/* ── 1. SLEEK COMPACT TOP BANNER ──────────────────────────────── */}
      <div className="glass flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-[#0c1220]/90 px-4 py-3 shadow-panel backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-accent-indigo/30 bg-accent-indigo/10 shadow-[0_0_12px_rgba(99,102,241,0.2)]">
            <Scale className="h-4 w-4 text-accent-indigo" />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-text-primary">
              Draw Intelligence
            </h1>
            <p className="text-[11px] text-text-secondary">
              Draw Magnet Index — composite analysis, high-parity list &amp; amateur draws
            </p>
          </div>
        </div>
      </div>

      {/* ── 2. 5-DAY HISTORY AUDIT STRIP ─────────────────────────────── */}
      <QuickHistoryStrip />

      {/* ── 3. BRANCH 1: Draw Magnet Index ──────────────────────────── */}
      <ChainBranch
        title="Draw Magnet Index"
        description={isMock ? "Full ranked draw list · Demo" : "Full ranked draw list"}
        data={payload.draws}
        loading={result.loading}
        error={null}
        columns={drawColumnsWithVerifyAndDna}
        rowKey={(r, i) => `${r.fixture_id}-${i}`}
        emptyMessage="No draw picks for this date."
      />

      {/* ── 4. BRANCH 2: High Parity List ───────────────────────────── */}
      <ChainBranch
        title="High Parity List"
        description={isMock ? "Parity ≥ 0.9 subset · Demo" : "Parity ≥ 0.9 subset"}
        data={payload.parity_list}
        loading={result.loading}
        error={null}
        columns={drawColumnsWithVerifyAndDna}
        rowKey={(r, i) => `${r.fixture_id}-${i}`}
        emptyMessage="No high-parity fixtures for this date."
      />

      {/* ── 5. BRANCH 3: Amateurs List ──────────────────────────────── */}
      <ChainBranch
        title="Amateurs List"
        description={isMock ? "Total draws > 5 subset · Demo" : "Total draws > 5 subset"}
        data={payload.amateurs_list}
        loading={result.loading}
        error={null}
        columns={drawColumnsWithVerifyAndDna}
        rowKey={(r, i) => `${r.fixture_id}-${i}`}
        emptyMessage="No amateur-table fixtures for this date."
      />
    </div>
  );
}
