"use client";

import { Zap } from "lucide-react";
import {
  ggApi,
  type GGCrossVerifyPick,
  type GGForensicPick,
  type GGO15Pick,
  type GGPrecisionPick,
  type GGPsychologyPick,
  type GGSupremePick,
} from "@/lib/api";
import { useSelectedDate } from "@/lib/date-context";
import { useApi } from "@/lib/use-api";
import {
  ChainBranch,
  ChainStage,
  ProbCell,
  TierBadge,
  type PredictionColumn,
} from "@/components/predictions";
import {
  MOCK_GG_CROSS,
  MOCK_GG_FORENSICS,
  MOCK_GG_PRECISION,
  MOCK_GG_PSYCH,
  MOCK_GG_SUPREME,
} from "@/lib/mock-chains";

// ============================================================
// Columns = backend return / print board keys
// Supreme   → AGGREGATOR/gg_supreme_vip.py
// Forensics → AGGREGATOR/gg_forensics_audit.py
// Psychology→ PSYCHOLOGY/gg_psychology.py board cols
// Precision → Engine/gg_precision_engine.py gg_show_cols / o15_show_cols
// Cross-verify → FILTER/gg_precision_filter.py
// ============================================================

const supremeColumns: PredictionColumn<GGSupremePick>[] = [
  {
    key: "fixture_id",
    header: "fixture_id",
    render: (r) => <span className="font-mono text-2xs">{r.fixture_id}</span>,
  },
  {
    key: "Fixture",
    header: "Fixture",
    render: (r) => (
      <span className="font-medium text-text-primary">{r.Fixture}</span>
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
    key: "fixture_id",
    header: "fixture_id",
    render: (r) => <span className="font-mono text-2xs">{r.fixture_id}</span>,
  },
  {
    key: "league_id",
    header: "league_id",
    render: (r) => <span className="font-mono text-2xs">{r.league_id}</span>,
  },
  {
    key: "Fixture",
    header: "Fixture",
    render: (r) => (
      <span className="font-medium text-text-primary">{r.Fixture}</span>
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

const psychologyColumns: PredictionColumn<GGPsychologyPick>[] = [
  {
    key: "Fixture",
    header: "Fixture",
    render: (r) => (
      <span className="font-medium text-text-primary">{r.Fixture}</span>
    ),
  },
  { key: "MC_Rank", header: "MC_Rank", render: (r) => r.MC_Rank },
  {
    key: "MC_Prob",
    header: "MC_Prob",
    render: (r) => <ProbCell value={r.MC_Prob} showBar={false} />,
  },
  {
    key: "Psych_Score",
    header: "Psych_Score",
    align: "right",
    render: (r) => r.Psych_Score,
  },
  {
    key: "Tier",
    header: "Tier",
    render: (r) => <TierBadge tier={r.Tier} />,
  },
  {
    key: "Spears",
    header: "Spears",
    className: "max-w-[200px] truncate",
    render: (r) => r.Spears || "—",
  },
  {
    key: "Psych_Triggers",
    header: "Psych_Triggers",
    className: "max-w-[220px] truncate",
    render: (r) => r.Psych_Triggers || "—",
  },
];

/** Matches Engine/gg_precision_engine.py gg_show_cols (+ identity). */
const ggColumns: PredictionColumn<GGPrecisionPick>[] = [
  {
    key: "fixture_id",
    header: "fixture_id",
    render: (r) => <span className="font-mono text-2xs">{r.fixture_id}</span>,
  },
  {
    key: "fixture",
    header: "fixture",
    render: (r) => (
      <span className="font-medium text-text-primary">{r.fixture}</span>
    ),
  },
  {
    key: "home_team",
    header: "home_team",
    render: (r) => r.home_team,
  },
  {
    key: "away_team",
    header: "away_team",
    render: (r) => r.away_team,
  },
  {
    key: "gg_tier",
    header: "gg_tier",
    render: (r) => <TierBadge tier={r.gg_tier} />,
  },
  {
    key: "gg_score",
    header: "gg_score",
    align: "right",
    render: (r) => r.gg_score,
  },
  {
    key: "gg_signals_fired",
    header: "gg_signals_fired",
    align: "right",
    render: (r) => r.gg_signals_fired,
  },
  {
    key: "mc_btts_prob",
    header: "mc_btts_prob",
    render: (r) => <ProbCell value={r.mc_btts_prob * 100} showBar={false} />,
  },
  {
    key: "venue_btts_combined",
    header: "venue_btts_combined",
    align: "right",
    render: (r) => r.venue_btts_combined,
  },
  {
    key: "h2h_btts_rate",
    header: "h2h_btts_rate",
    align: "right",
    render: (r) => r.h2h_btts_rate,
  },
  {
    key: "home_gk_liable",
    header: "Home GK Wall Liable",
    render: (r) => (r.home_gk_liable ? "Yes" : "No"),
  },
  {
    key: "away_gk_liable",
    header: "Away GK Wall Liable",
    render: (r) => (r.away_gk_liable ? "Yes" : "No"),
  },
  {
    key: "home_gk_cpg",
    header: "Home GK Wall",
    align: "right",
    render: (r) => r.home_gk_cpg.toFixed(2),
  },
  {
    key: "away_gk_cpg",
    header: "Away GK Wall",
    align: "right",
    render: (r) => r.away_gk_cpg.toFixed(2),
  },
  {
    key: "sig1_mc_btts",
    header: "sig1_mc_btts",
    align: "right",
    render: (r) => r.sig1_mc_btts,
  },
  {
    key: "sig2_venue_btts",
    header: "sig2_venue_btts",
    align: "right",
    render: (r) => r.sig2_venue_btts,
  },
  {
    key: "sig3_gk_vuln",
    header: "sig3_gk_vuln",
    align: "right",
    render: (r) => r.sig3_gk_vuln,
  },
  {
    key: "sig4_h2h_btts",
    header: "sig4_h2h_btts",
    align: "right",
    render: (r) => r.sig4_h2h_btts,
  },
  {
    key: "sig5_directional",
    header: "sig5_directional",
    align: "right",
    render: (r) => r.sig5_directional,
  },
  {
    key: "home_gk_note",
    header: "Home GK Note",
    className: "max-w-[160px] truncate",
    render: (r) => r.home_gk_note || "—",
  },
  {
    key: "away_gk_note",
    header: "Away GK Note",
    className: "max-w-[160px] truncate",
    render: (r) => r.away_gk_note || "—",
  },
  {
    key: "lambda_home",
    header: "lambda_home",
    align: "right",
    render: (r) => r.lambda_home,
  },
  {
    key: "lambda_away",
    header: "lambda_away",
    align: "right",
    render: (r) => r.lambda_away,
  },
  {
    key: "fatigue_home",
    header: "Home Fatigue",
    align: "right",
    render: (r) => r.fatigue_home.toFixed(2),
  },
  {
    key: "fatigue_away",
    header: "Away Fatigue",
    align: "right",
    render: (r) => r.fatigue_away.toFixed(2),
  },
  {
    key: "league_weight",
    header: "league_weight",
    align: "right",
    render: (r) => r.league_weight,
  },
];

/** Matches Engine/gg_precision_engine.py o15_show_cols (+ identity). */
const o15Columns: PredictionColumn<GGO15Pick>[] = [
  {
    key: "fixture_id",
    header: "fixture_id",
    render: (r) => <span className="font-mono text-2xs">{r.fixture_id}</span>,
  },
  {
    key: "fixture",
    header: "fixture",
    render: (r) => (
      <span className="font-medium text-text-primary">{r.fixture}</span>
    ),
  },
  {
    key: "home_team",
    header: "home_team",
    render: (r) => r.home_team,
  },
  {
    key: "away_team",
    header: "away_team",
    render: (r) => r.away_team,
  },
  {
    key: "o15_tier",
    header: "o15_tier",
    render: (r) => <TierBadge tier={r.o15_tier} />,
  },
  {
    key: "o15_score",
    header: "o15_score",
    align: "right",
    render: (r) => r.o15_score,
  },
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
  {
    key: "league_weight",
    header: "league_weight",
    align: "right",
    render: (r) => r.league_weight ?? "—",
  },
  {
    key: "sig1_combined_lambda",
    header: "sig1_combined_lambda",
    align: "right",
    render: (r) => r.sig1_combined_lambda,
  },
  {
    key: "sig2_mc_over15",
    header: "sig2_mc_over15",
    align: "right",
    render: (r) => r.sig2_mc_over15,
  },
  {
    key: "sig3_venue_goals_avg",
    header: "sig3_venue_goals_avg",
    align: "right",
    render: (r) => r.sig3_venue_goals_avg,
  },
  {
    key: "sig4_league_weight",
    header: "sig4_league_weight",
    align: "right",
    render: (r) => r.sig4_league_weight,
  },
  {
    key: "sig5_fatigue_penalty",
    header: "Fatigue Penalty",
    align: "right",
    render: (r) => r.sig5_fatigue_penalty,
  },
  {
    key: "fatigue_home",
    header: "Home Fatigue",
    align: "right",
    render: (r) => r.fatigue_home.toFixed(2),
  },
  {
    key: "fatigue_away",
    header: "Away Fatigue",
    align: "right",
    render: (r) => r.fatigue_away.toFixed(2),
  },
];

const crossVerifyColumns: PredictionColumn<GGCrossVerifyPick>[] = [
  {
    key: "fixture_id",
    header: "fixture_id",
    render: (r) => <span className="font-mono text-2xs">{r.fixture_id}</span>,
  },
  {
    key: "league_id",
    header: "league_id",
    render: (r) => <span className="font-mono text-2xs">{r.league_id}</span>,
  },
  {
    key: "home_team",
    header: "home_team",
    render: (r) => (
      <span className="font-medium text-text-primary">{r.home_team}</span>
    ),
  },
  {
    key: "away_team",
    header: "away_team",
    render: (r) => (
      <span className="font-medium text-text-primary">{r.away_team}</span>
    ),
  },
  {
    key: "gg_prob_pct",
    header: "gg_prob_pct",
    render: (r) => <ProbCell value={r.gg_prob_pct} showBar={false} />,
  },
  {
    key: "tier",
    header: "tier",
    render: (r) => <TierBadge tier={r.tier} />,
  },
  {
    key: "verification_days",
    header: "verification_days",
    align: "right",
    render: (r) => r.verification_days,
  },
  {
    key: "table_distance",
    header: "table_distance",
    align: "right",
    render: (r) => r.table_distance,
  },
  {
    key: "audit_timestamp",
    header: "audit_timestamp",
    className: "max-w-[160px] truncate",
    render: (r) => r.audit_timestamp || "—",
  },
];

export function GGMarketPanel({ embedded = false }: { embedded?: boolean }) {
  const { date } = useSelectedDate();
  const precision = useApi(() => ggApi.getPrecision(date), [date], {
    fallback: MOCK_GG_PRECISION,
    cacheKey: `gg-precision:${date}`,
  });

  // Render-time fallback (dashboard parity): never blank the twin-head
  // branches on Network Error when Sportmonks / API is offline.
  const live = precision.data;
  const liveHasRows =
    Boolean(live) &&
    ((live!.gg?.length ?? 0) > 0 || (live!.o15?.length ?? 0) > 0);
  const precisionPayload = liveHasRows ? live! : MOCK_GG_PRECISION;
  const precisionIsMock = !liveHasRows || precision.isMock;

  return (
    <div
      data-embedded={embedded || undefined}
      className="flex flex-col gap-4 p-6"
    >
      <div className="glass flex items-center gap-3 rounded-lg p-4 shadow-panel">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-cyan/15">
          <Zap className="h-5 w-5 text-accent-cyan" />
        </div>
        <div>
          <h1 className="text-base font-bold text-text-primary">
            GG / BTTS Intelligence
          </h1>
          <p className="text-xs text-text-secondary">
            Multi-stage BTTS engine — Supreme picks, forensic DNA audit,
            psychology layer, precision twin-head (GG + O1.5), and 7-day
            cross-verification filter.
          </p>
        </div>
      </div>

      <div>
        <ChainStage
          title="GG Supreme — Final Aggregator"
          description="Top-of-chain picks after full 3-stage GG audit"
          fetcher={() => ggApi.getSupreme(date)}
          deps={[date]}
          columns={supremeColumns}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No supreme picks for this date."
          fallbackData={MOCK_GG_SUPREME}
        />
      </div>

      <div>
        <ChainStage
          title="GG Forensics"
          description="DNA intelligence, Poisson%, H2H BTTS rates, forensic verdict"
          fetcher={() => ggApi.getForensics(date)}
          deps={[date]}
          columns={forensicsColumns}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No forensic picks for this date."
          fallbackData={MOCK_GG_FORENSICS}
        />
      </div>

      <div>
        <ChainStage
          title="GG Psychology"
          description="Monte Carlo rank, psychology score, spears and trigger signals"
          fetcher={() => ggApi.getPsychology(date)}
          deps={[date]}
          columns={psychologyColumns}
          rowKey={(r, i) => `${r.Fixture}-${i}`}
          emptyMessage="No psychology audits for this date."
          fallbackData={MOCK_GG_PSYCH}
        />
      </div>

      <div>
        <ChainBranch
          title="GG Precision — BTTS Head"
          description={
            precisionIsMock
              ? "GG precision engine — Poisson, venue BTTS, GK vulnerability · Demo"
              : "GG precision engine — Poisson, venue BTTS, GK vulnerability"
          }
          data={precisionPayload.gg}
          loading={precision.loading}
          error={null}
          columns={ggColumns}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No GG precision picks for this date."
        />
      </div>

      <div>
        <ChainBranch
          title="Over 1.5 Precision — Twin Head"
          description={
            precisionIsMock
              ? "Over 1.5 precision — lambda, venue goals avg, fatigue · Demo"
              : "Over 1.5 precision — lambda, venue goals avg, fatigue"
          }
          data={precisionPayload.o15}
          loading={precision.loading}
          error={null}
          columns={o15Columns}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No Over 1.5 precision picks for this date."
        />
      </div>

      <div>
        <ChainStage
          title="GG Cross-Verification"
          description="7-day rolling BTTS cross-verification — verified vs. live table distance"
          fetcher={() => ggApi.getCrossVerify()}
          deps={[]}
          columns={crossVerifyColumns}
          rowKey={(r, i) => `${r.fixture_id}-${i}`}
          emptyMessage="No cross-verification data right now."
          fallbackData={MOCK_GG_CROSS}
        />
      </div>
    </div>
  );
}

export default function GGPage() {
  return <GGMarketPanel />;
}
