"use client";

import { useMemo } from "react";
import { Zap } from "lucide-react";
import {
  ggApi,
  type GGForensicPick,
  type GGO15Pick,
  type GGPrecisionPick,
  type GGSupremePick,
} from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
import { useApi } from "@/lib/use-api";
import { useDnaV2 } from "@/lib/use-dna-v2";
import { createDnaColumn } from "@/components/dna/DnaCountBadge";
import { createVerifyColumn } from "@/components/predictions/createVerifyColumn";
import { createIntelligentPassColumn } from "@/components/predictions/IntelligentPassColumn";
import { QuickHistoryStrip } from "@/components/layout/QuickHistoryStrip";
import {
  ChainBranch,
  ChainStage,
  ProbCell,
  TierBadge,
  type PredictionColumn,
} from "@/components/predictions";
import {
  MOCK_GG_FORENSICS,
  MOCK_GG_PRECISION,
  MOCK_GG_SUPREME,
} from "@/lib/mock-chains";
import { FixtureRiskTag } from "@/components/FixtureRiskTag";

const supremeColumns: PredictionColumn<GGSupremePick>[] = [
  {
    key: "Fixture",
    header: "Fixture",
    render: (r) => (
      <FixtureRiskTag row={r} label={r.Fixture} className="font-medium text-text-primary" />
    ),
  },
  {
    key: "Category",
    header: "Category",
    render: (r) => <TierBadge tier={r.Category} />,
  },
  {
    key: "Cat_Priority",
    header: "Cat_Priority",
    align: "right",
    render: (r) => r.Cat_Priority,
  },
  {
    key: "Monte_GG_Prob",
    header: "Monte_GG_Prob",
    render: (r) => <ProbCell value={r.Monte_GG_Prob} showBar={false} />,
  },
  {
    key: "NGG_Risk",
    header: "NGG_Risk",
    align: "right",
    render: (r) => r.NGG_Risk,
  },
  {
    key: "Base_Marks",
    header: "Base_Marks",
    className: "max-w-[160px] truncate",
    render: (r) => r.Base_Marks || "—",
  },
  {
    key: "DNA_Status",
    header: "DNA_Status",
    render: (r) => r.DNA_Status,
  },
  {
    key: "Psych_Score",
    header: "Psych_Score",
    align: "right",
    render: (r) => String(r.Psych_Score),
  },
  {
    key: "Psych_Triggers",
    header: "Psych_Triggers",
    className: "max-w-[200px] truncate",
    render: (r) => r.Psych_Triggers || "—",
  },
  { key: "VIP_Status", header: "VIP_Status", render: (r) => r.VIP_Status },
  {
    key: "Veto_Status",
    header: "Veto_Status",
    render: (r) => (
      <span
        className={
          r.Veto_Status && r.Veto_Status !== "None"
            ? "text-accent-red"
            : "text-text-dim"
        }
      >
        {r.Veto_Status || "—"}
      </span>
    ),
  },
  {
    key: "Spears",
    header: "Spears",
    className: "max-w-[200px] truncate",
    render: (r) => r.Spears || "—",
  },
];

const forensicsColumns: PredictionColumn<GGForensicPick>[] = [
  {
    key: "league_id",
    header: "league_id",
    render: (r) => <FixtureRiskTag row={r} label={r.league_id} className="font-mono text-2xs" />,
  },
  {
    key: "Fixture",
    header: "Fixture",
    render: (r) => (
      <FixtureRiskTag row={r} label={r.Fixture} className="font-medium text-text-primary" />
    ),
  },
  { key: "Score", header: "Score", render: (r) => r.Score },
  {
    key: "DNA_Intelligence",
    header: "DNA_Intelligence",
    render: (r) => r.DNA_Intelligence,
  },
  {
    key: "Poisson%",
    header: "Poisson%",
    render: (r) => <ProbCell value={r["Poisson%"]} showBar={false} />,
  },
  { key: "H2H_GG", header: "H2H_GG", render: (r) => r.H2H_GG },
  {
    key: "DNA_Insight",
    header: "DNA_Insight",
    className: "max-w-[180px] truncate",
    render: (r) => r.DNA_Insight,
  },
  { key: "Ranks", header: "Ranks", render: (r) => r.Ranks },
  {
    key: "Forensic_Audit",
    header: "Forensic_Audit",
    className: "max-w-[220px] truncate",
    render: (r) => r.Forensic_Audit,
  },
];

const ggColumns: PredictionColumn<GGPrecisionPick>[] = [
  {
    key: "fixture",
    header: "fixture",
    render: (r) => (
      <FixtureRiskTag row={r} label={r.fixture} className="font-medium text-text-primary" />
    ),
  },
  { key: "home_team", header: "home_team", render: (r) => <FixtureRiskTag row={r} label={r.home_team} /> },
  { key: "away_team", header: "away_team", render: (r) => <FixtureRiskTag row={r} label={r.away_team} /> },
  { key: "gg_tier", header: "gg_tier", render: (r) => <TierBadge tier={r.gg_tier} /> },
  { key: "gg_score", header: "gg_score", align: "right", render: (r) => r.gg_score },
  { key: "gg_signals_fired", header: "gg_signals_fired", align: "right", render: (r) => r.gg_signals_fired },
  { key: "mc_btts_prob", header: "mc_btts_prob", render: (r) => <ProbCell value={r.mc_btts_prob * 100} showBar={false} /> },
  { key: "venue_btts_combined", header: "venue_btts_combined", align: "right", render: (r) => r.venue_btts_combined },
  { key: "h2h_btts_rate", header: "h2h_btts_rate", align: "right", render: (r) => r.h2h_btts_rate },
  { key: "home_gk_liable", header: "Home GK Wall Liable", render: (r) => (r.home_gk_liable ? "Yes" : "No") },
  { key: "away_gk_liable", header: "Away GK Wall Liable", render: (r) => (r.away_gk_liable ? "Yes" : "No") },
  { key: "home_gk_cpg", header: "Home GK Wall", align: "right", render: (r) => r.home_gk_cpg.toFixed(2) },
  { key: "away_gk_cpg", header: "Away GK Wall", align: "right", render: (r) => r.away_gk_cpg.toFixed(2) },
  { key: "sig1_mc_btts", header: "sig1_mc_btts", align: "right", render: (r) => r.sig1_mc_btts },
  { key: "sig2_venue_btts", header: "sig2_venue_btts", align: "right", render: (r) => r.sig2_venue_btts },
  { key: "sig3_gk_vuln", header: "sig3_gk_vuln", align: "right", render: (r) => r.sig3_gk_vuln },
  { key: "sig4_h2h_btts", header: "sig4_h2h_btts", align: "right", render: (r) => r.sig4_h2h_btts },
  { key: "sig5_directional", header: "sig5_directional", align: "right", render: (r) => r.sig5_directional },
  { key: "home_gk_note", header: "Home GK Note", className: "max-w-[160px] truncate", render: (r) => r.home_gk_note || "—" },
  { key: "away_gk_note", header: "Away GK Note", className: "max-w-[160px] truncate", render: (r) => r.away_gk_note || "—" },
  { key: "lambda_home", header: "lambda_home", align: "right", render: (r) => r.lambda_home },
  { key: "lambda_away", header: "lambda_away", align: "right", render: (r) => r.lambda_away },
  { key: "fatigue_home", header: "Home Fatigue", align: "right", render: (r) => r.fatigue_home.toFixed(2) },
  { key: "fatigue_away", header: "Away Fatigue", align: "right", render: (r) => r.fatigue_away.toFixed(2) },
  { key: "league_weight", header: "league_weight", align: "right", render: (r) => r.league_weight },
];

const o15Columns: PredictionColumn<GGO15Pick>[] = [
  { key: "fixture", header: "fixture", render: (r) => <FixtureRiskTag row={r} label={r.fixture} className="font-medium text-text-primary" /> },
  { key: "home_team", header: "home_team", render: (r) => <FixtureRiskTag row={r} label={r.home_team} /> },
  { key: "away_team", header: "away_team", render: (r) => <FixtureRiskTag row={r} label={r.away_team} /> },
  { key: "o15_tier", header: "o15_tier", render: (r) => <TierBadge tier={r.o15_tier} /> },
  { key: "o15_score", header: "o15_score", align: "right", render: (r) => r.o15_score },
  { key: "combined_lambda", header: "combined_lambda", align: "right", render: (r) => Number(r.combined_lambda).toFixed(2) },
  { key: "mc_over15_prob", header: "mc_over15_prob", render: (r) => <ProbCell value={r.mc_over15_prob * 100} showBar={false} /> },
  { key: "combined_venue_goals_avg", header: "combined_venue_goals_avg", align: "right", render: (r) => Number(r.combined_venue_goals_avg).toFixed(2) },
  { key: "venue_goals_avg_home", header: "venue_goals_avg_home", align: "right", render: (r) => Number(r.venue_goals_avg_home).toFixed(2) },
  { key: "venue_goals_avg_away", header: "venue_goals_avg_away", align: "right", render: (r) => Number(r.venue_goals_avg_away).toFixed(2) },
  { key: "league_weight", header: "league_weight", align: "right", render: (r) => r.league_weight ?? "—" },
  { key: "sig1_combined_lambda", header: "sig1_combined_lambda", align: "right", render: (r) => r.sig1_combined_lambda },
  { key: "sig2_mc_over15", header: "sig2_mc_over15", align: "right", render: (r) => r.sig2_mc_over15 },
  { key: "sig3_venue_goals_avg", header: "sig3_venue_goals_avg", align: "right", render: (r) => r.sig3_venue_goals_avg },
  { key: "sig4_league_weight", header: "sig4_league_weight", align: "right", render: (r) => r.sig4_league_weight },
  { key: "sig5_fatigue_penalty", header: "Fatigue Penalty", align: "right", render: (r) => r.sig5_fatigue_penalty },
  { key: "fatigue_home", header: "Home Fatigue", align: "right", render: (r) => r.fatigue_home.toFixed(2) },
  { key: "fatigue_away", header: "Away Fatigue", align: "right", render: (r) => r.fatigue_away.toFixed(2) },
];

export function GGMarketPanel({ embedded = false }: { embedded?: boolean }) {
  const { date } = useSelectedDate();
  const { data: dnaV2 } = useDnaV2();
  const precision = useApi(() => ggApi.getPrecision(date), [date], {
    fallback: MOCK_GG_PRECISION,
    cacheKey: `gg-precision:${date}`,
  });

  // 1. GG Supreme (Verify -> DNA -> Intelligent Pass Count -> Rest)
  const supremeColumnsWithVerifyAndDna = useMemo(
    () => [
      createVerifyColumn<GGSupremePick>(),
      createDnaColumn<GGSupremePick>(dnaV2?.market_factors, "gg", date),
      createIntelligentPassColumn<GGSupremePick>({
        market: "gg",
        getTeam: (r) => (r as { team_name?: string }).team_name,
        getLabel: (r) => r.Fixture,
        date,
      }),
      ...supremeColumns,
    ],
    [dnaV2, date]
  );

  // 2. Over 1.5 Precision (Verify -> DNA -> Intelligent Pass Count -> Rest)
  const o15ColumnsWithVerifyAndDna = useMemo(
    () => [
      createVerifyColumn<GGO15Pick>(),
      createDnaColumn<GGO15Pick>(dnaV2?.market_factors, "over15", date),
      createIntelligentPassColumn<GGO15Pick>({
        market: "gg_o15",
        getLabel: (r) => r.fixture,
        date,
      }),
      ...o15Columns,
    ],
    [dnaV2, date]
  );

  // 3. GG Forensics (Verify -> Rest)
  const forensicsColumnsWithVerify = useMemo(
    () => [createVerifyColumn<GGForensicPick>(), ...forensicsColumns],
    []
  );

  // 5. GG Precision BTTS Head (Verify -> Intelligent Pass Count -> Rest)
  const ggColumnsWithVerify = useMemo(
    () => [
      createVerifyColumn<GGPrecisionPick>(),
      createIntelligentPassColumn<GGPrecisionPick>({
        market: "gg_precision",
        getLabel: (r) => r.fixture,
        date,
      }),
      ...ggColumns,
    ],
    [date]
  );

  const live = precision.data;
  const precisionPayload = live;
  const precisionIsMock = precision.isMock;

  return (
    <div
      data-embedded={embedded || undefined}
      className="flex flex-col gap-4 p-3.5 sm:p-5 md:p-6"
    >
      {/* ── 1. COMPACT SLEEK TOP BANNER ──────────────────────────────── */}
      <div className="glass flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-[#0c1220]/90 px-4 py-3 shadow-panel backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-accent-cyan/30 bg-accent-cyan/10 shadow-[0_0_12px_rgba(6,182,212,0.2)]">
            <Zap className="h-4 w-4 text-accent-cyan" />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-text-primary">
              GG / BTTS Intelligence
            </h1>
            <p className="text-[11px] text-text-secondary">
              Multi-stage BTTS engine — Supreme picks, forensic DNA audit &amp; precision twin-head
            </p>
          </div>
        </div>
      </div>

      {/* ── 2. 5-DAY HISTORY AUDIT STRIP ─────────────────────────────── */}
      <QuickHistoryStrip />

      {/* ── 3. STAGE 1: GG Supreme ───────────────────────────────────── */}
      <div>
        <ChainStage
          title="GG Intelligence"
          description="Top-of-chain picks after full 3-stage GG audit"
          fetcher={() => ggApi.getSupreme(date)}
          deps={[date]}
          columns={supremeColumnsWithVerifyAndDna}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No supreme picks for this date."
          fallbackData={MOCK_GG_SUPREME}
        />
      </div>

      {/* ── 4. STAGE 2: GG Forensics ─────────────────────────────────── */}
      <div>
        <ChainStage
          title="GG Forensics"
          description="DNA intelligence, Poisson%, H2H BTTS rates, forensic verdict"
          fetcher={() => ggApi.getForensics(date)}
          deps={[date]}
          columns={forensicsColumnsWithVerify}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No forensic picks for this date."
          fallbackData={MOCK_GG_FORENSICS}
        />
      </div>

      {/* ── 6. STAGE 4: GG Precision BTTS Head ───────────────────────── */}
      <div>
        <ChainBranch
          title="GG Precision"
          description={
            precisionIsMock
              ? "GG precision engine — Poisson, venue BTTS, GK vulnerability · Demo"
              : "GG precision engine — Poisson, venue BTTS, GK vulnerability"
          }
          data={precisionPayload?.gg ?? []}
          loading={precision.loading}
          error={precision.error}
          columns={ggColumnsWithVerify}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No GG precision picks for this date."
        />
      </div>

      {/* ── 7. STAGE 5: Over 1.5 Precision Twin Head ─────────────────── */}
      <div>
        <ChainBranch
          title="GG Over 1.5"
          description={
            precisionIsMock
              ? "Over 1.5 precision — lambda, venue goals avg, fatigue · Demo"
              : "Over 1.5 precision — lambda, venue goals avg, fatigue"
          }
          data={precisionPayload?.o15 ?? []}
          loading={precision.loading}
          error={precision.error}
          columns={o15ColumnsWithVerifyAndDna}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No Over 1.5 precision picks for this date."
        />
      </div>

    </div>
  );
}

export default function GGPage() {
  return <GGMarketPanel />;
}
