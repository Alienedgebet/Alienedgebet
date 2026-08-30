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
import { createVerifyColumn } from "@/components/predictions/createVerifyColumn";
import { QuickHistoryStrip } from "@/components/layout/QuickHistoryStrip";
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

  // 1. Apex (Verify -> DNA -> Rest)
  const apexColumnsWithVerifyAndDna = useMemo(
    () => [
      createVerifyColumn<Over25ApexPick>(),
      createDnaColumn<Over25ApexPick>(dnaV2?.market_factors, "over25", date),
      ...apexColumns,
    ],
    [dnaV2, date]
  );

  // 2. Gold (Verify -> Rest)
  const goldColumnsWithVerify = useMemo(
    () => [createVerifyColumn<Over25GoldPick>(), ...goldColumns],
    []
  );

  // 3. Forecast (Verify -> Rest)
  const forecastColumnsWithVerify = useMemo(
    () => [createVerifyColumn<Over25ForecastPick>(), ...forecastColumns],
    []
  );

  // 4. Kill-Switch Stage 3 (Verify -> Rest)
  const stage3ColumnsWithVerify = useMemo(
    () => [createVerifyColumn<Over25Stage3Pick>(), ...stage3Columns],
    []
  );

  // 5. Psychology (Verify -> Rest)
  const psychologyColumnsWithVerify = useMemo(
    () => [createVerifyColumn<Over25PsychologyPick>(), ...psychologyColumns],
    []
  );

  // 6. Council Stage 2 (Verify -> Rest)
  const stage2ColumnsWithVerify = useMemo(
    () => [createVerifyColumn<Over25Stage2Pick>(), ...stage2Columns],
    []
  );

  // 7. Base Stage 1 (Verify -> Rest)
  const stage1ColumnsWithVerify = useMemo(
    () => [createVerifyColumn<Over25Stage1Pick>(), ...stage1Columns],
    []
  );

  return (
    <div
      data-embedded={embedded || undefined}
      className="flex flex-col gap-4 p-3.5 sm:p-5 md:p-6"
    >
      {/* ── 1. SLEEK COMPACT TOP BANNER ──────────────────────────────── */}
      <div className="glass flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-[#0c1220]/90 px-4 py-3 shadow-panel backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-accent-amber/30 bg-accent-amber/10 shadow-[0_0_12px_rgba(245,158,11,0.2)]">
            <TrendingUp className="h-4 w-4 text-accent-amber" />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-text-primary">
              Over 2.5 Intelligence
            </h1>
            <p className="text-[11px] text-text-secondary">
              Full 7-stage engine chain — Apex picks, gold flags, forecast &amp; kill-switch
            </p>
          </div>
        </div>
      </div>

      {/* ── 2. 5-DAY HISTORY AUDIT STRIP ─────────────────────────────── */}
      <QuickHistoryStrip />

      {/* ── 3. STAGE 1: Over 2.5 Apex ────────────────────────────────── */}
      <div>
        <ChainStage
          title="Over 2.5 Apex — Final Aggregator"
          description="Elite output"
          fetcher={() => over25Api.getApex(date)}
          deps={[date]}
          columns={apexColumnsWithVerifyAndDna}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No apex picks for this date."
          fallbackData={MOCK_O25_APEX}
        />
      </div>

      {/* ── 4. STAGE 2: Over 2.5 Gold ────────────────────────────────── */}
      <div>
        <ChainStage
          title="Over 2.5 Gold"
          description="100%-flag gold engine"
          fetcher={() => over25Api.getGold(date)}
          deps={[date]}
          columns={goldColumnsWithVerify}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No gold picks for this date."
          fallbackData={MOCK_O25_GOLD}
        />
      </div>

      {/* ── 5. STAGE 3: Over 2.5 Forecast ────────────────────────────── */}
      <div>
        <ChainStage
          title="Over 2.5 Forecast"
          description="Forecast layer"
          fetcher={() => over25Api.getForecast(date)}
          deps={[date]}
          columns={forecastColumnsWithVerify}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No forecast picks for this date."
          fallbackData={MOCK_O25_FORECAST}
        />
      </div>

      {/* ── 6. STAGE 4: Over 2.5 Kill-Switch (Stage 3) ────────────────── */}
      <div>
        <ChainStage
          title="Over 2.5 Kill-Switch (Stage 3)"
          description="Failure-audited grading"
          fetcher={() => over25Api.getStage3(date)}
          deps={[date]}
          columns={stage3ColumnsWithVerify}
          rowKey={(r, i) => `${r.Match}-${i}`}
          emptyMessage="No stage 3 picks for this date."
          fallbackData={MOCK_O25_S3}
        />
      </div>

      {/* ── 7. STAGE 5: Over 2.5 Psychology ──────────────────────────── */}
      <div>
        <ChainStage
          title="Over 2.5 Psychology"
          description="Psychology layer"
          fetcher={() => over25Api.getPsychology(date)}
          deps={[date]}
          columns={psychologyColumnsWithVerify}
          rowKey={(r, i) => `${r.Fixture}-${i}`}
          emptyMessage="No psychology audits for this date."
          fallbackData={MOCK_O25_PSYCH}
        />
      </div>

      {/* ── 8. STAGE 6: Over 2.5 Council (Stage 2) ───────────────────── */}
      <div>
        <ChainStage
          title="Over 2.5 Council (Stage 2)"
          description="Multi-algorithm voting"
          fetcher={() => over25Api.getStage2(date)}
          deps={[date]}
          columns={stage2ColumnsWithVerify}
          rowKey={(r, i) => `${r.id}-${i}`}
          emptyMessage="No stage 2 picks for this date."
          fallbackData={MOCK_O25_S2}
        />
      </div>

      {/* ── 9. STAGE 7: Over 2.5 Probabilistic Base (Stage 1) ─────────── */}
      <div>
        <ChainStage
          title="Over 2.5 Probabilistic Base (Stage 1)"
          description="Foundation base"
          fetcher={() => over25Api.getStage1(date)}
          deps={[date]}
          columns={stage1ColumnsWithVerify}
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
