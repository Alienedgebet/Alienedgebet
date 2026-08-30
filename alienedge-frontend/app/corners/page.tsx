"use client";

import { useMemo } from "react";
import { CornerUpRight } from "lucide-react";
import {
  cornersApi,
  type CornerAggregatorPick,
  type CornerCatalystPick,
  type CornerPsychologyPick,
  type CornerStage2Pick,
  type CornerStage1Pick,
} from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
import { useDnaV2 } from "@/lib/use-dna-v2";
import { createDnaColumnByLabel } from "@/components/dna/DnaCountBadge";
import { createVerifyColumn } from "@/components/predictions/createVerifyColumn";
import { QuickHistoryStrip } from "@/components/layout/QuickHistoryStrip";
import { ChainStage, TierBadge, ProbCell, type PredictionColumn } from "@/components/predictions";
import {
  MOCK_CORNER_AGG,
  MOCK_CORNER_CAT,
  MOCK_CORNER_PSYCH,
  MOCK_CORNER_S1,
  MOCK_CORNER_S2,
} from "@/lib/mock-chains";

const aggregatorColumns: PredictionColumn<CornerAggregatorPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <span className="font-medium text-text-primary">{r.Fixture}</span>,
  },
  { key: "score", header: "Master Score", align: "right", render: (r) => r.Master_Score },
  { key: "tier", header: "Tier", render: (r) => <TierBadge tier={r.Tier} /> },
  { key: "chaos", header: "Chaos Rating", align: "right", render: (r) => r.Chaos_Rating },
  { key: "fav", header: "True Corner Fav", render: (r) => r.True_Corner_Fav },
  { key: "flow", header: "Match Flow", render: (r) => r.Match_Flow },
  { key: "u25", header: "U2.5%", render: (r) => <ProbCell value={r["U2.5%"]} showBar={false} /> },
  { key: "total", header: "Total Exp", align: "right", render: (r) => r.Total_Exp },
  {
    key: "wounded",
    header: "Wounded (H/A)",
    render: (r) => (
      <span className="text-2xs">
        <span className={r.Home_Wounded === "True" ? "text-accent-red" : "text-text-dim"}>
          {r.Home_Wound_Int || "—"}
        </span>
        {" / "}
        <span className={r.Away_Wounded === "True" ? "text-accent-red" : "text-text-dim"}>
          {r.Away_Wound_Int || "—"}
        </span>
      </span>
    ),
  },
];

const catalystColumns: PredictionColumn<CornerCatalystPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <span className="font-medium text-text-primary">{r.fixture_name}</span>,
  },
  { key: "corners", header: "Predicted Corners", align: "right", render: (r) => r.predicted_corners },
  { key: "tier", header: "Tier", render: (r) => <TierBadge tier={r.corner_tier} /> },
  {
    key: "positions",
    header: "Table Pos (H/A)",
    align: "right",
    render: (r) => `${r.home_position} / ${r.away_position}`,
  },
  { key: "friction", header: "Friction Grade", render: (r) => r.friction_grade },
  {
    key: "wounded",
    header: "Wounded Beast",
    render: (r) => (
      <div className="flex flex-col gap-0.5 text-2xs">
        {r.home_is_wounded_beast && (
          <span className="text-accent-red">H: {r.home_wounded_intensity}</span>
        )}
        {r.away_is_wounded_beast && (
          <span className="text-accent-red">A: {r.away_wounded_intensity}</span>
        )}
        {!r.home_is_wounded_beast && !r.away_is_wounded_beast && <span className="text-text-dim">—</span>}
      </div>
    ),
  },
];

const psychologyColumns: PredictionColumn<CornerPsychologyPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <span className="font-medium text-text-primary">{r.fixture_name}</span>,
  },
  {
    key: "positions",
    header: "Table Pos (H/A)",
    align: "right",
    render: (r) => `${r.home_position} / ${r.away_position}`,
  },
  { key: "gap", header: "Standings Gap", align: "right", render: (r) => r.standings_gap },
  { key: "friction", header: "Friction Grade", render: (r) => r.friction_grade },
  { key: "tactical", header: "Tactical Grade", render: (r) => r.tactical_intelligence_grade },
  {
    key: "note",
    header: "Tactical Note",
    className: "max-w-[220px] truncate",
    render: (r) => r.tactical_note || "—",
  },
  {
    key: "wounded",
    header: "Wounded Beast",
    render: (r) =>
      r.is_wounded_beast ? (
        <span className="text-accent-red">
          {r.wounded_team_name}: {r.wounded_reason}
        </span>
      ) : (
        <span className="text-text-dim">—</span>
      ),
  },
];

const stage2Columns: PredictionColumn<CornerStage2Pick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <span className="font-medium text-text-primary">{r.fixture}</span>,
  },
  {
    key: "predicted",
    header: "Corners (S1/S2)",
    align: "right",
    render: (r) => `${r.stage1_predicted_corners} → ${r.stage2_predicted_corners}`,
  },
  { key: "expected", header: "Expected Total", align: "right", render: (r) => r.expected_total_corners },
  { key: "tier", header: "Tier", render: (r) => <TierBadge tier={r.corner_tier} /> },
  { key: "style", header: "Style Alignment", render: (r) => r.style_alignment },
  { key: "confidence", header: "Avg Confidence", align: "right", render: (r) => r.avg_confidence },
  {
    key: "persistent",
    header: "Persistent (V/O)",
    render: (r) => (
      <span className="text-2xs">
        H: {r.home_is_persistent_venue ? "V" : "—"}/{r.home_is_persistent_overall ? "O" : "—"} · A:{" "}
        {r.away_is_persistent_venue ? "V" : "—"}/{r.away_is_persistent_overall ? "O" : "—"}
      </span>
    ),
  },
];

const stage1Columns: PredictionColumn<CornerStage1Pick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <span className="font-medium text-text-primary">{r.fixture}</span>,
  },
  { key: "expected", header: "Expected Total", align: "right", render: (r) => r.expected_total_corners },
  { key: "tier", header: "Tier", render: (r) => <TierBadge tier={r.corner_tier} /> },
  { key: "diff", header: "Expected Diff", align: "right", render: (r) => r.expected_difference },
  { key: "team_more", header: "Team With More", render: (r) => r.team_more_corners },
  {
    key: "prob_like",
    header: "Prob-Like %",
    render: (r) => <ProbCell value={r.team_more_corners_probability_like} showBar={false} />,
  },
  {
    key: "odds",
    header: "Odds (Win/O2.5)",
    align: "right",
    render: (r) => `${r.home_win_odds.toFixed(2)} / ${r.over_2_5_odds.toFixed(2)}`,
  },
  { key: "confidence", header: "Avg Confidence", align: "right", render: (r) => r.avg_confidence },
];

export default function CornersPage() {
  const { date } = useSelectedDate();
  const { data: dnaV2 } = useDnaV2();

  // 1. Master Aggregator (Verify -> DNA -> Rest)
  const aggregatorColumnsWithVerifyAndDna = useMemo(
    () => [
      createVerifyColumn<CornerAggregatorPick>(),
      createDnaColumnByLabel<CornerAggregatorPick>(
        dnaV2?.market_factors,
        "corners",
        date,
        (r) => r.Fixture
      ),
      ...aggregatorColumns,
    ],
    [dnaV2, date]
  );

  // 2. Catalyst (Verify -> Rest)
  const catalystColumnsWithVerify = useMemo(
    () => [createVerifyColumn<CornerCatalystPick>(), ...catalystColumns],
    []
  );

  // 3. Psychology (Verify -> Rest)
  const psychologyColumnsWithVerify = useMemo(
    () => [createVerifyColumn<CornerPsychologyPick>(), ...psychologyColumns],
    []
  );

  // 4. Refiner Stage 2 (Verify -> Rest)
  const stage2ColumnsWithVerify = useMemo(
    () => [createVerifyColumn<CornerStage2Pick>(), ...stage2Columns],
    []
  );

  // 5. Miner Stage 1 (Verify -> Rest)
  const stage1ColumnsWithVerify = useMemo(
    () => [createVerifyColumn<CornerStage1Pick>(), ...stage1Columns],
    []
  );

  return (
    <div
      className="flex flex-col gap-4 p-3.5 sm:p-5 md:p-6"
    >
      {/* ── 1. SLEEK COMPACT TOP BANNER ──────────────────────────────── */}
      <div className="glass flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-[#0c1220]/90 px-4 py-3 shadow-panel backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-accent-cyan/30 bg-accent-cyan/10 shadow-[0_0_12px_rgba(6,182,212,0.2)]">
            <CornerUpRight className="h-4 w-4 text-accent-cyan" />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-text-primary">
              Corners Intelligence
            </h1>
            <p className="text-[11px] text-text-secondary">
              Full 5-stage Corner Empire chain — master aggregation, catalyst &amp; psychology
            </p>
          </div>
        </div>
      </div>

      {/* ── 2. 5-DAY HISTORY AUDIT STRIP ─────────────────────────────── */}
      <QuickHistoryStrip />

      {/* ── 3. STAGE 1: Corner Master Aggregator ────────────────────── */}
      <div>
        <ChainStage
          title="Corner Master Aggregator"
          description="Elite output"
          fetcher={() => cornersApi.getAggregator(date)}
          deps={[date]}
          columns={aggregatorColumnsWithVerifyAndDna}
          rowKey={(r, i) => `${r.Fixture}-${i}`}
          emptyMessage="No aggregator picks for this date."
          fallbackData={MOCK_CORNER_AGG}
        />
      </div>

      {/* ── 4. STAGE 2: Corner Catalyst ─────────────────────────────── */}
      <div>
        <ChainStage
          title="Corner Catalyst"
          description="Wounded-beast catalyst layer"
          fetcher={() => cornersApi.getCatalyst(date)}
          deps={[date]}
          columns={catalystColumnsWithVerify}
          rowKey={(r, i) => `${r.fixture_name}-${i}`}
          emptyMessage="No catalyst picks for this date."
          fallbackData={MOCK_CORNER_CAT}
        />
      </div>

      {/* ── 5. STAGE 3: Corner Psychology ───────────────────────────── */}
      <div>
        <ChainStage
          title="Corner Psychology"
          description="Standings & tactical psychology"
          fetcher={() => cornersApi.getPsychology(date)}
          deps={[date]}
          columns={psychologyColumnsWithVerify}
          rowKey={(r, i) => `${r.fixture_name}-${i}`}
          emptyMessage="No psychology audits for this date."
          fallbackData={MOCK_CORNER_PSYCH}
        />
      </div>

      {/* ── 6. STAGE 4: Corner Refiner (Stage 2) ────────────────────── */}
      <div>
        <ChainStage
          title="Corner Refiner (Stage 2)"
          description="Style-alignment refinement"
          fetcher={() => cornersApi.getStage2(date)}
          deps={[date]}
          columns={stage2ColumnsWithVerify}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No stage 2 picks for this date."
          fallbackData={MOCK_CORNER_S2}
        />
      </div>

      {/* ── 7. STAGE 5: Corner Miner (Stage 1) ──────────────────────── */}
      <div>
        <ChainStage
          title="Corner Miner (Stage 1)"
          description="Foundation base"
          fetcher={() => cornersApi.getStage1(date)}
          deps={[date]}
          columns={stage1ColumnsWithVerify}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No stage 1 picks for this date."
          fallbackData={MOCK_CORNER_S1}
        />
      </div>
    </div>
  );
}
