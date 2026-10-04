"use client";

import { useMemo, useState } from "react";
import { Flame } from "lucide-react";
import type { AxiosResponse } from "axios";
import {
  over15Api,
  ggApi,
  type GGO15Pick,
  type Over15PsychologyPick,
  type Over15LegacyPick,
  type Over15Stage3Pick,
} from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
import { fmt } from "@/lib/utils";
import { createVerifyColumn } from "@/components/predictions/createVerifyColumn";
import { createIntelligentPassColumn } from "@/components/predictions/IntelligentPassColumn";
import { QuickHistoryStrip } from "@/components/layout/QuickHistoryStrip";
import { ChainStage, TierBadge, ProbCell, type PredictionColumn } from "@/components/predictions";
import { MOCK_O15_PSYCH, MOCK_O15_S3 } from "@/lib/mock-chains";
import { FixtureRiskTag } from "@/components/FixtureRiskTag";
import { VERIFY_REFRESH_MS } from "@/lib/use-api";
import { SignalRankToggle } from "@/components/predictions/SignalRankToggle";
import { sortO15 } from "@/lib/cross-engine-ranking";

/**
 * Columns for the GG Over 1.5 twin head.
 *
 * Deliberately identical to the GG page's "GG Over 1.5" block: it is the SAME
 * payload (/api/gg/precision -> o15), so the two must render identically or the
 * same fixture looks different depending on which page you are on.
 */
const ggo15Columns: PredictionColumn<GGO15Pick>[] = [
  {
    key: "fixture",
    header: "fixture",
    render: (r) => (
      <FixtureRiskTag row={r} label={r.fixture} className="font-medium text-text-primary" />
    ),
  },
  { key: "home_team", header: "home_team", render: (r) => <FixtureRiskTag row={r} label={r.home_team} /> },
  { key: "away_team", header: "away_team", render: (r) => <FixtureRiskTag row={r} label={r.away_team} /> },
  { key: "o15_tier", header: "o15_tier", render: (r) => <TierBadge tier={r.o15_tier} /> },
  { key: "o15_score", header: "o15_score", align: "right", render: (r) => r.o15_score },
  {
    key: "combined_lambda",
    header: "combined_lambda",
    align: "right",
    render: (r) => Number(r.combined_lambda).toFixed(2),
  },
  {
    key: "mc_over15_prob",
    header: "mc_over15_prob",
    render: (r) => <ProbCell value={r.mc_over15_prob * 100} showBar={false} />,
  },
  {
    key: "combined_venue_goals_avg",
    header: "combined_venue_goals_avg",
    align: "right",
    render: (r) => Number(r.combined_venue_goals_avg).toFixed(2),
  },
  {
    key: "venue_goals_avg_home",
    header: "venue_goals_avg_home",
    align: "right",
    render: (r) => Number(r.venue_goals_avg_home).toFixed(2),
  },
  {
    key: "venue_goals_avg_away",
    header: "venue_goals_avg_away",
    align: "right",
    render: (r) => Number(r.venue_goals_avg_away).toFixed(2),
  },
  { key: "league_weight", header: "league_weight", align: "right", render: (r) => r.league_weight ?? "—" },
  { key: "fatigue_home", header: "Home Fatigue", align: "right", render: (r) => r.fatigue_home.toFixed(2) },
  { key: "fatigue_away", header: "Away Fatigue", align: "right", render: (r) => r.fatigue_away.toFixed(2) },
];

const psychologyColumns: PredictionColumn<Over15PsychologyPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => <FixtureRiskTag row={r} label={r.Fixture} className="font-medium text-text-primary" />,
  },
  { key: "poisson", header: "Base Poisson", render: (r) => <ProbCell value={r.Base_Poisson} showBar={false} /> },
  { key: "grade", header: "Base Grade", render: (r) => r.Base_Grade },
  { key: "score", header: "Score", align: "right", render: (r) => r.Score },
  { key: "tier", header: "Tier", render: (r) => <TierBadge tier={r.Tier} /> },
  {
    key: "reasons",
    header: "Reasons",
    className: "max-w-[240px] truncate",
    render: (r) => r.Reasons || "—",
  },
];

const stage3Columns: PredictionColumn<Over15Stage3Pick>[] = [
  {
    key: "match",
    header: "Match",
    render: (r) => <FixtureRiskTag row={r} label={r.Match} className="font-medium text-text-primary" />,
  },
  { key: "poisson", header: "Poisson %", render: (r) => <ProbCell value={r["Poisson%"]} showBar={false} /> },
  // Same CSV-string Odds hazard as the Over 2.5 stage-2 column — this market
  // inherits the same engine output shape. `fmt` keeps a numeric string
  // renderable and degrades an absent price to "—" rather than throwing.
  { key: "odds", header: "Odds", align: "right", render: (r) => fmt(r.Odds, 2) },
  { key: "grade", header: "Grade", render: (r) => <TierBadge tier={r.Grade} /> },
  { key: "h2h", header: "H2H Record", render: (r) => r.H2H_Record },
  { key: "picked", header: "Picked By", render: (r) => r.PickedBy },
  {
    key: "fail",
    header: "Failures",
    className: "max-w-[200px] truncate",
    render: (r) => r.Failures || "—",
  },
];

export default function Over15Page() {
  const { date } = useSelectedDate();
  // Default ON: Poisson% >= 55.6 AND Grade >= 5 is the ordering the full-history
  // backtest supports (120 rows, 93.3% vs 72.8% for the rest, corrected
  // p = 0.035, bootstrap 95% CI [+9.4, +31.6] pp). It applies to the "Over 1.5
  // Gold" stage, which is the engine that emits those two fields.
  // See lib/cross-engine-ranking.ts.
  const [smartRank, setSmartRank] = useState(true);

  const fetchStage3 = useMemo(
    () => async (): Promise<AxiosResponse<Over15Stage3Pick[]>> => {
      const response = await over15Api.getStage3(date);
      if (smartRank && Array.isArray(response.data)) {
        // Rebind .data rather than spreading the response: spreading widens the
        // type to a fresh object literal and breaks the ChainStage contract.
        response.data = sortO15(response.data);
      }
      return response;
    },
    [date, smartRank]
  );

  // 1. Psychology (Verify -> Rest)
  const psychologyColumnsWithVerify = useMemo(
    () => [
      createVerifyColumn<Over15PsychologyPick>(),
      createIntelligentPassColumn<Over15PsychologyPick>({
        market: "over15",
        getLabel: (r) => r.Fixture,
        date,
      }),
      ...psychologyColumns,
    ],
    []
  );

  // 2. Stage 3 Base (Verify -> Rest)
  const stage3ColumnsWithVerify = useMemo(
    () => [
      createVerifyColumn<Over15Stage3Pick>(),
      createIntelligentPassColumn<Over15Stage3Pick>({
        market: "over15",
        getLabel: (r) => r.Match,
        date,
      }),
      ...stage3Columns,
    ],
    []
  );

  const ggo15ColumnsWithVerify = useMemo(
    () => [createVerifyColumn<GGO15Pick>(), ...ggo15Columns],
    []
  );

  /**
   * The FROZEN PRE-FIX block.
   *
   * Same columns as the live psychology block on purpose — the point is to read
   * the two verdicts against each other, and a different column set would make
   * a difference in the data look like a difference in the rendering.
   *
   * Deliberately NO Intelligent Pass column here. That evaluator is the current
   * one; running it over frozen old picks would stamp today's judgement onto
   * yesterday's engine and the comparison would be worthless. The legacy block
   * shows only what the old engine actually said.
   */
  const legacyColumns = useMemo(
    () => psychologyColumns as PredictionColumn<Over15LegacyPick>[],
    []
  );

  /**
   * The GG Over 1.5 twin head — the SAME payload the GG page renders, so the
   * two pages cannot drift apart. ChainStage consumes a bare row array, so the
   * endpoint's { gg, o15 } envelope is unwrapped to just the `o15` half here;
   * the endpoint still serves `gg` and the GG page still uses it.
   */
  const fetchGGO15 = useMemo(
    () => async (): Promise<AxiosResponse<GGO15Pick[]>> => {
      const response = await ggApi.getPrecision(date);
      return { ...response, data: response.data?.o15 ?? [] };
    },
    [date]
  );

  return (
    <div
      className="flex flex-col gap-4 p-3.5 sm:p-5 md:p-6"
    >
      {/* ── 1. SLEEK COMPACT TOP BANNER ──────────────────────────────── */}
      <div className="glass flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-[#0c1220]/90 px-4 py-3 shadow-panel backdrop-blur-md">
        <div className="flex w-9 h-9 shrink-0 items-center justify-center rounded-lg border border-accent-amber/30 bg-accent-amber/10 shadow-[0_0_12px_rgba(245,158,11,0.2)]">
          <Flame className="h-4 w-4 text-accent-amber" />
        </div>
        <div>
          <h1 className="text-sm font-black uppercase tracking-wider text-text-primary">
            Over 1.5 Intelligence
          </h1>
          <p className="text-[11px] text-text-secondary">
            2-stage engine chain — psychology audit &amp; base stage. The
            psychology block is the FIXED engine; the PRE-FIX block beneath it is
            the same engine before the 2026-09-30 fix, frozen for comparison.
          </p>
        </div>
        <SignalRankToggle
          active={smartRank}
          onChange={setSmartRank}
          activeLabel="Smart rank"
          inactiveLabel="As served"
          help="Picks the backtested combination to the top: Poisson% >= 55.6 AND Grade >= 5 (120 rows, 93.3% vs 72.8% for the rest, corrected p = 0.035, bootstrap 95% CI [+9.4, +31.6] pp). Applies to the Over 1.5 Gold stage. Re-check with: python3 signal_backtest.py --market o15"
        />
      </div>

      {/* ── 2. 5-DAY HISTORY AUDIT STRIP ─────────────────────────────── */}
      <QuickHistoryStrip />

      {/* ── 3. Over 1.5 Intelligence (the FIXED engine) ───────────────── */}
      <div>
        <ChainStage
          title="Over 1.5 Intelligence"
          description="FIXED ENGINE — psychology layer, live output"
          fetcher={() => over15Api.getPsychology(date)}
          deps={[date]}
          columns={psychologyColumnsWithVerify}
          rowKey={(r, i) => `${r.Fixture}-${i}`}
          emptyMessage="No psychology audits for this date."
          fallbackData={MOCK_O15_PSYCH}
          refreshMs={VERIFY_REFRESH_MS}
        />
      </div>

      {/* ── 3b. Over 1.5 PRE-FIX (frozen, for comparison) ────────────────
          The engine fix landed 2026-09-30 18:11 and 19:53, but the pipeline
          had already started at 18:00:21 and had imported every engine module
          by then — so that run produced PRE-FIX output. This is that output,
          frozen before the next run overwrote it. Read it against the block
          above to see what the fix changed. */}
      <div>
        <ChainStage
          title="Over 1.5 — PRE-FIX (frozen)"
          description="OLD ENGINE output, kept only for comparison. Not a second engine and not live — the snapshot of the run that predates the fix. The live verdict is the block above."
          fetcher={() => over15Api.getLegacy(date)}
          deps={[date]}
          columns={legacyColumns}
          rowKey={(r, i) => `${r.Fixture}-legacy-${i}`}
          emptyMessage="No pre-fix snapshot for this date."
        />
      </div>

      {/* ── 4. Over 1.5 Gold ─────────────────────────────────────────── */}
      <div>
        <ChainStage
          title="Over 1.5 Gold"
          description="Foundation base"
          fetcher={fetchStage3}
          deps={[date, smartRank]}
          columns={stage3ColumnsWithVerify}
          rowKey={(r, i) => `${r.Match}-${i}`}
          emptyMessage="No stage 3 picks for this date."
          fallbackData={MOCK_O15_S3}
          refreshMs={VERIFY_REFRESH_MS}
        />
      </div>

      {/* ── 5. GG Over 1.5 (twin head — also shown on the GG page) ───── */}
      <div>
        <ChainStage
          title="GG Over 1.5"
          description="Precision twin head — lambda, venue goals avg, fatigue (same payload as the GG page)"
          fetcher={fetchGGO15}
          deps={[date]}
          columns={ggo15ColumnsWithVerify}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No GG Over 1.5 picks for this date."
          refreshMs={VERIFY_REFRESH_MS}
        />
      </div>
    </div>
  );
}
