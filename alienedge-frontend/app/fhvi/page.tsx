"use client";

import { Hourglass } from "lucide-react";
import { specialsApi, type FHVIPick } from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
import { ChainStage, TierBadge, ScoreBar, type PredictionColumn } from "@/components/predictions";
import { MOCK_FHVI } from "@/lib/mock-chains";

const columns: PredictionColumn<FHVIPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <span className="font-medium text-text-primary">{r.fixture}</span>,
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

export default function FHVIPage() {
  const { date } = useSelectedDate();

  return (
    <div className="flex flex-col gap-4 p-6">
      <div className="glass flex items-center gap-3 rounded-lg p-4 shadow-panel">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-indigo/15">
          <Hourglass className="h-5 w-5 text-accent-indigo" />
        </div>
        <div>
          <h1 className="text-base font-bold text-text-primary">First Half Volatility Intelligence</h1>
          <p className="text-xs text-text-secondary">
            Single-code special — the First Half Volatility Index streak miner, one head, no
            psychology/aggregator siblings.
          </p>
        </div>
      </div>

      <div>
        <ChainStage
          title="FHVI Streak Miner"
          description="Foundation base"
          fetcher={() => specialsApi.getFHVI(date)}
          deps={[date]}
          columns={columns}
          rowKey={(r, i) => `${r.fixture}-${i}`}
          emptyMessage="No FHVI picks for this date."
          fallbackData={MOCK_FHVI}
        />
      </div>
    </div>
  );
}
