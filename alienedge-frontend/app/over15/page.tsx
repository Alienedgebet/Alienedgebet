"use client";

import { useMemo } from "react";
import { Flame } from "lucide-react";
import {
  over15Api,
  type Over15PsychologyPick,
  type Over15Stage3Pick,
} from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
import { createVerifyColumn } from "@/components/predictions/createVerifyColumn";
import { createIntelligentPassColumn } from "@/components/predictions/IntelligentPassColumn";
import { QuickHistoryStrip } from "@/components/layout/QuickHistoryStrip";
import { ChainStage, TierBadge, ProbCell, type PredictionColumn } from "@/components/predictions";
import { MOCK_O15_PSYCH, MOCK_O15_S3 } from "@/lib/mock-chains";
import { FixtureRiskTag } from "@/components/FixtureRiskTag";
import { VERIFY_REFRESH_MS } from "@/lib/use-api";

const psychologyColumns: PredictionColumn<Over15PsychologyPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <FixtureRiskTag row={r} label={r.Fixture} className="font-medium text-text-primary" />,
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
    render: (r) => <FixtureRiskTag row={r} label={r.Match} className="font-medium text-text-primary" />,
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

  // 1. Psychology (Verify -> Rest)
  const psychologyColumnsWithVerify = useMemo(
    () => [
      createVerifyColumn<Over15PsychologyPick>(),
      createIntelligentPassColumn<Over15PsychologyPick>({
        market: "over15",
        getLabel: (r) => r.Fixture,
        date,
      }),
      ...psychologyColumns,
    ],
    []
  );

  // 2. Stage 3 Base (Verify -> Rest)
  const stage3ColumnsWithVerify = useMemo(
    () => [
      createVerifyColumn<Over15Stage3Pick>(),
      createIntelligentPassColumn<Over15Stage3Pick>({
        market: "over15",
        getLabel: (r) => r.Match,
        date,
      }),
      ...stage3Columns,
    ],
    []
  );

  return (
    <div
      className="flex flex-col gap-4 p-3.5 sm:p-5 md:p-6"
    >
      {/* ── 1. SLEEK COMPACT TOP BANNER ──────────────────────────────── */}
      <div className="glass flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-[#0c1220]/90 px-4 py-3 shadow-panel backdrop-blur-md">
        <div className="flex w-9 h-9 shrink-0 items-center justify-center rounded-lg border border-accent-amber/30 bg-accent-amber/10 shadow-[0_0_12px_rgba(245,158,11,0.2)]">
          <Flame className="h-4 w-4 text-accent-amber" />
        </div>
        <div>
          <h1 className="text-sm font-black uppercase tracking-wider text-text-primary">
            Over 1.5 Intelligence
          </h1>
          <p className="text-[11px] text-text-secondary">
            2-stage engine chain — psychology audit &amp; base stage
          </p>
        </div>
      </div>

      {/* ── 2. 5-DAY HISTORY AUDIT STRIP ─────────────────────────────── */}
      <QuickHistoryStrip />

      {/* ── 3. Over 1.5 Intelligence ─────────────────────────────────── */}
      <div>
        <ChainStage
          title="Over 1.5 Intelligence"
          description="Psychology layer"
          fetcher={() => over15Api.getPsychology(date)}
          deps={[date]}
          columns={psychologyColumnsWithVerify}
          rowKey={(r, i) => `${r.Fixture}-${i}`}
          emptyMessage="No psychology audits for this date."
          fallbackData={MOCK_O15_PSYCH}
          refreshMs={VERIFY_REFRESH_MS}
        />
      </div>

      {/* ── 4. Over 1.5 Gold ─────────────────────────────────────────── */}
      <div>
        <ChainStage
          title="Over 1.5 Gold"
          description="Foundation base"
          fetcher={() => over15Api.getStage3(date)}
          deps={[date]}
          columns={stage3ColumnsWithVerify}
          rowKey={(r, i) => `${r.Match}-${i}`}
          emptyMessage="No stage 3 picks for this date."
          fallbackData={MOCK_O15_S3}
          refreshMs={VERIFY_REFRESH_MS}
        />
      </div>
    </div>
  );
}
