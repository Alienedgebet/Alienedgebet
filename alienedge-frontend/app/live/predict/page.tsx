"use client";

import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Search,
  ShieldAlert,
  Timer,
} from "lucide-react";
import {
  liveApi,
  type LivePrediction,
  type LivePredictionJudge,
} from "@/lib/api";
import { ScoreBar } from "@/components/predictions";
import { cn } from "@/lib/utils";

/**
 * LIVE PREDICTION — Stage 8.
 *
 * Type two team names, get the match as it stands. This is a different engine
 * from the Code 6 storm: that one watches for a structural storm and could not
 * fire before 45' at all, because it needs a settled pressure majority. This one
 * reasons from minutes remaining and live chance creation, so it is meaningful
 * from the first minute.
 *
 * Nothing here is hidden. Every probability, every question the engine asked,
 * the source field each answer came from, and all five judges' verdicts are on
 * the page by default. If the judges block the prediction, no numbers are
 * shown — the engine would rather say nothing than guess.
 */

function VerdictBadge({ verdict }: { verdict: LivePrediction["verdict"] }) {
  if (!verdict) return null;
  const map = {
    PASS: {
      cls: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
      icon: CheckCircle2,
      text: "Judged pass",
    },
    WARN: {
      cls: "border-amber-500/40 bg-amber-500/10 text-amber-300",
      icon: AlertTriangle,
      text: "Judged with warnings",
    },
    BLOCK: {
      cls: "border-red-500/40 bg-red-500/10 text-red-300",
      icon: ShieldAlert,
      text: "Withheld by judges",
    },
  } as const;
  const { cls, icon: Icon, text } = map[verdict];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] font-semibold uppercase tracking-wide",
        cls
      )}
    >
      <Icon className="h-3.5 w-3.5" />
      {text}
    </span>
  );
}

function Market({
  label,
  value,
  hint,
}: {
  label: string;
  value: number;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.03] p-3">
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <span className="text-[11px] uppercase tracking-wide text-white/55">
          {label}
        </span>
        <span className="text-lg font-bold tabular-nums text-white">
          {value.toFixed(1)}%
        </span>
      </div>
      <ScoreBar score={value} max={100} showValue={false} />
      {hint ? (
        <p className="mt-1.5 text-[10px] leading-snug text-white/40">{hint}</p>
      ) : null}
    </div>
  );
}

function JudgeRow({ judge }: { judge: LivePredictionJudge }) {
  const tone =
    judge.verdict === "PASS"
      ? "text-emerald-300"
      : judge.verdict === "WARN"
        ? "text-amber-300"
        : "text-red-300";
  return (
    <li className="flex flex-col gap-0.5 border-b border-white/5 py-2 last:border-0">
      <span className="flex items-center gap-2 text-xs font-semibold text-white/75">
        <span className={cn("font-mono", tone)}>[{judge.verdict}]</span>
        {judge.judge}
      </span>
      <span className="text-[11px] leading-snug text-white/50">
        {judge.reason}
      </span>
    </li>
  );
}

export default function LivePredictPage() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<{
    matches: { fixture_id: string; name: string; minute?: number | null }[];
    prediction: LivePrediction | null;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  async function runSearch(q: string) {
    const trimmed = q.trim();
    if (!trimmed) return;
    setLoading(true);
    setSearched(true);
    try {
      const { data } = await liveApi.searchPrediction(trimmed);
      setResult({ matches: data.matches, prediction: data.prediction });
    } catch {
      setResult({ matches: [], prediction: null });
    } finally {
      setLoading(false);
    }
  }

  const p = result?.prediction ?? null;

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-white">Live Match Prediction</h1>
        <p className="mt-1.5 max-w-3xl text-sm text-white/55">
          Type both team names to get an instant read of a match already in
          progress — win, draw, who scores, and where the goal total is heading.
          Every number below is shown with the questions the engine asked and the
          five independent judges that verified it.
        </p>
      </header>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void runSearch(query);
        }}
        className="mb-6 flex gap-2"
      >
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="e.g. denmark portugal"
          aria-label="Two team names"
          className="flex-1 rounded-lg border border-white/15 bg-white/[0.04] px-4 py-2.5 text-sm text-white outline-none placeholder:text-white/30 focus:border-white/40"
        />
        <button
          type="submit"
          disabled={loading || !query.trim()}
          className="inline-flex items-center gap-2 rounded-lg bg-white px-5 py-2.5 text-sm font-semibold text-black disabled:opacity-40"
        >
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Search className="h-4 w-4" />
          )}
          Predict
        </button>
      </form>

      {searched && !loading && result?.matches.length === 0 ? (
        <p className="rounded-lg border border-white/10 bg-white/[0.03] p-4 text-sm text-white/60">
          No live match found for that. Check the spelling, or try just one
          team name.
        </p>
      ) : null}

      {result && result.matches.length > 1 ? (
        <div className="mb-4 flex flex-wrap gap-2">
          {result.matches.map((m) => (
            <span
              key={m.fixture_id}
              className="rounded-md border border-white/10 px-2 py-1 text-[11px] text-white/60"
            >
              {m.name}
              {m.minute != null ? ` · ${m.minute}'` : ""}
            </span>
          ))}
        </div>
      ) : null}

      {p ? (
        <section className="space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-white/10 bg-white/[0.03] p-4">
            <div>
              <h2 className="text-lg font-semibold text-white">{p.fixture}</h2>
              <p className="mt-1 flex items-center gap-3 text-xs text-white/55">
                <span className="inline-flex items-center gap-1">
                  <Timer className="h-3.5 w-3.5" />
                  {p.minute}&apos;
                </span>
                <span className="font-mono">{p.score}</span>
                <span
                  className={cn(
                    "rounded px-1.5 py-0.5 text-[10px] font-semibold",
                    p.mode === "FULL"
                      ? "bg-emerald-500/15 text-emerald-300"
                      : "bg-amber-500/15 text-amber-300"
                  )}
                >
                  {p.mode === "FULL"
                    ? "Full intelligence"
                    : "Live state only"}
                </span>
              </p>
            </div>
            <VerdictBadge verdict={p.verdict} />
          </div>

          {p.mode === "LIVE_ONLY" ? (
            <p className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-[11px] leading-relaxed text-amber-200/90">
              No pre-match audit exists for this match — the provider never
              returned an official lineup — so there is no keeper, absence or
              market intelligence to draw on. This reading uses the
              match&apos;s own chance creation only.
            </p>
          ) : null}

          {p.predictions ? (
            <>
              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-white/45">
                  Result
                </h3>
                <div className="grid gap-3 sm:grid-cols-3">
                  <Market
                    label={`${p.home_team} win`}
                    value={p.predictions.home_win}
                  />
                  <Market label="Draw" value={p.predictions.draw} />
                  <Market
                    label={`${p.away_team} win`}
                    value={p.predictions.away_win}
                  />
                </div>
              </div>

              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-white/45">
                  To score
                </h3>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Market
                    label={`${p.predictions.home_to_score.team} to score`}
                    value={p.predictions.home_to_score.pct}
                  />
                  <Market
                    label={`${p.predictions.away_to_score.team} to score`}
                    value={p.predictions.away_to_score.pct}
                  />
                </div>
              </div>

              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-white/45">
                  Goals
                </h3>
                <div className="grid gap-3 sm:grid-cols-3">
                  <Market label="Over 2.5" value={p.predictions.over_2_5} />
                  <Market label="Under 3.5" value={p.predictions.under_3_5} />
                  <Market
                    label="Exactly 3 goals"
                    value={p.predictions.exactly_3_goals}
                    hint="Over 2.5 and Under 3.5 overlap here — this is the band they share."
                  />
                </div>
              </div>
            </>
          ) : (
            <p className="rounded-lg border border-white/10 bg-white/[0.03] p-4 text-sm text-white/60">
              No prediction is shown.{" "}
              {p.error ?? "The judges withheld this one."}
            </p>
          )}

          <div className="grid gap-5 lg:grid-cols-2">
            <div className="rounded-lg border border-white/10 bg-white/[0.03] p-4">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-white/45">
                What the engine asked
              </h3>
              <ul className="space-y-2.5">
                {p.trace.map((q) => (
                  <li
                    key={q.id}
                    className="border-b border-white/5 pb-2 last:border-0"
                  >
                    <p className="text-[11px] font-medium text-white/80">
                      {q.question}
                    </p>
                    <p
                      className={cn(
                        "mt-0.5 text-[11px] leading-snug",
                        q.available
                          ? "text-white/50"
                          : "text-white/30 italic"
                      )}
                    >
                      {q.answer}
                    </p>
                    <p className="mt-0.5 font-mono text-[9px] text-white/25">
                      src: {q.source}
                    </p>
                  </li>
                ))}
              </ul>
            </div>

            <div className="rounded-lg border border-white/10 bg-white/[0.03] p-4">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-white/45">
                Independent judges
              </h3>
              {p.judges && p.judges.length ? (
                <ul>
                  {p.judges.map((j) => (
                    <JudgeRow key={j.judge} judge={j} />
                  ))}
                </ul>
              ) : (
                <p className="text-[11px] text-white/40">
                  No prediction was issued, so no panel ran.
                </p>
              )}
              {p.model ? (
                <p className="mt-3 border-t border-white/10 pt-2 font-mono text-[9px] leading-relaxed text-white/30">
                  anchor: {p.model.anchor} · total{" "}
                  {p.model.anchor_total_goals} · {p.model.minutes_remaining}{" "}
                  min left
                </p>
              ) : null}
            </div>
          </div>
        </section>
      ) : null}
    </main>
  );
}
