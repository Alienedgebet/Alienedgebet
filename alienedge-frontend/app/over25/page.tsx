"use client";

import { useMemo } from "react";
import { TrendingUp } from "lucide-react";
import {
  over25Api,
  type Over25ApexPick,
  type Over25GoldPick,
  type Over25ForecastPick,
  type Over25Stage3Pick,
  type Over25PsychologyPick,
  type Over25Stage2Pick,
  type Over25Stage1Pick,
} from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
import { useDnaV2 } from "@/lib/use-dna-v2";
import { createDnaColumn } from "@/components/dna/DnaCountBadge";
import { ChainStage, TierBadge, ProbCell, type PredictionColumn } from "@/components/predictions";
import {
  MOCK_O25_APEX,
  MOCK_O25_FORECAST,
  MOCK_O25_GOLD,
  MOCK_O25_PSYCH,
  MOCK_O25_S1,
  MOCK_O25_S2,
  MOCK_O25_S3,
} from "@/lib/mock-chains";

const apexColumns: PredictionColumn<Over25ApexPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <span className="font-medium text-text-primary">{r.Fixture}</span>,
  },
  { key: "category", header: "Category", render: (r) => <TierBadge tier={r.Category} /> },
  {
    key: "prob",
    header: "Super Monte %",
    render: (r) => <ProbCell value={r.Super_Monte_Prob} showBar={false} />,
  },
  { key: "risk", header: "U25 Risk", align: "right", render: (r) => r.U25_Risk },
  { key: "grade", header: "Base Grade", render: (r) => r.Base_Grade },
  { key: "dna", header: "DNA Status", render: (r) => r.DNA_Status },
  { key: "vip", header: "VIP", render: (r) => r.VIP_Status },
  {
    key: "veto",
    header: "Veto",
    render: (r) => (
      <span className={r.Veto_Status && r.Veto_Status !== "None" ? "text-accent-red" : "text-text-dim"}>
        {r.Veto_Status || "—"}
      </span>
    ),
  },
];

const goldColumns: PredictionColumn<Over25GoldPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => (
      <span className="font-medium text-text-primary">
        {r.teams.home.name} vs {r.teams.away.name}
      </span>
    ),
  },
  { key: "league", header: "League", render: (r) => r.league },
  {
    key: "flags",
    header: "Gold Flags",
    className: "max-w-[260px]",
    render: (r) => (
      <div className="flex flex-wrap gap-1 text-2xs">
        {Object.entries(r.flags)
          .filter(([, v]) => v)
          .map(([k]) => (
            <span
              key={k}
              className="rounded border border-accent-amber/30 bg-accent-amber/10 px-1 py-0.5 text-accent-amber"
            >
              {k.replace(/_/g, " ")}
            </span>
          ))}
      </div>
    ),
  },
  {
    key: "goals",
    header: "Goals L5 (H/A)",
    align: "right",
    render: (r) => `${r.metrics.home_goals_last_5} / ${r.metrics.away_goals_last_5}`,
  },
  { key: "h2h", header: "H2H Analyzed", align: "right", render: (r) => r.metrics.h2h_matches_analyzed },
];

const forecastColumns: PredictionColumn<Over25ForecastPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <span className="font-medium text-text-primary">{r.fixture}</span>,
  },
  { key: "league", header: "League", render: (r) => r.league },
  {
    key: "kill",
    header: "Kill Switch",
    render: (r) => (
      <span className={r.kill_switch_pass ? "text-accent-green" : "text-accent-red"}>
        {r.kill_switch_pass ? "Pass" : "Fail"}
      </span>
    ),
  },
  {
    key: "poisson",
    header: "Poisson Over %",
    render: (r) => <ProbCell value={r.poisson_over_prob_num} showBar={false} />,
  },
  { key: "odds", header: "O2.5 Odds", align: "right", render: (r) => r.o25_odds.toFixed(2) },
  { key: "votes", header: "Council Votes", render: (r) => r.council_votes },
  { key: "pos_gap", header: "Pos Gap", align: "right", render: (r) => r.pos_gap },
  { key: "h2h_overs", header: "H2H Overs /5", align: "right", render: (r) => r.h2h_overs_last_5 },
];

const stage3Columns: PredictionColumn<Over25Stage3Pick>[] = [
  {
    key: "match",
    header: "Match",
    render: (r) => <span className="font-medium text-text-primary">{r.Match}</span>,
  },
  { key: "poisson", header: "Poisson %", render: (r) => <ProbCell value={r["Poisson%"]} showBar={false} /> },
  { key: "odds", header: "Odds", align: "right", render: (r) => r.Odds.toFixed(2) },
  { key: "grade", header: "Grade", render: (r) => <TierBadge tier={r.Grade} /> },
  { key: "h2h", header: "H2H Record", render: (r) => r.H2H_Record },
  { key: "picked", header: "Picked By", render: (r) => r.PickedBy },
  {
    key: "fail",
    header: "Failures",
    className: "max-w-[200px] truncate",
    render: (r) => r.Failures || "—",
  },
];

const psychologyColumns: PredictionColumn<Over25PsychologyPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <span className="font-medium text-text-primary">{r.Fixture}</span>,
  },
  { key: "poisson", header: "Base Poisson", render: (r) => <ProbCell value={r.Base_Poisson} showBar={false} /> },
  { key: "grade", header: "Base Grade", render: (r) => r.Base_Grade },
  { key: "score", header: "Score", align: "right", render: (r) => r.Score },
  { key: "tier", header: "Tier", render: (r) => <TierBadge tier={r.Tier} /> },
  {
    key: "reasons",
    header: "Reasons",
    className: "max-w-[220px] truncate",
    render: (r) => r.Reasons || "—",
  },
];

const stage2Columns: PredictionColumn<Over25Stage2Pick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <span className="font-medium text-text-primary">{r.fixture}</span>,
  },
  { key: "time", header: "Time", render: (r) => r.Time },
  { key: "votes", header: "Votes", align: "right", render: (r) => r.Votes },
  { key: "odds", header: "Odds", align: "right", render: (r) => r.Odds.toFixed(2) },
  { key: "algo", header: "Algorithm", render: (r) => r.Algorithm },
  {
    key: "reasons",
    header: "Reasons",
    className: "max-w-[220px] truncate",
    render: (r) => r.Reasons || "—",
  },
];

const stage1Columns: PredictionColumn<Over25Stage1Pick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <span className="font-medium text-text-primary">{r.fixture}</span>,
  },
  { key: "time", header: "Time", render: (r) => r.Time },
  { key: "confidence", header: "Confidence", render: (r) => r.Confidence },
  { key: "odds", header: "Odds", align: "right", render: (r) => r.Odds.toFixed(2) },
  { key: "algo", header: "Algorithm", render: (r) => r.Algorithm },
];

export function Over25MarketPanel({ embedded = false }: { embedded?: boolean }) {
  const { date } = useSelectedDate();
  const { data: dnaV2 } = useDnaV2();

  const apexColumnsWithDna = useMemo(
    () => [
      createDnaColumn<Over25ApexPick>(dnaV2?.market_factors, "over25", date),
      ...apexColumns,
    ],
    [dnaV2, date]
  );

  return (
    <div
      data-embedded={embedded || undefined}
      className="flex flex-col gap-4 p-6"
    >
      <div className="glass flex items-center gap-3 rounded-lg p-4 shadow-panel">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-green/15">
          <TrendingUp className="h-5 w-5 text-accent-green" />
        </div>
        <div>
          <h1 className="text-base font-bold text-text-primary">Over 2.5 Intelligence</h1>
          <p className="text-xs text-text-secondary">
            Full 7-stage engine chain, every stage visible — apex aggregation up top, down through
            gold flags, forecast, kill-switch, psychology, council and the probabilistic base.
          </p>
        </div>
      </div>

      <div>
        <ChainStage
          title="Over 2.5 Apex — Final Aggregator"
          description="Elite output"
          fetcher={() => over25Api.getApex(date)}
          deps={[date]}
          columns={apexColumnsWithDna}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No apex picks for this date."
          fallbackData={MOCK_O25_APEX}
        />
      </div>

      <div>
        <ChainStage
          title="Over 2.5 Gold"
          description="100%-flag gold engine"
          fetcher={() => over25Api.getGold(date)}
          deps={[date]}
          columns={goldColumns}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No gold picks for this date."
          fallbackData={MOCK_O25_GOLD}
        />
      </div>

      <div>
        <ChainStage
          title="Over 2.5 Forecast"
          description="Forecast layer"
          fetcher={() => over25Api.getForecast(date)}
          deps={[date]}
          columns={forecastColumns}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No forecast picks for this date."
          fallbackData={MOCK_O25_FORECAST}
        />
      </div>

      <div>
        <ChainStage
          title="Over 2.5 Kill-Switch (Stage 3)"
          description="Failure-audited grading"
          fetcher={() => over25Api.getStage3(date)}
          deps={[date]}
          columns={stage3Columns}
          rowKey={(r, i) => `${r.Match}-${i}`}
          emptyMessage="No stage 3 picks for this date."
          fallbackData={MOCK_O25_S3}
        />
      </div>

      <div>
        <ChainStage
          title="Over 2.5 Psychology"
          description="Psychology layer"
          fetcher={() => over25Api.getPsychology(date)}
          deps={[date]}
          columns={psychologyColumns}
          rowKey={(r, i) => `${r.Fixture}-${i}`}
          emptyMessage="No psychology audits for this date."
          fallbackData={MOCK_O25_PSYCH}
        />
      </div>

      <div>
        <ChainStage
          title="Over 2.5 Council (Stage 2)"
          description="Multi-algorithm voting"
          fetcher={() => over25Api.getStage2(date)}
          deps={[date]}
          columns={stage2Columns}
          rowKey={(r, i) => `${r.id}-${i}`}
          emptyMessage="No stage 2 picks for this date."
          fallbackData={MOCK_O25_S2}
        />
      </div>

      <div>
        <ChainStage
          title="Over 2.5 Probabilistic Base (Stage 1)"
          description="Foundation base"
          fetcher={() => over25Api.getStage1(date)}
          deps={[date]}
          columns={stage1Columns}
          rowKey={(r, i) => `${r.id}-${i}`}
          emptyMessage="No stage 1 picks for this date."
          fallbackData={MOCK_O25_S1}
        />
      </div>
    </div>
  );
}

export default function Over25Page() {
  return <Over25MarketPanel />;
}
