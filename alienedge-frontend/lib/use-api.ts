"use client";

import { useCallback, useEffect, useRef, useState, type DependencyList } from "react";
import { isAxiosError, type AxiosError, type AxiosResponse } from "axios";
import { clearRawCache } from "@/lib/api";

// ============================================================
// GENERIC DATA-FETCHING HOOK
// Wraps any lib/api.ts call with loading/error/data state so
// market pages don't hand-roll useEffect boilerplate per stage.
//
// DEMO CONTRACT (strict by default):
//   A. Successful real non-empty response  → REAL DATA
//   B. Successful real empty response      → REAL EMPTY (never demo)
//   C. API/network/timeout/5xx failure     → API FAILURE (never demo)
//   D. Demo/mock explicitly requested      → DEMO DATA (isMock=true)
//
// Demo is only applied when explicitly enabled, either per-hook via the
// `demo` option or globally via NEXT_PUBLIC_DEMO_MODE=1. `isMock` is TRUE
// only while actual mock data is displayed.
// Optional `cacheKey` enables in-memory caching so revisiting a
// page within the TTL window returns data instantly without a
// network round-trip.
// ============================================================

// ── In-memory response cache ──────────────────────────────────
// Scoped to the browser session (cleared on full reload).
// TTL is intentionally short — football fixture data for a given
// date is static within a session but we don't want to serve
// yesterday's data if the user runs analysis across midnight.

const CACHE_TTL_MS = 3 * 60 * 1000; // 3 minutes

/**
 * How often a Verify feed re-checks the backend.
 *
 * 45s sits inside the 30-45s target and comfortably under the ~4 minute live
 * scanner cycle, so an unsettled match's verdict (PENDING -> IN_PLAY ->
 * WON/LOST) is picked up promptly without hammering the API. Pages pass this
 * straight to `useApi`/`ChainStage`, which reuses the existing polling
 * mechanism — a tick bypasses the cache and hits the network, then the newer
 * backend payload replaces the cached one.
 */
export const VERIFY_REFRESH_MS = 45_000;

/** Explicit global demo-mode switch for the whole deployment. */
export const DEMO_MODE_ENABLED =
  process.env.NEXT_PUBLIC_DEMO_MODE === "1" ||
  process.env.NEXT_PUBLIC_DEMO_MODE === "true";

interface CacheEntry<T> {
  data: T;
  ts: number;
}

const apiCache = new Map<string, CacheEntry<unknown>>();
const PERSISTENT_CACHE_PREFIX = "alienedge:api-cache:";
// The persistent tier keeps a page instant on re-entry. It NO LONGER decides
// whether data is deleted — only whether it must be re-checked against the
// backend. Expiry marks a payload as needing revalidation; it never discards a
// settled (finished) Verify record, which must survive as history.
const PERSISTENT_CACHE_TTL_MS = 24 * 60 * 60 * 1000;

// ── Verify / verification awareness ───────────────────────────────────
// A Verify verdict reaches a terminal state once the match is decided. Only
// these verdicts are "settled" and therefore permanent; everything else
// (PENDING, IN_PLAY) is provisional and must be re-checked.
const TERMINAL_VERDICTS = new Set(["WON", "LOST", "VOID", "SETTLED", "CANCELLED"]);

function readVerificationVerdict(node: unknown): string | null {
  // A verification payload lives on a row as `row.verification`. Read it
  // defensively: feeds are heterogeneous and a malformed row must never throw
  // inside a cache read.
  if (!node || typeof node !== "object") return null;
  const verification = (node as Record<string, unknown>).verification;
  if (!verification || typeof verification !== "object") return null;
  const verdict = (verification as Record<string, unknown>).verdict;
  return typeof verdict === "string" ? verdict : null;
}

/** True when this row carries a terminal (settled) Verify verdict. */
function isSettledRow(node: unknown): boolean {
  const verdict = readVerificationVerdict(node);
  return verdict !== null && TERMINAL_VERDICTS.has(verdict);
}

function collectNodes(payload: unknown, out: unknown[], depth = 0): void {
  // Walks a response payload to find candidate row objects. Payloads are
  // either a flat array of rows or a composite object of such arrays
  // (e.g. { u25: [...], u35: [...] }), so both shapes are handled.
  if (depth > 3 || payload == null) return;
  if (Array.isArray(payload)) {
    for (const item of payload) collectNodes(item, out, depth + 1);
    return;
  }
  if (typeof payload !== "object") return;
  const record = payload as Record<string, unknown>;
  if ("verification" in record) {
    out.push(record);
    return;
  }
  for (const value of Object.values(record)) {
    if (Array.isArray(value) || (value && typeof value === "object")) {
      collectNodes(value, out, depth + 1);
    }
  }
}

/**
 * True when this payload contains Verify data.
 *
 * Only payloads that actually carry verification objects opt into the
 * settled-preservation and revalidation behaviour below. Every other
 * `useApi` consumer (live feeds, weekly strips, dashboard) keeps exactly the
 * caching semantics it has today, so this change cannot leak into them.
 */
export function payloadHasVerification(payload: unknown): boolean {
  const nodes: unknown[] = [];
  collectNodes(payload, nodes);
  return nodes.some((node) => readVerificationVerdict(node) !== null);
}

/** True when at least one row in this payload has settled. */
function payloadIsSettled(payload: unknown): boolean {
  const nodes: unknown[] = [];
  collectNodes(payload, nodes);
  return nodes.some((node) => isSettledRow(node));
}

function getPersistentEntry<T>(key: string): CacheEntry<T> | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(`${PERSISTENT_CACHE_PREFIX}${key}`);
    if (!raw) return null;
    const entry = JSON.parse(raw) as CacheEntry<T>;
    if (!entry) {
      window.localStorage.removeItem(`${PERSISTENT_CACHE_PREFIX}${key}`);
      return null;
    }
    if (Date.now() - Number(entry.ts) > PERSISTENT_CACHE_TTL_MS) {
      // Expired. A SETTLED payload is permanent history: keep serving it and
      // let the refresh mechanism re-check the backend. An unsettled payload
      // is discarded so the next read reflects reality rather than replaying a
      // stale "Pending" for another day.
      if (payloadIsSettled(entry.data)) {
        return entry;
      }
      window.localStorage.removeItem(`${PERSISTENT_CACHE_PREFIX}${key}`);
      return null;
    }
    return entry;
  } catch {
    return null;
  }
}

function getCached<T>(key: string): T | null {
  const entry = apiCache.get(key) as CacheEntry<T> | undefined;
  if (entry) {
    // The memory tier expires quickly. As with the persistent tier, a settled
    // payload is retained past its TTL so a finished match never disappears
    // from the board; only unsettled data is dropped for re-fetching.
    if (Date.now() - entry.ts > CACHE_TTL_MS && !payloadIsSettled(entry.data)) {
      apiCache.delete(key);
    } else {
      return entry.data;
    }
  }
  const persistent = getPersistentEntry<T>(key);
  if (persistent !== null) {
    // Carry the ORIGINAL timestamp across from the persistent tier. Re-stamping
    // with Date.now() would make a payload read back from localStorage look
    // brand new, so it would never age out and never trigger revalidation —
    // which is exactly the stale-"Pending" bug this change exists to fix.
    apiCache.set(key, { data: persistent.data as unknown, ts: persistent.ts });
  }
  return persistent !== null ? persistent.data : null;
}

function setCached<T>(key: string, data: T): void {
  const entry: CacheEntry<T> = { data, ts: Date.now() };
  apiCache.set(key, { data: data as unknown, ts: entry.ts });
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(`${PERSISTENT_CACHE_PREFIX}${key}`, JSON.stringify(entry));
    } catch {
      // Storage can be unavailable in private browsing; memory caching still works.
    }
  }
}

/** Invalidate all cache entries that start with a given prefix. */
export function invalidateCache(prefix: string): void {
  for (const key of apiCache.keys()) {
    if (key.startsWith(prefix)) apiCache.delete(key);
  }
}

// ── Hook types ────────────────────────────────────────────────

export interface UseApiOptions<T> {
  /**
   * Typed demo payload used ONLY when demo is explicitly enabled (see
   * `demo`). The live fetch always runs — fallback never replaces the call
   * on its own.
   */
  fallback?: T | (() => T);
  /**
   * When provided, successful live responses are stored under this key
   * and returned synchronously on the next mount/dep-change if still
   * fresh (< 3 min). Derive keys from endpoint name + serialised deps,
   * e.g. `"win-apex:2026-08-07"`.
   */
  cacheKey?: string;
  refreshMs?: number;
  /**
   * Explicit opt-in for demo fallback rendering. When `true`, `fallback`
   * is used as the initial seed, to fill genuinely-empty engine responses,
   * and when the request fails — always flagged with `isMock: true`. When
   * `false` or omitted, the fallback is NEVER applied automatically: a real
   * empty response stays a real empty state and failures surface as
   * `error`. Defaults to `NEXT_PUBLIC_DEMO_MODE === "1"`.
   */
  demo?: boolean;
}

export interface UseApiResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  /**
   * True while a fetch is in flight AND previous data already exists —
   * i.e. a background revalidation (date change, manual refetch), not the
   * very first load. Lets consumers dim/keep the last render instead of
   * dropping to a skeleton on every request.
   */
  isRefetching: boolean;
  /** True when the current `data` came from `fallback`, not the live API. */
  isMock: boolean;
  /** True when the last refresh failed but the previous real payload is retained. */
  stale: boolean;
  /** Re-runs the fetcher against the current deps without waiting for them to change. */
  refetch: () => void;
}
export interface UseApiBatchItem<T> {
  key: string;
  fetcher: () => Promise<AxiosResponse<T>>;
  cacheKey?: string;
  fallback?: T | (() => T);
}

export interface UseApiBatchOptions {
  refreshMs?: number;
  demo?: boolean;
}

/**
 * Fetch independent market feeds in parallel while allowing each result to
 * paint as soon as it settles. Promise.allSettled keeps one slow/failed market
 * from blocking the rest of the dashboard.
 */
export function useApiBatch<T>(
  items: UseApiBatchItem<T>[],
  deps: DependencyList,
  options?: UseApiBatchOptions,
): UseApiResult<T>[] {
  const demoActive = options?.demo ?? DEMO_MODE_ENABLED;
  const requestKey = items.map((item) => item.key).join("|");
  const initial = items.map((item) => {
    const cached = item.cacheKey ? getCached<T>(item.cacheKey) : null;
    const fallback = demoActive ? resolveFallback(item.fallback) : undefined;
    const seeded = cached ?? fallback ?? null;
    return {
      data: seeded,
      loading: seeded === null,
      error: null as string | null,
      isRefetching: seeded !== null,
      isMock: cached === null && seeded !== null,
      stale: false,
      refetch: () => {},
    };
  });
  const [results, setResults] = useState<UseApiResult<T>[]>(initial);
  const activeKeyRef = useRef(requestKey);
  const [refetchTick, setRefetchTick] = useState(0);
  const lastTickRef = useRef(0);

  useEffect(() => {
    const refreshMs = options?.refreshMs ?? 0;
    if (refreshMs <= 0) return;
    const timer = window.setInterval(() => setRefetchTick((value) => value + 1), refreshMs);
    return () => window.clearInterval(timer);
  }, [options?.refreshMs]);

  useEffect(() => {
    let cancelled = false;
    const explicitRefresh = refetchTick !== lastTickRef.current;
    lastTickRef.current = refetchTick;
    if (explicitRefresh) clearRawCache();
    if (activeKeyRef.current !== requestKey) {
      activeKeyRef.current = requestKey;
      setResults(initial);
    } else {
      setResults((previous) => previous.map((result) => ({
        ...result,
        loading: result.data === null,
        isRefetching: result.data !== null,
        error: null,
      })));
    }

    const requests = items.map((item, index) => Promise.resolve()
      .then(item.fetcher)
      .then((response) => {
        if (cancelled) return response;
        const payload = response.data;
        const empty = isEmptyPayload(payload);
        setResults((previous) => previous.map((result, resultIndex) => {
          if (resultIndex !== index) return result;
          const fallback = demoActive ? resolveFallback(item.fallback) : undefined;
          if (empty && fallback !== undefined) {
            return { ...result, data: fallback, loading: false, isRefetching: false, isMock: true, stale: false, error: null };
          }
          if (empty && result.data !== null) {
            return { ...result, loading: false, isRefetching: false, isMock: false, stale: true, error: null };
          }
          if (item.cacheKey) setCached(item.cacheKey, payload);
          return { ...result, data: payload, loading: false, isRefetching: false, isMock: false, stale: false, error: null };
        }));
        return response;
      })
      .catch((error: unknown) => {
        if (cancelled) throw error;
        const message = isAxiosError(error)
          ? extractErrorDetail(error) ?? error.message
          : error instanceof Error
            ? error.message
            : "Request failed";
        setResults((previous) => previous.map((result, resultIndex) => resultIndex === index
          ? { ...result, loading: false, isRefetching: false, stale: result.data !== null, error: message }
          : result));
        throw error;
      }));

    void Promise.allSettled(requests);
    return () => { cancelled = true; };
    // The caller memoizes `items`; requestKey changes when the feed set changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, refetchTick, requestKey]);

  return results.map((result) => ({
    ...result,
    refetch: () => setRefetchTick((value) => value + 1),
  }));
}



// ── Helpers ───────────────────────────────────────────────────

function extractErrorDetail(err: AxiosError): string | undefined {
  const responseData = err.response?.data;
  if (responseData && typeof responseData === "object" && "detail" in responseData) {
    const detail = (responseData as Record<string, unknown>).detail;
    return typeof detail === "string" ? detail : undefined;
  }
  return undefined;
}

function resolveFallback<T>(fallback: T | (() => T) | undefined): T | undefined {
  if (fallback === undefined) return undefined;
  if (typeof fallback === "function") {
    return (fallback as () => T)();
  }
  return fallback;
}

/** Empty array, nullish, or composite whose array fields are all empty. */
function isEmptyPayload(data: unknown): boolean {
  if (data == null) return true;
  if (Array.isArray(data)) return data.length === 0;
  if (typeof data === "object") {
    const values = Object.values(data as Record<string, unknown>);
    if (values.length === 0) return true;
    const arrayValues = values.filter(Array.isArray);
    if (arrayValues.length > 0) {
      return arrayValues.every((v) => (v as unknown[]).length === 0);
    }
  }
  return false;
}

// ── Main hook ─────────────────────────────────────────────────

export function useApi<T>(
  fetcher: () => Promise<AxiosResponse<T>>,
  deps: DependencyList,
  options?: UseApiOptions<T>
): UseApiResult<T> {
  const { fallback, cacheKey, demo } = options ?? {};
  // Demo fallback is OFF unless explicitly requested per-hook (`demo`)
  // or explicitly enabled for the deployment (NEXT_PUBLIC_DEMO_MODE=1).
  const demoActive = demo ?? DEMO_MODE_ENABLED;

  // Seed priority: cache hit > explicit demo fallback > null.
  // Evaluated once at mount — the effect handles subsequent dep changes.
  const initialCached = cacheKey ? getCached<T>(cacheKey) : null;
  const seeded =
    initialCached ?? (demoActive ? resolveFallback(fallback) : null);
  const hasSeed = seeded != null;

  const [data, setData] = useState<T | null>(seeded ?? null);
  // Cache hit → no loading indicator; fallback seed → soft refetch indicator.
  const [loading, setLoading] = useState(initialCached ? false : !hasSeed);
  const [isRefetching, setIsRefetching] = useState(
    initialCached ? false : hasSeed
  );
  const [error, setError] = useState<string | null>(null);
  const [isMock, setIsMock] = useState(initialCached ? false : hasSeed);
  const [stale, setStale] = useState(false);
  const dataRef = useRef<T | null>(seeded ?? null);
  const requestKey = cacheKey ?? JSON.stringify(deps);
  const requestKeyRef = useRef(requestKey);
  const hasLoadedOnce = useRef(hasSeed || initialCached != null);
  const [refetchTick, setRefetchTick] = useState(0);
  const fallbackRef = useRef(fallback);
  useEffect(() => {
    fallbackRef.current = fallback;
  }, [fallback]);
  // Tick bookkeeping: a refetchTick CHANGE means an explicit refresh (manual
  // `refetch()` or the refreshMs poller) — such a re-run must BYPASS the
  // session cache and hit the network, otherwise polling would be swallowed
  // by a still-fresh cache entry and never actually update anything.
  const lastTickRef = useRef(0);

  // ── Auto-refresh polling ─────────────────────────────────────
  // Live pages previously required a manual re-navigation to see updated
  // verdicts (the session cache + effect only ran on mount/dep change), so a
  // match's badge lagged behind its real state indefinitely. When
  // `refreshMs` is set, the effect re-runs on a steady interval (via the
  // existing refetchTick mechanism, so all cache/demo semantics are
  // unchanged). 0/undefined = no polling.
  const refreshMs = options?.refreshMs ?? 0;
  useEffect(() => {
    if (!refreshMs || refreshMs <= 0) return;
    const t = window.setInterval(() => setRefetchTick((v) => v + 1), refreshMs);
    return () => window.clearInterval(t);
  }, [refreshMs]);

  const refetch = useCallback(() => setRefetchTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;

    // ── Cache hit ────────────────────────────────────────────
    // When the key changes (e.g. date change) or the component mounts fresh,
    // check the cache before touching the network. An explicit refresh
    // (manual `refetch()` or the refreshMs poller) bypasses the cache —
    // otherwise the poll would keep hitting the still-fresh entry and never
    // reach the network, defeating the whole point of polling.
    const explicitRefresh = refetchTick !== lastTickRef.current;
    lastTickRef.current = refetchTick;
    if (explicitRefresh) clearRawCache();
    if (cacheKey && !explicitRefresh) {
      const hit = getCached<T>(cacheKey);
      if (hit !== null) {
        // A Verify payload whose rows have NOT settled can still change at any
        // moment (a match kicks off, goes in-play, then settles). Serving it
        // from cache and returning early would pin a stale "Pending" on screen
        // until the next hard reload, because the 24h persistent tier would
        // keep answering this branch on every later mount.
        //
        // So: paint the cached rows immediately (page stays fast and history
        // stays visible), then CONTINUE to the fetch so the backend can replace
        // them. `keepVisible` below keeps the table on screen during the
        // background request rather than dropping to a skeleton.
        if (payloadHasVerification(hit) && !payloadIsSettled(hit)) {
          setData(hit);
          dataRef.current = hit;
          requestKeyRef.current = cacheKey ?? JSON.stringify(deps);
          setIsMock(false);
          setLoading(false);
          setIsRefetching(true);
          setError(null);
          hasLoadedOnce.current = true;
          // Deliberately no `return` here — fall through to the network fetch.
        } else {
          setData(hit);
          dataRef.current = hit;
          requestKeyRef.current = cacheKey ?? JSON.stringify(deps);
          setIsMock(false);
          setStale(false);
          setLoading(false);
          setIsRefetching(false);
          setError(null);
          hasLoadedOnce.current = true;
          return () => {
            cancelled = true;
          };
        }
      }
    }

    // ── Cache miss / no key → normal fetch ───────────────────
    const currentRequestKey = cacheKey ?? JSON.stringify(deps);
    const sameRequest = requestKeyRef.current === currentRequestKey;
    if (!sameRequest) {
      requestKeyRef.current = currentRequestKey;
      dataRef.current = null;
      hasLoadedOnce.current = false;
      setData(null);
      setStale(false);
      setIsMock(false);
    }

    // Keep a real payload visible during refresh failures. A transient timeout
    // must not make a previously working fixture feed look offline.
    const keepVisible = sameRequest && hasLoadedOnce.current && dataRef.current !== null;
    setLoading(!keepVisible);
    setIsRefetching(keepVisible);
    setError(null);

    const run = () => {
      if (cancelled) return;

      const applyFailure = (message: string) => {
        const fb = resolveFallback(fallbackRef.current);
        if (demoActive && fb !== undefined) {
          // D. Demo explicitly enabled → DEMO DATA (clearly flagged).
          setData(fb);
          setIsMock(true);
          setError(null);
        } else {
          // Keep the last successful real payload visible during a transient
          // failure. An explicit empty response still replaces it honestly.
          if (dataRef.current !== null) {
            setStale(true);
            setIsMock(false);
          } else {
            dataRef.current = null;
            setData(null);
            setStale(false);
          }
          setError(message);
        }
        setLoading(false);
        setIsRefetching(false);
        hasLoadedOnce.current = true;
      };

      let request: Promise<AxiosResponse<T>>;
      try {
        request = fetcher();
      } catch (err: unknown) {
        const message =
          err instanceof Error ? err.message : "Request failed";
        applyFailure(message);
        return;
      }

      request
        .then((res) => {
          if (cancelled) return;
          const payload = res.data;
          const empty = isEmptyPayload(payload);
          const fb = resolveFallback(fallbackRef.current);
          if (empty && demoActive && fb !== undefined) {
            // D. Demo explicitly enabled → DEMO DATA (clearly flagged).
            setData(fb);
            dataRef.current = fb;
            setIsMock(true);
            setStale(false);
            setError(null);
          } else if (empty && dataRef.current !== null) {
            // A refresh can briefly observe an empty cache while the pipeline
            // is being written. Keep the last real snapshot visible instead of
            // flashing the whole dashboard offline.
            setStale(true);
            setIsMock(false);
            setError(null);
          } else {
            // A/B. Real non-empty AND real empty are both served exactly
            // as the backend returned them — a legitimate empty engine
            // result (status=ok, row_count=0) must never become fake picks.
            if (cacheKey) setCached(cacheKey, payload);
            setData(payload);
            dataRef.current = payload;
            setIsMock(false);
            setStale(false);
            setError(null);
          }
          setLoading(false);
          setIsRefetching(false);
          hasLoadedOnce.current = true;
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          const isTimeout = isAxiosError(err)
            && (err.code === "ECONNABORTED"
              || /timeout/i.test(err.message || ""));
          if (isTimeout && attempts < 1) {
            attempts += 1;
            console.warn("[useApi] request timed out — retrying once");
            t2 = window.setTimeout(run, 1500);
            return;
          }
          const message = isAxiosError(err)
            ? extractErrorDetail(err) ?? err.message
            : err instanceof Error
              ? err.message
              : "Request failed";
          applyFailure(message);
        });
    };

    // Single automatic retry on timeout: a transient backend stall (e.g. a
    // burst landing while an upstream cooldown clears) used to surface as a
    // hard error/blank page. One quiet retry 1.5s later self-heals it without
    // changing any endpoint's real timeout budget (10s normal / 45s heavy) —
    // a genuinely down backend still surfaces its error after the retry.
    let attempts = 0;
    let t2: number | undefined;
    run();

    return () => {
      cancelled = true;
      if (t2 !== undefined) window.clearTimeout(t2);
    };
    // cacheKey is a derived string that changes when deps change, so it is
    // intentionally included in the spread without being listed separately.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, refetchTick, cacheKey]);

  return { data, loading, error, isRefetching, isMock, stale, refetch };
}
