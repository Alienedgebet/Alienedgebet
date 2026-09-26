"use client";

import { useMemo } from "react";
import { TrendingUp } from "lucide-react";
import {
  over25Api,
  specialsApi,
  type Over25ApexPick,
  type Over25GoldPick,
  type Over25Stage2Pick,
  type FHVIPick,
} from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
import { useDnaV2 } from "@/lib/use-dna-v2";
import { createDnaColumn } from "@/components/dna/DnaCountBadge";
import { createIntelligentPassColumn } from "@/components/predictions/IntelligentPassColumn";
import { createVerifyColumn } from "@/components/predictions/createVerifyColumn";
import { QuickHistoryStrip } from "@/components/layout/QuickHistoryStrip";
import { ChainStage, TierBadge, ProbCell, ScoreBar, type PredictionColumn } from "@/components/predictions";
import {
  MOCK_O25_APEX,
  MOCK_O25_GOLD,
  MOCK_O25_S2,
  MOCK_FHVI,
} from "@/lib/mock-chains";
import { FixtureRiskTag } from "@/components/FixtureRiskTag";
import { VERIFY_REFRESH_MS } from "@/lib/use-api";

const apexColumns: PredictionColumn<Over25ApexPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <FixtureRiskTag row={r} label={r.Fixture} className="font-medium text-text-primary" />,
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

const stage2Columns: PredictionColumn<Over25Stage2Pick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <FixtureRiskTag row={r} label={r.fixture} className="font-medium text-text-primary" />,
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

const fhviColumns: PredictionColumn<FHVIPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <FixtureRiskTag row={r} label={r.fixture} className="font-medium text-text-primary" />,
  },
  { key: "country", header: "Country", render: (r) => r.country },
  { key: "category", header: "Category", render: (r) => <TierBadge tier={r.Category} /> },
  { key: "label", header: "FHVI Label", render: (r) => r.fhvi_label },
  {
    key: "score",
    header: "FHVI Score",
    render: (r) => (
      <div className="flex flex-col gap-1">
        <span className="font-mono text-xs text-text-primary">{r.fhvi_score.toFixed(1)}</span>
        <ScoreBar score={r.fhvi_score} max={100} height={2.5} />
      </div>
    ),
  },
  { key: "pressure", header: "FH Pressure", align: "right", render: (r) => r.fh_pressure },
  { key: "comb_fh", header: "Comb FH Rate", align: "right", render: (r) => r.comb_fh_r },
  { key: "sh_avg", header: "Avg SH Goals", align: "right", render: (r) => r.avg_sh_goals },
  {
    key: "half_scores",
    header: "HT → FT",
    render: (r) => (
      <span className="font-mono">
        {r.ht_score} → {r.ft_score}
      </span>
    ),
  },
];

export function Over25MarketPanel({ embedded = false }: { embedded?: boolean }) {
  const { date } = useSelectedDate();
  const { data: dnaV2 } = useDnaV2();

  // 1. Apex (Verify -> DNA -> Rest)
  const apexColumnsWithVerifyAndDna = useMemo(
    () => [
      createVerifyColumn<Over25ApexPick>(),
      createDnaColumn<Over25ApexPick>(dnaV2?.market_factors, "over25", date),
      createIntelligentPassColumn<Over25ApexPick>({
        market: "over25",
        getLabel: (r) => r.Fixture,
        date,
      }),
      ...apexColumns,
    ],
    [dnaV2, date]
  );

  // 2. Gold (Verify -> Rest)
  const goldColumnsWithVerify = useMemo(
    () => [createVerifyColumn<Over25GoldPick>(), ...goldColumns],
    []
  );

  // 6. Council Stage 2 (Verify -> Rest)
  const stage2ColumnsWithVerify = useMemo(
    () => [createVerifyColumn<Over25Stage2Pick>(), ...stage2Columns],
    []
  );

  // 4. FHVI duplicate display (Verify -> Intelligent Pass Count -> Rest)
  // Same live data source as the FHVI page (specialsApi.getFHVI) — a second
  // presentation of the same panel, titled Over 2.5 Intelligence 2.
  const fhviColumnsWithVerify = useMemo(
    () => [
      createVerifyColumn<FHVIPick>(),
      createIntelligentPassColumn<FHVIPick>({
        market: "fhvi",
        getLabel: (r) => r.fixture,
        date,
      }),
      ...fhviColumns,
    ],
    [date]
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
          title="Over 2.5 Intelligence 1"
          description="Elite output"
          fetcher={() => over25Api.getApex(date)}
          deps={[date]}
          columns={apexColumnsWithVerifyAndDna}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No apex picks for this date."
          fallbackData={MOCK_O25_APEX}
          refreshMs={VERIFY_REFRESH_MS}
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
          refreshMs={VERIFY_REFRESH_MS}
        />
      </div>

      {/* ── 5. STAGE 3: Over 2.5 Judges (Stage 2) ─────────────────────── */}
      <div>
        <ChainStage
          title="Over 2.5 Judges"
          description="Multi-algorithm voting"
          fetcher={() => over25Api.getStage2(date)}
          deps={[date]}
          columns={stage2ColumnsWithVerify}
          rowKey={(r, i) => `${r.id}-${i}`}
          emptyMessage="No stage 2 picks for this date."
          fallbackData={MOCK_O25_S2}
          refreshMs={VERIFY_REFRESH_MS}
        />
      </div>
      {/* ── 5. FHVI DUPLICATE DISPLAY: Over 2.5 Intelligence 2 ──────── */}
      <div>
        <ChainStage
          title="Over 2.5 Intelligence 2"
          description="First Half Volatility Intelligence — same live FHVI data source"
          fetcher={() => specialsApi.getFHVI(date)}
          deps={[date]}
          columns={fhviColumnsWithVerify}
          rowKey={(r, i) => `${r.fixture}-${i}`}
          emptyMessage="No FHVI picks for this date."
          fallbackData={MOCK_FHVI}
          refreshMs={VERIFY_REFRESH_MS}
        />
      </div>
    </div>
  );
}

export default function Over25Page() {
  return <Over25MarketPanel />;
}
