"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  SlidersHorizontal,
  Trash2,
  Loader2,
  Clock,
  Check,
  Star,
  Sparkles,
  Target,
  Users,
  LayoutGrid,
  Radio,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth-context";
import { PushToggle, usePushNotifications } from "../edges/PushToggle";
import { cn } from "@/lib/utils";
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
  type UserRuleLiveAny,
  type RuleCandidateMatch,
  type PrematchFlagKey,
  type PrematchRateMetric,
  type ChemistryMarket,
  type ChemistryLevel,
  type RuleSide,
  type RuleGoalDirection,
  type RuleConditionMode,
  type UserRuleLiveGroup,
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

/** One line of plain English per condition, shown under the chips. */
const PREMATCH_TYPE_HINTS: Record<PrematchType, string> = {
  none: "Every fixture qualifies. Pick a condition to narrow the board.",
  flag: "A head-to-head engine that fires on 100% of its sample. Rare, and the only flag-based signal that names a market outright.",
  rate: "How often a side converted in the second half across its recent meetings. Set the bar you actually trust.",
  gk_liability: "Locked in at lineup announcement — the starting keeper's vulnerability cannot change once kickoff happens.",
  key_missing: "Counted from the official squad against the starting XI. Structural, and confirmed before a ball is kicked.",
  aggregator_chemistry: "How the two sides' styles interact on one market. Use it to gate a market, not to describe the match.",
  aggregator_breach: "A side flagged as structurally exposed by the danger engine. The sharpest prematch filter on this board.",
};

/**
 * Live conditions. `goals` is deliberately NOT here: the scoreline is a
 * LIMITATION on whether the alert may be sent at all, not a statistic being
 * watched, so it gets its own step and its own control.
 */
const LIVE_TYPE_LABELS: Record<Exclude<LiveConditionType, "goals">, string> = {
  snapshot: "Every Update",
  pressure_share: "Pressure Share",
  chaos_index: "Chaos Index",
  xg: "Live xG",
  sot: "Shots on Target",
  corners: "Corners",
  da: "Dangerous Attacks",
  key_player_lost: "Key Player Lost (Live)",
};

const GOAL_DIRECTION_LABELS: Record<RuleGoalDirection, string> = {
  under: "Under",
  over: "Over",
  exact: "Exactly",
};

const GOAL_DIRECTION_HINTS: Record<RuleGoalDirection, string> = {
  under: "Alerts only while the match is still UNDER this line — the last moment the price exists.",
  over: "Alerts only once the line has been BEATEN by the running total.",
  exact: "Alerts only when the goal total is exactly this number.",
};

/** Stable empty reference so the derived `candidates` memo never churns. */
const EMPTY_CANDIDATES: RuleCandidateMatch[] = [];

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

/** One live condition the user has added to the group. */
type LiveConditionDraft = {
  id: string;
  type: Exclude<LiveConditionType, "goals">;
  side: RuleSide;
  min_value: number;
  min_count: number;
};

/**
 * Live value slider bounds per type — keeps the UI honest about what range
 * each real stat actually moves in, so the user is not asked to pick a
 * "pressure share" of 400.
 *
 * Module-level, not component-level: newLiveDraft() seeds each condition's
 * default from this and is itself a module-level helper.
 */
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

let draftSeq = 0;
function nextDraftId(): string {
  draftSeq += 1;
  return `c${draftSeq}`;
}

function newLiveDraft(type: Exclude<LiveConditionType, "goals">): LiveConditionDraft {
  const cfg = liveSliderConfig(type);
  return {
    id: nextDraftId(),
    type,
    side: type === "chaos_index" ? "any" : "home",
    min_value: cfg?.max ?? 5,
    min_count: 1,
  };
}

function draftToCondition(d: LiveConditionDraft): UserRuleLive {
  if (d.type === "key_player_lost") {
    return { type: "key_player_lost", side: d.side, min_count: d.min_count };
  }
  return buildLive(d.type, d.side, d.min_value, d.side, d.min_count);
}

function describeGoalGate(direction: RuleGoalDirection, line: number): string {
  return `Scoreline ${GOAL_DIRECTION_LABELS[direction].toLowerCase()} ${line}`;
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
    case "goals":
      return describeGoalGate(l.direction, l.line);
    default:
      return "Unknown";
  }
}

/**
 * Describe a rule's live half, whichever shape it is stored in.
 *
 * Saved rules are always groups, but one saved before multi-select is still a
 * bare single condition on disk, so both must read. The group is labelled by
 * HOW it is decided, not just what it checks — "under 2.5" and "under 2.5 AND
 * xG 2" are very different alerts and must not look identical in the list.
 */
function describeLiveAny(live: UserRuleLiveAny): string {
  if (!("conditions" in live)) return describeLive(live);
  const parts = live.conditions.map(describeLive);
  if (parts.length === 0) return "Every live update";
  if (live.mode === "all" || live.threshold >= parts.length) {
    return parts.length === 1 ? parts[0] : `ALL of ${parts.length} (${parts.join(" + ")})`;
  }
  if (live.threshold === 1) return `ANY of ${parts.length} (${parts.join(" + ")})`;
  return `ANY ${live.threshold} of ${parts.length} (${parts.join(" + ")})`;
}

function describeRule(rule: UserRuleDef): { pre: string; live: string; window: string } {
  return {
    pre: describePrematch(rule.prematch),
    live: describeLiveAny(rule.live),
    window: rule.minute_window
      ? `${rule.minute_window.start}'–${rule.minute_window.end}'`
      : "Full match",
  };
}

/**
 * Does this live scoreline sit inside the user's goal limit?
 *
 * MUST stay identical to _scoreline_condition_met() in
 * LIVE_SCANNER/user_rules_store.py. It exists so the setup board can tell the
 * user "2 of your 3 matches are still inside this limit" BEFORE saving,
 * instead of leaving them to discover it when an alert silently never arrives.
 *
 * null means "not live, or unreadable" and counts as NOT inside, because the
 * server fails closed for exactly the same reason.
 */
function scoreInsideGate(
  score: [number, number] | null | undefined,
  direction: RuleGoalDirection,
  line: number
): boolean | null {
  if (!score) return null;
  const total = score[0] + score[1];
  const base = Math.floor(line);
  if (direction === "under") return total <= base;
  if (direction === "over") return total >= base + 1;
  return total === base;
}

export default function LiveRulesPage() {
  const { user } = useAuth();
  const userId = user?.user_id || null;
  // Where the alert will actually land. Read here so the setup page can tell
  // the user honestly that, without push switched on, they will have to open
  // the app themselves to see it.
  const { state: pushState } = usePushNotifications();

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

  // ── Candidate board ─────────────────────────────────────────────────────
  // Every known fixture, scored by the server with the same predicate the live
  // cycle uses. `key` is the condition this result belongs to, which is what
  // makes the loading state derivable instead of stored.
  const [candState, setCandState] = useState<{
    key: string;
    rows: RuleCandidateMatch[];
    error: string | null;
  }>({ key: "", rows: [], error: null });
  const [showOnlyMatching, setShowOnlyMatching] = useState(true);
  // SOFT watchlist: ids the user accepted. Stored on the rule for ranking and
  // marking; never used to suppress an alert.
  const [watchlist, setWatchlist] = useState<string[]>([]);

  // ── The scoreline gate, now ONE member of the live condition group ─────
  // It used to be an exclusive mode that replaced the live condition, which
  // made "under 2.5 AND home pressure > 60%" inexpressible.
  const [useGoalGate, setUseGoalGate] = useState(true);
  const [goalDirection, setGoalDirection] = useState<RuleGoalDirection>("under");
  const [goalLine, setGoalLine] = useState(2.5);

  // ── Live conditions: any number, with how many must hold ───────────────
  const [liveDrafts, setLiveDrafts] = useState<LiveConditionDraft[]>([
    newLiveDraft("pressure_share"),
  ]);
  const [condMode, setCondMode] = useState<RuleConditionMode>("all");
  const [condThreshold, setCondThreshold] = useState(1);

  // Minute window state
  const [useWindow, setUseWindow] = useState(false);
  const [windowStart, setWindowStart] = useState(0);
  const [windowEnd, setWindowEnd] = useState(90);

  const reload = useCallback(() => {
    if (!userId) return;
    setLoading(true);
    userRulesApi
      .list()
      .then((res) => setRules(res.data))
      .catch(() => setError("Could not load your saved alerts — showing none for now."))
      .finally(() => setLoading(false));
  }, [userId]);

  // Initial load. Deliberately NOT `reload()`: `loading` already starts true,
  // so there is nothing to set synchronously, and setting it inside the effect
  // body is exactly the cascading-render pattern React's lint rule rejects.
  // Every setState here happens in an async callback, and `cancelled` stops a
  // response that arrives after unmount from touching a dead component.
  useEffect(() => {
    if (!userId) return;
    let cancelled = false;
    userRulesApi
      .list()
      .then((res) => {
        if (!cancelled) setRules(res.data);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load your saved alerts — showing none for now.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [userId]);

  // ── The prematch condition the board should be scored against ───────────
  // Memoised so the fetch effect below depends on the CONDITION, not on the
  // eight separate state variables that compose it. Without this the effect
  // would re-fire on every unrelated keystroke.
  const prematchDraft = useMemo<UserRulePrematch>(
    () =>
      buildPrematch(
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
      ),
    [
      prematchType, prematchFlag, prematchMetric, prematchRateMinValue,
      gkSide, keyMissingSide, keyMissingCount, chemMarket, chemLevel, breachSide,
    ]
  );

  // Serialised key identifying which condition the board result belongs to.
  const candKey = JSON.stringify(prematchDraft);

  // Derived, never stored: a result from a different condition is not just
  // stale, it is a different board, so it is treated as "still loading" rather
  // than rendered against the wrong condition.
  const candLoading = candState.key !== candKey;
  const candidates = useMemo(
    () => (candState.key === candKey ? candState.rows : EMPTY_CANDIDATES),
    [candState.key, candState.rows, candKey]
  );
  const candError = candState.key === candKey ? candState.error : null;

  // Score the whole fixture board against the current condition.
  //
  // Loading state is DERIVED, not stored: the board is stale exactly when the
  // loaded key differs from the requested one, so `candLoading` is a comparison
  // rather than a setState in the effect body (which cascades a render on every
  // condition tweak). setState only ever happens in the async callbacks, and
  // `cancelled` stops a slow response for an abandoned condition from
  // overwriting a newer one.
  useEffect(() => {
    if (!userId) return;
    let cancelled = false;
    userRulesApi
      .getCandidates(prematchDraft)
      .then((res) => {
        if (!cancelled) {
          setCandState({ key: candKey, rows: res.data ?? [], error: null });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCandState({
            key: candKey,
            rows: [],
            error: "Could not load the match board — your alert is unaffected.",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [prematchDraft, candKey, userId]);

  const matchingCount = useMemo(
    () => candidates.filter((c) => c.met).length,
    [candidates]
  );

  const visibleCandidates = useMemo(
    () => (showOnlyMatching ? candidates.filter((c) => c.met) : candidates),
    [candidates, showOnlyMatching]
  );

  /**
   * How many of the user's ACCEPTED matches are still inside the goal limit.
   * This is the payoff of pairing the watchlist with the gate: the user can see,
   * at setup time, that the match they care about has already run past the
   * limit they just set — instead of waiting on an alert that can never come.
   */
  const watchlistInsideGate = useMemo(() => {
    if (!useGoalGate) return null;
    const accepted = candidates.filter((c) => watchlist.includes(c.fixture_id));
    if (accepted.length === 0) return null;
    let inside = 0;
    let scored = 0;
    for (const c of accepted) {
      const verdict = scoreInsideGate(c.live_score, goalDirection, goalLine);
      if (verdict === null) continue; // not live — unknown, not "outside"
      scored += 1;
      if (verdict) inside += 1;
    }
    return { inside, scored, total: accepted.length };
  }, [useGoalGate, candidates, watchlist, goalDirection, goalLine]);

  function toggleWatch(id: string) {
    setWatchlist((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  }

  function addLiveCondition(type: Exclude<LiveConditionType, "goals">) {
    setLiveDrafts((prev) =>
      prev.some((d) => d.type === type)
        ? prev // already in the group — no silent duplicates
        : [...prev, newLiveDraft(type)]
    );
  }

  function removeLiveCondition(id: string) {
    setLiveDrafts((prev) => prev.filter((d) => d.id !== id));
  }

  function updateLiveCondition(id: string, patch: Partial<LiveConditionDraft>) {
    setLiveDrafts((prev) => prev.map((d) => (d.id === id ? { ...d, ...patch } : d)));
  }

  /**
   * The live condition group exactly as it will be saved.
   *
   * The scoreline gate is a member of this list like any other, not a separate
   * mode — which is what makes "under 2.5 AND home pressure > 60%" possible.
   * `snapshot` is dropped when other conditions exist because it always passes
   * and would make an "all" group trivially true.
   */
  const liveGroup = useMemo<UserRuleLiveGroup>(() => {
    const conditions: UserRuleLive[] = liveDrafts.map(draftToCondition);
    if (useGoalGate) {
      conditions.unshift({ type: "goals", direction: goalDirection, line: goalLine });
    }
    const meaningful = conditions.filter((c) => c.type !== "snapshot");
    const final = meaningful.length > 0 ? meaningful : conditions;
    // The threshold can never exceed the number of conditions; clamping here
    // means removing a card can never leave the user saving an invalid rule.
    const threshold = Math.min(Math.max(1, condThreshold), final.length);
    return { conditions: final, mode: condMode, threshold };
  }, [liveDrafts, useGoalGate, goalDirection, goalLine, condMode, condThreshold]);

  const liveConditionCount = liveGroup.conditions.length;

  /** One line describing how the group is decided, for the review strip. */
  const liveGroupSummary = useMemo(() => {
    const parts = liveGroup.conditions.map((c) => describeLive(c));
    if (parts.length === 0) return "no live condition";
    const joined = parts.join(" + ");
    if (liveGroup.mode === "all" || liveGroup.threshold >= parts.length) {
      return `ALL of: ${joined}`;
    }
    if (liveGroup.threshold === 1) return `ANY of: ${joined}`;
    return `ANY ${liveGroup.threshold} of ${parts.length}: ${joined}`;
  }, [liveGroup]);



  async function handleSave() {
    if (!userId) return;
    setSaving(true);
    setError(null);
    try {
      const prematch = prematchDraft;
      // The scoreline gate REPLACES the live condition when it is on: the gate
      // is the limitation, and there is nothing to add on top of "the total is
      // still under the line". Turning it off falls back to the live stat.
      await userRulesApi.create({
        label: label.trim() || "Untitled Rule",
        prematch,
        live: liveGroup,
        ...(useWindow ? { minute_window: { start: windowStart, end: windowEnd } } : {}),
        watchlist,
        active: true,
      });
      setLabel("");
      setWatchlist([]);
      reload();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || "Could not set up this alert. Check your conditions and try again.");
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
      await userRulesApi.remove(rule.rule_id);
    } catch {
      reload();
    }
  }

  // A rule needs at least one real condition. The scoreline gate counts as one
  // on its own, so a prematch-less rule is still valid while the gate is on.
  // A rule needs at least one real condition. The scoreline gate counts on its
  // own, so a prematch-less rule is still valid while it is in the group.
  const invalidCombo =
    prematchType === "none" &&
    liveGroup.conditions.every((c) => c.type === "snapshot");

  return (
    <div className="flex flex-col gap-5 p-6">
      {/* ── HEADER ── */}
      <div className="glass relative overflow-hidden rounded-xl p-5 shadow-panel">
        <div
          aria-hidden
          className="pointer-events-none absolute -right-16 -top-24 h-56 w-56 rounded-full bg-accent-indigo/20 blur-3xl"
        />
        <div className="relative flex items-start gap-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent-indigo/15 ring-1 ring-accent-indigo/30">
            <SlidersHorizontal className="h-5 w-5 text-accent-indigo" />
          </div>
          <div className="min-w-0">
            <h1 className="text-lg font-bold tracking-tight text-text-primary">
              Setup My Alert
            </h1>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-text-secondary">
              Choose a real prematch signal, see every match it currently matches, accept the
              ones you care about, then set the goal limit the alert must respect before it
              reaches you. Runs server-side against every live fixture, every cycle.
            </p>
          </div>
        </div>
      </div>

      <div className="glass flex flex-col gap-5 rounded-xl p-5 shadow-panel">
        {/* ── NAME ── */}
        <div className="flex flex-col gap-1.5">
          <label className="text-2xs font-medium uppercase tracking-wider text-text-muted">
            Alert name
          </label>
          <input
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="e.g. Under 2.5 after a danger breach"
            className="w-full max-w-md rounded-lg border border-border bg-bg-elevated px-3.5 py-2.5 text-sm text-text-primary outline-none transition-colors focus:border-accent-indigo"
          />
        </div>

        {/* ══ STEP 1 — PREMATCH + MATCH BOARD ══ */}
        <section className="rounded-xl border border-border/70 bg-bg-elevated/30 p-4">
          <StepHeader
            n={1}
            icon={<LayoutGrid className="h-4 w-4" />}
            title="Prematch condition"
            subtitle="Pick one real signal, then review every match it matches."
            accent="indigo"
          />

          <div className="mb-3 flex flex-wrap gap-1.5">
            {(Object.keys(PREMATCH_TYPE_LABELS) as PrematchType[]).map((t) => (
              <Chip
                key={t}
                active={prematchType === t}
                accent="indigo"
                onClick={() => setPrematchType(t)}
              >
                {PREMATCH_TYPE_LABELS[t]}
              </Chip>
            ))}
          </div>

          <p className="mb-3 flex items-start gap-1.5 text-2xs leading-relaxed text-text-dim">
            <Sparkles className="mt-px h-3 w-3 shrink-0 text-accent-indigo/70" />
            {PREMATCH_TYPE_HINTS[prematchType]}
          </p>

          {prematchType === "flag" && (
            <select
              value={prematchFlag}
              onChange={(e) => setPrematchFlag(e.target.value as PrematchFlagKey)}
              className="w-full max-w-sm rounded-lg border border-border bg-bg-elevated px-3.5 py-2.5 text-sm text-text-primary outline-none transition-colors focus:border-accent-indigo"
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
                className="w-full max-w-sm rounded-lg border border-border bg-bg-elevated px-3.5 py-2.5 text-sm text-text-primary outline-none transition-colors focus:border-accent-indigo"
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
                Locked in at lineup announcement &mdash; the starting keeper&rsquo;s vulnerability
                cannot change once kickoff happens.
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
                className="w-full max-w-xs rounded-lg border border-border bg-bg-elevated px-3.5 py-2.5 text-sm text-text-primary outline-none transition-colors focus:border-accent-indigo"
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
                className="w-full max-w-xs rounded-lg border border-border bg-bg-elevated px-3.5 py-2.5 text-sm text-text-primary outline-none transition-colors focus:border-accent-indigo"
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

          {/* ══ THE MATCH BOARD ══ */}
          <div className="mt-4 rounded-lg border border-border/70 bg-bg-primary/40">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 px-3.5 py-2.5">
              <div className="flex items-center gap-2">
                <Users className="h-3.5 w-3.5 text-accent-cyan" />
                <span className="text-2xs font-semibold uppercase tracking-wider text-text-secondary">
                  Matches under this condition
                </span>
                {!candLoading && (
                  <span className="rounded-full bg-accent-cyan/15 px-2 py-0.5 text-2xs font-semibold text-accent-cyan">
                    {matchingCount} of {candidates.length}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2.5">
                {watchlist.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setWatchlist([])}
                    className="text-2xs text-text-dim underline-offset-2 transition-colors hover:text-text-secondary hover:underline"
                  >
                    Clear {watchlist.length} accepted
                  </button>
                )}
                <label className="flex cursor-pointer items-center gap-1.5 text-2xs text-text-dim">
                  <input
                    type="checkbox"
                    checked={showOnlyMatching}
                    onChange={(e) => setShowOnlyMatching(e.target.checked)}
                    className="h-3 w-3 accent-accent-cyan"
                  />
                  Only matching
                </label>
              </div>
            </div>

            <div className="max-h-80 overflow-y-auto">
              {candLoading ? (
                <div className="flex items-center gap-2 px-3.5 py-6 text-2xs text-text-dim">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> Scoring the board…
                </div>
              ) : candError ? (
                <p className="px-3.5 py-6 text-center text-2xs text-accent-amber">{candError}</p>
              ) : visibleCandidates.length === 0 ? (
                <p className="px-3.5 py-6 text-center text-2xs leading-relaxed text-text-dim">
                  No fixture currently satisfies this condition.
                  <br />
                  The board is built from the prematch feeds on disk right now — try a broader
                  condition, or lower the threshold.
                </p>
              ) : (
                <ul className="divide-y divide-border/50">
                  {visibleCandidates.map((c) => (
                    <CandidateRow
                      key={c.fixture_id}
                      match={c}
                      accepted={watchlist.includes(c.fixture_id)}
                      onToggle={() => toggleWatch(c.fixture_id)}
                      gate={useGoalGate ? { direction: goalDirection, line: goalLine } : null}
                    />
                  ))}
                </ul>
              )}
            </div>

            <p className="border-t border-border/60 px-3.5 py-2 text-2xs leading-relaxed text-text-muted">
              Accepting a match marks it and puts it first in your alerts. It never narrows the
              alert — any fixture that later satisfies the condition can still fire it.
            </p>
          </div>
        </section>

        {/* ══ STEP 2 — LIVE CONDITIONS (pick any combination) ══ */}
        <section className="rounded-xl border border-accent-amber/25 bg-accent-amber/[0.04] p-4">
          <StepHeader
            n={2}
            icon={<Radio className="h-4 w-4" />}
            title="Live conditions"
            subtitle="Add as many as you like, then choose how many must be met before the alert goes out."
            accent="amber"
          />

          {/* ── the scoreline gate, one member of the group ── */}
          <div className="mb-3 rounded-lg border border-accent-amber/30 bg-bg-primary/40 p-3">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wider text-accent-amber">
                <Target className="h-3.5 w-3.5" />
                Scoreline gate
              </span>
              <Chip active={useGoalGate} accent="amber" onClick={() => setUseGoalGate((v) => !v)}>
                {useGoalGate ? "Added" : "Not added"}
              </Chip>
            </div>

            {useGoalGate && (
              <>
                <div className="mb-2.5 flex flex-wrap gap-1.5">
                  {(Object.keys(GOAL_DIRECTION_LABELS) as RuleGoalDirection[]).map((d) => (
                    <Chip
                      key={d}
                      active={goalDirection === d}
                      accent="amber"
                      onClick={() => {
                        setGoalDirection(d);
                        // `exact` only accepts whole goals and the server rejects
                        // a fractional one with a 422, so snap the line here
                        // rather than letting the user save something invalid.
                        if (d === "exact") setGoalLine(Math.round(goalLine));
                      }}
                    >
                      {GOAL_DIRECTION_LABELS[d]}
                    </Chip>
                  ))}
                </div>
                <p className="mb-2.5 text-2xs leading-relaxed text-text-secondary">
                  {GOAL_DIRECTION_HINTS[goalDirection]}
                </p>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-2xs text-text-dim">Goal line</span>
                  <div className="flex items-center gap-1">
                    <StepperButton
                      onClick={() =>
                        setGoalLine((v) => Math.max(0, v - (goalDirection === "exact" ? 1 : 0.5)))
                      }
                      disabled={goalLine <= 0}
                    >
                      −
                    </StepperButton>
                    <span className="min-w-[3.5rem] text-center font-mono text-sm font-semibold text-text-primary">
                      {goalLine}
                    </span>
                    <StepperButton
                      onClick={() =>
                        setGoalLine((v) => Math.min(10, v + (goalDirection === "exact" ? 1 : 0.5)))
                      }
                      disabled={goalLine >= 10}
                    >
                      +
                    </StepperButton>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {(goalDirection === "exact" ? [1, 2, 3, 4, 5] : [0.5, 1.5, 2.5, 3.5, 4.5]).map(
                      (v) => (
                        <Chip key={v} active={goalLine === v} accent="amber" onClick={() => setGoalLine(v)}>
                          {v}
                        </Chip>
                      )
                    )}
                  </div>
                </div>
              </>
            )}
          </div>

          {/* ── the other live conditions, as removable cards ── */}
          <div className="flex flex-col gap-2">
            {liveDrafts.map((d) => {
              const cfg = liveSliderConfig(d.type);
              const needsSide = LIVE_SIDED_TYPES.includes(d.type) && d.type !== "key_player_lost";
              const isCount = d.type === "key_player_lost";
              return (
                <div
                  key={d.id}
                  className="rounded-lg border border-border/70 bg-bg-primary/40 p-3"
                >
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <span className="text-2xs font-semibold uppercase tracking-wider text-text-secondary">
                      {LIVE_TYPE_LABELS[d.type]}
                    </span>
                    <button
                      type="button"
                      onClick={() => removeLiveCondition(d.id)}
                      aria-label={`Remove ${LIVE_TYPE_LABELS[d.type]}`}
                      className="flex h-6 w-6 items-center justify-center rounded border border-border/60 text-text-dim transition-colors hover:border-accent-red/40 hover:text-accent-red"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    {needsSide && (
                      <SideSelector
                        value={d.side}
                        onChange={(v) => updateLiveCondition(d.id, { side: v })}
                        accent="cyan"
                      />
                    )}
                    <div className="flex min-w-[10rem] flex-1 items-center gap-2">
                      <input
                        type="range"
                        min={isCount ? 1 : cfg?.min ?? 0}
                        max={isCount ? 5 : cfg?.max ?? 100}
                        step={isCount ? 1 : cfg?.step ?? 1}
                        value={isCount ? d.min_count : d.min_value}
                        onChange={(e) =>
                          updateLiveCondition(
                            d.id,
                            isCount
                              ? { min_count: Number(e.target.value) }
                              : { min_value: Number(e.target.value) }
                          )
                        }
                        className="h-1 flex-1 cursor-pointer appearance-none rounded-full bg-border accent-accent-cyan"
                      />
                      <span className="min-w-[2.5rem] text-right font-mono text-xs font-semibold text-text-primary">
                        {isCount ? d.min_count : d.min_value}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* ── add another ── */}
          <div className="mt-3 flex flex-wrap gap-1.5">
            {(Object.keys(LIVE_TYPE_LABELS) as Exclude<LiveConditionType, "goals">[])
              .filter((t) => !liveDrafts.some((d) => d.type === t))
              .map((t) => (
                <Chip key={t} active={false} accent="cyan" onClick={() => addLiveCondition(t)}>
                  + {LIVE_TYPE_LABELS[t]}
                </Chip>
              ))}
            {liveDrafts.length + (useGoalGate ? 1 : 0) === 0 && (
              <span className="text-2xs text-text-dim">
                Add at least one condition.
              </span>
            )}
          </div>

          {/* ── how many must be met ── */}
          {liveConditionCount > 1 && (
            <div className="mt-3 rounded-lg border border-border/70 bg-bg-primary/40 p-3">
              <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-text-muted">
                How many must be met?
              </p>
              <div className="flex flex-wrap items-center gap-1.5">
                <Chip active={condMode === "all"} accent="cyan" onClick={() => setCondMode("all")}>
                  All {liveConditionCount}
                </Chip>
                {Array.from({ length: liveConditionCount - 1 }, (_, i) => i + 1).map((n) => (
                  <Chip
                    key={n}
                    active={condMode === "at_least" && condThreshold === n}
                    accent="cyan"
                    onClick={() => {
                      setCondMode("at_least");
                      setCondThreshold(n);
                    }}
                  >
                    Any {n}
                  </Chip>
                ))}
              </div>
              <p className="mt-2 text-2xs leading-relaxed text-text-secondary">
                {liveGroupSummary}
              </p>
            </div>
          )}

          {watchlistInsideGate && watchlistInsideGate.total > 0 && (
            <div
              className={cn(
                "mt-3 flex items-start gap-2 rounded-lg border px-3 py-2.5",
                watchlistInsideGate.scored === 0
                  ? "border-border/60 bg-bg-primary/30"
                  : watchlistInsideGate.inside > 0
                    ? "border-accent-green/25 bg-accent-green/[0.06]"
                    : "border-accent-red/30 bg-accent-red/[0.06]"
              )}
            >
              <Radio
                className={cn(
                  "mt-px h-3.5 w-3.5 shrink-0",
                  watchlistInsideGate.scored === 0
                    ? "text-text-dim"
                    : watchlistInsideGate.inside > 0
                      ? "text-accent-green"
                      : "text-accent-red"
                )}
              />
              <p className="text-2xs leading-relaxed text-text-secondary">
                {watchlistInsideGate.scored === 0 ? (
                  <>
                    None of your {watchlistInsideGate.total} accepted match
                    {watchlistInsideGate.total === 1 ? " is" : "es are"} live yet, so there is
                    no scoreline to check. The gate applies from kickoff.
                  </>
                ) : watchlistInsideGate.inside > 0 ? (
                  <>
                    <span className="font-semibold text-accent-green">
                      {watchlistInsideGate.inside} of {watchlistInsideGate.scored}
                    </span>{" "}
                    live accepted match{watchlistInsideGate.scored === 1 ? " is" : "es are"}{" "}
                    still {GOAL_DIRECTION_LABELS[goalDirection].toLowerCase()} {goalLine}.
                  </>
                ) : (
                  <>
                    <span className="font-semibold text-accent-red">
                      All {watchlistInsideGate.scored}
                    </span>{" "}
                    live accepted match{watchlistInsideGate.scored === 1 ? " has" : "es have"}{" "}
                    already run past {GOAL_DIRECTION_LABELS[goalDirection].toLowerCase()}{" "}
                    {goalLine}. Other fixtures that qualify will still alert — these will not.
                  </>
                )}
              </p>
            </div>
          )}
        </section>


        {/* ══ STEP 4 — MINUTE WINDOW ══ */}
        <section className="rounded-xl border border-border/70 bg-bg-elevated/30 p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <StepHeader
              n={4}
              icon={<Clock className="h-4 w-4" />}
              title="Minute window"
              subtitle="Narrow the alert to the part of the match that matters to you."
              accent="indigo"
            />
            <Chip active={useWindow} accent="amber" onClick={() => setUseWindow((v) => !v)}>
              {useWindow ? "Enabled" : "Full Match"}
            </Chip>
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
                  className="w-20 rounded-lg border border-border bg-bg-elevated px-2.5 py-2 text-sm text-text-primary outline-none transition-colors focus:border-accent-amber"
                />
              </label>
              <span className="mt-5 text-text-dim">–</span>
              <label className="flex flex-col gap-1 text-2xs text-text-dim">
                To
                <input
                  type="number"
                  min={0}
                  max={120}
                  value={windowEnd}
                  onChange={(e) => setWindowEnd(Number(e.target.value))}
                  className="w-20 rounded-lg border border-border bg-bg-elevated px-2.5 py-2 text-sm text-text-primary outline-none transition-colors focus:border-accent-amber"
                />
              </label>
              <span className="mt-5 text-2xs text-text-dim">minutes</span>
            </div>
          ) : (
            <p className="text-2xs text-text-dim">This rule checks every minute of the match.</p>
          )}
        </section>

        {/* ══ REVIEW ══ */}
        <div className="rounded-xl border border-border/70 bg-bg-primary/40 p-4">
          <p className="mb-2.5 text-2xs font-semibold uppercase tracking-wider text-text-muted">
            This alert will
          </p>
          <ul className="flex flex-col gap-1.5">
            <ReviewLine
              n="1"
              text={`Trigger on a fixture where — ${describePrematch(prematchDraft).toLowerCase()}.`}
            />
            <ReviewLine
              n="2"
              text={`Go out when — ${liveGroupSummary}.`}
            />
            <ReviewLine
              n="3"
              text={
                useWindow
                  ? `Between minute ${windowStart} and minute ${windowEnd} only.`
                  : `At any minute of the match.`
              }
            />
            <ReviewLine
              n="4"
              text={
                watchlist.length === 0
                  ? `No matches accepted yet — it will consider every qualifying fixture.`
                  : `${watchlist.length} accepted match${watchlist.length === 1 ? "" : "es"} marked and ranked first. It still fires on any other fixture that qualifies.`
              }
            />
          </ul>
        </div>

        {invalidCombo && (
          <p className="text-2xs text-accent-red">
            An alert needs at least one real condition — pick a prematch condition, a scoreline
            limit, or a live threshold beyond &quot;Every Update&quot;.
          </p>
        )}
        {error && <p className="text-2xs text-accent-red">{error}</p>}

        {/* ── WHERE THIS ALERT WILL REACH YOU ── */}
        <div className="rounded-xl border border-border/70 bg-bg-elevated/30 p-4">
          <p className="mb-2.5 text-2xs font-semibold uppercase tracking-wider text-text-muted">
            Where this alert will reach you
          </p>
          <PushToggle className="border-0 bg-transparent p-0" />
          <p className="mt-2.5 text-2xs leading-relaxed text-text-muted">
            {pushState.subscribed
              ? "This alert will be pushed to your phone and shown here, whether or not the app is open."
              : "Turn on push above to be alerted on your phone. Without it this alert only appears when you open the app."}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Button
            onClick={handleSave}
            disabled={saving || invalidCombo || !userId}
            className="h-10 gap-2 rounded-lg bg-accent-indigo px-6 text-sm font-semibold text-white transition-all hover:bg-accent-indigo/85"
          >
            {saving ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> Setting up…
              </>
            ) : (
              <>
                <Check className="h-4 w-4" /> Setup my alert
              </>
            )}
          </Button>
          {saving && <span className="text-2xs text-text-dim">Arming it on the live scanner…</span>}
        </div>
      </div>

      <div className="glass flex flex-col gap-2 rounded-xl p-5 shadow-panel">
        <div className="mb-1 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-text-primary">Your alerts</h2>
          <span className="font-mono text-2xs text-text-dim">{rules.length} total</span>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 py-6 text-xs text-text-dim">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading your alerts…
          </div>
        ) : rules.length === 0 ? (
          <p className="py-6 text-center text-xs text-text-dim">
            No alerts set up yet — build one above to start getting personalized alerts.
          </p>
        ) : (
          <div className="divide-y divide-border/60">
            {rules.map((rule) => {
              const { pre, live, window } = describeRule(rule);
              const watchCount = rule.watchlist?.length ?? 0;
              return (
                <div key={rule.rule_id} className="flex items-center justify-between gap-3 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-1.5 truncate text-xs font-semibold text-text-primary">
                      {watchCount > 0 && (
                        <Star className="h-3 w-3 shrink-0 fill-accent-amber/60 text-accent-amber" />
                      )}
                      {rule.label}
                    </p>
                    <p className="mt-0.5 text-2xs text-text-dim">
                      {pre} <span className="text-text-muted">AND</span> {live}
                      <span className="ml-2 rounded border border-border/50 px-1 py-0.5 text-[0.6rem] text-text-dim">
                        {window}
                      </span>
                      {watchCount > 0 && (
                        <span className="ml-2 inline-flex items-center gap-1 text-accent-amber/80">
                          <Star className="h-2.5 w-2.5" />
                          {watchCount} marked
                        </span>
                      )}
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

type Accent = "indigo" | "cyan" | "amber";

const ACCENT_ACTIVE: Record<Accent, string> = {
  indigo: "border-accent-indigo/50 bg-accent-indigo/15 text-accent-indigo",
  cyan: "border-accent-cyan/50 bg-accent-cyan/15 text-accent-cyan",
  amber: "border-accent-amber/50 bg-accent-amber/15 text-accent-amber",
};

const ACCENT_TEXT: Record<Accent, string> = {
  indigo: "text-accent-indigo",
  cyan: "text-accent-cyan",
  amber: "text-accent-amber",
};

/** One selectable option pill. */
function Chip({
  active,
  onClick,
  accent,
  children,
}: {
  active: boolean;
  onClick: () => void;
  accent: Accent;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "rounded-lg border px-3 py-1.5 text-2xs font-semibold uppercase tracking-wide transition-colors",
        active
          ? ACCENT_ACTIVE[accent]
          : "border-border/60 text-text-dim hover:border-border hover:text-text-secondary"
      )}
    >
      {children}
    </button>
  );
}

/** The numbered step header used by all four steps. */
function StepHeader({
  n,
  icon,
  title,
  subtitle,
  accent,
}: {
  n: number;
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  accent: Accent;
}) {
  return (
    <div className="mb-3 flex items-start gap-2.5">
      <span
        className={cn(
          "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-lg border text-2xs font-bold",
          accent === "indigo" && "border-accent-indigo/40 bg-accent-indigo/15",
          accent === "cyan" && "border-accent-cyan/40 bg-accent-cyan/15",
          accent === "amber" && "border-accent-amber/40 bg-accent-amber/15",
          ACCENT_TEXT[accent]
        )}
      >
        {n}
      </span>
      <div className="min-w-0">
        <p className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wider text-text-primary">
          {icon}
          {title}
        </p>
        <p className="mt-0.5 text-2xs leading-relaxed text-text-muted">{subtitle}</p>
      </div>
    </div>
  );
}

/** The −/+ control wrapped around the goal line. */
function StepperButton({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label="Adjust goal line"
      className="flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-bg-elevated text-sm text-text-secondary transition-colors hover:border-accent-amber/50 hover:text-accent-amber disabled:pointer-events-none disabled:opacity-30"
    >
      {children}
    </button>
  );
}

/** One numbered sentence in the review strip. */
function ReviewLine({ n, text }: { n: string; text: string }) {
  return (
    <li className="flex items-start gap-2.5">
      <span className="mt-px flex h-4 w-4 shrink-0 items-center justify-center rounded bg-accent-indigo/15 text-[0.6rem] font-bold text-accent-indigo">
        {n}
      </span>
      <span className="text-2xs leading-relaxed text-text-secondary">{text}</span>
    </li>
  );
}

/** A small factual pill. Never renders a value the feed did not publish. */
function FactPill({
  tone,
  children,
}: {
  tone: "neutral" | "good" | "bad";
  children: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "rounded border px-1.5 py-0.5 text-[0.6rem] font-medium",
        tone === "neutral" && "border-border/60 text-text-dim",
        tone === "good" && "border-accent-green/30 bg-accent-green/10 text-accent-green",
        tone === "bad" && "border-accent-red/30 bg-accent-red/10 text-accent-red"
      )}
    >
      {children}
    </span>
  );
}

/**
 * One match on the setup board.
 *
 * Everything shown here is a real, already-on-disk fact — the condition
 * predicate's own reason string, the confirmed lineup/formation, the missing
 * count, the danger status, and (only for a genuinely live fixture) the running
 * scoreline. A field the feed did not publish is simply omitted rather than
 * shown as a zero, because "0 key players missing" and "we have no squad data"
 * are opposite facts and only one of them is a reason to act.
 */
function CandidateRow({
  match,
  accepted,
  onToggle,
  gate,
}: {
  match: RuleCandidateMatch;
  accepted: boolean;
  onToggle: () => void;
  gate: { direction: RuleGoalDirection; line: number } | null;
}) {
  const ev = match.evidence;
  const gateVerdict = gate ? scoreInsideGate(match.live_score, gate.direction, gate.line) : null;

  return (
    <li>
      <button
        type="button"
        onClick={onToggle}
        aria-pressed={accepted}
        className={cn(
          "flex w-full items-start gap-3 px-3.5 py-3 text-left transition-colors",
          accepted ? "bg-accent-amber/[0.07]" : "hover:bg-bg-elevated/50"
        )}
      >
        {/* Accept toggle */}
        <span
          className={cn(
            "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-colors",
            accepted
              ? "border-accent-amber bg-accent-amber/20 text-accent-amber"
              : "border-border/70 text-transparent"
          )}
        >
          {accepted ? <Star className="h-3 w-3 fill-accent-amber" /> : <Check className="h-3 w-3" />}
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span
              className={cn(
                "truncate text-xs font-semibold",
                match.met ? "text-text-primary" : "text-text-muted"
              )}
            >
              {match.name}
            </span>

            {!match.met && (
              <FactPill tone="neutral">does not match</FactPill>
            )}

            {match.live_score && (
              <span className="rounded bg-accent-cyan/15 px-1.5 py-0.5 font-mono text-[0.6rem] font-bold text-accent-cyan">
                {match.live_score[0]}–{match.live_score[1]} LIVE
              </span>
            )}

            {match.live_score === null && gate && (
              <FactPill tone="neutral">not live</FactPill>
            )}
          </div>

          <p className="mt-1 text-2xs leading-relaxed text-text-dim">{match.reason}</p>

          {/* Real, on-disk evidence only. */}
          <div className="mt-1.5 flex flex-wrap gap-1">
            {ev.has_formation && Object.values(ev.formations ?? {}).length > 0 && (
              <FactPill tone="neutral">
                {Object.values(ev.formations ?? {}).join(" / ")}
              </FactPill>
            )}
            {ev.home_missing != null && (
              <FactPill tone={ev.home_missing > 0 ? "bad" : "neutral"}>
                H missing {ev.home_missing}
              </FactPill>
            )}
            {ev.away_missing != null && (
              <FactPill tone={ev.away_missing > 0 ? "bad" : "neutral"}>
                A missing {ev.away_missing}
              </FactPill>
            )}
            {ev.home_gk_out && <FactPill tone="bad">GK down (H)</FactPill>}
            {ev.away_gk_out && <FactPill tone="bad">GK down (A)</FactPill>}
            {ev.home_breach && <FactPill tone="bad">Danger (H)</FactPill>}
            {ev.away_breach && <FactPill tone="bad">Danger (A)</FactPill>}
            {ev.has_lineup && !ev.home_breach && !ev.away_breach && !ev.home_gk_out && !ev.away_gk_out && (
              <FactPill tone="good">Lineup confirmed</FactPill>
            )}
          </div>
        </div>

        {/* Where this match sits against the goal limit the user just set. */}
        {gate && (
          <span
            className={cn(
              "mt-0.5 shrink-0 rounded-md border px-2 py-1 text-[0.6rem] font-semibold",
              gateVerdict === null
                ? "border-border/60 text-text-dim"
                : gateVerdict
                  ? "border-accent-green/40 bg-accent-green/10 text-accent-green"
                  : "border-accent-red/40 bg-accent-red/10 text-accent-red"
            )}
          >
            {gateVerdict === null
              ? "—"
              : gateVerdict
                ? "Inside limit"
                : "Past limit"}
          </span>
        )}
      </button>
    </li>
  );
}
