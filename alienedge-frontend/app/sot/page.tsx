"use client";

import { Crosshair } from "lucide-react";
import { specialsApi, type SOTPick } from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
import { ChainStage, TierBadge, ProbCell, type PredictionColumn } from "@/components/predictions";
import { MOCK_SOT } from "@/lib/mock-chains";

const columns: PredictionColumn<SOTPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <span className="font-medium text-text-primary">{r.Fixture}</span>,
  },
  { key: "verdict", header: "Verdict", render: (r) => <TierBadge tier={r.Verdict} /> },
  { key: "proj", header: "SOT Expectancy", align: "right", render: (r) => r.Proj_SOT },
  {
    key: "poisson",
    header: "Poisson Over 8.5",
    render: (r) => <ProbCell value={r["Poisson_Over_8.5"]} showBar={false} />,
  },
  { key: "consistency", header: "Consistency", render: (r) => r.Consistency },
  { key: "script", header: "Game Script", render: (r) => r.Game_Script },
  { key: "momentum", header: "Momentum", render: (r) => r.Momentum },
  { key: "odds", header: "1x2 Home Odd", align: "right", render: (r) => r["1x2_Home_Odd"] ?? "—" },
];

export default function SOTPage() {
  const { date } = useSelectedDate();

  return (
    <div className="flex flex-col gap-4 p-6">
      <div className="glass flex items-center gap-3 rounded-lg p-4 shadow-panel">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-amber/15">
          <Crosshair className="h-5 w-5 text-accent-amber" />
        </div>
        <div>
          <h1 className="text-base font-bold text-text-primary">Shots on Target Intelligence</h1>
          <p className="text-xs text-text-secondary">
            Single-code special — the Cerberus S.O.T. engine, one head, no psychology/aggregator
            siblings.
          </p>
        </div>
      </div>

      <div>
        <ChainStage
          title="Cerberus S.O.T. Engine"
          description="Foundation base"
          fetcher={() => specialsApi.getSOT(date)}
          deps={[date]}
          columns={columns}
          rowKey={(r, i) => `${r.Fixture}-${i}`}
          emptyMessage="No S.O.T. picks for this date."
          fallbackData={MOCK_SOT}
        />
      </div>
    </div>
  );
}
