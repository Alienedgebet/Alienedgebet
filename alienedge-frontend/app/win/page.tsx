"use client";

import { useMemo } from "react";
import { Trophy } from "lucide-react";
import {
  foundationApi,
  winApi,
  type DnaProfile,
  type WinApexPick,
  type WinForecastPick,
  type WinU2SPick,
} from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
import { useDnaV2 } from "@/lib/use-dna-v2";
import { createDnaColumn } from "@/components/dna/DnaCountBadge";
import { createVerifyColumn } from "@/components/predictions/createVerifyColumn";
import { createIntelligentPassColumn } from "@/components/predictions/IntelligentPassColumn";
import { QuickHistoryStrip } from "@/components/layout/QuickHistoryStrip";
import {
  ChainStage,
  ProbCell,
  TierBadge,
  type PredictionColumn,
} from "@/components/predictions";
import {
  MOCK_DNA,
  MOCK_WIN_APEX,
  MOCK_WIN_FORECAST,
  MOCK_WIN_U2S,
} from "@/lib/mock-chains";

// ============================================================
// Columns = exact backend return / printout keys
// ============================================================

const apexColumns: PredictionColumn<WinApexPick>[] = [
  {
    key: "Fixture",
    header: "Fixture",
    render: (r) => (
      <span className="font-medium text-text-primary">{r.Fixture}</span>
    ),
  },
  { key: "Target", header: "Target", render: (r) => r.Target },
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
    key: "Monte_Win_Prob",
    header: "Monte_Win_Prob",
    render: (r) => <ProbCell value={r.Monte_Win_Prob} showBar={false} />,
  },
  {
    key: "Monte_Draw_Prob",
    header: "Monte_Draw_Prob",
    align: "right",
    render: (r) => (
      <span className="font-mono text-text-muted">
        {Number(r.Monte_Draw_Prob).toFixed(1)}%
      </span>
    ),
  },
  {
    key: "Lambda_Detail",
    header: "Lambda_Detail",
    className: "max-w-[200px] truncate",
    render: (r) => r.Lambda_Detail,
  },
  {
    key: "Underdog_Risk",
    header: "Underdog_Risk",
    render: (r) => r.Underdog_Risk,
  },
  {
    key: "Psych_Score",
    header: "Psych_Score",
    align: "right",
    render: (r) => String(r.Psych_Score),
  },
  {
    key: "Psych_Logic",
    header: "Psych_Logic",
    className: "max-w-[220px] truncate",
    render: (r) => r.Psych_Logic || "—",
  },
  {
    key: "Chokehold_Status",
    header: "Chokehold_Status",
    render: (r) => r.Chokehold_Status || "—",
  },
  {
    key: "Veto_Reason",
    header: "Veto_Reason",
    className: "max-w-[200px] truncate",
    render: (r) => r.Veto_Reason || "—",
  },
];

const u2sColumns: PredictionColumn<WinU2SPick>[] = [
  {
    key: "Fixture",
    header: "Fixture",
    render: (r) => (
      <span className="font-medium text-text-primary">{r.Fixture}</span>
    ),
  },
  { key: "Underdog", header: "Underdog", render: (r) => r.Underdog },
  {
    key: "Audit_Verdict",
    header: "Audit_Verdict",
    render: (r) => r.Audit_Verdict,
  },
  {
    key: "Spear_Matchup",
    header: "Spear_Matchup",
    className: "max-w-[180px] truncate",
    render: (r) => r.Spear_Matchup,
  },
  {
    key: "Dog_Venue_SOT",
    header: "SOT Expectancy (Dog)",
    align: "right",
    render: (r) => r.Dog_Venue_SOT,
  },
  {
    key: "Fav_Venue_SOT",
    header: "SOT Expectancy (Fav)",
    align: "right",
    render: (r) => r.Fav_Venue_SOT,
  },
  {
    key: "Dog_H2H_SOT",
    header: "Dog H2H SOT",
    align: "right",
    render: (r) => String(r.Dog_H2H_SOT),
  },
  {
    key: "Fav_H2H_SOT",
    header: "Fav H2H SOT",
    align: "right",
    render: (r) => String(r.Fav_H2H_SOT),
  },
  {
    key: "Dog_Opp_Avg_Conceded",
    header: "Dog_Opp_Avg_Conceded",
    align: "right",
    render: (r) => String(r.Dog_Opp_Avg_Conceded),
  },
  {
    key: "Fav_Opp_Avg_Conceded",
    header: "Fav_Opp_Avg_Conceded",
    align: "right",
    render: (r) => String(r.Fav_Opp_Avg_Conceded),
  },
  {
    key: "Dog_Scoring_Consistency",
    header: "Dog_Scoring_Consistency",
    className: "max-w-[140px] truncate",
    render: (r) => r.Dog_Scoring_Consistency,
  },
  {
    key: "Psych_Score",
    header: "Psych_Score",
    align: "right",
    render: (r) => String(r.Psych_Score),
  },
  {
    key: "Tier",
    header: "Tier",
    render: (r) => <TierBadge tier={r.Tier} />,
  },
  {
    key: "Triggers",
    header: "Triggers",
    className: "max-w-[220px] truncate",
    render: (r) => r.Triggers || "—",
  },
];

const forecastColumns: PredictionColumn<WinForecastPick>[] = [
  {
    key: "fixture",
    header: "fixture",
    render: (r) => (
      <span className="font-medium text-text-primary">{r.fixture}</span>
    ),
  },
  { key: "side", header: "side", render: (r) => r.side },
  { key: "team_name", header: "team_name", render: (r) => r.team_name },
  {
    key: "poisson_win_prob",
    header: "poisson_win_prob",
    render: (r) => <ProbCell value={r.poisson_win_prob} showBar={false} />,
  },
  {
    key: "win_odds",
    header: "win_odds",
    align: "right",
    render: (r) => Number(r.win_odds).toFixed(2),
  },
  {
    key: "poisson_draw_prob",
    header: "poisson_draw_prob",
    align: "right",
    render: (r) => (
      <span className="font-mono text-text-muted">{r.poisson_draw_prob}</span>
    ),
  },
  {
    key: "last_5_wins_overall",
    header: "last_5_wins_overall",
    align: "right",
    render: (r) => r.last_5_wins_overall,
  },
  {
    key: "last_5_wins_at_venue",
    header: "last_5_wins_at_venue",
    align: "right",
    render: (r) => r.last_5_wins_at_venue,
  },
  {
    key: "last_5_goals_scored",
    header: "last_5_goals_scored",
    align: "right",
    render: (r) => r.last_5_goals_scored,
  },
  {
    key: "opp_last_5_goals_scored",
    header: "opp_last_5_goals_scored",
    align: "right",
    render: (r) => r.opp_last_5_goals_scored,
  },
  {
    key: "opp_last_5_losses",
    header: "opp_last_5_losses",
    align: "right",
    render: (r) => r.opp_last_5_losses,
  },
  {
    key: "opp_last_5_conceded_raw",
    header: "opp_last_5_conceded_raw",
    align: "right",
    render: (r) => r.opp_last_5_conceded_raw,
  },
  {
    key: "opp_no_clean_sheet_count",
    header: "opp_no_clean_sheet_count",
    align: "right",
    render: (r) => r.opp_no_clean_sheet_count,
  },
  {
    key: "h2h_wins_last_5",
    header: "h2h_wins_last_5",
    align: "right",
    render: (r) => r.h2h_wins_last_5,
  },
  {
    key: "last_3_no_draw_BOTH",
    header: "last_3_no_draw_BOTH",
    align: "right",
    render: (r) => (r.last_3_no_draw_BOTH ? "Yes" : "No"),
  },
  {
    key: "parity_score",
    header: "parity_score",
    align: "right",
    render: (r) => r.parity_score,
  },
  {
    key: "parity_even_count",
    header: "parity_even_count",
    align: "right",
    render: (r) => r.parity_even_count,
  },
];

const dnaColumns: PredictionColumn<DnaProfile>[] = [
  {
    key: "team_name",
    header: "Team",
    render: (r) => (
      <span className="font-medium text-text-primary">{r.team_name}</span>
    ),
  },
  { key: "Archetype", header: "Archetype", render: (r) => r.Archetype },
  {
    key: "Goal_Intent",
    header: "Goal Intent",
    align: "right",
    render: (r) => r.Market_Power_Scores.Goal_Intent.toFixed(1),
  },
  {
    key: "Win_Dominance",
    header: "Win Dominance",
    align: "right",
    render: (r) => r.Market_Power_Scores.Win_Dominance.toFixed(1),
  },
  {
    key: "BTTS_Friction",
    header: "BTTS Friction",
    align: "right",
    render: (r) => r.Market_Power_Scores.BTTS_Friction.toFixed(1),
  },
  {
    key: "Corner_Power",
    header: "Corner Power",
    align: "right",
    render: (r) => r.Market_Power_Scores.Corner_Power.toFixed(1),
  },
  {
    key: "Tempo",
    header: "Tempo",
    align: "right",
    render: (r) => r.Tactical_DNA.Tempo,
  },
  {
    key: "Line_Height",
    header: "Line Height",
    render: (r) => r.Tactical_DNA.Line_Height,
  },
];

export function WinMarketPanel({ embedded = false }: { embedded?: boolean }) {
  const { date } = useSelectedDate();
  const { data: dnaV2 } = useDnaV2();

  // 1. Win Apex (Verify -> DNA -> Intelligent Pass Count -> Rest)
  const apexColumnsWithVerifyAndDna = useMemo(
    () => [
      createVerifyColumn<WinApexPick>(),
      createDnaColumn<WinApexPick>(dnaV2?.market_factors, "win", date),
      createIntelligentPassColumn<WinApexPick>({
        market: "win",
        getTeam: (r) => r.Target,
        getLabel: (r) => r.Fixture,
        date,
      }),
      ...apexColumns,
    ],
    [dnaV2, date]
  );

  // 3. Underdog-to-Score (Verify -> Intelligent Pass Count -> Rest)
  const u2sColumnsWithVerify = useMemo(
    () => [
      createVerifyColumn<WinU2SPick>(),
      createIntelligentPassColumn<WinU2SPick>({
        market: "u2s",
        getTeam: (r) => r.Underdog,
        getLabel: (r) => r.Fixture,
        date,
      }),
      ...u2sColumns,
    ],
    [date]
  );

  // 4. Win Forecast (Verify -> Intelligent Pass Count -> Rest)
  const forecastColumnsWithVerify = useMemo(
    () => [
      createVerifyColumn<WinForecastPick>(),
      createIntelligentPassColumn<WinForecastPick>({
        market: "win",
        getTeam: (r) => r.team_name,
        getLabel: (r) => r.fixture,
        date,
      }),
      ...forecastColumns,
    ],
    [date]
  );

  return (
    <div
      data-embedded={embedded || undefined}
      className="flex flex-col gap-4 p-3.5 sm:p-5 md:p-6"
    >
      {/* Sleek Compact Top Banner */}
      <div className="glass flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-[#0c1220]/90 px-4 py-3 shadow-panel backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-accent-green/30 bg-accent-green/10 shadow-[0_0_12px_rgba(16,185,129,0.2)]">
            <Trophy className="h-4 w-4 text-accent-green" />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-text-primary">
              Win Intelligence
            </h1>
            <p className="text-[11px] text-text-secondary">
              Multi-stage win probability engine — Apex picks, U2S signal &amp; forecast data
            </p>
          </div>
        </div>
      </div>

      {/* 5-Day History Audit Strip */}
      <QuickHistoryStrip />

      {/* Stage 1: Win Intelligence */}
      <ChainStage
        title="Win Intelligence"
        description="Top-of-chain picks after full 3-stage audit"
        fetcher={() => winApi.getApex(date)}
        deps={[date]}
        columns={apexColumnsWithVerifyAndDna}
        rowKey={(r, i) => `${r.fixture_id}-${i}`}
        emptyMessage="No apex picks for this date."
        fallbackData={MOCK_WIN_APEX}
      />

      {/* Stage 2: DNA & Goal Intent Board */}
      <ChainStage
        title="DNA & Goal Intent Board"
        description="Tactical DNA scores: Goal Intent, Win Dominance, BTTS Friction, Corner Power"
        fetcher={() => foundationApi.getDNA(date)}
        deps={[date]}
        columns={dnaColumns}
        rowKey={(r, i) => `${r.team_id}-${i}`}
        emptyMessage="No DNA profiles for this date."
        fallbackData={MOCK_DNA}
      />

      {/* Stage 4: Underdog-to-Score Signal (U2S) */}
      <ChainStage
        title="Underdog-to-Score Signal (U2S)"
        description="Shots-on-target and scoring consistency analysis for underdog picks"
        fetcher={() => winApi.getU2S(date)}
        deps={[date]}
        columns={u2sColumnsWithVerify}
        rowKey={(r, i) => `${r.Fixture}-${i}`}
        emptyMessage="No U2S signals for this date."
        fallbackData={MOCK_WIN_U2S}
      />

      {/* Stage 5: Win Forecast */}
      <ChainStage
        title="Win Forecast"
        description="Poisson-ranked win probability with venue and H2H breakdown"
        fetcher={() => foundationApi.getWinForecast(date)}
        deps={[date]}
        columns={forecastColumnsWithVerify}
        rowKey={(r, i) => `${r.fixture_id}-${r.side}-${i}`}
        emptyMessage="No forecast data for this date."
        fallbackData={MOCK_WIN_FORECAST}
      />

    </div>
  );
}

export default function WinPage() {
  return <WinMarketPanel />;
}
