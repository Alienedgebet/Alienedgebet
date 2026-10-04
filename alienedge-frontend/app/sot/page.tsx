"use client";

import { useMemo, useState } from "react";
import type { AxiosResponse } from "axios";
import { Crosshair } from "lucide-react";
import { specialsApi, type SOTPick } from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
import { createVerifyColumn } from "@/components/predictions/createVerifyColumn";
import { createIntelligentPassColumn } from "@/components/predictions/IntelligentPassColumn";
import { SignalRankToggle } from "@/components/predictions/SignalRankToggle";
import { sortSOT } from "@/lib/signal-ranking";
import { useDnaV2 } from "@/lib/use-dna-v2";
import {
  createPickStatsColumn,
  splitFixtureTeams,
} from "@/components/dna/PickStatsCell";
import { QuickHistoryStrip } from "@/components/layout/QuickHistoryStrip";
import { ChainStage, TierBadge, ProbCell, type PredictionColumn } from "@/components/predictions";
import { MOCK_SOT } from "@/lib/mock-chains";
import { FixtureRiskTag } from "@/components/FixtureRiskTag";
import { VERIFY_REFRESH_MS } from "@/lib/use-api";

const columns: PredictionColumn<SOTPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <FixtureRiskTag row={r} label={r.Fixture} className="font-medium text-text-primary" />,
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
  // (2026-10-04) Added for the Stats column: one call already used by the other
  // pick pages, delivering both teams' last-five form.
  const { data: dnaV2 } = useDnaV2();
  // Default ON: this is the one ordering the backtest actually supports
  // (Consistency >= 48 AND Proj_SOT >= 9.3 -> 96.1% over 51 settled rows,
  // p = 0.00136, surviving a Bonferroni correction). See
  // lib/signal-ranking.ts for the full numbers and how to re-check them.
  const [smartRank, setSmartRank] = useState(true);

  const fetchSOT = useMemo(
    () => async (): Promise<AxiosResponse<SOTPick[]>> => {
      const response = await specialsApi.getSOT(date);
      if (smartRank && Array.isArray(response.data)) {
        // Rebind .data rather than spreading the response: spreading widens
        // the type to a fresh object literal and breaks the ChainStage
        // fetcher contract.
        response.data = sortSOT(response.data);
      }
      return response;
    },
    [date, smartRank]
  );

  // Verify -> Stats -> Intelligent Pass Count -> Fixture -> Rest
  // Stats (2026-10-04): last-five form + H2H history on demand. SOT rows carry
  // no fixture_id, so form resolves by team name and H2H reports that it could
  // not be checked — which the panel words differently from "never met".
  const columnsWithVerify = useMemo(
    () => [
      createVerifyColumn<SOTPick>(),
      createPickStatsColumn<SOTPick>({
        dna: dnaV2,
        date,
        getFixtureId: (r) => r.fixture_id,
        getHomeTeam: (r) => splitFixtureTeams(r.Fixture).home,
        getAwayTeam: (r) => splitFixtureTeams(r.Fixture).away,
      }),
      createIntelligentPassColumn<SOTPick>({
        market: "sot",
        getLabel: (r) => r.Fixture,
        date,
      }),
      ...columns,
    ],
    [date, dnaV2]
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
        <SignalRankToggle
          active={smartRank}
          onChange={setSmartRank}
          activeLabel="Smart rank"
          inactiveLabel="As served"
          help="Picks the backtested combination to the top: Consistency >= 48 AND Proj_SOT >= 9.3 (49/51 = 96.1% vs 81.5% baseline, p = 0.00136). Re-check with: python3 signal_backtest.py --market sot"
        />
      </div>

      {/* ── 2. 5-DAY HISTORY AUDIT STRIP ─────────────────────────────── */}
      <QuickHistoryStrip />

      {/* ── 3. SHORT ON TARGET OVER 6.5+ TABLE ───────────────────────── */}
      <div>
        <ChainStage
          title="Short On Target Over 6.5+"
          description="Foundation base"
          fetcher={fetchSOT}
          deps={[date, smartRank]}
          columns={columnsWithVerify}
          rowKey={(r, i) => `${r.Fixture}-${i}`}
          emptyMessage="No S.O.T. picks for this date."
          fallbackData={MOCK_SOT}
          refreshMs={VERIFY_REFRESH_MS}
        />
      </div>
    </div>
  );
}
