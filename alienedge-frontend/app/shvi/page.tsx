"use client";

import { useMemo } from "react";
import { TimerReset } from "lucide-react";
import {
  specialsApi,
  shMasterApi,
  type SHVIPick,
  type SHGGWinnerPick,
  type SHMasterPick,
  type SH8GoalPick,
} from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
import { createVerifyColumn } from "@/components/predictions/createVerifyColumn";
import { QuickHistoryStrip } from "@/components/layout/QuickHistoryStrip";
import { ChainStage, TierBadge, ScoreBar, type PredictionColumn } from "@/components/predictions";
import { MOCK_SH_8GOAL, MOCK_SH_GG, MOCK_SH_MASTER, MOCK_SHVI } from "@/lib/mock-chains";

const shviColumns: PredictionColumn<SHVIPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <span className="font-medium text-text-primary">{r.fixture}</span>,
  },
  { key: "country", header: "Country", render: (r) => r.country },
  { key: "category", header: "Category", render: (r) => <TierBadge tier={r.Category} /> },
  { key: "label", header: "SHVI Label", render: (r) => r.shvi_label },
  {
    key: "score",
    header: "SHVI Score",
    render: (r) => (
      <div className="flex flex-col gap-1">
        <span className="font-mono text-xs text-text-primary">{r.shvi_score.toFixed(1)}</span>
        <ScoreBar score={r.shvi_score} max={100} height={2.5} />
      </div>
    ),
  },
  { key: "pressure", header: "SH Pressure", align: "right", render: (r) => r.sh_pressure },
  { key: "comb_sh", header: "Comb SH Rate", align: "right", render: (r) => r.comb_sh_r },
  { key: "fh_avg", header: "Avg FH Goals", align: "right", render: (r) => r.avg_fh_goals },
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

const shGGWinnerColumns: PredictionColumn<SHGGWinnerPick>[] = [
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
    key: "labels",
    header: "Pick Labels",
    className: "max-w-[220px]",
    render: (r) => (
      <div className="flex flex-wrap gap-1 text-2xs">
        {r.pick_labels.map((l) => (
          <span key={l} className="rounded border border-accent-cyan/25 bg-accent-cyan/10 px-1 py-0.5 text-accent-cyan">
            {l}
          </span>
        ))}
      </div>
    ),
  },
  {
    key: "rates",
    header: "2H Rate (H/A)",
    align: "right",
    render: (r) => `${r.metrics.home_2h_rate} / ${r.metrics.away_2h_rate}`,
  },
  { key: "h2h", header: "H2H Analyzed", align: "right", render: (r) => r.metrics.h2h_matches_analyzed },
];

const shMasterColumns: PredictionColumn<SHMasterPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <span className="font-medium text-text-primary">{r.fixture}</span>,
  },
  { key: "league", header: "League", render: (r) => r.league },
  { key: "score", header: "SHVI Score", align: "right", render: (r) => r.shvi_score.toFixed(1) },
  { key: "pressure", header: "SH Pressure", align: "right", render: (r) => r.sh_pressure },
  { key: "rate", header: "SH Scoring Rate", render: (r) => r.sh_scoring_rate },
  { key: "fh_avg", header: "Avg FH Goals", align: "right", render: (r) => r.avg_fh_goals },
  { key: "late", header: "Late Threat", render: (r) => r.late_threat },
  {
    key: "half_scores",
    header: "HT → FT",
    render: (r) => (
      <span className="font-mono">
        {r.ht} → {r.ft}
      </span>
    ),
  },
];

const sh8GoalColumns: PredictionColumn<SH8GoalPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <span className="font-medium text-text-primary">{r.Fixture}</span>,
  },
  { key: "league", header: "League", render: (r) => r.League },
  { key: "time", header: "Time", render: (r) => r.Time },
  {
    key: "goals",
    header: "Goals L5 (H/A)",
    align: "right",
    render: (r) => `${r.H_Goals_L5} / ${r.A_Goals_L5}`,
  },
  {
    key: "labels",
    header: "Labels",
    className: "max-w-[200px] truncate",
    render: (r) => r.Labels,
  },
  { key: "status", header: "Status", render: (r) => <TierBadge tier={r.Status} /> },
];

export default function SHVIPage() {
  const { date } = useSelectedDate();

  // 1. SHVI Streak Miner (Verify -> Rest)
  const shviColumnsWithVerify = useMemo(
    () => [createVerifyColumn<SHVIPick>(), ...shviColumns],
    []
  );

  // 2. SH-GG Winner (Verify -> Rest)
  const shGGWinnerColumnsWithVerify = useMemo(
    () => [createVerifyColumn<SHGGWinnerPick>(), ...shGGWinnerColumns],
    []
  );

  // 3. SH Master Vortex (Verify -> Rest)
  const shMasterColumnsWithVerify = useMemo(
    () => [createVerifyColumn<SHMasterPick>(), ...shMasterColumns],
    []
  );

  // 4. SH 8-Goal Aggregator (Verify -> Rest)
  const sh8GoalColumnsWithVerify = useMemo(
    () => [createVerifyColumn<SH8GoalPick>(), ...sh8GoalColumns],
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
            <TimerReset className="h-4 w-4 text-accent-cyan" />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-text-primary">
              Second Half Volatility Intelligence
            </h1>
            <p className="text-[11px] text-text-secondary">
              SHVI streak miner plus SH Master supplementary panels (SH-GG, Vortex &amp; 8-Goal)
            </p>
          </div>
        </div>
      </div>

      {/* ── 2. 5-DAY HISTORY AUDIT STRIP ─────────────────────────────── */}
      <QuickHistoryStrip />

      {/* ── 3. STAGE 1: SHVI Streak Miner ────────────────────────────── */}
      <div>
        <ChainStage
          title="SHVI Streak Miner"
          description="Foundation base"
          fetcher={() => specialsApi.getSHVI(date)}
          deps={[date]}
          columns={shviColumnsWithVerify}
          rowKey={(r, i) => `${r.fixture}-${i}`}
          emptyMessage="No SHVI picks for this date."
          fallbackData={MOCK_SHVI}
        />
      </div>

      {/* ── 4. STAGE 2: SH-GG Winner ─────────────────────────────────── */}
      <div>
        <ChainStage
          title="SH-GG Winner"
          description="SH Master supplementary panel"
          fetcher={() => shMasterApi.getSHGGWinner(date)}
          deps={[date]}
          columns={shGGWinnerColumnsWithVerify}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No SH-GG winner picks for this date."
          fallbackData={MOCK_SH_GG}
        />
      </div>

      {/* ── 5. STAGE 3: SH Master Vortex ─────────────────────────────── */}
      <div>
        <ChainStage
          title="SH Master Vortex"
          description="SH Master supplementary panel"
          fetcher={() => shMasterApi.getSHMaster(date)}
          deps={[date]}
          columns={shMasterColumnsWithVerify}
          rowKey={(r, i) => `${r.fixture}-${i}`}
          emptyMessage="No SH Master picks for this date."
          fallbackData={MOCK_SH_MASTER}
        />
      </div>

      {/* ── 6. STAGE 4: SH 8-Goal Aggregator ─────────────────────────── */}
      <div>
        <ChainStage
          title="SH 8-Goal Aggregator"
          description="SH Master supplementary panel"
          fetcher={() => shMasterApi.getSH8Goal(date)}
          deps={[date]}
          columns={sh8GoalColumnsWithVerify}
          rowKey={(r, i) => `${r.Fixture_ID}-${i}`}
          emptyMessage="No SH 8-goal picks for this date."
          fallbackData={MOCK_SH_8GOAL}
        />
      </div>
    </div>
  );
}
