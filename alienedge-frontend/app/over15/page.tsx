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
import { createVerifyColumn } from "@/components/predictions/createVerifyColumn";
import { QuickHistoryStrip } from "@/components/layout/QuickHistoryStrip";
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

export default function Over15Page() {
  const { date } = useSelectedDate();
  const { data: dnaV2 } = useDnaV2();

  // 1. Apex (Verify -> DNA -> Rest)
  const apexColumnsWithVerifyAndDna = useMemo(
    () => [
      createVerifyColumn<Over15ApexPick>(),
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

  // 2. Psychology (Verify -> Rest)
  const psychologyColumnsWithVerify = useMemo(
    () => [createVerifyColumn<Over15PsychologyPick>(), ...psychologyColumns],
    []
  );

  // 3. Stage 3 Base (Verify -> Rest)
  const stage3ColumnsWithVerify = useMemo(
    () => [createVerifyColumn<Over15Stage3Pick>(), ...stage3Columns],
    []
  );

  return (
    <div
      className="flex flex-col gap-4 p-3.5 sm:p-5 md:p-6"
    >
      {/* ── 1. SLEEK COMPACT TOP BANNER ──────────────────────────────── */}
      <div className="glass flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-[#0c1220]/90 px-4 py-3 shadow-panel backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-accent-amber/30 bg-accent-amber/10 shadow-[0_0_12px_rgba(245,158,11,0.2)]">
            <Flame className="h-4 w-4 text-accent-amber" />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-text-primary">
              Over 1.5 Intelligence
            </h1>
            <p className="text-[11px] text-text-secondary">
              Full 3-stage engine chain — Apex picks, psychology audit &amp; base stage
            </p>
          </div>
        </div>
      </div>

      {/* ── 2. 5-DAY HISTORY AUDIT STRIP ─────────────────────────────── */}
      <QuickHistoryStrip />

      {/* ── 3. STAGE 1: Over 1.5 Apex ────────────────────────────────── */}
      <div>
        <ChainStage
          title="Over 1.5 Apex — Final Aggregator"
          description="Elite output"
          fetcher={() => over15Api.getApex(date)}
          deps={[date]}
          columns={apexColumnsWithVerifyAndDna}
          rowKey={(r, i) => `${r.Fixture}-${i}`}
          emptyMessage="No apex picks for this date."
          fallbackData={MOCK_O15_APEX}
        />
      </div>

      {/* ── 4. STAGE 2: Over 1.5 Psychology ──────────────────────────── */}
      <div>
        <ChainStage
          title="Over 1.5 Psychology"
          description="Psychology layer"
          fetcher={() => over15Api.getPsychology(date)}
          deps={[date]}
          columns={psychologyColumnsWithVerify}
          rowKey={(r, i) => `${r.Fixture}-${i}`}
          emptyMessage="No psychology audits for this date."
          fallbackData={MOCK_O15_PSYCH}
        />
      </div>

      {/* ── 5. STAGE 3: Over 1.5 Base (Stage 3) ──────────────────────── */}
      <div>
        <ChainStage
          title="Over 1.5 Base (Stage 3)"
          description="Foundation base"
          fetcher={() => over15Api.getStage3(date)}
          deps={[date]}
          columns={stage3ColumnsWithVerify}
          rowKey={(r, i) => `${r.Match}-${i}`}
          emptyMessage="No stage 3 picks for this date."
          fallbackData={MOCK_O15_S3}
        />
      </div>
    </div>
  );
}
