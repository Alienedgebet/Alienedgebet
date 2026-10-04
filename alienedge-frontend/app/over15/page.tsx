"use client";

import { useMemo } from "react";
import { Flame } from "lucide-react";
import type { AxiosResponse } from "axios";
import {
  over15Api,
  ggApi,
  type GGO15Pick,
  type Over15PsychologyPick,
  type Over15LegacyPick,
  type Over15GoldPick,
  type Over15VipPick,
} from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
import { createVerifyColumn } from "@/components/predictions/createVerifyColumn";
import { createIntelligentPassColumn } from "@/components/predictions/IntelligentPassColumn";
import { QuickHistoryStrip } from "@/components/layout/QuickHistoryStrip";
import { ChainStage, TierBadge, ProbCell, type PredictionColumn } from "@/components/predictions";
import { MOCK_O15_PSYCH } from "@/lib/mock-chains";
import { FixtureRiskTag } from "@/components/FixtureRiskTag";
import { VERIFY_REFRESH_MS } from "@/lib/use-api";

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

/**
 * Columns for the "Over 1.5 Gold" block.
 *
 * These render the Gold engine's NESTED row shape ({teams, metrics, flags}) —
 * identical to the Over 2.5 Gold block's columns, because it is the same row.
 * The only difference is which page it is on and therefore how the Verify
 * column grades it.
 */
const goldColumns: PredictionColumn<Over15GoldPick>[] = [
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
    key: "flags",
    header: "Gold Flags",
    className: "max-w-[260px]",
    render: (r) => (
      <div className="flex flex-wrap gap-1 text-2xs">
        {Object.entries(r.flags)
          .filter(([, v]) => v)
          .map(([k]) => (
            <span
              key={k}
              className="rounded border border-accent-amber/30 bg-accent-amber/10 px-1 py-0.5 text-accent-amber"
            >
              {k.replace(/_/g, " ")}
            </span>
          ))}
      </div>
    ),
  },
  {
    key: "goals",
    header: "Goals L5 (H/A)",
    align: "right",
    render: (r) => `${r.metrics.home_goals_last_5} / ${r.metrics.away_goals_last_5}`,
  },
  { key: "h2h", header: "H2H Analyzed", align: "right", render: (r) => r.metrics.h2h_matches_analyzed },
];

/**
 * Columns for the "Over 1.5 VIP" block.
 *
 * The goals column shows the SAMPLE SIZE next to the total, because the
 * underlying window is the team's last five matches and thin-history teams come
 * back short. "9 / 8 (3g)" is honest about what the number rests on; a bare
 * "9 / 8" would read as a five-game average when it may be a two-game one.
 */
const vipColumns: PredictionColumn<Over15VipPick>[] = [
  {
    key: "fixture",
    header: "Fixture",
    render: (r) => (
      <span className="font-medium text-text-primary">
        {r.teams.home.name} vs {r.teams.away.name}
      </span>
    ),
  },
  {
    key: "vip_tier",
    header: "VIP Tier",
    render: (r) => (r.vip_tier ? <TierBadge tier={r.vip_tier} /> : <span className="text-text-secondary">—</span>),
  },
  {
    key: "goals",
    header: "Goals L5 (H/A)",
    align: "right",
    render: (r) => {
      const { home_goals_last_5: h, away_goals_last_5: a } = r.metrics;
      if (h == null || a == null) return <span className="text-text-secondary">—</span>;
      const n = Math.min(r.metrics.home_games_sampled ?? 5, r.metrics.away_games_sampled ?? 5);
      return `${h} / ${a}${n < 5 ? ` (${n}g)` : ""}`;
    },
  },
  {
    key: "labels",
    header: "Why VIP",
    className: "max-w-[280px]",
    render: (r) => (
      <div className="flex flex-wrap gap-1 text-2xs">
        {(r.pick_labels ?? []).map((l) => (
          <span
            key={l}
            className="rounded border border-accent-amber/30 bg-accent-amber/10 px-1 py-0.5 text-accent-amber"
          >
            {l.replace(/^[^\w]+\s*/, "")}
          </span>
        ))}
      </div>
    ),
  },
  {
    key: "reason",
    header: "Rule",
    className: "max-w-[220px] truncate text-2xs text-text-secondary",
    render: (r) => r.vip_reason || "—",
  },
];

export default function Over15Page() {
  const { date } = useSelectedDate();

  /**
   * The Gold engine's rows.
   *
   * NOT re-sorted. The old block ran `sortO15`, which promotes rows by
   * Poisson% >= 55.6 AND Grade >= 5 — a rule calibrated on 120 STAGE-3 rows.
   * Gold rows have neither field (its schema is {teams, metrics, flags}), so
   * the comparator cannot apply to them and must not be forced onto them.
   * The engine's own ordering is the order it emitted.
   */
  const fetchGold = useMemo(
    () => (): Promise<AxiosResponse<Over15GoldPick[]>> => over15Api.getGold(date),
    [date]
  );

  /**
   * The VIP rows.
   *
   * Not re-sorted client-side: /api/over15/vip already returns tier order, then
   * strongest recent scoring within a tier. Sorting again here would discard
   * that ordering without adding information.
   */
  const fetchVIP = useMemo(
    () => (): Promise<AxiosResponse<Over15VipPick[]>> => over15Api.getVIP(date),
    [date]
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

  // 2. Gold (Verify -> Rest)
  const goldColumnsWithVerify = useMemo(
    () => [
      createVerifyColumn<Over15GoldPick>(),
      createIntelligentPassColumn<Over15GoldPick>({
        market: "over15",
        getLabel: (r) => `${r.teams.home.name} vs ${r.teams.away.name}`,
        date,
      }),
      ...goldColumns,
    ],
    [date]
  );

  // 3. Over 1.5 VIP (Verify -> Rest)
  const vipColumnsWithVerify = useMemo(
    () => [
      createVerifyColumn<Over15VipPick>(),
      createIntelligentPassColumn<Over15VipPick>({
        market: "over15",
        getLabel: (r) => `${r.teams.home.name} vs ${r.teams.away.name}`,
        date,
      }),
      ...vipColumns,
    ],
    [date]
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
      </div>

      {/* ── 2. 5-DAY HISTORY AUDIT STRIP ─────────────────────────────── */}
      <QuickHistoryStrip />

      {/* ── 2b. Over 1.5 VIP ──────────────────────────────────────────
          Highest-precision block on the page, so it sits first.

          Source: Engine/sh_gg_winner.py — the SAME rows as "Second Half Over1
          B" on the SHVI page, read from the same store. Nothing is re-run.

          That engine emits any fixture carrying at least one of five streaks,
          which is ~99% of what it inspects, so raw it measures at exactly the
          base rate. This block applies a filter measured on 571 settled
          fixtures: it keeps 89 of 571 (84% discarded, 84 of 89 misses removed)
          and those 89 went Over 1.5 94.4% of the time.

          NOT PROVEN. Eighteen slices were tested, so one or two look good by
          chance alone; the best z is ~+2.5 and none clears a Bonferroni
          correction. Hence "VIP", not "LOCK". Re-validate as the sample grows.

          Tiers rank by each side's last-5 goals (8/7/6). On the sample they did
          NOT separate — all three landed at 100% on n=12/4/10 — so treat them
          as a ranking label, not a claim that T1 is proven better than T3.
          Tiers need Engine/sh_gg_winner.py's goals_last_5 fields, which only
          exist from 2026-10-04; older dates show "—" rather than a guess. */}
      <div>
        <ChainStage
          title="Over 1.5 VIP"
          description="SH-GG Winner output, filtered and tiered for Over 1.5 — BOTH 2H GOAL + a supporting H2H streak, or 2+ streaks without the AWAY-win flag. Provisional: 94.4% on 89 settled fixtures, not yet statistically proven."
          fetcher={fetchVIP}
          deps={[date]}
          columns={vipColumnsWithVerify}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No VIP picks for this date. This filter is deliberately strict — it needs at least two independent streaks to agree, and drops the AWAY H2H WIN flag entirely because that flag measured 74% against an 84% base rate, i.e. it points the wrong way. An empty block here is a real result, not a failure."
          refreshMs={VERIFY_REFRESH_MS}
        />
      </div>

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

      {/* ── 4. Over 1.5 Gold ───────────────────────────────────────────
          These are the SAME rows the Over 2.5 page shows under "Over 2.5
          Gold" — both blocks read the one `over25_gold` payload, unfiltered
          and unmodified, so the fixture list is identical by construction.

          The Gold engine's only two hard filters are both Over 1.5
          conditions (H2H 100% over 1.5, and both sides 8+ goals in the last
          5), which is why it belongs on this page at all. Unlike the stage-3
          block that held this slot before, it does not read the tier
          ladder's output, so it is an independent opinion rather than a
          downstream view of the engine above.

          Verify grades Over 1.5 (2+ goals) here, because that is the page it
          is rendered on. The Over 2.5 Gold block grades the same fixtures on
          3+ goals. */}
      <div>
        <ChainStage
          title="Over 1.5 Gold"
          description="Gold engine — independent Over 1.5 pick. H2H 100% over 1.5 + both sides 8+ goals in the last 5. Same rows as Over 2.5 Gold."
          fetcher={fetchGold}
          deps={[date]}
          columns={goldColumnsWithVerify}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No Gold picks for this date. This engine is deliberately ultra-selective — it requires H2H to be 100% over 1.5 AND both teams to have scored 8+ in their last 5, so it returns nothing on most days. An empty block here is a real result, not a failure."
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
