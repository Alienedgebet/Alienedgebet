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

/**
 * THE PERSISTENT CORNER KINGS, in the app.
 *
 * This table was already being built by the corner miner on every run and
 * printed to the server console — ranked, with each team's actual corner list —
 * and then discarded by the qualification filter. It was the most visible piece
 * of the engine and the least visible in the product, which is why the feature
 * read as missing rather than as broken.
 *
 * It is here now, and it shows the underlying last-N corner list rather than a
 * bare flag, so the claim can be checked instead of trusted.
 */
function PersistentKingsPanel({ report }: { report: CornerConsistencyReport }) {
  if (!report.available) {
    return (
      <div className="rounded-lg border border-dashed border-border-bright bg-bg-elevated/30 px-3.5 py-4">
        <p className="text-xs font-semibold text-text-secondary">
          Corner consistency not yet available
        </p>
        <p className="mt-1 text-2xs leading-relaxed text-text-dim">
          {report.reason ??
            "The corner miner has not written a consistency run yet. It will appear here after the next run."}
        </p>
      </div>
    );
  }

  const only = report.qualified_via_consistency_only ?? [];

  return (
    <div className="flex flex-col gap-3">
      <p className="text-2xs leading-relaxed text-text-dim">
        {report.rule}{" "}
        {report.date && (
          <span className="text-text-secondary">Run for {report.date}.</span>
        )}
      </p>

      {report.kings.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border-bright bg-bg-elevated/30 px-3.5 py-4">
          <p className="text-xs font-semibold text-text-secondary">
            No team is corner-consistent today
          </p>
          <p className="mt-1 text-2xs leading-relaxed text-text-dim">
            No side hit more than 4 corners in at least 4 of its last 5 matches,
            so nothing is flagged. That is a real answer, not a missing one.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-2xs">
            <thead>
              <tr className="border-b border-border/60 text-text-dim">
                <th className="py-1.5 pr-2 font-medium">fixture</th>
                <th className="py-1.5 pr-2 font-medium">both?</th>
                <th className="py-1.5 pr-2 text-right font-medium">exp total</th>
                <th className="py-1.5 pr-2 font-medium">home last 5</th>
                <th className="py-1.5 font-medium">away last 5</th>
              </tr>
            </thead>
            <tbody>
              {report.kings.map((k, i) => (
                <tr key={`${k.fixture}-${i}`} className="border-b border-border/30">
                  <td className="py-1.5 pr-2 font-medium text-text-primary">
                    {k.fixture}
                  </td>
                  <td className="py-1.5 pr-2">
                    <span
                      className={cn(
                        "rounded border px-1.5 py-px font-semibold",
                        k.score === 2
                          ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-300"
                          : "border-accent-green/40 bg-accent-green/10 text-accent-green"
                      )}
                    >
                      {k.score === 2 ? "BOTH" : "ONE"}
                    </span>
                  </td>
                  <td className="py-1.5 pr-2 text-right font-mono text-text-secondary">
                    {typeof k.total === "number" ? k.total.toFixed(1) : "—"}
                  </td>
                  <td className="py-1.5 pr-2 font-mono text-text-secondary">
                    {cornerList(k.h_count, k.h_list)}
                  </td>
                  <td className="py-1.5 font-mono text-text-secondary">
                    {cornerList(k.a_count, k.a_list)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {only.length > 0 && (
        <div className="rounded-lg border border-accent-indigo/40 bg-accent-indigo/5 px-3 py-2">
          <p className="text-2xs font-semibold uppercase tracking-wide text-accent-indigo">
            Qualified on consistency alone ({only.length})
          </p>
          <p className="mt-1 text-2xs leading-relaxed text-text-secondary">
            These would have been dropped by the tier/confidence filter before
            2026-09-28. They are here only because a side is genuinely
            corner-consistent.
          </p>
          <ul className="mt-1.5 flex flex-col gap-0.5">
            {only.map((f, i) => (
              <li key={`${f.fixture}-${i}`} className="text-2xs text-text-dim">
                · {f.fixture} — {f.tier} tier, confidence {f.avg_confidence};
                corners H {f.home_lastN?.join(", ")} · A {f.away_lastN?.join(", ")}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** "4/5 · 8, 7, 6, 5, 4" — the count, then the evidence. */
function cornerList(count: number, list: number[]) {
  if (!Array.isArray(list) || list.length === 0) {
    return <span className="text-text-dim">no history</span>;
  }
  return (
    <span title={`${count} of the last ${list.length} above 4 corners`}>
      <span className="text-text-primary">{count}/{list.length}</span>{" "}
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

  // The Persistent Corner Kings, served from the miner\'s own run (2026-09-28).
  // Fetched directly rather than through ChainStage because it is a single
  // panel, not a table of picks, and it is deliberately NOT date-scoped — it
  // carries its own date so the panel can state which run it is showing.
  const [consistency, setConsistency] = useState<CornerConsistencyReport | null>(null);
  const [consistencyError, setConsistencyError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    cornersApi
      .getConsistency()
      .then((res) => {
        if (!cancelled) setConsistency(res.data);
      })
      .catch((e) => {
        if (!cancelled) {
          setConsistencyError(
            e?.response?.data?.detail ?? "Could not load corner consistency."
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [date]);

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
      <div className="rounded-xl border border-border/70 bg-bg-elevated/30 p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent-cyan/15 text-accent-cyan">
              <CornerUpRight className="h-3.5 w-3.5" />
            </div>
            <div>
              <h2 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
                Persistent corner kings
              </h2>
              <p className="text-2xs text-text-dim">
                Teams that reliably generate corners
              </p>
            </div>
          </div>
          {consistency?.count ? (
            <span className="text-2xs text-text-dim">
              {consistency.count} flagged
            </span>
          ) : null}
        </div>
        {consistencyError ? (
          <p className="text-2xs text-amber-300">{consistencyError}</p>
        ) : consistency ? (
          <PersistentKingsPanel report={consistency} />
        ) : (
          <p className="text-2xs text-text-dim">Loading corner consistency…</p>
        )}
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
