"use client";

import { useMemo } from "react";
import { Crosshair } from "lucide-react";
import { specialsApi, type SOTPick } from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
import { createVerifyColumn } from "@/components/predictions/createVerifyColumn";
import { QuickHistoryStrip } from "@/components/layout/QuickHistoryStrip";
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

  // Verify -> Fixture -> Rest
  const columnsWithVerify = useMemo(
    () => [createVerifyColumn<SOTPick>(), ...columns],
    []
  );

  return (
    <div className="flex flex-col gap-4 p-3.5 sm:p-5 md:p-6">
      {/* ── 1. SLEEK COMPACT TOP BANNER ──────────────────────────────── */}
      <div className="glass flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-[#0c1220]/90 px-4 py-3 shadow-panel backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-accent-amber/30 bg-accent-amber/10 shadow-[0_0_12px_rgba(245,158,11,0.2)]">
            <Crosshair className="h-4 w-4 text-accent-amber" />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-text-primary">
              Shots on Target Intelligence
            </h1>
            <p className="text-[11px] text-text-secondary">
              Single-code special — Cerberus S.O.T. engine expectancy &amp; Poisson probability
            </p>
          </div>
        </div>
      </div>

      {/* ── 2. 5-DAY HISTORY AUDIT STRIP ─────────────────────────────── */}
      <QuickHistoryStrip />

      {/* ── 3. CERBERUS S.O.T. ENGINE TABLE ──────────────────────────── */}
      <div>
        <ChainStage
          title="Cerberus S.O.T. Engine"
          description="Foundation base"
          fetcher={() => specialsApi.getSOT(date)}
          deps={[date]}
          columns={columnsWithVerify}
          rowKey={(r, i) => `${r.Fixture}-${i}`}
          emptyMessage="No S.O.T. picks for this date."
          fallbackData={MOCK_SOT}
        />
      </div>
    </div>
  );
}
