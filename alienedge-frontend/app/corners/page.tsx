"use client";

import { useMemo } from "react";
import { CornerUpRight } from "lucide-react";
import {
  cornersApi,
  type CornerAggregatorPick,
  type CornerStage2Pick,
} from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
import { useDnaV2 } from "@/lib/use-dna-v2";
import { createDnaColumnByLabel } from "@/components/dna/DnaCountBadge";
import { createIntelligentPassColumn } from "@/components/predictions/IntelligentPassColumn";
import { createVerifyColumn } from "@/components/predictions/createVerifyColumn";
import { QuickHistoryStrip } from "@/components/layout/QuickHistoryStrip";
import { ChainStage, TierBadge, ProbCell, type PredictionColumn } from "@/components/predictions";
import {
  MOCK_CORNER_AGG,
  MOCK_CORNER_S2,
} from "@/lib/mock-chains";
import { FixtureRiskTag } from "@/components/FixtureRiskTag";

const aggregatorColumns: PredictionColumn<CornerAggregatorPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <FixtureRiskTag row={r} label={r.Fixture} className="font-medium text-text-primary" />,
  },
  { key: "score", header: "Master Score", align: "right", render: (r) => r.Master_Score },
  { key: "tier", header: "Tier", render: (r) => <TierBadge tier={r.Tier} /> },
  { key: "chaos", header: "Chaos Rating", align: "right", render: (r) => r.Chaos_Rating },
  { key: "fav", header: "True Corner Fav", render: (r) => r.True_Corner_Fav },
  { key: "flow", header: "Match Flow", render: (r) => r.Match_Flow },
  { key: "u25", header: "U2.5%", render: (r) => <ProbCell value={r["U2.5%"]} showBar={false} /> },
  { key: "total", header: "Total Exp", align: "right", render: (r) => r.Total_Exp },
  {
    key: "actual_corners",
    header: "Actual Corners",
    align: "right",
    className: "text-right",
    render: (r) => {
      const v = (r as unknown as Record<string, unknown>).verification as {
        h_corners?: number;
        a_corners?: number;
        total_corners?: number;
        verdict?: string;
        note?: string;
      } | undefined;
      if (!v || v.verdict === "PENDING" || (v.h_corners == null && v.a_corners == null)) {
        return <span className="text-2xs text-text-dim">—</span>;
      }
      const h = v.h_corners ?? 0;
      const a = v.a_corners ?? 0;
      const t = v.total_corners ?? h + a;
      return (
        <span className="font-mono text-2xs text-amber-200" title={v.note || ""}>
          {h}+{a}={t}
        </span>
      );
    },
  },
  {
    key: "wounded",
    header: "Wounded (H/A)",
    render: (r) => (
      <span className="text-2xs">
        <span className={r.Home_Wounded === "True" ? "text-accent-red" : "text-text-dim"}>
          {r.Home_Wound_Int || "—"}
        </span>
        {" / "}
        <span className={r.Away_Wounded === "True" ? "text-accent-red" : "text-text-dim"}>
          {r.Away_Wound_Int || "—"}
        </span>
      </span>
    ),
  },
];

const stage2Columns: PredictionColumn<CornerStage2Pick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <FixtureRiskTag row={r} label={r.fixture_name} className="font-medium text-text-primary" />,
  },
  {
    key: "predicted",
    header: "Corners (S1/S2)",
    align: "right",
    render: (r) => `${r.stage1_predicted_corners} → ${r.stage2_predicted_corners}`,
  },
  { key: "expected", header: "Predicted Corners", align: "right", render: (r) => r.predicted_corners },
  {
    key: "actual_corners",
    header: "Actual Corners",
    align: "right",
    className: "text-right",
    render: (r) => {
      const v = (r as unknown as Record<string, unknown>).verification as {
        h_corners?: number;
        a_corners?: number;
        total_corners?: number;
        verdict?: string;
        note?: string;
      } | undefined;
      if (!v || v.verdict === "PENDING" || (v.h_corners == null && v.a_corners == null)) {
        return <span className="text-2xs text-text-dim">—</span>;
      }
      const h = v.h_corners ?? 0;
      const a = v.a_corners ?? 0;
      const t = v.total_corners ?? h + a;
      return (
        <span className="font-mono text-2xs text-amber-200" title={v.note || ""}>
          {h}+{a}={t}
        </span>
      );
    },
  },
  { key: "tier", header: "Tier", render: (r) => <TierBadge tier={r.corner_tier} /> },
  { key: "style", header: "Style Alignment", render: (r) => r.style_alignment },
  { key: "confidence", header: "Avg Confidence", align: "right", render: (r) => r.avg_confidence },
  {
    key: "persistent",
    header: "Persistent (V/O)",
    render: (r) => (
      <span className="text-2xs">
        H: {r.home_is_persistent_venue ? "V" : "—"}/{r.home_is_persistent_overall ? "O" : "—"} · A:{" "}
        {r.away_is_persistent_venue ? "V" : "—"}/{r.away_is_persistent_overall ? "O" : "—"}
      </span>
    ),
  },
];

export default function CornersPage() {
  const { date } = useSelectedDate();
  const { data: dnaV2 } = useDnaV2();

  // 1. Master Aggregator (Verify -> DNA -> Rest)
  const aggregatorColumnsWithVerifyAndDna = useMemo(
    () => [
      createVerifyColumn<CornerAggregatorPick>(),
      createDnaColumnByLabel<CornerAggregatorPick>(
        dnaV2?.market_factors,
        "corners",
        date,
        (r) => r.Fixture
      ),
      createIntelligentPassColumn<CornerAggregatorPick>({
        market: "corners",
        getLabel: (r) => r.Fixture,
        date,
      }),
      ...aggregatorColumns,
    ],
    [dnaV2, date]
  );

  // 4. Refiner Stage 2 (Verify -> Rest)
  const stage2ColumnsWithVerify = useMemo(
    () => [createVerifyColumn<CornerStage2Pick>(), ...stage2Columns],
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
            <CornerUpRight className="h-4 w-4 text-accent-cyan" />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-text-primary">
              Corners Intelligence
            </h1>
            <p className="text-[11px] text-text-secondary">
              Full 5-stage Corner Empire chain — master aggregation, catalyst &amp; psychology
            </p>
          </div>
        </div>
      </div>

      {/* ── 2. 5-DAY HISTORY AUDIT STRIP ─────────────────────────────── */}
      <QuickHistoryStrip />

      {/* ── 3. Corner Intelligence ─────────────────────────────────── */}
      <div>
        <ChainStage
          title="Corner Intelligence"
          description="Elite output"
          fetcher={() => cornersApi.getAggregator(date)}
          deps={[date]}
          columns={aggregatorColumnsWithVerifyAndDna}
          rowKey={(r, i) => `${r.Fixture}-${i}`}
          emptyMessage="No aggregator picks for this date."
          fallbackData={MOCK_CORNER_AGG}
        />
      </div>

      {/* ── 6. Corner ────────────────────────────────────────────────── */}
      <div>
        <ChainStage
          title="Corner"
          description="Style-alignment refinement"
          fetcher={() => cornersApi.getStage2(date)}
          deps={[date]}
          columns={stage2ColumnsWithVerify}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No stage 2 picks for this date."
          fallbackData={MOCK_CORNER_S2}
        />
      </div>

    </div>
  );
}
