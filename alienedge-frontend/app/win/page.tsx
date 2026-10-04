"use client";

import { useMemo, useState } from "react";
import { Trophy } from "lucide-react";
import {
  foundationApi,
  underdogApi,
  winApi,
  type WinApexPick,
  type WinForecastPick,
  type WinU2SPick,
} from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
import { useDnaV2 } from "@/lib/use-dna-v2";
import { createDnaColumn } from "@/components/dna/DnaCountBadge";
import { createPickStatsColumn } from "@/components/dna/PickStatsCell";
import { createVerifyColumn } from "@/components/predictions/createVerifyColumn";
import { createIntelligentPassColumn } from "@/components/predictions/IntelligentPassColumn";
import { QuickHistoryStrip } from "@/components/layout/QuickHistoryStrip";
import {
  ChainStage,
  ProbCell,
  TierBadge,
  type PredictionColumn,
} from "@/components/predictions";
import {
  MOCK_WIN_APEX,
  MOCK_WIN_FORECAST,
  MOCK_WIN_U2S,
} from "@/lib/mock-chains";
import type { AxiosResponse } from "axios";
import { SignalRankToggle } from "@/components/predictions/SignalRankToggle";
import { sortWin, sortU2S, withBorrowed, dedupeFixtureSides } from "@/lib/cross-engine-ranking";

import { FixtureRiskTag } from "@/components/FixtureRiskTag";
import { VERIFY_REFRESH_MS } from "@/lib/use-api";

// ============================================================
// Columns = exact backend return / printout keys
// ============================================================

const apexColumns: PredictionColumn<WinApexPick>[] = [
  {
    key: "Fixture",
    header: "Fixture",
    render: (r) => (
      <FixtureRiskTag row={r} label={r.Fixture} className="font-medium text-text-primary" />
    ),
    explain: (
      <p>
        <b>The match.</b> Home team vs away team, exactly as the provider lists
        it. Nothing is scored from this — it exists so you can identify the row,
        and so the DNA/SportyBet history card can look the fixture up.
      </p>
    ),
  },
  {
    key: "Target",
    header: "Target",
    render: (r) => <FixtureRiskTag row={r} label={r.Target} />,
    explain: (
      <p>
        <b>Which side this row is betting on.</b> Every row is one bet on one
        team, not a match-level opinion. A fixture can appear twice — once per
        side — and when it does, each row is graded against its own team.
      </p>
    ),
  },
  {
    key: "Category",
    header: "Category",
    render: (r) => <TierBadge tier={r.Category} />,
    explain: (
      <div className="space-y-2">
        <p>
          <b>The class of pick</b>, assigned after the full three-stage audit.
          It reflects how the row survived, not how strong the team is.
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li><b>VIP / strong</b> — cleared several independent gates.</li>
          <li><b>Standard</b> — cleared the core gates.</li>
          <li><b>Longshot</b> — survived on a weaker basis.</li>
        </ul>
        <p className="text-text-dim">
          Category is an output of the audit chain, not an input to it.
        </p>
      </div>
    ),
  },
  {
    key: "Cat_Priority",
    header: "Cat_Priority",
    align: "right",
    render: (r) => r.Cat_Priority,
    explain: (
      <p>
        <b>Sort weight inside a category.</b> Rows are ordered by category
        first, then this number, then the win probability. It is a tie-breaker
        for presentation — a lower number means &ldquo;show me earlier&rdquo;, not &ldquo;more
        likely&rdquo;.
      </p>
    ),
  },
  {
    key: "Monte_Win_Prob",
    header: "Monte_Win_Prob",
    render: (r) => <ProbCell value={r.Monte_Win_Prob} showBar={false} />,
    explain: (
      <div className="space-y-2">
        <p>
          <b>Simulated chance the target wins</b>, as a percentage. Produced by
          a Monte Carlo run over a Poisson goal model built from each side&rsquo;s
          scoring and conceding rates.
        </p>
        <p>
          It is the model&rsquo;s own opinion <i>before</i> the later audit stages
          apply. It is not a bookmaker&rsquo;s price and it is not a guarantee — it is
          the raw input the rest of the chain builds on.
        </p>
      </div>
    ),
  },
  // (2026-10-04) Monte_Draw_Prob and Lambda_Detail are NO LONGER RENDERED here.
  //
  // DISPLAY ONLY. Both remain in WinApexPick, are still emitted by
  // AGGREGATOR/win_apex_aggregator.py, and Monte_Draw_Prob still drives the
  // aggregator's own sort (final sort is by Cat_Priority, Monte_Win_Prob,
  // Monte_Draw_Prob). Nothing about the model or the data changed — these two
  // simply stopped being worth a column of screen space, and a visible draw
  // number risked reading as a signal the pick was made on when it is not one.
  //
  // Safe to remove: no client-side ordering reads them. sortWin() in
  // lib/cross-engine-ranking.ts keys on poisson_win_prob and win_odds only.
  {
    key: "Underdog_Risk",
    header: "Underdog_Risk",
    render: (r) => r.Underdog_Risk,
    explain: (
      <p>
        <b>Risk flag for betting an outsider.</b> Set when the target is the
        underdog. It marks how exposed this pick is to the classic trap — the
        favourite wins the league but the outsider takes the points — so you can
        discount the row accordingly. It does not change the pick; it labels it.
      </p>
    ),
  },
  {
    key: "Psych_Score",
    header: "Psych_Score",
    align: "right",
    render: (r) => String(r.Psych_Score),
    explain: (
      <p>
        <b>Behavioural-model score</b> for the matchup. It blends things a
        pure goal model cannot see: how each side performs under pressure,
        momentum, and how the two styles interact.
      </p>
    ),
  },
  {
    key: "Psych_Logic",
    header: "Psych_Logic",
    className: "max-w-[220px] truncate",
    render: (r) => r.Psych_Logic || "—",
    explain: (
      <p>
        <b>Why that score.</b> The short plain-English reason the behavioural
        model gave for the number above — the triggers it actually fired on.
        Read it with the score: the score says how strongly, the logic says on
        what. It is truncated in the table; the full text is on the row itself.
      </p>
    ),
  },
  {
    key: "Chokehold_Status",
    header: "Chokehold_Status",
    render: (r) => r.Chokehold_Status || "—",
    explain: (
      <p>
        <b>Opponent suppression check.</b> When it reads{" "}
        <b>OPPONENT CHOKED</b>, the opponent&rsquo;s own attacking route was found to
        be shut down by this matchup — the side has nowhere to create. This is
        one of the gates that can <i>reject</i> a pick, so seeing it clear is not
        neutral: it means that particular objection was tested and passed.
      </p>
    ),
  },
  {
    key: "Veto_Reason",
    header: "Veto_Reason",
    className: "max-w-[200px] truncate",
    render: (r) => r.Veto_Reason || "—",
    explain: (
      <p>
        <b>What would have killed this pick.</b> The veto stage looks for
        disqualifying conditions. A row only survives to appear here if the veto
        did <i>not</i> fire — so this is usually empty. When it is not empty, the
        row was kept anyway under a named exception, and this states which.
      </p>
    ),
  },
];

const u2sColumns: PredictionColumn<WinU2SPick>[] = [
  {
    key: "Fixture",
    header: "Fixture",
    render: (r) => (
      <FixtureRiskTag row={r} label={r.Fixture} className="font-medium text-text-primary" />
    ),
  },
  { key: "Underdog", header: "Underdog", render: (r) => r.Underdog },
  {
    key: "Audit_Verdict",
    header: "Audit_Verdict",
    render: (r) => r.Audit_Verdict,
  },
  {
    key: "Spear_Matchup",
    header: "Spear_Matchup",
    className: "max-w-[180px] truncate",
    render: (r) => r.Spear_Matchup,
  },
  {
    key: "Dog_Venue_SOT",
    header: "SOT Expectancy (Dog)",
    align: "right",
    render: (r) => r.Dog_Venue_SOT,
  },
  {
    key: "Fav_Venue_SOT",
    header: "SOT Expectancy (Fav)",
    align: "right",
    render: (r) => r.Fav_Venue_SOT,
  },
  {
    key: "Dog_H2H_SOT",
    header: "Dog H2H SOT",
    align: "right",
    render: (r) => String(r.Dog_H2H_SOT),
  },
  {
    key: "Fav_H2H_SOT",
    header: "Fav H2H SOT",
    align: "right",
    render: (r) => String(r.Fav_H2H_SOT),
  },
  {
    key: "Dog_Opp_Avg_Conceded",
    header: "Dog_Opp_Avg_Conceded",
    align: "right",
    render: (r) => String(r.Dog_Opp_Avg_Conceded),
  },
  {
    key: "Fav_Opp_Avg_Conceded",
    header: "Fav_Opp_Avg_Conceded",
    align: "right",
    render: (r) => String(r.Fav_Opp_Avg_Conceded),
  },
  {
    key: "Dog_Scoring_Consistency",
    header: "Dog_Scoring_Consistency",
    className: "max-w-[140px] truncate",
    render: (r) => r.Dog_Scoring_Consistency,
  },
  {
    key: "Psych_Score",
    header: "Psych_Score",
    align: "right",
    render: (r) => String(r.Psych_Score),
  },
  {
    key: "Tier",
    header: "Tier",
    render: (r) => <TierBadge tier={r.Tier} />,
  },
  {
    key: "Triggers",
    header: "Triggers",
    className: "max-w-[220px] truncate",
    render: (r) => r.Triggers || "—",
  },
];

const forecastColumns: PredictionColumn<WinForecastPick>[] = [
  {
    key: "fixture",
    header: "fixture",
    render: (r) => (
      <FixtureRiskTag row={r} label={r.fixture} className="font-medium text-text-primary" />
    ),
  },
  { key: "side", header: "side", render: (r) => r.side },
  { key: "team_name", header: "team_name", render: (r) => <FixtureRiskTag row={r} label={r.team_name} /> },
  {
    key: "poisson_win_prob",
    header: "poisson_win_prob",
    render: (r) => <ProbCell value={r.poisson_win_prob} showBar={false} />,
  },
  {
    key: "win_odds",
    header: "win_odds",
    align: "right",
    render: (r) => Number(r.win_odds).toFixed(2),
  },
  {
    key: "poisson_draw_prob",
    header: "poisson_draw_prob",
    align: "right",
    render: (r) => (
      <FixtureRiskTag row={r} label={r.poisson_draw_prob} className="font-mono text-text-muted" />
    ),
  },
  {
    key: "last_5_wins_overall",
    header: "last_5_wins_overall",
    align: "right",
    render: (r) => r.last_5_wins_overall,
  },
  {
    key: "last_5_wins_at_venue",
    header: "last_5_wins_at_venue",
    align: "right",
    render: (r) => r.last_5_wins_at_venue,
  },
  {
    key: "last_5_goals_scored",
    header: "last_5_goals_scored",
    align: "right",
    render: (r) => r.last_5_goals_scored,
  },
  {
    key: "opp_last_5_goals_scored",
    header: "opp_last_5_goals_scored",
    align: "right",
    render: (r) => r.opp_last_5_goals_scored,
  },
  {
    key: "opp_last_5_losses",
    header: "opp_last_5_losses",
    align: "right",
    render: (r) => r.opp_last_5_losses,
  },
  {
    key: "opp_last_5_conceded_raw",
    header: "opp_last_5_conceded_raw",
    align: "right",
    render: (r) => r.opp_last_5_conceded_raw,
  },
  {
    key: "opp_no_clean_sheet_count",
    header: "opp_no_clean_sheet_count",
    align: "right",
    render: (r) => r.opp_no_clean_sheet_count,
  },
  {
    key: "h2h_wins_last_5",
    header: "h2h_wins_last_5",
    align: "right",
    render: (r) => r.h2h_wins_last_5,
  },
  {
    key: "last_3_no_draw_BOTH",
    header: "last_3_no_draw_BOTH",
    align: "right",
    render: (r) => (r.last_3_no_draw_BOTH ? "Yes" : "No"),
  },
  {
    key: "parity_score",
    header: "parity_score",
    align: "right",
    render: (r) => r.parity_score,
  },
  {
    key: "parity_even_count",
    header: "parity_even_count",
    align: "right",
    render: (r) => r.parity_even_count,
  },
];

export function WinMarketPanel({ embedded = false }: { embedded?: boolean }) {
  const { date } = useSelectedDate();
  const { data: dnaV2 } = useDnaV2();
  // Default ON: poisson_win_prob >= 41.09 AND win_odds <= 2.16 is the strongest
  // ordering measured in this project (587 rows, 65.1% vs 31.5% for the rest,
  // corrected p = 0.0000 over 2,873 cut-points, bootstrap CI [+29.5, +37.8],
  // leave-one-day-out 15 of 16 days, base 38.0%). Each row is an individual bet
  // graded against its own side, so ranking by that bet's own probability is a
  // real precision gain. See lib/cross-engine-ranking.ts.
  const [smartRank, setSmartRank] = useState(true);

  // The WIN ordering is applied to the FORECAST stage, not the Raw stage.
  // `win_raw` has no `poisson_win_prob` at all (0 of 158 rows on 2026-09-27)
  // while `win_forecast` has it on every row, so ranking the Raw payload would
  // silently qualify nothing and show a blank probability column.
  const fetchForecast = useMemo(
    () => async (): Promise<AxiosResponse<WinForecastPick[]>> => {
      const response = await foundationApi.getWinForecast(date);
      if (!Array.isArray(response.data)) return response;
      // Drop the losing side of each fixture FIRST, then rank what remains.
      // Doing it the other way round would rank a bet that has already been
      // eliminated by its own fixture's opposite row.
      const onePerFixture = dedupeFixtureSides(response.data);
      response.data = smartRank ? sortWin(onePerFixture) : onePerFixture;
      return response;
    },
    [date, smartRank]
  );

  // U2S is ADVISORY: its verdict grades the stored `Underdog` column, so this
  // ordering ranks FIXTURE QUALITY and is not a prediction of the u2s market.
  // It is defensible only because the borrowed dog_odds is itself
  // pick-independent. Default OFF so it is never mistaken for the market.
  const [smartRankU2S, setSmartRankU2S] = useState(false);

  const fetchU2S = useMemo(
    () => async (): Promise<AxiosResponse<WinU2SPick[]>> => {
      const response = await winApi.getU2S(date);
      if (!smartRankU2S || !Array.isArray(response.data)) return response;
      // The borrowed dog_odds lives in the underdog base engine's payload.
      // A failed fetch degrades to the own-engine rule rather than breaking.
      let borrowed: Record<string, Record<string, unknown>> = {};
      try {
        const base = await underdogApi.getBase(date);
        if (Array.isArray(base.data)) {
          for (const row of base.data) {
            if (!row?.fixture) continue;
            borrowed[row.fixture] = { dog_odds: row.dog_odds };
          }
        }
      } catch {
        borrowed = {};
      }
      response.data = sortU2S(
        withBorrowed(response.data, borrowed),
      ) as WinU2SPick[];
      return response;
    },
    [date, smartRankU2S]
  );

  // 1. Win Apex (Verify -> DNA count -> Stats -> Intelligent Pass Count -> Rest)
  const apexColumnsWithVerifyAndDna = useMemo(
    () => [
      createVerifyColumn<WinApexPick>(),
      createDnaColumn<WinApexPick>(dnaV2?.market_factors, "win", date),
      // (2026-10-04) Match history on demand: last five per side + H2H. Pure
      // display — see components/dna/PickStatsCell.tsx. `Fixture` is
      // "Home vs Away" in this payload and Target is the bet side, so the card's
      // home/away labels come from splitting Fixture on " vs ".
      createPickStatsColumn<WinApexPick>({
        dna: dnaV2,
        date,
        getFixtureId: (r) => r.fixture_id,
        getHomeTeam: (r) => (r.Fixture ?? "").split(/\s+vs\.?\s+/)[0]?.trim() ?? null,
        getAwayTeam: (r) => (r.Fixture ?? "").split(/\s+vs\.?\s+/)[1]?.trim() ?? null,
      }),
      createIntelligentPassColumn<WinApexPick>({
        market: "win",
        getTeam: (r) => r.Target,
        getLabel: (r) => r.Fixture,
        date,
      }),
      ...apexColumns,
    ],
    [dnaV2, date]
  );

  // 3. Underdog-to-Score (Verify -> Intelligent Pass Count -> Rest)
  const u2sColumnsWithVerify = useMemo(
    () => [
      createVerifyColumn<WinU2SPick>(),
      createIntelligentPassColumn<WinU2SPick>({
        market: "u2s",
        getTeam: (r) => r.Underdog,
        getLabel: (r) => r.Fixture,
        date,
      }),
      ...u2sColumns,
    ],
    [date]
  );

  // 4. Win Forecast (Verify -> Intelligent Pass Count -> Rest)
  const forecastColumnsWithVerify = useMemo(
    () => [
      createVerifyColumn<WinForecastPick>(),
      createIntelligentPassColumn<WinForecastPick>({
        market: "win",
        getTeam: (r) => r.team_name,
        getLabel: (r) => r.fixture,
        date,
      }),
      ...forecastColumns,
    ],
    [date]
  );

  return (
    <div
      data-embedded={embedded || undefined}
      className="flex flex-col gap-4 p-3.5 sm:p-5 md:p-6"
    >
      {/* Sleek Compact Top Banner */}
      <div className="glass flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-[#0c1220]/90 px-4 py-3 shadow-panel backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-accent-green/30 bg-accent-green/10 shadow-[0_0_12px_rgba(16,185,129,0.2)]">
            <Trophy className="h-4 w-4 text-accent-green" />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-text-primary">
              Win Intelligence
            </h1>
            <p className="text-[11px] text-text-secondary">
              Multi-stage win probability engine — Apex picks, U2S signal &amp; forecast data
            </p>
          </div>
        </div>
        <SignalRankToggle
          active={smartRank}
          onChange={setSmartRank}
          activeLabel="Smart rank"
          inactiveLabel="As served"
          help="Picks the backtested combination to the top of the Raw stage: poisson_win_prob >= 41.09 AND win_odds <= 2.16 (587 rows, 65.1% vs 31.5% for the rest, +33.6pp, Bonferroni-corrected p = 0.0000 across 2,873 tested cut-points, better on 15 of 16 leave-one-day-out days). Each row is one bet graded against its own side. Re-check with: python3 signal_backtest.py --market win"
        />
      </div>

      {/* 5-Day History Audit Strip */}
      <QuickHistoryStrip />

      {/* Stage 1: Win Intelligence */}
      <ChainStage
        title="Win Intelligence"
        description="Top-of-chain picks after full 3-stage audit"
        fetcher={() => winApi.getApex(date)}
        deps={[date]}
        columns={apexColumnsWithVerifyAndDna}
        rowKey={(r, i) => `${r.fixture_id}-${i}`}
        emptyMessage="No apex picks for this date."
        fallbackData={MOCK_WIN_APEX}
        refreshMs={VERIFY_REFRESH_MS}
      />

      {/* (2026-10-04) The "DNA & Goal Intent Board" block was REMOVED here.
          DISPLAY ONLY — no backend change of any kind.

          Goal Intent is still very much alive: win_apex_aggregator.py reads
          Goal_Intent + Tempo + Risk_Appetite to derive fav_side, which becomes
          dna_align, and that gates whether a row is promoted to a pick at all.
          None of that changed and none of it is exposed here on purpose — a
          visible Goal Intent number invites reading it as the reason the pick
          exists, when it is one of several gates and the published row is the
          honest summary of all of them.

          The full SportyBet-style history card (last 5 + H2H) remains
          available per pick via the Stats column, which is the display that
          carries no intelligence with it. */}

      {/* Stage 4: Underdog-to-Score Signal (U2S) — smart ranked */}
      <div>
        <div className="mb-2 flex items-center justify-end">
          <SignalRankToggle
            active={smartRankU2S}
            onChange={setSmartRankU2S}
            activeLabel="Quality rank"
            inactiveLabel="As served"
            tentative
            help="ADVISORY, off by default. U2S is graded against the stored Underdog column, so this ranks FIXTURE QUALITY, not the u2s market itself. Dog_Venue_SOT >= 12 AND Fav_Venue_SOT <= 15 gives 257 rows at 77.0% (base 66.5%); adding the borrowed underdog dog_odds <= 3.44 reaches 83.2% on 125 rows. The borrowed field is pick-independent, which is the only reason this is defensible. Re-check with: python3 signal_backtest.py --market u2s"
          />
        </div>
        <ChainStage
          title="Underdog-to-Score Signal (U2S)"
          description="Shots-on-target and scoring consistency analysis for underdog picks"
          fetcher={fetchU2S}
          deps={[date, smartRankU2S]}
          columns={u2sColumnsWithVerify}
          rowKey={(r, i) => `${r.Fixture}-${i}`}
          emptyMessage="No U2S signals for this date."
          fallbackData={MOCK_WIN_U2S}
          refreshMs={VERIFY_REFRESH_MS}
        />
      </div>

      {/* Stage 5: Win Forecast — one row per fixture, smart ranked */}
      <ChainStage
        title="Win Forecast"
        description="Poisson-ranked win probability with venue and H2H breakdown"
        fetcher={fetchForecast}
        deps={[date, smartRank]}
        columns={forecastColumnsWithVerify}
        rowKey={(r, i) => `${r.fixture_id}-${r.side}-${i}`}
        emptyMessage="No forecast data for this date."
        fallbackData={MOCK_WIN_FORECAST}
        refreshMs={VERIFY_REFRESH_MS}
      />

    </div>
  );
}

export default function WinPage() {
  return <WinMarketPanel />;
}
