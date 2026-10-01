"use client";

/**
 * WHY THIS PAGE EXISTS
 * --------------------
 * The Live board shows two numbers side by side for every team:
 *
 *     🟢 BLESSING      87.1% · GK 1.00
 *
 * which reads as a contradiction, because they are computed from different
 * things:
 *
 *   * 87.1%  = `vulnerability_pct` = missing positional weight / total
 *              positional weight. It COUNTS absences. It has never decided the
 *              badge — `live_signed_impact` says so itself: the number was
 *              "displayed on the card and then never used".
 *   * BLESSING = `net_impact`, a SIGNED measure. Negative means the players
 *              who left were WORSE than the ones now starting — the XI was
 *              upgraded.
 *
 * So 87.1% with BLESSING is not an arithmetic error. It is a team that lost a
 * lot of depth and gained quality. The card never said so, so it looked wrong.
 *
 * This page shows the working: numerator, denominator, the per-position
 * breakdown, every absent player with the rating and appearances behind them,
 * the signed verdict with its evidence, and the goalkeeper decision.
 */
import Link from "next/link";
import { use } from "react";
import { ArrowLeft, ShieldAlert } from "lucide-react";

import {
  liveDangerApi,
  type DangerSideDetail,
  type LiveDangerDetail,
} from "@/lib/api";
import { useApi } from "@/lib/use-api";

const CARD = "rounded-xl border border-border/70 bg-bg-elevated/25 shadow-panel";
const HEAD = "text-2xs font-bold uppercase tracking-wider text-text-secondary";
const DIM = "text-text-dim";
const VAL = "text-slate-200 font-mono";

const VERDICT_TONE: Record<string, string> = {
  DANGER: "border-red-500/60 bg-red-500/10 text-red-300",
  BLESSING: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  ROTATION: "border-amber-500/40 bg-amber-500/10 text-amber-300",
};

function num(v: number | null | undefined, d = 2): string {
  return v === null || v === undefined || Number.isNaN(v) ? "—" : Number(v).toFixed(d);
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className={DIM}>{label}</div>
      <div className={VAL}>{value}</div>
    </div>
  );
}

function Section({ title, right, children }: {
  title: string; right?: string; children: React.ReactNode;
}) {
  return (
    <div className="mt-3 rounded-lg border border-white/8 bg-black/25 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className={HEAD}>{title}</span>
        {right ? <span className={`font-mono text-2xs ${DIM}`}>{right}</span> : null}
      </div>
      {children}
    </div>
  );
}

function SidePanel({ side, label }: { side: DangerSideDetail; label: string }) {
  const v = side.vulnerability;
  const verdict = (side.verdict ?? "UNKNOWN").toUpperCase();
  const total = v.absent_by_position.reduce((a, b) => a + b.weight, 0);

  return (
    <section className={CARD}>
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/5 px-4 py-3">
        <div>
          <span className={`font-mono text-2xs uppercase tracking-wider ${DIM}`}>{label}</span>
          <h2 className="text-sm font-bold text-text-primary">{side.team_name}</h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded-lg border px-2.5 py-1 font-mono text-2xs font-bold ${
            VERDICT_TONE[verdict] ?? "border-white/10 bg-white/5 text-slate-300"
          }`}>{verdict}</span>
          <span className={`font-mono text-2xs ${DIM}`}>
            net {num(side.net_impact, 1)} · conf {num(side.impact_confidence)}
            {side.regime ? ` · ${side.regime}` : ""}
          </span>
        </div>
      </header>

      <div className="px-4 py-3">
        <div className="rounded-lg border border-cyan-500/25 bg-cyan-500/[0.06] p-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-2xs font-bold uppercase tracking-wider text-cyan-300">
              Missing-XI weight
            </span>
            <span className="font-mono text-lg font-bold text-cyan-200">
              {v.pct === null ? "—" : `${v.pct}%`}
            </span>
          </div>
          <p className="mt-1.5 text-[11px] leading-relaxed text-slate-300">
            {v.what_it_measures}
          </p>
          <div className="mt-2 grid grid-cols-2 gap-2 font-mono text-2xs sm:grid-cols-4">
            <Stat label="numerator" value={num(v.missing_weight, 1)} />
            <Stat label="denominator" value={num(v.total_weight, 1)} />
            <Stat label="goalkeeper share" value={
              v.goalkeeper_share_of_scale === null ? "—" : `${v.goalkeeper_share_of_scale}%`
            } />
            <Stat label="absent" value={String(side.absent_players.length)} />
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-amber-200/90">
            <strong className="text-amber-300">Not the verdict:</strong>{" "}
            {v.why_it_is_not_the_verdict}
          </p>
        </div>
<Section title="Absent weight by position" right={`Σ ${num(total, 1)}`}>
          <div className="mt-1.5 space-y-1">
            {v.absent_by_position.map((row) => (
              <div key={row.pos} className="flex items-center gap-2">
                <span className={`w-20 shrink-0 font-mono text-2xs text-text-secondary`}>{row.pos}</span>
                <span className={`w-8 shrink-0 font-mono text-2xs ${DIM}`}>×{row.count}</span>
                <div className="h-2 flex-1 overflow-hidden rounded bg-white/5">
                  <div className="h-full rounded bg-cyan-500/60"
                    style={{ width: `${Math.min(100, (row.weight / Math.max(1, total)) * 100)}%` }} />
                </div>
                <span className={`w-12 shrink-0 text-right font-mono text-2xs ${VAL}`}>{num(row.weight, 1)}</span>
              </div>
            ))}
            {v.absent_by_position.length === 0 && (
              <p className={`text-2xs ${DIM}`}>No key player is absent from this side.</p>
            )}
          </div>
        </Section>

        <Section title="Signed verdict">
          <p className="mt-1 text-[11px] leading-relaxed text-slate-300">
            {side.verdict_reason ?? "No verdict reason recorded."}
          </p>
          <div className="mt-2 grid grid-cols-2 gap-2 font-mono text-2xs sm:grid-cols-4">
            <Stat label="quality lost" value={num(side.quality_lost, 1)} />
            <Stat label="replacement credit" value={num(side.replacement_credit, 1)} />
            <Stat label="rotation uplift" value={num(side.rotation_uplift, 1)} />
            <Stat label="formation" value={side.formation ?? "—"} />
          </div>
        </Section>

        <Section title="Goalkeeper" right={`${(side.goalkeeper.verdict ?? "UNKNOWN").toUpperCase()}${
          side.goalkeeper.available ? ` · leak ${num(side.goalkeeper.leak_per_90)}/90` : " · no leak figure"
        }`}>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-300">
            {side.goalkeeper.note ?? "No goalkeeper note recorded."}
          </p>
        </Section>

        <AbsentTable side={side} />
      </div>
    </section>
  );
}

function AbsentTable({ side }: { side: DangerSideDetail }) {
  if (side.absent_players.length === 0) return null;
  return (
    <div className="mt-3 overflow-x-auto">
      <div className={`mb-1 ${HEAD}`}>
        Who is absent, and the weight each one carries
      </div>
      <table className="w-full text-left text-2xs">
        <thead>
          <tr className={`border-b border-white/8 ${DIM}`}>
            <th className="py-1 pr-2 font-semibold">player</th>
            <th className="py-1 pr-2 font-semibold">pos</th>
            <th className="py-1 pr-2 text-right font-semibold">rating</th>
            <th className="py-1 pr-2 text-right font-semibold">apps</th>
            <th className="py-1 pr-2 text-right font-semibold">mins</th>
            <th className="py-1 text-right font-semibold">weight</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-white/5">
          {side.absent_players.map((p, i) => (
            <tr key={`${p.name}-${i}`} className="text-slate-300">
              <td className="py-1 pr-2 text-slate-100">{p.name}</td>
              <td className={`py-1 pr-2 text-text-secondary`}>{p.pos}</td>
              <td className={`py-1 pr-2 text-right font-mono`}>{num(p.rating)}</td>
              <td className={`py-1 pr-2 text-right font-mono`}>{p.apps ?? "—"}</td>
              <td className={`py-1 pr-2 text-right font-mono`}>{p.mins ?? "—"}</td>
              <td className="py-1 text-right font-mono text-cyan-300">{num(p.weight, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Shell({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-3 p-3.5 sm:p-5 md:p-6">
      <Link href="/live/incoming"
        className="inline-flex w-fit items-center gap-1.5 text-xs font-bold text-text-secondary hover:text-cyan-300">
        <ArrowLeft className="h-3.5 w-3.5" /> Back to the Live board
      </Link>
      <div>
        <h1 className="text-sm font-black uppercase tracking-wider text-text-primary">{title}</h1>
        <p className="text-[11px] text-text-secondary">
          Every figure below is derived from the live danger audit. Nothing here
          is a display-only label.
        </p>
      </div>
      {children}
    </div>
  );
}

export default function LiveDangerPage({
  params,
}: {
  params: Promise<{ fixtureId: string }>;
}) {
  const { fixtureId } = use(params);
  const { data, loading, error } = useApi(
    () => liveDangerApi.getDetail(fixtureId),
    [fixtureId],
    { cacheKey: `live-danger-${fixtureId}`, refreshMs: 30_000 }
  );

  // useApi already unwraps the Axios envelope, so `data` IS the payload.
  const detail = data as LiveDangerDetail | undefined;

  if (error) {
    return (
      <Shell title="Danger derivation">
        <div className="rounded-xl border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-200">
          {String((error as unknown as Error)?.message ?? error)}
        </div>
      </Shell>
    );
  }
  if (loading && !detail) {
    return (
      <Shell title="Danger derivation">
        <div className="flex items-center gap-2 text-sm text-text-secondary">
          <ShieldAlert className="h-4 w-4 animate-pulse" /> Loading derivation…
        </div>
      </Shell>
    );
  }
  if (detail?.error) {
    return (
      <Shell title="Danger derivation">
        <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-200">
          {detail.error}
        </div>
      </Shell>
    );
  }
  if (!detail) return <Shell title="Danger derivation" />;

  return (
    <Shell title={detail.fixture ?? "Danger derivation"}>
      <div className="flex flex-wrap items-center gap-2 text-2xs text-text-secondary">
        {detail.style_alignment && (
          <span className="rounded border border-white/10 bg-white/5 px-2 py-0.5 font-mono">
            style alignment {detail.style_alignment}
          </span>
        )}
        {detail.openness_score !== null && detail.openness_score !== undefined && (
          <span className="rounded border border-white/10 bg-white/5 px-2 py-0.5 font-mono">
            openness {num(detail.openness_score, 3)}
          </span>
        )}
        {detail.match_chemistry &&
          Object.entries(detail.match_chemistry).map(([market, level]) => (
            <span key={market} className="rounded border border-white/10 bg-white/5 px-2 py-0.5 font-mono">
              {market} {level}
            </span>
          ))}
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        {detail.home && <SidePanel side={detail.home} label="home" />}
        {detail.away && <SidePanel side={detail.away} label="away" />}
      </div>
    </Shell>
  );
}