"use client";

import { useCallback, useEffect, useState } from "react";
import { dnaV2Api, type DnaV2Response } from "@/lib/api";
import { useApi, type UseApiResult } from "@/lib/use-api";
import { useSelectedDate } from "@/lib/date-context";
import { MOCK_DNA_V2 } from "@/lib/mock-dna-v2";

/**
 * Shared DNA v2 data source for every market page + the DNA Analysis page.
 *
 * All pages call this exact same hook for the SAME DATE so they share one
 * `useApi` cache entry (`dna-v2:{date}`) — whichever page loads first
 * populates the cache, and every other page (including the full-screen DNA
 * Analysis page opened from a fixture-list click) reads it back instantly
 * with zero extra network wait.
 *
 * The hook respects the globally selected date: a historical page fetches
 * `/api/dna/v2/{date}` and can NEVER silently show another date's DNA. The
 * default "today" view instead uses `/api/dna/v2/latest` (the newest
 * available pipeline snapshot) when the current calendar date has not been
 * generated yet. Pass `dateOverride` (the DNA Analysis page passes its
 * `?date=` URL param) to override the global selection.
 *
 * Uses the disk-only `/api/dna/v2/{date}` / `/api/dna/v2/latest` endpoints
 * (no engine recompute) so this is safe to call from every list page without
 * hammering the DNA v2 engine or the SportMonks API on every render.
 *
 * Falls back to MOCK_DNA_V2 ONLY when demo mode is explicitly enabled
 * (NEXT_PUBLIC_DEMO_MODE=1 or the `demo` option) — the DNA badge + full
 * DNA Analysis page are demoable, but a real empty result now stays a
 * real empty state instead of auto-swapping to fake data.
 */
export function useDnaV2(dateOverride?: string): UseApiResult<DnaV2Response> {
  const { date: selectedDate } = useSelectedDate();
  const date = dateOverride || selectedDate;
  // Date-first with latest-fallback: ALWAYS request the explicitly selected
  // date's snapshot first so a next-day pipeline landing mid-evening can
  // never replace today's DNA view while the user is still on today's
  // fixtures. The `dna-v2:latest` endpoint is only consulted when the dated
  // file genuinely does not exist (pipeline hasn't run for that date yet).
  // Implemented as two stable fetchers selected by whether the dated fetch
  // already resolved — no polling loop, no extra renders.
  const [useLatestFallback, setUseLatestFallback] = useState(false);
  useEffect(() => {
    setUseLatestFallback(false);
  }, [date]);
  const fetcher = useCallback(() => {
    if (useLatestFallback) return dnaV2Api.getLatest();
    return dnaV2Api.get(date).then((res) => {
      const d = res.data as DnaV2Response | null | undefined;
      const empty =
        !d ||
        (Object.keys(d.dna_profiles ?? {}).length === 0 &&
          (d.fixture_clashes ?? []).length === 0 &&
          Object.keys(d.market_factors ?? {}).length === 0);
      if (empty) {
        // Dated snapshot genuinely absent — fall back to newest available.
        setUseLatestFallback(true);
        return dnaV2Api.getLatest();
      }
      return res;
    });
  }, [date, useLatestFallback]);
  return useApi(fetcher, [date, useLatestFallback], {
    cacheKey: useLatestFallback ? `dna-v2:${date}:via-latest` : `dna-v2:${date}`,
    fallback: MOCK_DNA_V2,
  });
}
