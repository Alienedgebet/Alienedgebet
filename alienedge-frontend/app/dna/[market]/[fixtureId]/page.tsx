"use client";

import { useMemo } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, Loader2, Swords } from "lucide-react";
import { cn } from "@/lib/utils";
import { useDnaV2 } from "@/lib/use-dna-v2";
import type {
  DnaV2Factor,
  DnaV2FixtureFactors,
  DnaV2MarketKey,
  DnaV2Profile,
} from "@/lib/api";

const MARKET_LABELS: Record<DnaV2MarketKey, string> = {
  win: "Win",
  gg: "GG / BTTS",
  over25: "Over 2.5",
  over15: "Over 1.5",
  unders: "Unders",
  draw: "Draw",
  corners: "Corners",
};

const VALID_MARKETS = new Set<string>(Object.keys(MARKET_LABELS));

const PILLARS: Array<{ key: keyof DnaV2Profile["Market_Power_Scores"]; label: string }> = [
  { key: "Win_Dominance", label: "Win Dominance" },
  { key: "Goal_Intent", label: "Goal Intent" },
  { key: "BTTS_Friction", label: "BTTS Friction" },
  { key: "Box_Dominance", label: "Box Dominance" },
  { key: "Corner_Power", label: "Corner Power" },
];

const RAW_METRIC_LABELS: Record<keyof DnaV2Profile["Raw_Audit_Metrics"], string> = {
  Avg_Corners: "Avg Corners",
  Estimated_Crosses: "Estimated Crosses",
  Estimated_Blocks: "Estimated Blocks",
  Dangerous_Attacks: "Dangerous Attacks",
  Passing_Control: "Passing Control",
  Big_Chances_Created: "Big Chances Created",
  Shots_Insidebox: "Shots Insidebox",
  Shots_Outsidebox: "Shots Outsidebox",
  Inside_Shot_Ratio_Pct: "Inside Shot Ratio %",
  Tackles_Avg: "Tackles (avg)",
  Interceptions_Avg: "Interceptions (avg)",
  Own_Pass_Quality_Pct: "Own Pass Quality %",
  Opp_Pass_Acc_Allowed: "Opp Pass Acc. Allowed",
  Opp_Dangerous_Attacks: "Opp Dangerous Attacks",
  Resistance_Score: "Resistance Score",
};

function initials(name: string | undefined): string {
  if (!name) return "??";
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join("");
}

function TeamAvatar({ name }: { name: string | undefined }) {
  return (
    <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-border-bright bg-bg-elevated font-mono text-sm font-bold text-text-primary">
      {initials(name)}
    </div>
  );
}

function FactorRow({ factor }: { factor: DnaV2Factor }) {
  return (
    <div className="flex items-center gap-3 py-2">
      <span
        className={cn(
          "w-16 shrink-0 text-right font-mono text-sm font-bold tabular-nums",
          factor.winner === "home" ? "text-accent-green" : "text-text-dim"
        )}
      >
        {factor.home_value}
      </span>
      <div className="flex-1 text-center">
        <p className="text-xs text-text-secondary">{factor.name}</p>
        <p className="mt-0.5 font-mono text-2xs uppercase tracking-wider text-text-dim">
          {factor.winner === "neutral" ? "Neutral" : factor.winner === "home" ? "Home edge" : "Away edge"}
        </p>
      </div>
      <span
        className={cn(
          "w-16 shrink-0 text-left font-mono text-sm font-bold tabular-nums",
          factor.winner === "away" ? "text-accent-green" : "text-text-dim"
        )}
      >
        {factor.away_value}
      </span>
    </div>
  );
}

function PillarBar({
  label,
  home,
  away,
}: {
  label: string;
  home: number;
  away: number;
}) {
  const total = Math.max(home + away, 1);
  const homePct = (home / total) * 100;
  return (
    <div className="py-2">
      <div className="mb-1 flex items-center justify-between text-2xs">
        <span className="font-mono font-semibold text-text-primary">{home}</span>
        <span className="uppercase tracking-wider text-text-muted">{label}</span>
        <span className="font-mono font-semibold text-text-primary">{away}</span>
      </div>
      <div className="flex h-1.5 overflow-hidden rounded-full bg-bg-elevated">
        <div className="bg-accent-indigo" style={{ width: `${homePct}%` }} />
        <div className="flex-1 bg-accent-cyan" />
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-border bg-bg-card p-4">
      <h2 className="mb-3 font-mono text-2xs font-semibold uppercase tracking-wider text-text-muted">
        {title}
      </h2>
      {children}
    </section>
  );
}

export default function DnaAnalysisPage() {
  const params = useParams<{ market: string; fixtureId: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const date = searchParams.get("date") ?? "";

  const { data, loading, isRefetching } = useDnaV2();

  const market = VALID_MARKETS.has(params.market)
    ? (params.market as DnaV2MarketKey)
    : "win";

  const entry: DnaV2FixtureFactors | undefined =
    data?.market_factors?.[params.fixtureId];

  const clash = useMemo(
    () => data?.fixture_clashes.find((c) => String(c.fixture_id) === params.fixtureId),
    [data, params.fixtureId]
  );

  const homeProfile: DnaV2Profile | undefined = useMemo(() => {
    if (!data || !entry) return undefined;
    return Object.values(data.dna_profiles).find(
      (p) => p.team_name === entry.home_team
    );
  }, [data, entry]);

  const awayProfile: DnaV2Profile | undefined = useMemo(() => {
    if (!data || !entry) return undefined;
    return Object.values(data.dna_profiles).find(
      (p) => p.team_name === entry.away_team
    );
  }, [data, entry]);

  const marketCounts = entry?.markets?.[market];
  const totalFactors = marketCounts
    ? marketCounts.home_count + marketCounts.away_count + marketCounts.factors.filter((f) => f.winner === "neutral").length
    : 0;
  const homePct = totalFactors > 0 && marketCounts ? Math.round((marketCounts.home_count / totalFactors) * 100) : 0;
  const awayPct = totalFactors > 0 && marketCounts ? Math.round((marketCounts.away_count / totalFactors) * 100) : 0;

  const showLoading = loading && !entry;

  return (
    <div className="fixed inset-0 z-[70] flex flex-col overflow-y-auto bg-bg-primary">
      {/* Header */}
      <header className="sticky top-0 z-10 flex shrink-0 items-center gap-3 border-b border-border bg-bg-primary/95 px-4 py-3 backdrop-blur-md">
        <button
          type="button"
          onClick={() => router.back()}
          aria-label="Close DNA analysis"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded border border-border text-text-secondary transition-colors hover:border-border-bright hover:text-text-primary"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-text-primary">
            {entry?.fixture ?? "DNA Analysis"}
          </p>
          <p className="font-mono text-2xs uppercase tracking-wider text-text-muted">
            {MARKET_LABELS[market]} DNA · Engine v2
          </p>
        </div>
        {isRefetching && <Loader2 className="h-4 w-4 shrink-0 animate-spin text-accent-indigo" />}
      </header>

      {showLoading ? (
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-accent-indigo" />
        </div>
      ) : !entry || !homeProfile || !awayProfile ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center">
          <Swords className="h-6 w-6 text-text-dim" />
          <p className="text-sm text-text-secondary">No DNA v2 data available for this fixture yet.</p>
          <p className="text-2xs text-text-dim">Run the DNA v2 engine for this date, then reopen this page.</p>
        </div>
      ) : (
        <div className="mx-auto w-full max-w-3xl flex-1 space-y-4 px-4 py-4 md:px-6 md:py-6">
          {/* Team header + DNA count for this market */}
          <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-bg-card p-4">
            <div className="flex min-w-0 flex-1 items-center gap-2.5">
              <TeamAvatar name={entry.home_team} />
              <span className="truncate text-sm font-semibold text-text-primary">{entry.home_team}</span>
            </div>

            <div className="flex shrink-0 flex-col items-center px-2">
              <div className="font-mono text-2xl font-bold tabular-nums text-text-primary">
                {marketCounts?.home_count ?? 0}
                <span className="mx-1 text-text-dim">:</span>
                {marketCounts?.away_count ?? 0}
              </div>
              <p className="font-mono text-2xs uppercase tracking-wider text-text-dim">
                {MARKET_LABELS[market]} DNA count
              </p>
            </div>

            <div className="flex min-w-0 flex-1 items-center justify-end gap-2.5">
              <span className="truncate text-right text-sm font-semibold text-text-primary">{entry.away_team}</span>
              <TeamAvatar name={entry.away_team} />
            </div>
          </div>

          {/* DNA percentage + structural edge */}
          <Section title="Structural edge">
            <div className="mb-3 flex h-2 overflow-hidden rounded-full bg-bg-elevated">
              <div className="bg-accent-indigo" style={{ width: `${homePct}%` }} />
              <div className="bg-accent-cyan" style={{ width: `${awayPct}%` }} />
            </div>
            <div className="flex items-center justify-between text-2xs text-text-muted">
              <span>{entry.home_team} — {homePct}%</span>
              <span className="font-semibold text-text-primary">
                Overall edge: {clash?.overall_structural_edge ?? "Contested"}
              </span>
              <span>{entry.away_team} — {awayPct}%</span>
            </div>
          </Section>

          {/* Market signals from the style clash */}
          {clash && (
            <Section title="Market signals (style clash)">
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="rounded border border-border bg-bg-elevated/40 p-2">
                  <p className="font-mono text-2xs text-text-dim">Over/Under</p>
                  <p className="mt-1 text-xs font-semibold text-text-primary">{clash.market_signals.Over_Under}</p>
                </div>
                <div className="rounded border border-border bg-bg-elevated/40 p-2">
                  <p className="font-mono text-2xs text-text-dim">GG/No GG</p>
                  <p className="mt-1 text-xs font-semibold text-text-primary">{clash.market_signals.GG_NoGG}</p>
                </div>
                <div className="rounded border border-border bg-bg-elevated/40 p-2">
                  <p className="font-mono text-2xs text-text-dim">Corners</p>
                  <p className="mt-1 text-xs font-semibold text-text-primary">{clash.market_signals.Corners}</p>
                </div>
              </div>
            </Section>
          )}

          {/* Per-market factor breakdown — the exact factors behind the count above */}
          {marketCounts && (
            <Section title={`${MARKET_LABELS[market]} DNA factors`}>
              <div className="divide-y divide-border/40">
                {marketCounts.factors.map((factor) => (
                  <FactorRow key={factor.name} factor={factor} />
                ))}
              </div>
            </Section>
          )}

          {/* Market Power Scores — all five pillars, both teams */}
          <Section title="Market power scores">
            {PILLARS.map((p) => (
              <PillarBar
                key={p.key}
                label={p.label}
                home={homeProfile.Market_Power_Scores[p.key]}
                away={awayProfile.Market_Power_Scores[p.key]}
              />
            ))}
          </Section>

          {/* Tactical DNA — full block for both teams */}
          <Section title="Tactical DNA">
            <div className="grid grid-cols-2 gap-4">
              {[
                { name: entry.home_team, tactical: homeProfile.Tactical_DNA, archetype: homeProfile.Archetype },
                { name: entry.away_team, tactical: awayProfile.Tactical_DNA, archetype: awayProfile.Archetype },
              ].map((side) => (
                <div key={side.name} className="space-y-1.5">
                  <p className="truncate text-xs font-semibold text-text-primary">{side.name}</p>
                  <p className="text-2xs text-accent-indigo">{side.archetype}</p>
                  <dl className="space-y-1 font-mono text-2xs text-text-secondary">
                    <div className="flex justify-between"><dt className="text-text-dim">Tempo</dt><dd>{side.tactical.Tempo}</dd></div>
                    <div className="flex justify-between"><dt className="text-text-dim">Line Height</dt><dd>{side.tactical.Line_Height}</dd></div>
                    <div className="flex justify-between"><dt className="text-text-dim">Risk Appetite</dt><dd>{side.tactical.Risk_Appetite}</dd></div>
                    <div className="flex justify-between"><dt className="text-text-dim">Verticality</dt><dd>{side.tactical.Verticality}</dd></div>
                    <div className="flex justify-between"><dt className="text-text-dim">Shot Quality</dt><dd className="text-right">{side.tactical.Shot_Quality}</dd></div>
                    <div className="flex justify-between"><dt className="text-text-dim">Transition</dt><dd className="text-right">{side.tactical.Transition_Style}</dd></div>
                    <div className="flex justify-between"><dt className="text-text-dim">Transition Score</dt><dd>{side.tactical.Transition_Score}</dd></div>
                  </dl>
                </div>
              ))}
            </div>
          </Section>

          {/* Raw Audit Metrics — every field, nothing hidden */}
          <Section title="Raw audit metrics">
            <div className="divide-y divide-border/40">
              {(Object.keys(RAW_METRIC_LABELS) as Array<keyof DnaV2Profile["Raw_Audit_Metrics"]>).map((key) => (
                <div key={key} className="flex items-center justify-between py-1.5 text-xs">
                  <span className="font-mono text-sm font-semibold tabular-nums text-text-primary">
                    {homeProfile.Raw_Audit_Metrics[key]}
                  </span>
                  <span className="px-2 text-center text-2xs text-text-muted">{RAW_METRIC_LABELS[key]}</span>
                  <span className="font-mono text-sm font-semibold tabular-nums text-text-primary">
                    {awayProfile.Raw_Audit_Metrics[key]}
                  </span>
                </div>
              ))}
            </div>
          </Section>

          <p className="pb-4 text-center font-mono text-2xs text-text-dim">
            Source: DNA Engine V2 · {date || "latest"}
          </p>
        </div>
      )}
    </div>
  );
}
