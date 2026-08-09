"use client";

import { useMemo } from "react";
import { Flame } from "lucide-react";
import {
  over15Api,
  type Over15ApexPick,
  type Over15PsychologyPick,
  type Over15Stage3Pick,
} from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
import { useDnaV2 } from "@/lib/use-dna-v2";
import { createDnaColumnByLabel } from "@/components/dna/DnaCountBadge";
import { ChainStage, TierBadge, ProbCell, type PredictionColumn } from "@/components/predictions";
import { MOCK_O15_APEX, MOCK_O15_PSYCH, MOCK_O15_S3 } from "@/lib/mock-chains";

const apexColumns: PredictionColumn<Over15ApexPick>[] = [
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
    className: "max-w-[240px] truncate",
    render: (r) => r.Reasons || "—",
  },
];

const psychologyColumns: PredictionColumn<Over15PsychologyPick>[] = [
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
    className: "max-w-[240px] truncate",
    render: (r) => r.Reasons || "—",
  },
];

const stage3Columns: PredictionColumn<Over15Stage3Pick>[] = [
  {
    key: "match",
    header: "Match",
    render: (r) => <span className="font-medium text-text-primary">{r.Match}</span>,
  },
  { key: "odds", header: "Odds", align: "right", render: (r) => r.Odds.toFixed(2) },
  { key: "poisson", header: "Poisson %", render: (r) => <ProbCell value={r["Poisson%"]} showBar={false} /> },
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

export default function Over15Page() {
  const { date } = useSelectedDate();
  const { data: dnaV2 } = useDnaV2();

  const apexColumnsWithDna = useMemo(
    () => [
      createDnaColumnByLabel<Over15ApexPick>(
        dnaV2?.market_factors,
        "over15",
        date,
        (r) => r.Fixture
      ),
      ...apexColumns,
    ],
    [dnaV2, date]
  );

  return (
    <div
      className="flex flex-col gap-4 p-6"
    >
      <div className="glass flex items-center gap-3 rounded-lg p-4 shadow-panel">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-amber/15">
          <Flame className="h-5 w-5 text-accent-amber" />
        </div>
        <div>
          <h1 className="text-base font-bold text-text-primary">Over 1.5 Intelligence</h1>
          <p className="text-xs text-text-secondary">
            Full engine chain, every stage visible — apex aggregation up top, the psychology audit,
            and the failure-audited base stage underneath it.
          </p>
        </div>
      </div>

      <div>
        <ChainStage
          title="Over 1.5 Apex — Final Aggregator"
          description="Elite output"
          fetcher={() => over15Api.getApex(date)}
          deps={[date]}
          columns={apexColumnsWithDna}
          rowKey={(r, i) => `${r.Fixture}-${i}`}
          emptyMessage="No apex picks for this date."
          fallbackData={MOCK_O15_APEX}
        />
      </div>

      <div>
        <ChainStage
          title="Over 1.5 Psychology"
          description="Psychology layer"
          fetcher={() => over15Api.getPsychology(date)}
          deps={[date]}
          columns={psychologyColumns}
          rowKey={(r, i) => `${r.Fixture}-${i}`}
          emptyMessage="No psychology audits for this date."
          fallbackData={MOCK_O15_PSYCH}
        />
      </div>

      <div>
        <ChainStage
          title="Over 1.5 Base (Stage 3)"
          description="Foundation base"
          fetcher={() => over15Api.getStage3(date)}
          deps={[date]}
          columns={stage3Columns}
          rowKey={(r, i) => `${r.Match}-${i}`}
          emptyMessage="No stage 3 picks for this date."
          fallbackData={MOCK_O15_S3}
        />
      </div>
    </div>
  );
}
