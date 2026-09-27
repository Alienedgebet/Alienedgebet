"use client";

import { useState, useMemo, type ReactNode } from "react";
import {
  Bell,
  Flame,
  CheckCircle,
  Activity,
  RefreshCw,
  ChevronRight,
  Info,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { QuickHistoryStrip } from "@/components/layout/QuickHistoryStrip";
import { useSelectedDate } from "@/lib/date-context";
import { useApi } from "@/lib/use-api";
import { liveApi, type LiveAlertPick } from "@/lib/api";
import { MOCK_LIVE_ALERTS } from "@/lib/mock-chains";

/**
 * One card per fixture. The storm track can fire up to three times on the
 * same match, so three near-identical cards is noise; one card turns the
 * escalation into the story.
 */
type StormGroup = {
  f_id: string;
  fixture: string;
  alerts: LiveAlertPick[];
  peak: LiveAlertPick;
  first: LiveAlertPick;
};

const STAGE_ORDER: Record<string, number> = {
  developing: 0,
  sustained: 1,
  peaking: 2,
};

const STAGE_LABEL: Record<string, string> = {
  developing: "Developing",
  sustained: "Sustained",
  peaking: "Peaking",
};

const OUTCOME: Record<string, { label: string; tone: string; note: string }> = {
  goal_followed: {
    label: "Goal followed",
    tone: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
    note: "At least one goal was scored after this alert fired.",
  },
  no_further_goal: {
    label: "No further goal",
    tone: "border-slate-500/40 bg-slate-500/10 text-slate-300",
    note: "The match finished without another goal.",
  },
  unverifiable: {
    label: "Not verifiable",
    tone: "border-slate-600/40 bg-slate-600/10 text-slate-400",
    note: "No scoreline was recorded when this alert fired, so there is nothing to compare the final score against.",
  },
  pending: {
    label: "Match in progress",
    tone: "border-cyan-500/40 bg-cyan-500/10 text-cyan-300",
    note: "The final score appears here once the match ends.",
  },
};

function Flag({ children, tone }: { children: ReactNode; tone: string }) {
  return (
    <span
      className={cn(
        "rounded-md border px-2 py-0.5 text-[9.5px] font-bold uppercase tracking-wide",
        tone
      )}
    >
      {children}
    </span>
  );
}

/**
 * The verification strip: the score at the instant the storm first fired,
 * against the final score, and whether anything was scored in between.
 *
 * This is what the page was missing entirely. An alert used to be an opinion
 * about a moment with no recorded state, which made it impossible to check.
 * Everything here is descriptive — it states what the scoreline did and makes
 * no claim about how accurate the engine is.
 */
function VerificationStrip({ group }: { group: StormGroup }) {
  const first = group.first;
  const peak = group.peak;
  const trigger = first.score_at_trigger;
  const final = peak.final_score;
  const outcome = peak.outcome ?? "pending";
  const meta = OUTCOME[outcome] ?? OUTCOME.pending;
  const after = peak.goals_after;

  return (
    <div className="rounded-xl border border-white/10 bg-black/30 px-3 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="text-center">
            <p className="font-mono text-xl font-black leading-none text-slate-100">
              {trigger ?? "—"}
            </p>
            <p className="mt-1 text-[9.5px] font-bold uppercase tracking-wide text-slate-500">
              at {first.minute}&apos;
            </p>
          </div>
          <div className="flex flex-col items-center px-1">
            <span className="text-[10px] text-slate-600">→</span>
            <span className="h-4 w-px bg-white/15" />
            <span className="text-[10px] text-slate-600">FT</span>
          </div>
          <div className="text-center">
            <p
              className={cn(
                "font-mono text-xl font-black leading-none",
                final ? "text-white" : "text-slate-600"
              )}
            >
              {final ?? "—"}
            </p>
            <p className="mt-1 text-[9.5px] font-bold uppercase tracking-wide text-slate-500">
              final
            </p>
          </div>
        </div>
        <div className="text-right">
          <Flag tone={meta.tone}>{meta.label}</Flag>
          {after != null && (
            <p className="mt-1 font-mono text-[10px] text-slate-500">
              {after} goal{after === 1 ? "" : "s"} after
            </p>
          )}
        </div>
      </div>
      <p className="mt-2 border-t border-white/10 pt-2 text-[10.5px] leading-relaxed text-slate-500">
        {meta.note}
      </p>
    </div>
  );
}

/** The storm timeline: one node per gate the fixture actually reached. */
function StormTimeline({ group }: { group: StormGroup }) {
  const nodes = useMemo(() => {
    const byStage = new Map<string, LiveAlertPick>();
    for (const a of group.alerts) {
      if (a.storm_stage && !byStage.has(a.storm_stage)) {
        byStage.set(a.storm_stage, a);
      }
    }
    const ordered = (["developing", "sustained", "peaking"] as const)
      .map((s) => ({ stage: s as string, alert: byStage.get(s) }))
      .filter((n) => Boolean(n.alert))
      .sort((a, b) => (STAGE_ORDER[a.stage] ?? 0) - (STAGE_ORDER[b.stage] ?? 0));
    return ordered as Array<{ stage: string; alert: LiveAlertPick }>;
  }, [group]);

  if (nodes.length === 0) return null;

  return (
    <div className="flex items-center">
      {nodes.map((n, i) => (
        <div key={n.stage} className="flex flex-1 items-start last:flex-none">
          <div className="flex flex-col items-center gap-1">
            <span
              className={cn(
                "h-2 w-2 rounded-full",
                n.stage === "peaking"
                  ? "bg-rose-400"
                  : n.stage === "sustained"
                    ? "bg-amber-400"
                    : "bg-cyan-400"
              )}
              aria-hidden
            />
            <span className="font-mono text-[10px] font-bold text-slate-300">
              {n.alert.minute}&apos;
            </span>
            <span className="w-[62px] text-center text-[9.5px] font-semibold leading-tight text-slate-400">
              {STAGE_LABEL[n.stage] ?? n.stage}
            </span>
          </div>
          {i < nodes.length - 1 && (
            <div className="mt-1 h-px flex-1 bg-white/15" aria-hidden />
          )}
        </div>
      ))}
    </div>
  );
}

function AlertGroupCard({ group }: { group: StormGroup }) {
  const peak = group.peak;
  const isPremium = peak.level.includes("PREMIUM");
  const isStandard = peak.level.includes("STANDARD");
  const isUserRule = Boolean(peak.rule_id);

  return (
    <article
      className={cn(
        "glass relative flex flex-col gap-3 rounded-2xl border p-4 shadow-xl backdrop-blur-md",
        isPremium
          ? "border-amber-500/30 bg-[#0d1322]/90"
          : isStandard
            ? "border-emerald-500/30 bg-[#0d1322]/90"
            : "border-white/10 bg-[#0d1322]/90"
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-black text-white">{group.fixture}</h3>
          <p className="mt-0.5 text-[11px] text-slate-500">
            {isUserRule
              ? `Your rule · ${peak.rule_label || "custom"}`
              : "Code 6 storm track"}
            {" · "}
            {group.alerts.length > 1
              ? `${group.alerts.length} stages`
              : "1 stage"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Flag
            tone={
              isPremium
                ? "border-amber-500/40 bg-amber-950/40 text-amber-300"
                : isStandard
                  ? "border-emerald-500/40 bg-emerald-950/40 text-emerald-300"
                  : "border-indigo-500/40 bg-indigo-950/40 text-indigo-300"
            }
          >
            {peak.level}
          </Flag>
          <span className="font-mono text-xs font-bold text-slate-300">
            {peak.confidence}%
          </span>
        </div>
      </div>

      <StormTimeline group={group} />
      <VerificationStrip group={group} />

      <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-2.5">
        <p className="text-[11.5px] leading-relaxed text-slate-300">
          {isUserRule
            ? "Your saved rule matched this match: the live conditions you chose were met inside the rule's time window."
            : "One side's squad was rated at least twice as weak as the other's, and the stronger side was controlling the match. Both held inside the window, so the storm gate called it."}
        </p>
        <details className="group mt-1.5">
          <summary className="flex cursor-pointer list-none items-center gap-1 text-[10px] text-slate-500">
            engine detail
            <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
          </summary>
          <p className="mt-1 font-mono text-[10px] leading-relaxed text-slate-500">
            {peak.msg}
          </p>
        </details>
      </div>

      {/* Real date AND time. The old card rendered a bare clock time, so an
          alert from a fortnight ago was indistinguishable from tonight's. */}
      <div className="flex items-center justify-between border-t border-white/5 pt-2 text-[10px] text-slate-500">
        <span>
          {group.alerts.length > 1
            ? `stages at ${group.alerts
                .map((a) => `${a.minute}'`)
                .reverse()
                .join(", ")}`
            : `alerted at ${peak.minute}'`}
        </span>
        <span className="font-mono">
          {new Date(peak.time).toLocaleString(undefined, {
            day: "2-digit",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      </div>
    </article>
  );
}

export default function LiveAlertScannerPage() {
  const { date } = useSelectedDate();
  const alertsQuery = useApi(
    () => liveApi.getAlerts(date),
    [date],
    { fallback: MOCK_LIVE_ALERTS, cacheKey: `live-alerts-${date}` }
  );
  const alerts = alertsQuery.data ?? [];
  const refreshing = alertsQuery.loading || alertsQuery.isRefetching;
  const [filterLevel, setFilterLevel] = useState<"ALL" | "PREMIUM" | "STANDARD" | "MONITOR">("ALL");

  const handleRefresh = () => alertsQuery.refetch();

  const filteredAlerts = alerts.filter((a) => {
    if (filterLevel === "PREMIUM") return a.level.includes("PREMIUM");
    if (filterLevel === "STANDARD") return a.level.includes("STANDARD");
    if (filterLevel === "MONITOR") return a.level.includes("MONITOR");
    return true;
  });

  const groups = useMemo(() => {
    const map = new Map<string, LiveAlertPick[]>();
    for (const a of filteredAlerts) {
      const key = a.f_id || a.fixture;
      const list = map.get(key);
      if (list) list.push(a);
      else map.set(key, [a]);
    }
    return Array.from(map.entries())
      .map(([f_id, list]) => {
        const sorted = [...list].sort((x, y) =>
          String(y.time).localeCompare(String(x.time))
        );
        return {
          f_id,
          fixture: sorted[0].fixture,
          alerts: sorted,
          peak: sorted[0],
          first: sorted[sorted.length - 1],
        };
      })
      .sort((a, b) => String(b.peak.time).localeCompare(String(a.peak.time)));
  }, [filteredAlerts]);

  return (
    <div className="flex flex-col gap-4 p-3.5 sm:p-5 md:p-6 max-w-7xl mx-auto w-full">
      {/* ── 1. HEADER ────────────────────────────────────────────── */}
      <div className="glass flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-[#0c1220]/90 px-4 py-3 shadow-panel backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-amber-500/30 bg-amber-950/20 shadow-[0_0_12px_rgba(245,158,11,0.2)]">
            <Bell className="h-4 w-4 text-amber-400 animate-pulse" />
          </div>
          <div>
            <h1 className="text-sm font-black uppercase tracking-wider text-text-primary flex items-center gap-2">
              Live Alert Scanner
              <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.2 font-mono text-[9px] font-bold text-emerald-400">
                STORM TRACK
              </span>
            </h1>
            <p className="text-[11px] text-text-secondary">
              Watches live matches for pressure storms, and checks each one
              against the final score
            </p>
          </div>
        </div>

        <button
          onClick={handleRefresh}
          className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs font-bold text-slate-300 hover:text-white transition-all active:scale-95"
        >
          <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin text-cyan-400")} />
          <span className="hidden sm:inline">Refresh</span>
        </button>
      </div>

      {/* ── WHAT THIS PAGE DOES, AND WHAT IT DOES NOT CLAIM ────────────
          The page previously led with a feature list — "forensic triggers,
          AI verification gates & custom alert streams" — which told an
          ordinary user nothing about whether the engine predicts goals. It
          does not, and that is worth stating plainly. */}
      <details className="group rounded-2xl border border-cyan-500/20 bg-cyan-950/10">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-4 py-3">
          <span className="flex items-center gap-2 text-xs font-black text-cyan-200">
            <Info className="h-4 w-4" />
            What this page does — and what it does not claim
          </span>
          <ChevronRight className="h-4 w-4 text-cyan-300 transition-transform group-open:rotate-90" />
        </summary>
        <div className="space-y-2 border-t border-cyan-500/15 px-4 py-3 text-[11.5px] leading-relaxed text-slate-300">
          <p>
            <strong className="text-white">What it watches.</strong> One
            team&apos;s squad rated at least twice as weak as the other&apos;s,
            while the stronger side controls the match. When both are true at
            the same time, the storm gate calls it.
          </p>
          <p>
            <strong className="text-white">What it does not do.</strong> It
            never reads the scoreboard and never predicts a goal. An alert says
            &ldquo;this match is turning&rdquo; — not &ldquo;a goal is coming&rdquo;.
            Anything that looks like a scoring prediction is your own reading,
            not the engine&apos;s claim.
          </p>
          <p>
            <strong className="text-white">Why one match can alert three
            times.</strong> The same question is asked at three points — 30-45&apos;
            (developing), 45-60&apos; (sustained) and 60-75&apos; (peaking, which
            demands a higher confidence bar). A later call has to be a stronger
            one.
          </p>
          <p>
            <strong className="text-white">How to read the card.</strong> The
            first score is the one standing when the storm first fired. The
            final score appears when the match ends, and the badge says plainly
            whether any goal was scored after the alert. That is a fact about the
            scoreline, not a claim about how accurate this engine is.
          </p>
        </div>
      </details>

      {/* ── 2. DAY STRIP (now actually wired to a date filter) ─────── */}
      <QuickHistoryStrip />

      {/* ── 3. FILTERS ────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 pb-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            onClick={() => setFilterLevel("ALL")}
            className={cn(
              "rounded-lg border px-3 py-1.5 text-xs font-bold transition-all",
              filterLevel === "ALL"
                ? "border-cyan-400 bg-cyan-500/10 text-cyan-300 shadow-[0_0_10px_rgba(6,182,212,0.2)]"
                : "border-white/10 bg-white/5 text-slate-400 hover:text-white"
            )}
          >
            All ({groups.length})
          </button>
          <button
            onClick={() => setFilterLevel("PREMIUM")}
            className={cn(
              "flex items-center gap-1 rounded-lg border px-3 py-1.5 text-xs font-bold transition-all",
              filterLevel === "PREMIUM"
                ? "border-amber-500/50 bg-amber-950/50 text-amber-300 shadow-[0_0_10px_rgba(245,158,11,0.2)]"
                : "border-white/10 bg-white/5 text-slate-400 hover:text-white"
            )}
          >
            <Flame className="h-3 w-3 text-amber-400" />
            Premium (≥50%)
          </button>
          <button
            onClick={() => setFilterLevel("STANDARD")}
            className={cn(
              "flex items-center gap-1 rounded-lg border px-3 py-1.5 text-xs font-bold transition-all",
              filterLevel === "STANDARD"
                ? "border-emerald-500/50 bg-emerald-950/50 text-emerald-300 shadow-[0_0_10px_rgba(16,185,129,0.2)]"
                : "border-white/10 bg-white/5 text-slate-400 hover:text-white"
            )}
          >
            <CheckCircle className="h-3 w-3 text-emerald-400" />
            Standard (≥30%)
          </button>
          <button
            onClick={() => setFilterLevel("MONITOR")}
            className={cn(
              "flex items-center gap-1 rounded-lg border px-3 py-1.5 text-xs font-bold transition-all",
              filterLevel === "MONITOR"
                ? "border-indigo-500/50 bg-indigo-950/50 text-indigo-300 shadow-[0_0_10px_rgba(99,102,241,0.2)]"
                : "border-white/10 bg-white/5 text-slate-400 hover:text-white"
            )}
          >
            <Activity className="h-3 w-3 text-indigo-400" />
            Monitor
          </button>
        </div>

        <span className="text-[11px] text-slate-400">
          {groups.length} fixture{groups.length === 1 ? "" : "s"} ·{" "}
          {filteredAlerts.length} alert{filteredAlerts.length === 1 ? "" : "s"}
        </span>
      </div>

      {/* ── 4. CARDS ───────────────────────────────────────────────── */}
      <div className="flex flex-col gap-3">
        {alertsQuery.loading && alerts.length === 0 && (
          <div className="rounded-xl border border-white/10 bg-[#0d1322]/90 p-6 text-center text-sm text-slate-400">
            Loading live alert stream…
          </div>
        )}
        {alertsQuery.error && (
          <div className="rounded-xl border border-red-500/30 bg-red-950/20 p-6 text-center text-sm text-red-300">
            Live alerts unavailable: {alertsQuery.error}
          </div>
        )}
        {!alertsQuery.loading && !alertsQuery.error && groups.length === 0 && (
          <div className="rounded-xl border border-white/10 bg-[#0d1322]/90 p-6 text-center text-sm leading-relaxed text-slate-400">
            No alerts fired on this day. A storm is only called when a squad is
            at least twice as weak as its opponent <em>and</em> the stronger
            side is dominating at the same time — rare by design, and rarer
            still in a quiet day.
          </div>
        )}
        {groups.map((g) => (
          <AlertGroupCard key={g.f_id} group={g} />
        ))}
      </div>
    </div>
  );
}
