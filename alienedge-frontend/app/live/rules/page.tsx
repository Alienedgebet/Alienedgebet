"use client";

import { useCallback, useEffect, useState } from "react";
import { SlidersHorizontal, Trash2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useLocalUserId } from "@/lib/use-local-user";
import {
  userRulesApi,
  PREMATCH_FLAG_OPTIONS,
  PREMATCH_RATE_OPTIONS,
  type UserRuleDef,
  type UserRulePrematch,
  type UserRuleLive,
  type PrematchFlagKey,
  type PrematchRateMetric,
} from "@/lib/api";

type PrematchType = "none" | "flag" | "rate";
type LiveType = "snapshot" | "pressure_share" | "chaos_index";
type Side = "home" | "away" | "any";

function buildPrematch(
  type: PrematchType,
  flag: PrematchFlagKey,
  metric: PrematchRateMetric,
  minValue: number
): UserRulePrematch {
  if (type === "flag") return { type: "flag", flag };
  if (type === "rate") return { type: "rate", metric, min_value: minValue };
  return { type: "none" };
}

function buildLive(type: LiveType, side: Side, minValue: number): UserRuleLive {
  if (type === "pressure_share") return { type: "pressure_share", side, min_value: minValue };
  if (type === "chaos_index") return { type: "chaos_index", min_value: minValue };
  return { type: "snapshot" };
}

function describeRule(rule: UserRuleDef): { pre: string; live: string } {
  const pre =
    rule.prematch.type === "none"
      ? "Any prematch state"
      : rule.prematch.type === "flag"
        ? (PREMATCH_FLAG_OPTIONS.find((o) => o.value === rule.prematch.flag)?.label ?? rule.prematch.flag)
        : `${PREMATCH_RATE_OPTIONS.find((o) => o.value === rule.prematch.metric)?.label ?? rule.prematch.metric} ≥ ${rule.prematch.min_value}%`;

  const live =
    rule.live.type === "snapshot"
      ? "Every live update"
      : rule.live.type === "pressure_share"
        ? `${rule.live.side === "any" ? "Either side" : rule.live.side === "home" ? "Home" : "Away"} pressure ≥ ${rule.live.min_value}%`
        : `Chaos index ≥ ${rule.live.min_value}`;

  return { pre, live };
}

export default function LiveRulesPage() {
  const userId = useLocalUserId();

  const [rules, setRules] = useState<UserRuleDef[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [label, setLabel] = useState("");
  const [prematchType, setPrematchType] = useState<PrematchType>("flag");
  const [prematchFlag, setPrematchFlag] = useState<PrematchFlagKey>(PREMATCH_FLAG_OPTIONS[0].value);
  const [prematchMetric, setPrematchMetric] = useState<PrematchRateMetric>(PREMATCH_RATE_OPTIONS[0].value);
  const [prematchMinValue, setPrematchMinValue] = useState(80);
  const [liveType, setLiveType] = useState<LiveType>("pressure_share");
  const [liveSide, setLiveSide] = useState<Side>("any");
  const [liveMinValue, setLiveMinValue] = useState(55);

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

  async function handleSave() {
    if (!userId) return;
    setSaving(true);
    setError(null);
    try {
      await userRulesApi.create({
        user_id: userId,
        label: label.trim() || "Untitled Rule",
        prematch: buildPrematch(prematchType, prematchFlag, prematchMetric, prematchMinValue),
        live: buildLive(liveType, liveSide, liveMinValue),
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

  return (
    <div className="flex flex-col gap-4 p-6">
      <div className="glass flex items-center gap-3 rounded-lg p-4 shadow-panel">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-indigo/15">
          <SlidersHorizontal className="h-5 w-5 text-accent-indigo" />
        </div>
        <div>
          <h1 className="text-base font-bold text-text-primary">Build My Alert</h1>
          <p className="text-xs text-text-secondary">
            Combine a real prematch signal with a real live-match condition. Saved rules run
            against every live fixture, every cycle, on the server — not just on this screen.
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

        <div className="rounded-lg border border-border/70 bg-bg-elevated/30 p-3">
          <p className="mb-2 text-2xs font-semibold uppercase tracking-wide text-text-muted">
            Step 1 — Prematch condition
          </p>
          <div className="mb-3 flex flex-wrap gap-1.5">
            {(["flag", "rate", "none"] as PrematchType[]).map((t) => (
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
                {t === "flag" ? "100% Flag" : t === "rate" ? "Rate Threshold" : "Any / Skip"}
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
                Minimum rate · {prematchMinValue}%
                <input
                  type="range"
                  min={50}
                  max={100}
                  step={1}
                  value={prematchMinValue}
                  onChange={(e) => setPrematchMinValue(Number(e.target.value))}
                  className="accent-accent-indigo"
                />
              </label>
            </div>
          )}

          {prematchType === "none" && (
            <p className="text-2xs text-text-dim">
              No prematch filter — this rule checks live conditions only, on every fixture.
            </p>
          )}
        </div>

        <div className="rounded-lg border border-border/70 bg-bg-elevated/30 p-3">
          <p className="mb-2 text-2xs font-semibold uppercase tracking-wide text-text-muted">
            Step 2 — Live condition
          </p>
          <div className="mb-3 flex flex-wrap gap-1.5">
            {(["pressure_share", "chaos_index", "snapshot"] as LiveType[]).map((t) => (
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
                {t === "pressure_share" ? "Pressure Share" : t === "chaos_index" ? "Chaos Index" : "Every Update"}
              </button>
            ))}
          </div>

          {liveType === "pressure_share" && (
            <div className="flex flex-col gap-3">
              <fieldset className="flex gap-1.5">
                {(["home", "away", "any"] as Side[]).map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setLiveSide(s)}
                    className={cn(
                      "rounded border px-3 py-1.5 text-2xs font-semibold uppercase tracking-wide transition-colors",
                      liveSide === s
                        ? "border-accent-indigo/50 bg-accent-indigo/15 text-accent-indigo"
                        : "border-border/60 text-text-dim hover:border-border"
                    )}
                  >
                    {s}
                  </button>
                ))}
              </fieldset>
              <label className="flex flex-col gap-1.5 text-2xs text-text-dim">
                Minimum pressure share · {liveMinValue}%
                <input
                  type="range"
                  min={40}
                  max={80}
                  step={1}
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
                min={0}
                max={12}
                step={0.5}
                value={liveMinValue}
                onChange={(e) => setLiveMinValue(Number(e.target.value))}
                className="accent-accent-amber"
              />
            </label>
          )}

          {liveType === "snapshot" && (
            <p className="text-2xs text-text-dim">
              Fires on every live cycle once the prematch condition is met — use this for a
              running feed rather than a spike alert.
            </p>
          )}
        </div>

        {invalidCombo && (
          <p className="text-2xs text-accent-red">
            A rule needs at least one real condition — pick a prematch flag/rate, or a live
            pressure/chaos threshold.
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
              const { pre, live } = describeRule(rule);
              return (
                <div key={rule.rule_id} className="flex items-center justify-between gap-3 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-semibold text-text-primary">{rule.label}</p>
                    <p className="mt-0.5 text-2xs text-text-dim">
                      {pre} <span className="text-text-muted">AND</span> {live}
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