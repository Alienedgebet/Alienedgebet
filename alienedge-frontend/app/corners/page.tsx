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
  { key: "confidence", header: "Avg Confidence", align: "right", render: (r) => r.avg_confidence },
  {
    key: "odds",
    header: "Odds (Win/O2.5)",
    align: "right",
    render: (r) => `${r.home_win_odds.toFixed(2)} / ${r.over_2_5_odds.toFixed(2)}`,
  },
];

export default function CornersPage() {
  const { date } = useSelectedDate();
  const { data: dnaV2 } = useDnaV2();

  const aggregatorColumnsWithDna = useMemo(
    () => [
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

  return (
    <div
      className="flex flex-col gap-4 p-6"
    >
      <div className="glass flex items-center gap-3 rounded-lg p-4 shadow-panel">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-cyan/15">
          <CornerUpRight className="h-5 w-5 text-accent-cyan" />
        </div>
        <div>
          <h1 className="text-base font-bold text-text-primary">Corners Intelligence</h1>
          <p className="text-xs text-text-secondary">
            Full 5-stage Corner Empire chain — master aggregation up top, the catalyst and
            psychology layers, then the two-stage refinement base.
          </p>
        </div>
      </div>

      <div>
        <ChainStage
          title="Corner Master Aggregator"
          description="Elite output"
          fetcher={() => cornersApi.getAggregator(date)}
          deps={[date]}
          columns={aggregatorColumnsWithDna}
          rowKey={(r, i) => `${r.Fixture}-${i}`}
          emptyMessage="No aggregator picks for this date."
          fallbackData={MOCK_CORNER_AGG}
        />
      </div>

      <div>
        <ChainStage
          title="Corner Catalyst"
          description="Wounded-beast catalyst layer"
          fetcher={() => cornersApi.getCatalyst(date)}
          deps={[date]}
          columns={catalystColumns}
          rowKey={(r, i) => `${r.fixture_name}-${i}`}
          emptyMessage="No catalyst picks for this date."
          fallbackData={MOCK_CORNER_CAT}
        />
      </div>

      <div>
        <ChainStage
          title="Corner Psychology"
          description="Standings & tactical psychology"
          fetcher={() => cornersApi.getPsychology(date)}
          deps={[date]}
          columns={psychologyColumns}
          rowKey={(r, i) => `${r.fixture_name}-${i}`}
          emptyMessage="No psychology audits for this date."
          fallbackData={MOCK_CORNER_PSYCH}
        />
      </div>

      <div>
        <ChainStage
          title="Corner Refiner (Stage 2)"
          description="Style-alignment refinement"
          fetcher={() => cornersApi.getStage2(date)}
          deps={[date]}
          columns={stage2Columns}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No stage 2 picks for this date."
          fallbackData={MOCK_CORNER_S2}
        />
      </div>

      <div>
        <ChainStage
          title="Corner Miner (Stage 1)"
          description="Foundation base"
          fetcher={() => cornersApi.getStage1(date)}
          deps={[date]}
          columns={stage1Columns}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No stage 1 picks for this date."
          fallbackData={MOCK_CORNER_S1}
        />
      </div>
    </div>
  );
}
