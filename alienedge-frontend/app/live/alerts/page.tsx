"use client";

import { useCallback, useEffect, useState } from "react";
import { SlidersHorizontal, Trash2, Loader2, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useLocalUserId } from "@/lib/use-local-user";
import {
  userRulesApi,
  PREMATCH_FLAG_OPTIONS,
  PREMATCH_RATE_OPTIONS,
  CHEMISTRY_MARKET_OPTIONS,
  CHEMISTRY_LEVEL_OPTIONS,
  LIVE_SIDED_TYPES,
  type UserRuleDef,
  type UserRulePrematch,
  type UserRuleLive,
  type PrematchFlagKey,
  type PrematchRateMetric,
  type ChemistryMarket,
  type ChemistryLevel,
  type RuleSide,
  type LiveConditionType,
} from "@/lib/api";

type PrematchType =
  | "none"
  | "flag"
  | "rate"
  | "gk_liability"
  | "key_missing"
  | "aggregator_chemistry"
  | "aggregator_breach";

const PREMATCH_TYPE_LABELS: Record<PrematchType, string> = {
  none: "Any / Skip",
  flag: "100% Flag (SH-GG)",
  rate: "Rate Threshold (SH-GG)",
  gk_liability: "GK Liability (Lineup)",
  key_missing: "Key Players Missing (Lineup)",
  aggregator_chemistry: "Market Chemistry (Aggregator)",
  aggregator_breach: "Danger Breach (Aggregator)",
};

const LIVE_TYPE_LABELS: Record<LiveConditionType, string> = {
  snapshot: "Every Update",
  pressure_share: "Pressure Share",
  chaos_index: "Chaos Index",
  xg: "Live xG",
  sot: "Shots on Target",
  corners: "Corners",
  da: "Dangerous Attacks",
  key_player_lost: "Key Player Lost (Live)",
};

function buildPrematch(
  type: PrematchType,
  flag: PrematchFlagKey,
  metric: PrematchRateMetric,
  rateMinValue: number,
  gkSide: RuleSide,
  keyMissingSide: RuleSide,
  keyMissingCount: number,
  chemMarket: ChemistryMarket,
  chemLevel: ChemistryLevel,
  breachSide: RuleSide
): UserRulePrematch {
  switch (type) {
    case "flag":
      return { type: "flag", flag };
    case "rate":
      return { type: "rate", metric, min_value: rateMinValue };
    case "gk_liability":
      return { type: "gk_liability", side: gkSide };
    case "key_missing":
      return { type: "key_missing", side: keyMissingSide, min_count: keyMissingCount };
    case "aggregator_chemistry":
      return { type: "aggregator_chemistry", market: chemMarket, level: chemLevel };
    case "aggregator_breach":
      return { type: "aggregator_breach", side: breachSide };
    default:
      return { type: "none" };
  }
}

function buildLive(
  type: LiveConditionType,
  side: RuleSide,
  minValue: number,
  keyLostSide: RuleSide,
  keyLostCount: number
): UserRuleLive {
  switch (type) {
    case "pressure_share":
      return { type: "pressure_share", side, min_value: minValue };
    case "chaos_index":
      return { type: "chaos_index", min_value: minValue };
    case "xg":
      return { type: "xg", side, min_value: minValue };
    case "sot":
      return { type: "sot", side, min_value: minValue };
    case "corners":
      return { type: "corners", side, min_value: minValue };
    case "da":
      return { type: "da", side, min_value: minValue };
    case "key_player_lost":
      return { type: "key_player_lost", side: keyLostSide, min_count: keyLostCount };
    default:
      return { type: "snapshot" };
  }
}

function describePrematch(p: UserRulePrematch): string {
  switch (p.type) {
    case "none":
      return "Any prematch state";
    case "flag":
      return PREMATCH_FLAG_OPTIONS.find((o) => o.value === p.flag)?.label ?? p.flag;
    case "rate":
      return `${PREMATCH_RATE_OPTIONS.find((o) => o.value === p.metric)?.label ?? p.metric} ≥ ${p.min_value}%`;
    case "gk_liability":
      return `GK liability (${p.side})`;
    case "key_missing":
      return `${p.side} missing ≥ ${p.min_count} key players`;
    case "aggregator_chemistry":
      return `${p.market} chemistry = ${CHEMISTRY_LEVEL_OPTIONS.find((o) => o.value === p.level)?.label ?? p.level}`;
    case "aggregator_breach":
      return `Danger breach (${p.side})`;
    default:
      return "Unknown";
  }
}

function describeLive(l: UserRuleLive): string {
  switch (l.type) {
    case "snapshot":
      return "Every live update";
    case "pressure_share":
      return `${l.side} pressure ≥ ${l.min_value}%`;
    case "chaos_index":
      return `Chaos ≥ ${l.min_value}`;
    case "xg":
      return `${l.side} xG ≥ ${l.min_value}`;
    case "sot":
      return `${l.side} SOT ≥ ${l.min_value}`;
    case "corners":
      return `${l.side} corners ≥ ${l.min_value}`;
    case "da":
      return `${l.side} dangerous attacks ≥ ${l.min_value}`;
    case "key_player_lost":
      return `${l.side} lost ≥ ${l.min_count} key player(s)`;
    default:
      return "Unknown";
  }
}

function describeRule(rule: UserRuleDef): { pre: string; live: string; window: string } {
  return {
    pre: describePrematch(rule.prematch),
    live: describeLive(rule.live),
    window: rule.minute_window
      ? `${rule.minute_window.start}'–${rule.minute_window.end}'`
      : "Full match",
  };
}

export default function LiveRulesPage() {
  const userId = useLocalUserId();

  const [rules, setRules] = useState<UserRuleDef[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [label, setLabel] = useState("");

  // Prematch state
  const [prematchType, setPrematchType] = useState<PrematchType>("flag");
  const [prematchFlag, setPrematchFlag] = useState<PrematchFlagKey>(PREMATCH_FLAG_OPTIONS[0].value);
  const [prematchMetric, setPrematchMetric] = useState<PrematchRateMetric>(PREMATCH_RATE_OPTIONS[0].value);
  const [prematchRateMinValue, setPrematchRateMinValue] = useState(80);
  const [gkSide, setGkSide] = useState<RuleSide>("any");
  const [keyMissingSide, setKeyMissingSide] = useState<RuleSide>("any");
  const [keyMissingCount, setKeyMissingCount] = useState(2);
  const [chemMarket, setChemMarket] = useState<ChemistryMarket>(CHEMISTRY_MARKET_OPTIONS[0].value);
  const [chemLevel, setChemLevel] = useState<ChemistryLevel>(CHEMISTRY_LEVEL_OPTIONS[0].value);
  const [breachSide, setBreachSide] = useState<RuleSide>("any");

  // Live state
  const [liveType, setLiveType] = useState<LiveConditionType>("pressure_share");
  const [liveSide, setLiveSide] = useState<RuleSide>("any");
  const [liveMinValue, setLiveMinValue] = useState(55);
  const [keyLostSide, setKeyLostSide] = useState<RuleSide>("any");
  const [keyLostCount, setKeyLostCount] = useState(1);

  // Minute window state
  const [useWindow, setUseWindow] = useState(false);
  const [windowStart, setWindowStart] = useState(0);
  const [windowEnd, setWindowEnd] = useState(90);

  const reload = useCallback(() => {
    if (!userId) return;
    setLoading(true);
    userRulesApi
      .list(userId)
      .then((res) => setRules(res.data))
      .catch(() => setError("Could not load your saved rules — showing none for now."))
      .finally(() => setLoading(false));
  }, [userId]);

  useEffect(() => {
    reload();
  }, [reload]);

  // Live value slider bounds/defaults per type — keeps the UI honest about
  // what range each real stat actually moves in.
  function liveSliderConfig(type: LiveConditionType): { min: number; max: number; step: number } {
    switch (type) {
      case "pressure_share":
        return { min: 40, max: 80, step: 1 };
      case "chaos_index":
        return { min: 0, max: 12, step: 0.5 };
      case "xg":
        return { min: 0, max: 4, step: 0.1 };
      case "sot":
        return { min: 0, max: 12, step: 1 };
      case "corners":
        return { min: 0, max: 12, step: 1 };
      case "da":
        return { min: 0, max: 60, step: 1 };
      default:
        return { min: 0, max: 100, step: 1 };
    }
  }

  async function handleSave() {
    if (!userId) return;
    setSaving(true);
    setError(null);
    try {
      const prematch = buildPrematch(
        prematchType,
        prematchFlag,
        prematchMetric,
        prematchRateMinValue,
        gkSide,
        keyMissingSide,
        keyMissingCount,
        chemMarket,
        chemLevel,
        breachSide
      );
      const live = buildLive(liveType, liveSide, liveMinValue, keyLostSide, keyLostCount);

      await userRulesApi.create({
        user_id: userId,
        label: label.trim() || "Untitled Rule",
        prematch,
        live,
        ...(useWindow ? { minute_window: { start: windowStart, end: windowEnd } } : {}),
        active: true,
      });
      setLabel("");
      reload();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || "Could not save this rule. Check your conditions and try again.");
    } finally {
      setSaving(false);
    }
  }

  async function handleToggle(rule: UserRuleDef) {
    setRules((prev) => prev.map((r) => (r.rule_id === rule.rule_id ? { ...r, active: !r.active } : r)));
    try {
      await userRulesApi.update(rule.rule_id, { active: !rule.active });
    } catch {
      reload();
    }
  }

  async function handleDelete(rule: UserRuleDef) {
    if (!userId) return;
    setRules((prev) => prev.filter((r) => r.rule_id !== rule.rule_id));
    try {
      await userRulesApi.remove(rule.rule_id, userId);
    } catch {
      reload();
    }
  }

  const invalidCombo = prematchType === "none" && liveType === "snapshot";
  const sliderCfg = liveSliderConfig(liveType);
  const liveNeedsSide = LIVE_SIDED_TYPES.includes(liveType) && liveType !== "key_player_lost";

  return (
    <div className="flex flex-col gap-4 p-6">
      <div className="glass flex items-center gap-3 rounded-lg p-4 shadow-panel">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-indigo/15">
          <SlidersHorizontal className="h-5 w-5 text-accent-indigo" />
        </div>
        <div>
          <h1 className="text-base font-bold text-text-primary">Build My Alert</h1>
          <p className="text-xs text-text-secondary">
            Combine a real prematch signal — from the SH-GG Winner engine, the lineup audit, or
            aggregator chemistry — with a real live condition and an optional minute window.
            Saved rules run against every live fixture, every cycle, on the server.
          </p>
        </div>
      </div>

      <div className="glass flex flex-col gap-5 rounded-lg p-4 shadow-panel">
        <div className="flex flex-col gap-1.5">
          <label className="text-2xs text-text-muted">Rule name</label>
          <input
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="e.g. Home BTTS second-half special"
            className="w-full max-w-md rounded border border-border bg-bg-elevated px-3 py-2 text-xs text-text-primary outline-none focus:border-accent-indigo"
          />
        </div>

        {/* ── STEP 1: PREMATCH ── */}
        <div className="rounded-lg border border-border/70 bg-bg-elevated/30 p-3">
          <p className="mb-2 text-2xs font-semibold uppercase tracking-wide text-text-muted">
            Step 1 — Prematch condition
          </p>
          <div className="mb-3 flex flex-wrap gap-1.5">
            {(Object.keys(PREMATCH_TYPE_LABELS) as PrematchType[]).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setPrematchType(t)}
                className={cn(
                  "rounded border px-2.5 py-1 text-2xs font-semibold uppercase tracking-wide transition-colors",
                  prematchType === t
                    ? "border-accent-indigo/50 bg-accent-indigo/15 text-accent-indigo"
                    : "border-border/60 text-text-dim hover:border-border"
                )}
              >
                {PREMATCH_TYPE_LABELS[t]}
              </button>
            ))}
          </div>

          {prematchType === "flag" && (
            <select
              value={prematchFlag}
              onChange={(e) => setPrematchFlag(e.target.value as PrematchFlagKey)}
              className="w-full max-w-sm rounded border border-border bg-bg-elevated px-3 py-2 text-xs text-text-primary outline-none focus:border-accent-indigo"
            >
              {PREMATCH_FLAG_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          )}

          {prematchType === "rate" && (
            <div className="flex flex-col gap-3">
              <select
                value={prematchMetric}
                onChange={(e) => setPrematchMetric(e.target.value as PrematchRateMetric)}
                className="w-full max-w-sm rounded border border-border bg-bg-elevated px-3 py-2 text-xs text-text-primary outline-none focus:border-accent-indigo"
              >
                {PREMATCH_RATE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              <label className="flex flex-col gap-1.5 text-2xs text-text-dim">
                Minimum rate · {prematchRateMinValue}%
                <input
                  type="range"
                  min={50}
                  max={100}
                  step={1}
                  value={prematchRateMinValue}
                  onChange={(e) => setPrematchRateMinValue(Number(e.target.value))}
                  className="accent-accent-indigo"
                />
              </label>
            </div>
          )}

          {prematchType === "gk_liability" && (
            <div className="flex flex-col gap-1.5">
              <p className="text-2xs text-text-dim">
                Locked in at lineup announcement — the starting keeper's vulnerability doesn't
                change once kickoff happens.
              </p>
              <SideSelector value={gkSide} onChange={setGkSide} accent="indigo" />
            </div>
          )}

          {prematchType === "key_missing" && (
            <div className="flex flex-col gap-3">
              <SideSelector value={keyMissingSide} onChange={setKeyMissingSide} accent="indigo" />
              <label className="flex flex-col gap-1.5 text-2xs text-text-dim">
                Minimum key players missing · {keyMissingCount}
                <input
                  type="range"
                  min={1}
                  max={6}
                  step={1}
                  value={keyMissingCount}
                  onChange={(e) => setKeyMissingCount(Number(e.target.value))}
                  className="accent-accent-indigo"
                />
              </label>
            </div>
          )}

          {prematchType === "aggregator_chemistry" && (
            <div className="flex flex-col gap-3 sm:flex-row">
              <select
                value={chemMarket}
                onChange={(e) => setChemMarket(e.target.value as ChemistryMarket)}
                className="w-full max-w-xs rounded border border-border bg-bg-elevated px-3 py-2 text-xs text-text-primary outline-none focus:border-accent-indigo"
              >
                {CHEMISTRY_MARKET_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              <select
                value={chemLevel}
                onChange={(e) => setChemLevel(e.target.value as ChemistryLevel)}
                className="w-full max-w-xs rounded border border-border bg-bg-elevated px-3 py-2 text-xs text-text-primary outline-none focus:border-accent-indigo"
              >
                {CHEMISTRY_LEVEL_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
          )}

          {prematchType === "aggregator_breach" && (
            <SideSelector value={breachSide} onChange={setBreachSide} accent="indigo" />
          )}

          {prematchType === "none" && (
            <p className="text-2xs text-text-dim">
              No prematch filter — this rule checks live conditions only, on every fixture.
            </p>
          )}
        </div>

        {/* ── STEP 2: LIVE ── */}
        <div className="rounded-lg border border-border/70 bg-bg-elevated/30 p-3">
          <p className="mb-2 text-2xs font-semibold uppercase tracking-wide text-text-muted">
            Step 2 — Live condition
          </p>
          <div className="mb-3 flex flex-wrap gap-1.5">
            {(Object.keys(LIVE_TYPE_LABELS) as LiveConditionType[]).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setLiveType(t)}
                className={cn(
                  "rounded border px-2.5 py-1 text-2xs font-semibold uppercase tracking-wide transition-colors",
                  liveType === t
                    ? "border-accent-cyan/50 bg-accent-cyan/15 text-accent-cyan"
                    : "border-border/60 text-text-dim hover:border-border"
                )}
              >
                {LIVE_TYPE_LABELS[t]}
              </button>
            ))}
          </div>

          {liveType === "snapshot" && (
            <p className="text-2xs text-text-dim">
              Fires on every live cycle once the prematch condition is met — use this for a
              running feed rather than a spike alert.
            </p>
          )}

          {liveNeedsSide && (
            <div className="flex flex-col gap-3">
              <SideSelector value={liveSide} onChange={setLiveSide} accent="cyan" />
              <label className="flex flex-col gap-1.5 text-2xs text-text-dim">
                Minimum {LIVE_TYPE_LABELS[liveType].toLowerCase()} · {liveMinValue}
                <input
                  type="range"
                  min={sliderCfg.min}
                  max={sliderCfg.max}
                  step={sliderCfg.step}
                  value={liveMinValue}
                  onChange={(e) => setLiveMinValue(Number(e.target.value))}
                  className="accent-accent-cyan"
                />
              </label>
            </div>
          )}

          {liveType === "chaos_index" && (
            <label className="flex flex-col gap-1.5 text-2xs text-text-dim">
              Minimum chaos index · {liveMinValue}
              <input
                type="range"
                min={sliderCfg.min}
                max={sliderCfg.max}
                step={sliderCfg.step}
                value={liveMinValue}
                onChange={(e) => setLiveMinValue(Number(e.target.value))}
                className="accent-accent-amber"
              />
            </label>
          )}

          {liveType === "key_player_lost" && (
            <div className="flex flex-col gap-3">
              <p className="text-2xs text-text-dim">
                Genuinely live — fires only when a starting key player (top-11 by squad worth) is
                actually substituted off during the match, tracked in real time.
              </p>
              <SideSelector value={keyLostSide} onChange={setKeyLostSide} accent="cyan" />
              <label className="flex flex-col gap-1.5 text-2xs text-text-dim">
                Minimum key players lost · {keyLostCount}
                <input
                  type="range"
                  min={1}
                  max={3}
                  step={1}
                  value={keyLostCount}
                  onChange={(e) => setKeyLostCount(Number(e.target.value))}
                  className="accent-accent-cyan"
                />
              </label>
            </div>
          )}
        </div>

        {/* ── STEP 3: MINUTE WINDOW ── */}
        <div className="rounded-lg border border-border/70 bg-bg-elevated/30 p-3">
          <div className="mb-2 flex items-center justify-between">
            <p className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wide text-text-muted">
              <Clock className="h-3.5 w-3.5" />
              Step 3 — Minute window (optional)
            </p>
            <button
              type="button"
              onClick={() => setUseWindow((v) => !v)}
              className={cn(
                "rounded border px-2.5 py-1 text-2xs font-semibold uppercase tracking-wide transition-colors",
                useWindow
                  ? "border-accent-amber/50 bg-accent-amber/15 text-accent-amber"
                  : "border-border/60 text-text-dim hover:border-border"
              )}
            >
              {useWindow ? "Enabled" : "Full Match"}
            </button>
          </div>

          {useWindow ? (
            <div className="flex flex-wrap items-center gap-3">
              <label className="flex flex-col gap-1 text-2xs text-text-dim">
                From
                <input
                  type="number"
                  min={0}
                  max={120}
                  value={windowStart}
                  onChange={(e) => setWindowStart(Number(e.target.value))}
                  className="w-20 rounded border border-border bg-bg-elevated px-2 py-1.5 text-xs text-text-primary outline-none focus:border-accent-amber"
                />
              </label>
              <span className="mt-4 text-text-dim">–</span>
              <label className="flex flex-col gap-1 text-2xs text-text-dim">
                To
                <input
                  type="number"
                  min={0}
                  max={120}
                  value={windowEnd}
                  onChange={(e) => setWindowEnd(Number(e.target.value))}
                  className="w-20 rounded border border-border bg-bg-elevated px-2 py-1.5 text-xs text-text-primary outline-none focus:border-accent-amber"
                />
              </label>
              <span className="mt-4 text-2xs text-text-dim">minutes</span>
            </div>
          ) : (
            <p className="text-2xs text-text-dim">This rule checks every minute of the match.</p>
          )}
        </div>

        {invalidCombo && (
          <p className="text-2xs text-accent-red">
            A rule needs at least one real condition — pick a prematch condition, or a live
            threshold beyond &quot;Every Update&quot;.
          </p>
        )}
        {error && <p className="text-2xs text-accent-red">{error}</p>}

        <Button onClick={handleSave} disabled={saving || invalidCombo || !userId}>
          {saving ? "Saving…" : "Save Rule"}
        </Button>
      </div>

      <div className="glass flex flex-col gap-2 rounded-lg p-4 shadow-panel">
        <div className="mb-1 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-text-primary">Your saved rules</h2>
          <span className="font-mono text-2xs text-text-dim">{rules.length} total</span>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 py-6 text-xs text-text-dim">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading your rules…
          </div>
        ) : rules.length === 0 ? (
          <p className="py-6 text-center text-xs text-text-dim">
            No rules saved yet — build one above to start getting personalized alerts.
          </p>
        ) : (
          <div className="divide-y divide-border/60">
            {rules.map((rule) => {
              const { pre, live, window } = describeRule(rule);
              return (
                <div key={rule.rule_id} className="flex items-center justify-between gap-3 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-semibold text-text-primary">{rule.label}</p>
                    <p className="mt-0.5 text-2xs text-text-dim">
                      {pre} <span className="text-text-muted">AND</span> {live}
                      <span className="ml-2 rounded border border-border/50 px-1 py-0.5 text-[0.6rem] text-text-dim">
                        {window}
                      </span>
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <button
                      type="button"
                      onClick={() => handleToggle(rule)}
                      className={cn(
                        "rounded border px-2 py-1 text-2xs font-semibold uppercase tracking-wide transition-colors",
                        rule.active
                          ? "border-accent-green/40 bg-accent-green/10 text-accent-green"
                          : "border-border/60 text-text-dim"
                      )}
                    >
                      {rule.active ? "Active" : "Paused"}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(rule)}
                      aria-label="Delete rule"
                      className="flex h-7 w-7 items-center justify-center rounded border border-border/60 text-text-dim transition-colors hover:border-accent-red/40 hover:text-accent-red"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function SideSelector({
  value,
  onChange,
  accent,
}: {
  value: RuleSide;
  onChange: (v: RuleSide) => void;
  accent: "indigo" | "cyan";
}) {
  const accentClass =
    accent === "indigo"
      ? "border-accent-indigo/50 bg-accent-indigo/15 text-accent-indigo"
      : "border-accent-cyan/50 bg-accent-cyan/15 text-accent-cyan";

  return (
    <fieldset className="flex gap-1.5">
      {(["home", "away", "any"] as RuleSide[]).map((s) => (
        <button
          key={s}
          type="button"
          onClick={() => onChange(s)}
          className={cn(
            "rounded border px-3 py-1.5 text-2xs font-semibold uppercase tracking-wide transition-colors",
            value === s ? accentClass : "border-border/60 text-text-dim hover:border-border"
          )}
        >
          {s}
        </button>
      ))}
    </fieldset>
  );
}