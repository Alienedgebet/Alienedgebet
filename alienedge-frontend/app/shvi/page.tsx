"use client";

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

  return (
    <div
      className="flex flex-col gap-4 p-6"
    >
      <div className="glass flex items-center gap-3 rounded-lg p-4 shadow-panel">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-cyan/15">
          <TimerReset className="h-5 w-5 text-accent-cyan" />
        </div>
        <div>
          <h1 className="text-base font-bold text-text-primary">Second Half Volatility Intelligence</h1>
          <p className="text-xs text-text-secondary">
            SHVI base stage plus the SH Master supplementary panels (SH-GG Winner, SH Master
            Vortex, SH 8-Goal Aggregator) — surfaced here rather than as a dashboard market card.
          </p>
        </div>
      </div>

      <div>
        <ChainStage
          title="SHVI Streak Miner"
          description="Foundation base"
          fetcher={() => specialsApi.getSHVI(date)}
          deps={[date]}
          columns={shviColumns}
          rowKey={(r, i) => `${r.fixture}-${i}`}
          emptyMessage="No SHVI picks for this date."
          fallbackData={MOCK_SHVI}
        />
      </div>

      <div>
        <ChainStage
          title="SH-GG Winner"
          description="SH Master supplementary panel"
          fetcher={() => shMasterApi.getSHGGWinner(date)}
          deps={[date]}
          columns={shGGWinnerColumns}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No SH-GG winner picks for this date."
          fallbackData={MOCK_SH_GG}
        />
      </div>

      <div>
        <ChainStage
          title="SH Master Vortex"
          description="SH Master supplementary panel"
          fetcher={() => shMasterApi.getSHMaster(date)}
          deps={[date]}
          columns={shMasterColumns}
          rowKey={(r, i) => `${r.fixture}-${i}`}
          emptyMessage="No SH Master picks for this date."
          fallbackData={MOCK_SH_MASTER}
        />
      </div>

      <div>
        <ChainStage
          title="SH 8-Goal Aggregator"
          description="SH Master supplementary panel"
          fetcher={() => shMasterApi.getSH8Goal(date)}
          deps={[date]}
          columns={sh8GoalColumns}
          rowKey={(r, i) => `${r.Fixture_ID}-${i}`}
          emptyMessage="No SH 8-goal picks for this date."
          fallbackData={MOCK_SH_8GOAL}
        />
      </div>
    </div>
  );
}
