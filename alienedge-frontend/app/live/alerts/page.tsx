"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Bell, Flame, Radio, ShieldCheck, SlidersHorizontal, UserCheck } from "lucide-react";
import {
  liveApi,
  userRulesApi,
  type LiveAlertPick,
  type LiveOrchestratorBoard,
  type LiveOrchestratorMatch,
  type UserRuleDef,
} from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { useLocalUserId } from "@/lib/use-local-user";
import { MOCK_LIVE_ALERTS, MOCK_LIVE_ORCHESTRATOR } from "@/lib/mock-chains";
import { RadialGauge } from "@/components/predictions";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * Page 6 — Live Module 6 Validator & Scanner.
 *
 * The old "Scanner rule customizer" here used to filter cards already on
 * screen — it never told the backend anything. It's been replaced with
 * "Your Active Rules" (real rules saved via /live/rules, actually
 * evaluated by the orchestrator every cycle) and "Your Alerts" (alerts
 * the backend fired specifically because one of YOUR rules matched).
 */

function boardFrom(data: LiveOrchestratorBoard | null, loading: boolean): LiveOrchestratorBoard {
  if (loading && (!data || !data.matches?.length)) return MOCK_LIVE_ORCHESTRATOR;
  if (data && Array.isArray(data.matches) && data.matches.length > 0) return data;
  return MOCK_LIVE_ORCHESTRATOR;
}

function alertRows(data: LiveAlertPick[] | null, loading: boolean): LiveAlertPick[] {
  if (loading && (!data || data.length === 0)) return MOCK_LIVE_ALERTS;
  if (data && data.length > 0) return data;
  return MOCK_LIVE_ALERTS;
}

function confidenceOf(m: LiveOrchestratorMatch): number {
  return m.intel?.match?.confidence_score ?? m.conf ?? 0;
}
function chaosOf(m: LiveOrchestratorMatch): number {
  return m.intel?.match?.chaos_index ?? m.chaos ?? 0;
}
function hPressureOf(m: LiveOrchestratorMatch): number {
  return m.intel?.match?.h_pressure_share ?? m.h_pressure ?? 0;
}
function aPressureOf(m: LiveOrchestratorMatch): number {
  return m.intel?.match?.a_pressure_share ?? m.a_pressure ?? 0;
}
function hXgOf(m: LiveOrchestratorMatch): number {
  return m.intel?.home?.live_xg ?? m.h_xg ?? 0;
}
function aXgOf(m: LiveOrchestratorMatch): number {
  return m.intel?.away?.live_xg ?? m.a_xg ?? 0;
}
function hSotOf(m: LiveOrchestratorMatch): number {
  return m.intel?.home?.sot ?? m.h_sot ?? 0;
}
function aSotOf(m: LiveOrchestratorMatch): number {
  return m.intel?.away?.sot ?? m.a_sot ?? 0;
}
function hDaOf(m: LiveOrchestratorMatch): number {
  return m.intel?.home?.da ?? 0;
}
function aDaOf(m: LiveOrchestratorMatch): number {
  return m.intel?.away?.da ?? 0;
}

function alertTone(level: string, conf: number): "premium" | "standard" | "monitor" {
  const u = (level ?? "").toUpperCase();
  if (u.includes("PREMIUM") || conf >= 50) return "premium";
  if (u.includes("STANDARD") || conf >= 30) return "standard";
  return "monitor";
}

function formatClock(iso: string): string {
  if (!iso) return "—";
  return iso.replace("T", " ").slice(0, 19);
}

function settlementLabel(market: string): string {
  const m = market.toUpperCase();
  if (m === "GG" || m.includes("GG")) return "GG SETTLED";
  if (m.includes("O2.5") || m.includes("OVER 2.5") || m === "O25") return "O2.5 SETTLED";
  return `${m} SETTLED`;
}

function describeRuleShort(rule: UserRuleDef): string {
  const pre = rule.prematch.type === "none" ? "any prematch" : rule.prematch.type === "flag" ? rule.prematch.flag.replace(/_/g, " ") : `${rule.prematch.metric?.replace(/_/g, " ")} ≥ ${rule.prematch.min_value}%`;
  const live =
    rule.live.type === "snapshot"
      ? "every update"
      : rule.live.type === "pressure_share"
        ? `${rule.live.side} pressure ≥ ${rule.live.min_value}%`
        : `chaos ≥ ${rule.live.min_value}`;
  return `${pre} + ${live}`;
}

export default function LiveAlertsPage() {
  const userId = useLocalUserId();

  const orchestrator = useApi(() => liveApi.getOrchestrator(), [], {
    fallback: MOCK_LIVE_ORCHESTRATOR,
    cacheKey: "live-alerts-orchestrator",
  });
  const alerts = useApi(() => liveApi.getAlerts(), [], {
    fallback: MOCK_LIVE_ALERTS,
    cacheKey: "live-alerts-alerts",
  });

  const board = boardFrom(orchestrator.data, orchestrator.loading);
  const matches = useMemo(() => board.matches ?? [], [board.matches]);
  const rows = alertRows(alerts.data, alerts.loading);

  const [selectedId, setSelectedId] = useState<string | null>(null);

  // ── Your saved rules ──
  const [myRules, setMyRules] = useState<UserRuleDef[]>([]);
  const [rulesLoading, setRulesLoading] = useState(true);

  // ── Your personal alerts (fired by YOUR rules specifically) ──
  const [myAlerts, setMyAlerts] = useState<LiveAlertPick[]>([]);
  const [myAlertsLoading, setMyAlertsLoading] = useState(true);
  const [myAlertsError, setMyAlertsError] = useState(false);

  useEffect(() => {
    if (!userId) return;
    setRulesLoading(true);
    userRulesApi
      .list(userId)
      .then((res) => setMyRules(res.data))
      .catch(() => setMyRules([]))
      .finally(() => setRulesLoading(false));

    setMyAlertsLoading(true);
    userRulesApi
      .getMyAlerts(userId)
      .then((res) => {
        setMyAlerts(res.data);
        setMyAlertsError(false);
      })
      .catch(() => setMyAlertsError(true))
      .finally(() => setMyAlertsLoading(false));
  }, [userId]);

  const activeMatch = useMemo(() => {
    if (!matches.length) return null;
    if (selectedId) {
      const hit = matches.find((m) => m.id === selectedId);
      if (hit) return hit;
    }
    return [...matches].sort((a, b) => confidenceOf(b) - confidenceOf(a))[0] ?? null;
  }, [matches, selectedId]);

  const activeConf = confidenceOf(activeMatch ?? ({} as LiveOrchestratorMatch));
  const activeChaos = chaosOf(activeMatch ?? ({} as LiveOrchestratorMatch));
  const validation = activeMatch?.validation ?? null;
  const settled = activeMatch?.settled ?? [];

  const sortedAlerts = useMemo(
    () => [...rows].sort((a, b) => String(b.time ?? "").localeCompare(String(a.time ?? ""))),
    [rows]
  );

  const anyMock = orchestrator.isMock || alerts.isMock;
  const activeRuleCount = myRules.filter((r) => r.active).length;

  return (
    <div className="relative flex flex-col gap-5 p-6 lg:flex-row lg:items-start">
      <div className="pointer-events-none absolute inset-0 -z-10 bg-hero-glow opacity-70" />

      <div className="flex min-w-0 flex-1 flex-col gap-5">
        {/* ── 1. Top metrics header ── */}
        <div className="glass flex flex-wrap items-center gap-5 rounded-xl px-5 py-4 shadow-panel">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-amber/20 shadow-glow-amber">
              <Bell className="h-4 w-4 text-accent-amber" />
            </div>
            <div>
              <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-text-primary">
                Code 6 · Validator & Scanner
                {anyMock && (
                  <Badge variant="outline" className="h-4 border-accent-amber/30 px-1 text-[0.6rem] text-accent-amber">
                    Demo
                  </Badge>
                )}
              </p>
              <p className="text-2xs text-text-dim">
                Cycle #{board.cycle || "—"} · Live {board.total_live} · DB {board.total_db} ·{" "}
                {board.session || "—"}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-4 sm:gap-6">
            <RadialGauge value={activeConf} label="Confidence" size={88} strokeWidth={7} />

            <div className="min-w-[7rem]">
              <p className="text-2xs uppercase tracking-wide text-text-dim">Chaos Index</p>
              <div className="mt-1 flex items-center gap-2">
                <span
                  className={cn(
                    "font-mono text-2xl font-bold tabular-nums",
                    activeChaos >= 5 ? "text-accent-amber" : "text-text-primary"
                  )}
                >
                  {activeChaos.toFixed(1)}
                </span>
                {activeChaos >= 5.0 && (
                  <Flame className="h-5 w-5 text-accent-amber drop-shadow-[0_0_8px_rgba(245,158,11,0.85)]" aria-label="High chaos" />
                )}
              </div>
              <p className="mt-0.5 truncate text-2xs text-text-dim">{activeMatch?.name ?? "No active fixture"}</p>
            </div>

            <div className="flex flex-col gap-1.5">
              <p className="text-2xs uppercase tracking-wide text-text-dim">Handshake gates</p>
              <div className="flex flex-wrap gap-1.5">
                <Badge
                  variant="outline"
                  className={cn(
                    "font-mono text-2xs",
                    validation === "VALID_30" || validation === "SUPREME_45"
                      ? "border-accent-cyan/40 bg-accent-cyan/10 text-accent-cyan"
                      : "border-border/60 text-text-dim"
                  )}
                >
                  30&apos; · VALID_30
                  {(validation === "VALID_30" || validation === "SUPREME_45") && " ✓"}
                </Badge>
                <Badge
                  variant="outline"
                  className={cn(
                    "font-mono text-2xs",
                    validation === "SUPREME_45"
                      ? "border-accent-green/40 bg-accent-green/10 text-accent-green"
                      : "border-border/60 text-text-dim"
                  )}
                >
                  45&apos; · SUPREME_45
                  {validation === "SUPREME_45" && " ✓"}
                </Badge>
              </div>
            </div>

            <div className="flex flex-col gap-1.5">
              <p className="text-2xs uppercase tracking-wide text-text-dim">Settlement</p>
              <div className="flex flex-wrap gap-1.5">
                {settled.length === 0 ? (
                  <span className="font-mono text-2xs text-text-dim">No markets settled</span>
                ) : (
                  settled.map((s) => (
                    <span
                      key={s}
                      className="rounded border border-accent-green/40 bg-accent-green/10 px-2 py-0.5 font-mono text-2xs font-semibold text-accent-green"
                    >
                      [ {settlementLabel(s)} 🟢 ]
                    </span>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>

        {/* ── 2. Your Active Rules (real, saved, server-evaluated) ── */}
        <section className="rounded-xl border border-border/70 bg-bg-elevated/30 px-4 py-4 shadow-panel">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <SlidersHorizontal className="h-4 w-4 text-accent-indigo" />
              <h2 className="text-sm font-semibold text-text-primary">Your active rules</h2>
              <span className="rounded border border-border-bright bg-bg-elevated px-1.5 py-0.5 font-mono text-2xs text-text-muted">
                {activeRuleCount} active
              </span>
            </div>
            <Link
              href="/live/rules"
              className="rounded-lg border border-accent-indigo/40 bg-accent-indigo/10 px-3 py-1.5 text-2xs font-semibold text-accent-indigo transition-colors hover:bg-accent-indigo/20"
            >
              Manage rules →
            </Link>
          </div>

          {rulesLoading ? (
            <Skeleton className="h-10 rounded-lg bg-bg-deep" />
          ) : myRules.length === 0 ? (
            <p className="text-xs text-text-dim">
              You haven&apos;t built an alert yet. Combine a prematch signal with a live condition
              on the <Link href="/live/rules" className="text-accent-indigo hover:underline">Build My Alert</Link> screen.
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {myRules.map((rule) => (
                <span
                  key={rule.rule_id}
                  className={cn(
                    "rounded-lg border px-2.5 py-1.5 text-2xs",
                    rule.active
                      ? "border-accent-green/30 bg-accent-green/5 text-text-secondary"
                      : "border-border/50 bg-bg-elevated/40 text-text-dim"
                  )}
                >
                  <span className="font-semibold text-text-primary">{rule.label}</span>
                  <span className="ml-1.5 font-mono">· {describeRuleShort(rule)}</span>
                  {!rule.active && <span className="ml-1.5 italic">(paused)</span>}
                </span>
              ))}
            </div>
          )}
        </section>

        {/* ── 3. Live match telemetry ── */}
        <section className="flex flex-col gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent-amber/15 text-accent-amber">
              <Radio className="h-4 w-4" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-text-primary">Live match telemetry</h2>
              <p className="text-2xs text-text-dim">
                Pressure share · xG / SOT / DA · structural forensics (doom / red / GK) · {matches.length} fixtures
              </p>
            </div>
          </div>

          {orchestrator.loading && matches.length === 0 ? (
            <Skeleton className="h-48 rounded-xl bg-bg-elevated" />
          ) : matches.length === 0 ? (
            <p className="rounded-xl border border-border/60 bg-bg-elevated/20 px-4 py-8 text-center text-sm text-text-dim">
              No live fixtures right now.
            </p>
          ) : (
            <div className="grid gap-3">
              {matches.map((m) => (
                <TelemetryCard
                  key={`${m.id}-${m.minute}`}
                  m={m}
                  selected={activeMatch?.id === m.id}
                  onSelect={() => setSelectedId(m.id)}
                />
              ))}
            </div>
          )}
        </section>
      </div>

      {/* ── 4. Sidebar: Your Alerts + System Alerts ── */}
      <aside className="flex w-full shrink-0 flex-col gap-4 lg:sticky lg:top-4 lg:w-[340px]">
        <div className="rounded-xl border border-border/70 bg-bg-elevated/40 shadow-panel">
          <div className="flex items-center gap-2 border-b border-border/60 px-4 py-3">
            <UserCheck className="h-4 w-4 text-accent-indigo" />
            <div>
              <h2 className="text-sm font-semibold text-text-primary">Your alerts</h2>
              <p className="text-2xs text-text-dim">Fired by your own saved rules</p>
            </div>
          </div>
          <div className="max-h-[40vh] space-y-2 overflow-y-auto p-3">
            {myAlertsLoading ? (
              <Skeleton className="h-24 rounded-lg bg-bg-deep" />
            ) : myAlertsError ? (
              <p className="px-2 py-6 text-center text-2xs text-text-dim">
                Couldn&apos;t reach your alert feed — try again shortly.
              </p>
            ) : myAlerts.length === 0 ? (
              <p className="px-2 py-6 text-center text-2xs text-text-dim">
                No alerts fired from your rules yet. Build one on{" "}
                <Link href="/live/rules" className="text-accent-indigo hover:underline">
                  Build My Alert
                </Link>
                .
              </p>
            ) : (
              myAlerts.map((r, i) => <AlertFeedCard key={`mine-${r.f_id}-${r.time}-${i}`} alert={r} />)
            )}
          </div>
        </div>

        <div className="rounded-xl border border-border/70 bg-bg-elevated/40 shadow-panel">
          <div className="flex items-center gap-2 border-b border-border/60 px-4 py-3">
            <ShieldCheck className="h-4 w-4 text-accent-green" />
            <div>
              <h2 className="text-sm font-semibold text-text-primary">System alerts</h2>
              <p className="text-2xs text-text-dim">SESSION_ALERTS · ready_to_push</p>
            </div>
            {alerts.isRefetching && <span className="ml-auto font-mono text-2xs text-text-dim">sync…</span>}
          </div>
          <div className="max-h-[40vh] space-y-2 overflow-y-auto p-3">
            {alerts.loading && sortedAlerts.length === 0 ? (
              <Skeleton className="h-24 rounded-lg bg-bg-deep" />
            ) : sortedAlerts.length === 0 ? (
              <p className="px-2 py-6 text-center text-2xs text-text-dim">No alerts this session.</p>
            ) : (
              sortedAlerts.map((r, i) => <AlertFeedCard key={`sys-${r.f_id}-${r.time}-${i}`} alert={r} />)
            )}
          </div>
        </div>
      </aside>
    </div>
  );
}

function TelemetryCard({
  m,
  selected,
  onSelect,
}: {
  m: LiveOrchestratorMatch;
  selected: boolean;
  onSelect: () => void;
}) {
  const conf = confidenceOf(m);
  const chaos = chaosOf(m);
  const hp = hPressureOf(m);
  const ap = aPressureOf(m);
  const totalP = hp + ap || 100;
  const hPct = (hp / totalP) * 100;
  const aPct = (ap / totalP) * 100;
  const f = m.forensics;
  const structOk = (f?.status ?? m.structural) === "OK";

  return (
    <article
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className={cn(
        "cursor-pointer rounded-xl border bg-bg-elevated/25 shadow-panel transition-colors",
        selected ? "border-accent-amber/50 ring-1 ring-accent-amber/30" : "border-border/70 hover:border-border"
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-border/60 px-4 py-3">
        <div>
          <div className="mb-1 flex flex-wrap items-center gap-1.5">
            <span
              className={cn(
                "rounded border px-1.5 py-0.5 font-mono text-2xs font-semibold",
                m.in_db
                  ? "border-accent-indigo/40 bg-accent-indigo/10 text-accent-indigo"
                  : "border-accent-red/40 bg-accent-red/10 text-accent-red"
              )}
            >
              {m.in_db ? "🎯 VIP" : "👁️ LIVE"}
            </span>
            <span className="font-mono text-2xs text-text-dim">ID {m.id}</span>
            <span className="font-mono text-2xs text-text-secondary">{m.minute}&apos;</span>
            {chaos >= 5.0 && <Flame className="h-3.5 w-3.5 text-accent-amber drop-shadow-[0_0_6px_rgba(245,158,11,0.8)]" />}
          </div>
          <h3 className="text-sm font-semibold text-text-primary">{m.name}</h3>
          <p className="mt-0.5 font-mono text-2xs text-text-dim">Conf {conf.toFixed(0)}%</p>
        </div>
        <span
          className={cn(
            "rounded border px-1.5 py-0.5 font-mono text-2xs",
            structOk
              ? "border-accent-green/30 bg-accent-green/10 text-accent-green"
              : "border-accent-amber/30 bg-accent-amber/10 text-accent-amber"
          )}
        >
          {structOk ? "Structural OK" : `⚠️ ${f?.status ?? m.structural}`}
        </span>
      </div>

      <div className="px-4 pt-3">
        <div className="mb-1 flex justify-between font-mono text-2xs text-text-secondary">
          <span>H {hp.toFixed(1)}%</span>
          <span className="text-text-dim">Pressure share</span>
          <span>A {ap.toFixed(1)}%</span>
        </div>
        <div className="flex h-2.5 overflow-hidden rounded-full bg-bg-deep">
          <div className="bg-accent-cyan transition-[width]" style={{ width: `${hPct}%` }} title={`Home ${hp.toFixed(1)}%`} />
          <div className="bg-accent-amber transition-[width]" style={{ width: `${aPct}%` }} title={`Away ${ap.toFixed(1)}%`} />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 px-4 py-3 font-mono text-2xs">
        <StatPair label="xG" home={hXgOf(m).toFixed(2)} away={aXgOf(m).toFixed(2)} />
        <StatPair label="SOT" home={String(hSotOf(m))} away={String(aSotOf(m))} />
        <StatPair label="DA" home={String(hDaOf(m))} away={String(aDaOf(m))} />
      </div>

      <div className="flex flex-wrap gap-1.5 border-t border-border/50 px-4 py-2.5">
        <span className="rounded border border-border/60 bg-bg-deep/60 px-1.5 py-0.5 font-mono text-2xs text-text-secondary">
          Doom {Number(f?.h_doom ?? 0).toFixed(2)} / {Number(f?.a_doom ?? 0).toFixed(2)}
        </span>
        {(f?.h_red || f?.a_red) && (
          <span className="rounded border border-accent-red/40 bg-accent-red/10 px-1.5 py-0.5 font-mono text-2xs text-accent-red">
            Red {f?.h_red ? "H" : ""}
            {f?.h_red && f?.a_red ? "+" : ""}
            {f?.a_red ? "A" : ""}
          </span>
        )}
        {(f?.h_gk || f?.a_gk) && (
          <span className="rounded border border-accent-amber/40 bg-accent-amber/10 px-1.5 py-0.5 font-mono text-2xs text-accent-amber">
            GK risk {f?.h_gk ? "H" : ""}
            {f?.h_gk && f?.a_gk ? "+" : ""}
            {f?.a_gk ? "A" : ""}
          </span>
        )}
        {!f?.h_red && !f?.a_red && !f?.h_gk && !f?.a_gk && <span className="font-mono text-2xs text-text-dim">No red / GK flags</span>}
      </div>
    </article>
  );
}

function StatPair({ label, home, away }: { label: string; home: string; away: string }) {
  return (
    <div className="rounded-lg border border-border/50 bg-bg-deep/40 px-2 py-1.5 text-center">
      <p className="text-[0.6rem] uppercase tracking-wide text-text-dim">{label}</p>
      <p className="mt-0.5 text-text-primary">
        <span className="text-accent-cyan">{home}</span>
        <span className="mx-1 text-text-dim">·</span>
        <span className="text-accent-amber">{away}</span>
      </p>
    </div>
  );
}

function AlertFeedCard({ alert }: { alert: LiveAlertPick }) {
  const conf = alert.confidence ?? 0;
  const tone = alertTone(alert.level ?? "", conf);

  return (
    <article
      className={cn(
        "rounded-lg border px-3 py-2.5",
        tone === "premium" && "border-accent-amber/50 bg-accent-amber/5 shadow-[0_0_12px_rgba(245,158,11,0.18)]",
        tone === "standard" && "border-accent-green/45 bg-accent-green/5",
        tone === "monitor" && "border-border/50 bg-bg-deep/50"
      )}
    >
      <div className="mb-1 flex flex-wrap items-center gap-1.5">
        <span
          className={cn(
            "font-mono text-2xs font-semibold",
            tone === "premium" && "text-accent-amber",
            tone === "standard" && "text-accent-green",
            tone === "monitor" && "text-text-dim"
          )}
        >
          {alert.level || (tone === "premium" ? "🔥 PREMIUM" : tone === "standard" ? "✅ STANDARD" : "📊 MONITOR")}
        </span>
        <span className="font-mono text-2xs text-text-dim">{alert.minute}&apos;</span>
        <span className="ml-auto font-mono text-2xs tabular-nums text-text-secondary">{conf.toFixed(0)}%</span>
      </div>
      <p className="text-xs font-medium text-text-primary">{alert.fixture}</p>
      {alert.rule_label && (
        <p className="mt-0.5 font-mono text-2xs text-accent-indigo">via &quot;{alert.rule_label}&quot;</p>
      )}
      <p className="mt-1 line-clamp-3 text-2xs leading-relaxed text-text-secondary">{alert.msg}</p>
      <p className="mt-1.5 font-mono text-[0.6rem] text-text-dim">{formatClock(alert.time)}</p>
    </article>
  );
}