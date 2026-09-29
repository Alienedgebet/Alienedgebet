"use client";

import { useEffect, useMemo, useState } from "react";
import type { AxiosResponse } from "axios";
import { CornerUpRight } from "lucide-react";
import {
  cornersApi,
  foundationApi,
  type CornerAggregatorPick,
  type CornerConsistencyReport,
  type CornerStage2Pick,
} from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
import { useDnaV2 } from "@/lib/use-dna-v2";
import { createDnaColumnByLabel } from "@/components/dna/DnaCountBadge";
import { createIntelligentPassColumn } from "@/components/predictions/IntelligentPassColumn";
import { createVerifyColumn } from "@/components/predictions/createVerifyColumn";
import { SignalRankToggle } from "@/components/predictions/SignalRankToggle";
import { cornersQualifies } from "@/lib/signal-ranking";
import { sortCornersRefined, withBorrowed } from "@/lib/cross-engine-ranking";
import { QuickHistoryStrip } from "@/components/layout/QuickHistoryStrip";
import { ChainStage, TierBadge, ProbCell, type PredictionColumn } from "@/components/predictions";
import {
  MOCK_CORNER_AGG,
  MOCK_CORNER_S2,
} from "@/lib/mock-chains";
import { FixtureRiskTag } from "@/components/FixtureRiskTag";
import { VERIFY_REFRESH_MS } from "@/lib/use-api";
import { cn } from "@/lib/utils";

const aggregatorColumns: PredictionColumn<CornerAggregatorPick>[] = [
  {
    key: "king",
    header: "Corner consistency",
    render: (r) => (
      <div className="flex flex-col gap-0.5 text-2xs">
        <span title="Home corner consistency">
          H <KingBadge icon={r.H_King} />
        </span>
        <span title="Away corner consistency">
          A <KingBadge icon={r.A_King} />
        </span>
      </div>
    ),
  },
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
    header: "Corner consistency",
    render: (r) => (
      <div className="flex flex-col gap-0.5 text-2xs">
        <ConsistencyChip
          label="H"
          count={r.home_over_4_corners_count}
          persistent={r.home_is_persistent_over_4}
        />
        <ConsistencyChip
          label="A"
          count={r.away_over_4_corners_count}
          persistent={r.away_is_persistent_over_4}
        />
        <span
          className="text-text-dim"
          title={
            r.home_is_persistent_venue
              ? "Home is consistent at this venue"
              : r.home_is_persistent_overall
              ? "Home is consistent overall"
              : "Home shows no consistency"
          }
        >
          venue H:{r.home_is_persistent_venue ? "✓" : "—"} A:
          {r.away_is_persistent_venue ? "✓" : "—"}
        </span>
      </div>
    ),
  },
];

/**
 * The aggregator's consistency badge, icon only.
 *
 * The aggregator emits 👑 (consistent at this venue), ⭐ (consistent overall)
 * and ❌ (no consistency) as H_King/A_King. It has written these on every run
 * for a long time and the corners page never referenced them, so a home team
 * carrying a 👑 was invisible — the same class of bug as the over-4 flag, but
 * with the data already sitting in the payload.
 *
 * Icon only by decision: the checkable "4/5" count lives on the stage-2 table,
 * and the aggregator CSV does not carry it. An unlabelled icon is still better
 * than data nobody can see, and the tooltip says which side it is.
 */
function KingBadge({ icon }: { icon?: string }) {
  if (!icon || icon === "❌") {
    return (
      <span className="text-text-dim" title="No corner consistency">
        —
      </span>
    );
  }
  const venue = icon === "👑";
  return (
    <span
      className={cn(
        "font-semibold",
        venue ? "text-emerald-300" : "text-accent-green"
      )}
      title={
        venue
          ? "Consistently generates corners at this venue"
          : "Consistently generates corners overall"
      }
    >
      {icon}
    </span>
  );
}

/**
 * "4/5" beats a tick in a column, because a tick cannot be checked.
 *
 * The count is the number of the team's last 5 matches in which it took more
 * than 4 corners, and the flag is the engine's own verdict (4 or more = yes).
 * Showing both means a reader can disagree with the verdict and know exactly
 * which match made them disagree.
 */
function ConsistencyChip({
  label,
  count,
  persistent,
}: {
  label: string;
  count?: number;
  persistent?: boolean;
}) {
  const n = typeof count === "number" ? count : null;
  const tier =
    persistent === true
      ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-300"
      : persistent === false
      ? "border-border-bright bg-bg-elevated text-text-dim"
      : "border-border/60 bg-bg-elevated/50 text-text-dim";
  return (
    <span
      className={cn(
        "inline-flex w-fit items-center gap-1 rounded border px-1.5 py-px font-mono",
        tier
      )}
      title={
        n === null
          ? "No corner consistency recorded for this team"
          : `${n} of the last 5 matches above 4 corners — ${
              persistent ? "engine reads this as consistent" : "engine reads this as not consistent"
            }`
      }
    >
      <span className="font-sans opacity-60">{label}</span>
      {n === null ? "—" : `${n}/5`}
    </span>
  );
}

/* ── the persistent corner kings, as a real engine stage ──────────── */

/**
 * The Kings row shape, mirroring the engine's own dict.
 *
 * This used to be a hand-rolled <div> with its own <table>. That was a
 * mistake: bypassing ChainStage meant bypassing createVerifyColumn(), so the
 * panel had no WON/LOST/PENDING and no actual corner score, AND it had none of
 * the collapse behaviour every other stage on this page has. It was the only
 * thing on the screen you could neither collapse nor verify.
 *
 * As a normal stage it gets both, from the shared components, with no bespoke
 * markup.
 */
interface CornerKingRow {
  fixture: string;
  /** 2 = both teams persistent, 1 = one side. */
  score: number;
  total: number;
  h_count: number;
  a_count: number;
  h_list: number[];
  a_list: number[];
  verification?: Record<string, unknown>;
}

const kingColumns: PredictionColumn<CornerKingRow>[] = [
  createVerifyColumn<CornerKingRow>(),
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => (
      <span className="font-medium text-text-primary">{r.fixture}</span>
    ),
  },
  {
    key: "both",
    header: "Both?",
    align: "center",
    render: (r) => (
      <span
        className={cn(
          "rounded border px-1.5 py-px text-2xs font-bold",
          r.score === 2
            ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-300"
            : "border-accent-green/40 bg-accent-green/10 text-accent-green"
        )}
      >
        {r.score === 2 ? "BOTH" : "ONE"}
      </span>
    ),
  },
  {
    key: "total",
    header: "Exp total",
    align: "right",
    render: (r) => (
      <span className="font-mono text-2xs">
        {typeof r.total === "number" ? r.total.toFixed(1) : "—"}
      </span>
    ),
  },
  {
    key: "home",
    header: "Home last 5",
    render: (r) => <CornerList count={r.h_count} list={r.h_list} side="H" />,
  },
  {
    key: "away",
    header: "Away last 5",
    render: (r) => <CornerList count={r.a_count} list={r.a_list} side="A" />,
  },
];

/**
 * "4/5 · 8, 7, 6, 5, 4" — the count, then the evidence.
 *
 * A king badge that cannot be checked is not worth much, so the raw list sits
 * beside the flag rather than behind it.
 */
function CornerList({
  count,
  list,
  side,
}: {
  count: number;
  list: number[];
  side: string;
}) {
  if (!Array.isArray(list) || list.length === 0) {
    return <span className="text-2xs text-text-dim">{side} no history</span>;
  }
  return (
    <span
      className="font-mono text-2xs"
      title={`${side}: ${count} of the last ${list.length} matches above 4 corners`}
    >
      <span className="text-text-primary">
        {count}/{list.length}
      </span>{" "}
      <span className="text-text-dim">· {list.join(", ")}</span>
    </span>
  );
}

export default function CornersPage() {
  const { date } = useSelectedDate();
  const { data: dnaV2 } = useDnaV2();
  // Default ON: U2.5% <= 48.8 AND at most one side wounded is the ordering the
  // full-history backtest supports (92.7% vs 81.5% for the rest, p = 0.000037,
  // 10 of 11 leave-one-day-out days). See lib/signal-ranking.ts.
  const [smartRank, setSmartRank] = useState(true);

  // The Persistent Corner Kings, served from the miner's own run.
  //
  // Fetched as a normal engine stage rather than a bespoke panel, so it gets the
  // shared verify column (WON / LOST / PENDING with the actual corner score) and
  // the same collapse behaviour as every other stage on this page. The first
  // version hand-rolled its own <div> + <table>, which bypassed both — it was
  // the only thing on screen you could neither collapse nor verify.
  //
  // Deliberately NOT date-scoped: the payload carries its own date and that is
  // stated in the stage description, rather than implying a freshness it may
  // not have.
  const fetchConsistency = useMemo(
    () => async (): Promise<AxiosResponse<CornerKingRow[]>> => {
      const res = await cornersApi.getConsistency();
      return { ...res, data: (res.data?.kings ?? []) as CornerKingRow[] };
    },
    []
  );

  // The run's own date, read once for the stage caption.
  const [consistencyDate, setConsistencyDate] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    cornersApi
      .getConsistency()
      .then((res) => {
        if (!cancelled) setConsistencyDate(res.data?.date ?? null);
      })
      .catch(() => {
        /* the stage renders its own error; this is caption only */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const fetchAggregator = useMemo(
    () => async (): Promise<AxiosResponse<CornerAggregatorPick[]>> => {
      const response = await cornersApi.getAggregator(date);
      if (smartRank && Array.isArray(response.data)) {
        // The borrowed refinement comes from the calibration engine, a
        // DIFFERENT payload. A failed calibration fetch must not break the
        // corners list, so it degrades to the own-engine rule alone rather
        // than losing the ranking.
        let borrowed: Record<string, Record<string, unknown>> = {};
        try {
          const calibration = await foundationApi.getCalibration(date);
          if (Array.isArray(calibration.data)) {
            for (const row of calibration.data) {
              if (!row?.fixture) continue;
              borrowed[row.fixture] = { parity_gap: row.parity_gap };
            }
          }
        } catch {
          borrowed = {};
        }
        // Rebind .data rather than spreading the response: spreading widens
        // the type to a fresh object literal and breaks the ChainStage
        // fetcher contract.
        response.data = sortCornersRefined(
          withBorrowed(response.data, borrowed),
          (row) => cornersQualifies(row),
        ) as CornerAggregatorPick[];
      }
      return response;
    },
    [date, smartRank]
  );

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
        <SignalRankToggle
          active={smartRank}
          onChange={setSmartRank}
          activeLabel="Smart rank"
          inactiveLabel="As served"
          help="Picks the backtested combination to the top: U2.5% <= 48.8 AND at most one side wounded (247 rows, 92.7% vs 81.5% for the rest, p = 0.000037, better on 10 of 11 leave-one-day-out days). Re-check with: python3 signal_backtest.py --market corners"
        />
      </div>

      {/* ── 2. 5-DAY HISTORY AUDIT STRIP ─────────────────────────────── */}
      <QuickHistoryStrip />

      {/* ── 3. Corner Intelligence ─────────────────────────────────── */}
      <div>
        <ChainStage
          title="Corner Intelligence"
          description="Elite output"
          fetcher={fetchAggregator}
          deps={[date, smartRank]}
          columns={aggregatorColumnsWithVerifyAndDna}
          rowKey={(r, i) => `${r.Fixture}-${i}`}
          emptyMessage="No aggregator picks for this date."
          fallbackData={MOCK_CORNER_AGG}
          refreshMs={VERIFY_REFRESH_MS}
        />
      </div>

      {/* ── 5b. Persistent Corner Kings ──────────────────────────────── */}
      <div>
        <ChainStage<CornerKingRow>
          title="Persistent corner kings"
          description={`Teams that reliably generate corners — more than 4 in at least 4 of their last 5, venue-filtered.${
            consistencyDate ? ` Run for ${consistencyDate}.` : ""
          }`}
          fetcher={fetchConsistency}
          deps={[]}
          columns={kingColumns}
          rowKey={(r, i) => `${r.fixture}-${i}`}
          emptyMessage="No team is corner-consistent right now — nothing hit more than 4 corners in 4 of its last 5."
          fallbackData={[]}
          refreshMs={VERIFY_REFRESH_MS}
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
          refreshMs={VERIFY_REFRESH_MS}
        />
      </div>

    </div>
  );
}
