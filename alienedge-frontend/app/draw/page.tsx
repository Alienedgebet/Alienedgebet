"use client";

import { useMemo, useState } from "react";
import { Scale } from "lucide-react";
import { specialsApi, type DrawPick } from "@/lib/api";
import { SignalRankToggle } from "@/components/predictions/SignalRankToggle";
import { sortDraw } from "@/lib/cross-engine-ranking";
import { useSelectedDate } from "@/lib/date-context";
import { useApi, VERIFY_REFRESH_MS } from "@/lib/use-api";
import { useDnaV2 } from "@/lib/use-dna-v2";
import { createDnaColumn } from "@/components/dna/DnaCountBadge";
import { createIntelligentPassColumn } from "@/components/predictions/IntelligentPassColumn";
import { createVerifyColumn } from "@/components/predictions/createVerifyColumn";
import { QuickHistoryStrip } from "@/components/layout/QuickHistoryStrip";
import { ChainBranch, TierBadge, ProbCell, type PredictionColumn } from "@/components/predictions";
import { MOCK_DRAW } from "@/lib/mock-chains";
import { FixtureRiskTag } from "@/components/FixtureRiskTag";

const drawColumns: PredictionColumn<DrawPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <FixtureRiskTag row={r} label={r.fixture} className="font-medium text-text-primary" />,
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
  // Default ON: composite_draw_score >= 0.391 AND h2h_draws >= 1 clears the
  // Bonferroni correction outright (288 rows, 46.9% vs 17.6% for the rest,
  // +29.2pp, corrected p = 0.0000 over 11,830 cut-points, bootstrap CI
  // [+23.6, +35.4], leave-one-day-out 10/13, base 25.0%).
  // See lib/cross-engine-ranking.ts.
  const [smartRank, setSmartRank] = useState(true);
  const result = useApi(() => specialsApi.getDraw(date), [date], {
    fallback: MOCK_DRAW,
    cacheKey: `draw:${date}`,
    refreshMs: VERIFY_REFRESH_MS,
  });

  // Verify -> DNA -> Rest (Used across all 3 draw branches)
  const drawColumnsWithVerifyAndDna = useMemo(
    () => [
      createVerifyColumn<DrawPick>(),
      createDnaColumn<DrawPick>(dnaV2?.market_factors, "draw", date),
      createIntelligentPassColumn<DrawPick>({
        market: "draw",
        getTeam: (r) => r.home_team,
        getLabel: (r) => r.fixture,
        date,
      }),
      ...drawColumns,
    ],
    [dnaV2, date]
  );

  // Real data stays real; real empty stays real empty; demo rows appear
  // only when useApi flagged them (demo explicitly enabled). API failures
  // surface through ChainBranch's error state below.
  const payload = result.data;
  const isMock = result.isMock;

  // Applied AFTER the fetch so the mock/demo path and the real path are ordered
  // identically, and only to the main draw list. The parity branch below is a
  // DIFFERENT market (score gap <= 2) whose rule was not measured, so it keeps
  // the engine's own order.
  const orderedDraws = useMemo(
    () =>
      smartRank && payload?.draws
        ? sortDraw(payload.draws)
        : payload?.draws ?? [],
    // Depend on `payload` itself, not `payload?.draws`: the React Compiler
    // infers the coarser dependency and skips optimisation when a narrower one
    // is declared, because a narrower dep can fire more often than the value
    // it guards.
    [payload, smartRank]
  );

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
              Draw Magnet — ranked draws &amp; No 3 Goal in a Roll &amp; Asian Handicap 2.5
            </p>
          </div>
        </div>
        <SignalRankToggle
          active={smartRank}
          onChange={setSmartRank}
          activeLabel="Smart rank"
          inactiveLabel="As served"
          help="Picks the backtested combination to the top of the Draw Magnet list: composite_draw_score >= 0.391 AND h2h_draws >= 1 (288 rows, 46.9% vs 17.6% for the rest, +29.2pp, Bonferroni-corrected p = 0.0000 across 11,830 tested cut-points, better on 10 of 13 leave-one-day-out days). Does not affect the parity branch. Re-check with: python3 signal_backtest.py --market draw"
        />
      </div>

      {/* ── 2. 5-DAY HISTORY AUDIT STRIP ─────────────────────────────── */}
      <QuickHistoryStrip />

      {/* ── 3. BRANCH 1: Draw Magnet ────────────────────────────────── */}
      <ChainBranch
        title="Draw Magnet"
        description={isMock ? "Full ranked draw list · Demo" : "Full ranked draw list"}
        data={orderedDraws}
        loading={result.loading}
        error={result.error}
        columns={drawColumnsWithVerifyAndDna}
        rowKey={(r, i) => `${r.fixture_id}-${i}`}
        emptyMessage="No draw picks for this date."
      />

      {/* ── 4. BRANCH 2: No 3 Goal in a Roll & Asian Handicap 2.5 ───── */}
      <ChainBranch
        title="No 3 Goal in a Roll & Asian Handicap 2.5"
        description={isMock ? "Parity ≥ 0.9 subset · Demo" : "Parity ≥ 0.9 subset"}
        data={payload?.parity_list ?? []}
        loading={result.loading}
        error={result.error}
        columns={drawColumnsWithVerifyAndDna}
        rowKey={(r, i) => `${r.fixture_id}-${i}`}
        emptyMessage="No high-parity fixtures for this date."
      />

    </div>
  );
}
