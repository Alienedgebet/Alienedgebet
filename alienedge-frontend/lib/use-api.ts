"use client";

import { useCallback, useEffect, useRef, useState, type DependencyList } from "react";
import { isAxiosError, type AxiosError, type AxiosResponse } from "axios";

// ============================================================
// GENERIC DATA-FETCHING HOOK
// Wraps any lib/api.ts call with loading/error/data state so
// market pages don't hand-roll useEffect boilerplate per stage.
// Optional `fallback` restores demo rows when the backend is down
// (same contract as dashboard withFallback / MOCK_PICKS).
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

interface CacheEntry<T> {
  data: T;
  ts: number;
}

const apiCache = new Map<string, CacheEntry<unknown>>();

function getCached<T>(key: string): T | null {
  const entry = apiCache.get(key) as CacheEntry<T> | undefined;
  if (!entry) return null;
  if (Date.now() - entry.ts > CACHE_TTL_MS) {
    apiCache.delete(key);
    return null;
  }
  return entry.data;
}

function setCached<T>(key: string, data: T): void {
  apiCache.set(key, { data: data as unknown, ts: Date.now() });
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
   * Typed demo payload used when the request fails or returns empty.
   * Live fetch still always runs — fallback never replaces the call.
   */
  fallback?: T | (() => T);
  /**
   * When provided, successful live responses are stored under this key
   * and returned synchronously on the next mount/dep-change if still
   * fresh (< 3 min). Derive keys from endpoint name + serialised deps,
   * e.g. `"win-apex:2026-08-07"`.
   */
  cacheKey?: string;
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
  /** Re-runs the fetcher against the current deps without waiting for them to change. */
  refetch: () => void;
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
  const { fallback, cacheKey } = options ?? {};

  // Seed priority: cache hit > fallback mock > null.
  // Evaluated once at mount — the effect handles subsequent dep changes.
  const initialCached = cacheKey ? getCached<T>(cacheKey) : null;
  const seeded = initialCached ?? resolveFallback(fallback);
  const hasSeed = seeded != null;

  const [data, setData] = useState<T | null>(seeded ?? null);
  // Cache hit → no loading indicator; fallback seed → soft refetch indicator.
  const [loading, setLoading] = useState(initialCached ? false : !hasSeed);
  const [isRefetching, setIsRefetching] = useState(
    initialCached ? false : hasSeed
  );
  const [error, setError] = useState<string | null>(null);
  const [isMock, setIsMock] = useState(initialCached ? false : hasSeed);
  const hasLoadedOnce = useRef(hasSeed || initialCached != null);
  const [refetchTick, setRefetchTick] = useState(0);
  const fallbackRef = useRef(fallback);
  fallbackRef.current = fallback;

  const refetch = useCallback(() => setRefetchTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;

    // ── Cache hit ────────────────────────────────────────────
    // When the key changes (e.g. date change) or the component mounts fresh,
    // check the cache before touching the network.
    if (cacheKey) {
      const hit = getCached<T>(cacheKey);
      if (hit !== null) {
        setData(hit);
        setIsMock(false);
        setLoading(false);
        setIsRefetching(false);
        setError(null);
        hasLoadedOnce.current = true;
        return () => {
          cancelled = true;
        };
      }
    }

    // ── Cache miss / no key → normal fetch ───────────────────
    const keepVisible =
      hasLoadedOnce.current ||
      resolveFallback(fallbackRef.current) !== undefined;
    setLoading(!keepVisible);
    setIsRefetching(keepVisible);
    setError(null);

    const run = () => {
      if (cancelled) return;

      let request: Promise<AxiosResponse<T>>;
      try {
        request = fetcher();
      } catch (err: unknown) {
        const message =
          err instanceof Error ? err.message : "Request failed";
        const fb = resolveFallback(fallbackRef.current);
        if (fb !== undefined) {
          setData(fb);
          setIsMock(true);
          setError(null);
        } else {
          setData(null);
          setIsMock(false);
          setError(message);
        }
        setLoading(false);
        setIsRefetching(false);
        hasLoadedOnce.current = true;
        return;
      }

      request
        .then((res) => {
          if (cancelled) return;
          const payload = res.data;
          const fb = resolveFallback(fallbackRef.current);
          if (isEmptyPayload(payload) && fb !== undefined) {
            setData(fb);
            setIsMock(true);
            setError(null);
          } else {
            // Store live response in cache for future navigations.
            if (cacheKey) setCached(cacheKey, payload);
            setData(payload);
            setIsMock(false);
            setError(null);
          }
          setLoading(false);
          setIsRefetching(false);
          hasLoadedOnce.current = true;
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          const message = isAxiosError(err)
            ? extractErrorDetail(err) ?? err.message
            : err instanceof Error
              ? err.message
              : "Request failed";
          const fb = resolveFallback(fallbackRef.current);
          if (fb !== undefined) {
            setData(fb);
            setIsMock(true);
            setError(null);
          } else {
            setData(null);
            setIsMock(false);
            setError(message);
          }
          setLoading(false);
          setIsRefetching(false);
          hasLoadedOnce.current = true;
        });
    };

    // Defer network work one tick so first paint wins on slow disks.
    const t = window.setTimeout(run, 0);

    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
    // cacheKey is a derived string that changes when deps change, so it is
    // intentionally included in the spread without being listed separately.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, refetchTick, cacheKey]);

  return { data, loading, error, isRefetching, isMock, refetch };
}
