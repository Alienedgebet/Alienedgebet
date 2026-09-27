"use client";

import { useMemo, useState } from "react";
import { Zap } from "lucide-react";
import type { AxiosResponse } from "axios";
import {
  ggApi,
  type GGForensicPick,
  type GGO15Pick,
  type GGSupremePick,
} from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
import { useApi, VERIFY_REFRESH_MS } from "@/lib/use-api";
import { useDnaV2 } from "@/lib/use-dna-v2";
import { createDnaColumn } from "@/components/dna/DnaCountBadge";
import { createVerifyColumn } from "@/components/predictions/createVerifyColumn";
import { createIntelligentPassColumn } from "@/components/predictions/IntelligentPassColumn";
import { QuickHistoryStrip } from "@/components/layout/QuickHistoryStrip";
import {
  ChainBranch,
  ChainStage,
  ProbCell,
  TierBadge,
  type PredictionColumn,
} from "@/components/predictions";
import {
  MOCK_GG_FORENSICS,
  MOCK_GG_PRECISION,
  MOCK_GG_SUPREME,
} from "@/lib/mock-chains";
import { FixtureRiskTag } from "@/components/FixtureRiskTag";
import { SignalRankToggle } from "@/components/predictions/SignalRankToggle";
import { sortGG, withBorrowed } from "@/lib/cross-engine-ranking";

const supremeColumns: PredictionColumn<GGSupremePick>[] = [
  {
    key: "Fixture",
    header: "Fixture",
    render: (r) => (
      <FixtureRiskTag row={r} label={r.Fixture} className="font-medium text-text-primary" />
    ),
  },
  {
    key: "Category",
    header: "Category",
    render: (r) => <TierBadge tier={r.Category} />,
  },
  {
    key: "Cat_Priority",
    header: "Cat_Priority",
    align: "right",
    render: (r) => r.Cat_Priority,
  },
  {
    key: "Monte_GG_Prob",
    header: "Monte_GG_Prob",
    render: (r) => <ProbCell value={r.Monte_GG_Prob} showBar={false} />,
  },
  {
    key: "NGG_Risk",
    header: "NGG_Risk",
    align: "right",
    render: (r) => r.NGG_Risk,
  },
  {
    key: "Base_Marks",
    header: "Base_Marks",
    className: "max-w-[160px] truncate",
    render: (r) => r.Base_Marks || "—",
  },
  {
    key: "DNA_Status",
    header: "DNA_Status",
    render: (r) => r.DNA_Status,
  },
  {
    key: "Psych_Score",
    header: "Psych_Score",
    align: "right",
    render: (r) => String(r.Psych_Score),
  },
  {
    key: "Psych_Triggers",
    header: "Psych_Triggers",
    className: "max-w-[200px] truncate",
    render: (r) => r.Psych_Triggers || "—",
  },
  { key: "VIP_Status", header: "VIP_Status", render: (r) => r.VIP_Status },
  {
    key: "Veto_Status",
    header: "Veto_Status",
    render: (r) => (
      <span
        className={
          r.Veto_Status && r.Veto_Status !== "None"
            ? "text-accent-red"
            : "text-text-dim"
        }
      >
        {r.Veto_Status || "—"}
      </span>
    ),
  },
  {
    key: "Spears",
    header: "Spears",
    className: "max-w-[200px] truncate",
    render: (r) => r.Spears || "—",
  },
];

const forensicsColumns: PredictionColumn<GGForensicPick>[] = [
  {
    key: "league_id",
    header: "league_id",
    render: (r) => <FixtureRiskTag row={r} label={r.league_id} className="font-mono text-2xs" />,
  },
  {
    key: "Fixture",
    header: "Fixture",
    render: (r) => (
      <FixtureRiskTag row={r} label={r.Fixture} className="font-medium text-text-primary" />
    ),
  },
  { key: "Score", header: "Score", render: (r) => r.Score },
  {
    key: "DNA_Intelligence",
    header: "DNA_Intelligence",
    render: (r) => r.DNA_Intelligence,
  },
  {
    key: "Poisson%",
    header: "Poisson%",
    render: (r) => <ProbCell value={r["Poisson%"]} showBar={false} />,
  },
  { key: "H2H_GG", header: "H2H_GG", render: (r) => r.H2H_GG },
  {
    key: "DNA_Insight",
    header: "DNA_Insight",
    className: "max-w-[180px] truncate",
    render: (r) => r.DNA_Insight,
  },
  { key: "Ranks", header: "Ranks", render: (r) => r.Ranks },
  {
    key: "Forensic_Audit",
    header: "Forensic_Audit",
    className: "max-w-[220px] truncate",
    render: (r) => r.Forensic_Audit,
  },
];


const o15Columns: PredictionColumn<GGO15Pick>[] = [
  { key: "fixture", header: "fixture", render: (r) => <FixtureRiskTag row={r} label={r.fixture} className="font-medium text-text-primary" /> },
  { key: "home_team", header: "home_team", render: (r) => <FixtureRiskTag row={r} label={r.home_team} /> },
  { key: "away_team", header: "away_team", render: (r) => <FixtureRiskTag row={r} label={r.away_team} /> },
  { key: "o15_tier", header: "o15_tier", render: (r) => <TierBadge tier={r.o15_tier} /> },
  { key: "o15_score", header: "o15_score", align: "right", render: (r) => r.o15_score },
  { key: "combined_lambda", header: "combined_lambda", align: "right", render: (r) => Number(r.combined_lambda).toFixed(2) },
  { key: "mc_over15_prob", header: "mc_over15_prob", render: (r) => <ProbCell value={r.mc_over15_prob * 100} showBar={false} /> },
  { key: "combined_venue_goals_avg", header: "combined_venue_goals_avg", align: "right", render: (r) => Number(r.combined_venue_goals_avg).toFixed(2) },
  { key: "venue_goals_avg_home", header: "venue_goals_avg_home", align: "right", render: (r) => Number(r.venue_goals_avg_home).toFixed(2) },
  { key: "venue_goals_avg_away", header: "venue_goals_avg_away", align: "right", render: (r) => Number(r.venue_goals_avg_away).toFixed(2) },
  { key: "league_weight", header: "league_weight", align: "right", render: (r) => r.league_weight ?? "—" },
  { key: "sig1_combined_lambda", header: "sig1_combined_lambda", align: "right", render: (r) => r.sig1_combined_lambda },
  { key: "sig2_mc_over15", header: "sig2_mc_over15", align: "right", render: (r) => r.sig2_mc_over15 },
  { key: "sig3_venue_goals_avg", header: "sig3_venue_goals_avg", align: "right", render: (r) => r.sig3_venue_goals_avg },
  { key: "sig4_league_weight", header: "sig4_league_weight", align: "right", render: (r) => r.sig4_league_weight },
  { key: "sig5_fatigue_penalty", header: "Fatigue Penalty", align: "right", render: (r) => r.sig5_fatigue_penalty },
  { key: "fatigue_home", header: "Home Fatigue", align: "right", render: (r) => r.fatigue_home.toFixed(2) },
  { key: "fatigue_away", header: "Away Fatigue", align: "right", render: (r) => r.fatigue_away.toFixed(2) },
];

export function GGMarketPanel({ embedded = false }: { embedded?: boolean }) {
  const { date } = useSelectedDate();
  const { data: dnaV2 } = useDnaV2();
  // Default ON: Base_Marks >= 3 AND Monte_GG_Prob >= 74.32 is the ordering the
  // full-history backtest supports (291 rows, 70.4% vs 56.0% for the rest,
  // corrected p = 0.013, leave-one-day-out 5/7). The top tier additionally
  // borrows gg_forensics.Forensic_Audit <= 3, lifting it to 75.2% on 129 rows
  // (leave-one-day-out 6/6). See lib/cross-engine-ranking.ts.
  const [smartRank, setSmartRank] = useState(true);
  const precision = useApi(() => ggApi.getPrecision(date), [date], {
    fallback: MOCK_GG_PRECISION,
    cacheKey: `gg-precision:${date}`,
    refreshMs: VERIFY_REFRESH_MS,
  });

  /**
   * The borrowed forensic audit lives in a DIFFERENT engine's payload, so the
   * fetcher joins it in by fixture. A failed forensics fetch must NOT break the
   * supreme list — the own-engine rule still applies on its own, so the page
   * degrades to the two-tier ordering instead of losing the ranking entirely.
   */
  const fetchSupreme = useMemo(
    () => async (): Promise<AxiosResponse<GGSupremePick[]>> => {
      const response = await ggApi.getSupreme(date);
      if (!smartRank || !Array.isArray(response.data)) return response;

      let borrowed: Record<string, Record<string, unknown>> = {};
      try {
        const forensics = await ggApi.getForensics(date);
        if (Array.isArray(forensics.data)) {
          for (const row of forensics.data) {
            // GGForensicPick declares 'Fixture' (capitalised); the cache also
            // carries a lowercase 'fixture' on some rows, so read both rather
            // than dropping the join whenever one shape appears.
            const label = row.Fixture ?? (row as unknown as Record<string, unknown>).fixture;
            if (!label) continue;
            borrowed[String(label)] = {
              Forensic_Audit: row.Forensic_Audit,
            };
          }
        }
      } catch {
        borrowed = {};
      }
      // Rebind .data rather than spreading the response: spreading widens the
      // type to a fresh object literal and breaks the ChainStage fetcher
      // contract (same reason the corners page does it this way).
      response.data = sortGG(withBorrowed(response.data, borrowed)) as GGSupremePick[];
      return response;
    },
    [date, smartRank]
  );

  // 1. GG Supreme (Verify -> DNA -> Intelligent Pass Count -> Rest)
  const supremeColumnsWithVerifyAndDna = useMemo(
    () => [
      createVerifyColumn<GGSupremePick>(),
      createDnaColumn<GGSupremePick>(dnaV2?.market_factors, "gg", date),
      createIntelligentPassColumn<GGSupremePick>({
        market: "gg",
        getTeam: (r) => (r as { team_name?: string }).team_name,
        getLabel: (r) => r.Fixture,
        date,
      }),
      ...supremeColumns,
    ],
    [dnaV2, date]
  );

  // 2. Over 1.5 Precision (Verify -> DNA -> Intelligent Pass Count -> Rest)
  const o15ColumnsWithVerifyAndDna = useMemo(
    () => [
      createVerifyColumn<GGO15Pick>(),
      createDnaColumn<GGO15Pick>(dnaV2?.market_factors, "over15", date),
      createIntelligentPassColumn<GGO15Pick>({
        market: "gg_o15",
        getLabel: (r) => r.fixture,
        date,
      }),
      ...o15Columns,
    ],
    [dnaV2, date]
  );

  // 3. GG Forensics (Verify -> Rest)
  const forensicsColumnsWithVerify = useMemo(
    () => [createVerifyColumn<GGForensicPick>(), ...forensicsColumns],
    []
  );

  // 5. GG Precision BTTS Head (Verify -> Intelligent Pass Count -> Rest)

  const live = precision.data;
  const precisionPayload = live;
  const precisionIsMock = precision.isMock;

  return (
    <div
      data-embedded={embedded || undefined}
      className="flex flex-col gap-4 p-3.5 sm:p-5 md:p-6"
    >
      {/* ── 1. COMPACT SLEEK TOP BANNER ──────────────────────────────── */}
      <div className="glass flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-[#0c1220]/90 px-4 py-3 shadow-panel backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-accent-cyan/30 bg-accent-cyan/10 shadow-[0_0_12px_rgba(6,182,212,0.2)]">
            <Zap className="h-4 w-4 text-accent-cyan" />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-text-primary">
              GG / BTTS Intelligence
            </h1>
            <p className="text-[11px] text-text-secondary">
              Multi-stage BTTS engine — Supreme picks, forensic DNA audit &amp; precision twin-head
            </p>
          </div>
        </div>
        <SignalRankToggle
          active={smartRank}
          onChange={setSmartRank}
          activeLabel="Smart rank"
          inactiveLabel="As served"
          help="Picks the backtested combination to the top: Base_Marks >= 3 AND Monte_GG_Prob >= 74.32 (291 rows, 70.4% vs 56.0% for the rest, corrected p = 0.013, better on 5 of 7 leave-one-day-out days). The top tier also borrows the forensic audit from the Forensics engine (Forensic_Audit <= 3), lifting it to 75.2% on 129 rows. Re-check with: python3 signal_backtest.py --market gg"
        />
      </div>

      {/* ── 2. 5-DAY HISTORY AUDIT STRIP ─────────────────────────────── */}
      <QuickHistoryStrip />

      {/* ── 3. STAGE 1: GG Supreme ───────────────────────────────────── */}
      <div>
        <ChainStage
          title="GG Intelligence"
          description="Top-of-chain picks after full 3-stage GG audit"
          fetcher={fetchSupreme}
          deps={[date, smartRank]}
          columns={supremeColumnsWithVerifyAndDna}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No supreme picks for this date."
          fallbackData={MOCK_GG_SUPREME}
          refreshMs={VERIFY_REFRESH_MS}
        />
      </div>

      {/* ── 4. STAGE 2: GG Forensics ─────────────────────────────────── */}
      <div>
        <ChainStage
          title="GG Forensics"
          description="DNA intelligence, Poisson%, H2H BTTS rates, forensic verdict"
          fetcher={() => ggApi.getForensics(date)}
          deps={[date]}
          columns={forensicsColumnsWithVerify}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No forensic picks for this date."
          fallbackData={MOCK_GG_FORENSICS}
          refreshMs={VERIFY_REFRESH_MS}
        />
      </div>

      {/* ── 6. GG OVER 1.5 (also shown on the Over 1.5 page) ────────── */}
      <div>
        <ChainBranch
          title="GG Over 1.5"
          description={
            precisionIsMock
              ? "Over 1.5 precision — lambda, venue goals avg, fatigue · Demo"
              : "Over 1.5 precision — lambda, venue goals avg, fatigue"
          }
          data={precisionPayload?.o15 ?? []}
          loading={precision.loading}
          error={precision.error}
          columns={o15ColumnsWithVerifyAndDna}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No Over 1.5 precision picks for this date."
        />
      </div>

    </div>
  );
}

export default function GGPage() {
  return <GGMarketPanel />;
}
