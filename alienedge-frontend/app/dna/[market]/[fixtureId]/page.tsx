"use client";

import { useCallback, useMemo } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, Loader2, Swords } from "lucide-react";
import { cn } from "@/lib/utils";
import { useDnaV2 } from "@/lib/use-dna-v2";
import { useApi } from "@/lib/use-api";
import { dnaV2Api, type DnaV2H2HResponse, type DnaV2MatchMeta, type DnaV2MatchMetaResponse } from "@/lib/api";
import SportyMatchOverview from "@/components/dna/SportyMatchOverview";
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

/**
 * Renders a schema v4 nullable figure. `null` means UNMEASURED — it must not
 * print as a number, and it must not print as a blank cell either. A dash is
 * the only honest rendering of "we never measured this".
 */
function fmt(v: number | null): number | string {
  return v == null ? "—" : v;
}

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

/**
 * One pairwise factor row.
 *
 * Three non-win outcomes must be visually distinct from a real verdict:
 *   unknown   — one side was never measured
 *   undecided — both measured, gap inside the measurement noise floor
 *   neutral   — the two values are exactly equal
 * Only "home"/"away" are wins, and only those get the accent colour.
 */
function FactorRow({ factor }: { factor: DnaV2Factor }) {
  // A null value is UNMEASURED, not zero. It gets an em-dash and an explicit
  // "Not measured" verdict rather than a number and a colour, so a data gap
  // is never dressed up as a losing (or winning) score.
  const unknown = factor.winner === "unknown";
  const undecided = factor.winner === "undecided";
  const verdict = unknown
    ? "Not measured"
    : undecided
      ? `Too close (${factor.difference ?? "?"} vs ${factor.min_margin ?? "?"} needed)`
      : factor.winner === "neutral"
        ? "Neutral"
        : factor.winner === "home"
          ? "Home edge"
          : "Away edge";

  return (
    <div className={cn("flex items-center gap-3 py-2", (unknown || undecided) && "opacity-60")}>
      <span
        className={cn(
          "w-16 shrink-0 text-right font-mono text-sm font-bold tabular-nums",
          factor.winner === "home" ? "text-accent-green" : "text-text-dim"
        )}
      >
        {fmt(factor.home_value)}
      </span>
      <div className="flex-1 text-center">
        <p className="text-xs text-text-secondary">{factor.name}</p>
        <p className="mt-0.5 font-mono text-2xs uppercase tracking-wider text-text-dim">
          {verdict}
        </p>
      </div>
      <span
        className={cn(
          "w-16 shrink-0 text-left font-mono text-sm font-bold tabular-nums",
          factor.winner === "away" ? "text-accent-green" : "text-text-dim"
        )}
      >
        {fmt(factor.away_value)}
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
  home: number | null;
  away: number | null;
}) {
  // An unmeasured pillar has no ratio to draw, so the track stays empty rather
  // than showing one side at 100% because the other side is unknown.
  const known = home != null && away != null;
  const total = known ? Math.max((home as number) + (away as number), 1) : 0;
  const homePct = known ? ((home as number) / total) * 100 : 0;
  return (
    <div className="py-2">
      <div className="mb-1 flex items-center justify-between text-2xs">
        <span className={cn("font-mono font-semibold", known ? "text-text-primary" : "text-text-dim")}>
          {fmt(home)}
        </span>
        <span className="uppercase tracking-wider text-text-muted">{label}</span>
        <span className={cn("font-mono font-semibold", known ? "text-text-primary" : "text-text-dim")}>
          {fmt(away)}
        </span>
      </div>
      <div className="flex h-1.5 overflow-hidden rounded-full bg-bg-elevated">
        {known ? (
          <>
            <div className="bg-accent-indigo" style={{ width: `${homePct}%` }} />
            <div className="flex-1 bg-accent-cyan" />
          </>
        ) : null}
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

  const { data, loading, isRefetching } = useDnaV2(date || undefined);

  // League / competition / table position for the SportyBet-style header.
  // Disk-only on the backend (it joins cache files this same run already
  // wrote), so this adds no engine run and no provider call. A failure is
  // non-fatal: the header simply keeps its em-dashes.
  //
  // With no date selected there is nothing to look up, so no request is made
  // at all. The empty case still returns a well-typed response rather than
  // null: useApi chains `request.then(...)` OUTSIDE its try/catch, so a null
  // return would throw instead of resolving.
  const matchMetaFetcher = useCallback((): ReturnType<typeof dnaV2Api.getMatchMeta> => {
    if (!date) {
      return Promise.resolve({
        data: { date: "", fixtures: {} },
      } as Awaited<ReturnType<typeof dnaV2Api.getMatchMeta>>);
    }
    return dnaV2Api.getMatchMeta(date);
  }, [date]);
  const { data: matchMetaRes } = useApi<DnaV2MatchMetaResponse>(
    matchMetaFetcher,
    [date],
    { cacheKey: date ? `dna-match-meta:${date}` : "dna-match-meta:none" }
  );
  const matchMeta: DnaV2MatchMeta | undefined = matchMetaRes?.fixtures?.[params.fixtureId];

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

  // The DNA "count" is not a strength score and it is not a prediction.
// Measured on a 130-fixture temporal holdout (each team's DNA built only from
// matches strictly BEFORE the fixture it judged), the count picked the winner
// 52.0% of the time versus 58.8% for always choosing the home team (p = 0.19,
// indistinguishable from a coin flip). Adding recent form did not help (51.0%).
// It is a style-statistic comparison, so it is labelled and sized as one.
//
// Three outcomes per factor, not two:
//   unknown   — one side's stat was never measured (never weighed)
//   undecided — both measured, but the gap is inside the measurement noise
//   home/away — the gap is real and larger than that noise floor
// Only home/away award a point. `undecided` must be excluded from the
// denominator too, otherwise a 2-0 built from two real separators out of six
// factors renders as a confident-looking bar.
const unknownFactors =
  marketCounts?.factors.filter((f) => f.winner === "unknown").length ?? 0;
const undecidedFactors =
  marketCounts?.factors.filter((f) => f.winner === "undecided").length ?? 0;
const neutralFactors =
  marketCounts?.factors.filter((f) => f.winner === "neutral").length ?? 0;
const decidedFactors = marketCounts
  ? marketCounts.factors.length - unknownFactors - undecidedFactors - neutralFactors
  : 0;
// Denominator = factors that actually produced a verdict for either side.
const totalFactors = marketCounts
  ? marketCounts.home_count + marketCounts.away_count
  : 0;
const homePct = totalFactors > 0 && marketCounts ? Math.round((marketCounts.home_count / totalFactors) * 100) : 0;
const awayPct = totalFactors > 0 && marketCounts ? Math.round((marketCounts.away_count / totalFactors) * 100) : 0;

  // Which side, if either, has too little measured data for its pillars to
  // mean anything. Such a team must be shown as UNMEASURED, never as weak.
  const lowCoverage = useMemo(() => {
    const flagged: string[] = [];
    for (const p of [homeProfile, awayProfile]) {
      if (!p) continue;
      const cov = p.Data_Coverage;
      const weak = p.insufficient_data === true || (cov ? cov.Stats_Matches < 3 : false);
      if (weak) {
        flagged.push(
          cov
            ? `${p.team_name} — only ${cov.Stats_Matches} of ${cov.Stats_Sample} matches had provider stats`
            : `${p.team_name} — insufficient match data`
        );
      }
    }
    return flagged;
  }, [homeProfile, awayProfile]);

  const showLoading = loading && !entry;

  // ── SportyBet-style panel: READ-ONLY mapping of data DNA already has ──────
  // Nothing here computes a prediction. `form_rows` is the display-only field
  // DNA now stores alongside its existing averages (see build_form_rows in
  // CORE/dna_engine_v2.py); it feeds no pillar, archetype or clash. Profiles
  // cached before that field existed simply lack it, and every panel below
  // degrades to an em-dash rather than inventing a result.
  //
  // HEAD-TO-HEAD IS NOW REAL. This block previously generated five hardcoded
  // "demo" rows with dates fixed at 2026-06-14 / 2026-03-22 / 2025-11-09 /
  // 2025-08-16 / 2025-03-23 and scorelines derived from a character-code hash
  // of the two team names — so every fixture on the site showed the same five
  // fabricated meetings, usually reading 1-1. They were labelled "demo", but
  // they were still invented results sitting where real history belongs, and
  // they were removed rather than kept.
  //
  // /api/dna/v2/h2h/{date}/{fixtureId} is the replacement: the provider's own
  // finished meetings between these two team ids. The counts and the "Highest
  // Win" callout are computed inside the component FROM that list, so the donut
  // and the meeting rows cannot disagree.
  //
  // `h2hError` is passed through rather than collapsed into an empty list,
  // because "these teams have never met" and "the provider was throttled" are
  // different facts and only one of them is a claim about the fixture.
  const h2hFetcher = useCallback((): ReturnType<typeof dnaV2Api.getH2H> => {
    if (!date || !params.fixtureId) {
      // Same reason match-meta returns a well-typed empty object rather than
      // null: useApi chains `.then()` outside its try/catch, so a null return
      // would throw instead of resolving. Cast through `unknown` because only
      // the `data` field is meaningful here — status/headers are never read.
      return Promise.resolve({
        data: {
          date: date ?? "",
          fixture_id: params.fixtureId ?? "",
          home_team: null,
          away_team: null,
          home_id: null,
          away_id: null,
          meetings: [],
          error: "no_data" as const,
        },
      } as unknown as Awaited<ReturnType<typeof dnaV2Api.getH2H>>);
    }
    return dnaV2Api.getH2H(date, params.fixtureId);
  }, [date, params.fixtureId]);

  const { data: h2hRes } = useApi<DnaV2H2HResponse>(h2hFetcher, [date, params.fixtureId], {
    cacheKey: date && params.fixtureId ? `dna-h2h:${date}:${params.fixtureId}` : "dna-h2h:none",
  });
  const h2h = h2hRes;

  // The provider identifies the two sides by id. Passing them through is what
  // lets the component attribute each past meeting to the right club when the
  // two have swapped venues since.
  const homeId = h2h?.home_id ?? null;
  const awayId = h2h?.away_id ?? null;

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
          {/* Data-coverage warning. A team whose provider stats never arrived is
              UNMEASURED, not weak — without this the zeros below read as a real
              assessment and the whole page silently misleads. */}
          {lowCoverage.length > 0 && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3">
              <p className="font-mono text-2xs font-semibold uppercase tracking-wider text-amber-400">
                Insufficient data — read the numbers below with care
              </p>
              <ul className="mt-1.5 space-y-0.5">
                {lowCoverage.map((msg) => (
                  <li key={msg} className="text-xs text-amber-200/80">
                    • {msg}. Any DNA figure shown as &ldquo;&mdash;&rdquo; was never measured, not zero.
                  </li>
                ))}
              </ul>
            </div>
          )}
          {/* SportyBet-style match header + H2H statistics.
              Mounted FIRST so it sits above the DNA engine output, which is
              left entirely untouched below. Read-only: it renders history and
              never contributes to a prediction. */}
          <SportyMatchOverview
            homeTeam={entry.home_team}
            awayTeam={entry.away_team}
            homeId={homeId}
            awayId={awayId}
            competition={matchMeta?.league_name ?? null}
            matchday={null}
            leagueGroup={matchMeta?.season_name ?? null}
            homePosition={matchMeta?.home_position ?? null}
            awayPosition={matchMeta?.away_position ?? null}
            isUnranked={matchMeta?.is_unranked ?? false}
            homeForm={homeProfile?.form_rows}
            awayForm={awayProfile?.form_rows}
            h2hMeetings={h2h?.meetings ?? null}
            h2hError={h2h?.error ?? null}
          />

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
                {MARKET_LABELS[market]} style factors
              </p>
            </div>

            <div className="flex min-w-0 flex-1 items-center justify-end gap-2.5">
              <span className="truncate text-right text-sm font-semibold text-text-primary">{entry.away_team}</span>
              <TeamAvatar name={entry.away_team} />
            </div>
          </div>

          {/* Factor split — NOT a strength percentage.
            This bar is the ratio of pairwise factors won. It was previously
            presented as "AFC Rushden & Diamonds — 13%", which reads as a
            13%-as-strong judgement but actually means "won 1 of 8 coin
            flips". It is now labelled with what it actually counts, and
            factors nobody could measure are disclosed instead of folded
            silently into the denominator. */}
          <Section title="Factor split">
            <div className="mb-3 flex h-2 overflow-hidden rounded-full bg-bg-elevated">
              <div className="bg-accent-indigo" style={{ width: `${homePct}%` }} />
              <div className="bg-accent-cyan" style={{ width: `${awayPct}%` }} />
            </div>
            <div className="flex items-center justify-between text-2xs text-text-muted">
              <span>
                {entry.home_team} — won {marketCounts?.home_count ?? 0}
              </span>
              <span className="font-semibold text-text-primary">
                Overall edge: {clash?.overall_structural_edge ?? "Contested"}
              </span>
              <span>
                won {marketCounts?.away_count ?? 0} — {entry.away_team}
              </span>
            </div>
            <p className="mt-2 text-center text-2xs leading-relaxed text-text-dim">
              {decidedFactors} of {marketCounts?.factors.length ?? 0} factors separated the teams
              {undecidedFactors > 0 && ` · ${undecidedFactors} too close to call`}
              {neutralFactors > 0 && ` · ${neutralFactors} tied`}
              {unknownFactors > 0 && ` · ${unknownFactors} not measured`}
              {totalFactors > 0 && ` · ${homePct}% / ${awayPct}% of separated factors`}
              {decidedFactors === 0 && unknownFactors === 0 && " — every factor was inside measurement noise"}
              {decidedFactors === 0 && unknownFactors > 0 && " — no factor could be measured for either side"}
            </p>
            <p className="mt-2 text-center text-2xs leading-relaxed text-text-dim">
              This is a comparison of style statistics, not a strength score and not a
              forecast. On a 130-fixture holdout it picked the winner 52% of the time
              versus 59% for always choosing the home team.
            </p>
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
                    <div className="flex justify-between"><dt className="text-text-dim">Tempo</dt><dd>{fmt(side.tactical.Tempo)}</dd></div>
                    <div className="flex justify-between"><dt className="text-text-dim">Line Height</dt><dd>{side.tactical.Line_Height}</dd></div>
                    <div className="flex justify-between"><dt className="text-text-dim">Risk Appetite</dt><dd>{side.tactical.Risk_Appetite}</dd></div>
                    <div className="flex justify-between"><dt className="text-text-dim">Verticality</dt><dd>{side.tactical.Verticality}</dd></div>
                    <div className="flex justify-between"><dt className="text-text-dim">Shot Quality</dt><dd className="text-right">{side.tactical.Shot_Quality}</dd></div>
                    <div className="flex justify-between"><dt className="text-text-dim">Transition</dt><dd className="text-right">{side.tactical.Transition_Style}</dd></div>
                    <div className="flex justify-between"><dt className="text-text-dim">Transition Score</dt><dd>{fmt(side.tactical.Transition_Score)}</dd></div>
                  </dl>
                </div>
              ))}
            </div>
          </Section>

          {/* Raw Audit Metrics — every field, nothing hidden.
              A null value renders as an em-dash and dims the row: it was never
              measured. Printing the raw null here would have produced a blank
              cell that reads like a rendering fault rather than a known gap. */}
          <Section title="Raw audit metrics">
            <div className="divide-y divide-border/40">
              {(Object.keys(RAW_METRIC_LABELS) as Array<keyof DnaV2Profile["Raw_Audit_Metrics"]>).map((key) => {
                const hv = homeProfile.Raw_Audit_Metrics[key];
                const av = awayProfile.Raw_Audit_Metrics[key];
                const unknown = hv == null || av == null;
                const cell = (v: number | null, align: string) => (
                  <span
                    className={cn(
                      "font-mono text-sm font-semibold tabular-nums",
                      align,
                      v == null ? "text-text-dim" : "text-text-primary"
                    )}
                  >
                    {v == null ? "—" : v}
                  </span>
                );
                return (
                  <div
                    key={key}
                    className={cn("flex items-center justify-between py-1.5 text-xs", unknown && "opacity-70")}
                    title={unknown ? "Not measured by the provider — this is a data gap, not a zero" : undefined}
                  >
                    {cell(hv, "text-right")}
                    <span className="px-2 text-center text-2xs text-text-muted">{RAW_METRIC_LABELS[key]}</span>
                    {cell(av, "text-left")}
                  </div>
                );
              })}
            </div>
            <p className="mt-2 text-center text-2xs text-text-dim">
              &ldquo;&mdash;&rdquo; means the provider never reported this stat — it is not a zero.
            </p>
          </Section>

          <p className="pb-4 text-center font-mono text-2xs text-text-dim">
            Source: DNA Engine V2 · {date || "latest"}
          </p>
        </div>
      )}
    </div>
  );
}
