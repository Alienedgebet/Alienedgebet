"use client";

import { useMemo } from "react";
import { Hourglass } from "lucide-react";
import { specialsApi, type FHVIPick } from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
import { createVerifyColumn } from "@/components/predictions/createVerifyColumn";
import { QuickHistoryStrip } from "@/components/layout/QuickHistoryStrip";
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

  // Verify -> Fixture -> Rest
  const columnsWithVerify = useMemo(
    () => [createVerifyColumn<FHVIPick>(), ...columns],
    []
  );

  return (
    <div className="flex flex-col gap-4 p-3.5 sm:p-5 md:p-6">
      {/* ── 1. SLEEK COMPACT TOP BANNER ──────────────────────────────── */}
      <div className="glass flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-[#0c1220]/90 px-4 py-3 shadow-panel backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-accent-indigo/30 bg-accent-indigo/10 shadow-[0_0_12px_rgba(99,102,241,0.2)]">
            <Hourglass className="h-4 w-4 text-accent-indigo" />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-text-primary">
              First Half Volatility Intelligence
            </h1>
            <p className="text-[11px] text-text-secondary">
              Single-code special — First Half Volatility Index (FHVI) streak miner
            </p>
          </div>
        </div>
      </div>

      {/* ── 2. 5-DAY HISTORY AUDIT STRIP ─────────────────────────────── */}
      <QuickHistoryStrip />

      {/* ── 3. FHVI STREAK MINER TABLE ───────────────────────────────── */}
      <div>
        <ChainStage
          title="FHVI Streak Miner"
          description="Foundation base"
          fetcher={() => specialsApi.getFHVI(date)}
          deps={[date]}
          columns={columnsWithVerify}
          rowKey={(r, i) => `${r.fixture}-${i}`}
          emptyMessage="No FHVI picks for this date."
          fallbackData={MOCK_FHVI}
        />
      </div>
    </div>
  );
}
