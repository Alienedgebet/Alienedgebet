"use client";

import { dnaV2Api, type DnaV2Response } from "@/lib/api";
import { useApi, type UseApiResult } from "@/lib/use-api";
import { useSelectedDate } from "@/lib/date-context";
import { getTodayDate } from "@/lib/date-utils";
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
  // Default/today: the pipeline may not have generated a snapshot for the
  // current calendar date yet, so fall back to the newest AVAILABLE snapshot
  // via the existing /api/dna/v2/latest endpoint. A deliberately selected
  // historical date is always fetched exactly (honest empty if none exists).
  const isToday = date === getTodayDate();
  const fetcher = isToday ? () => dnaV2Api.getLatest() : () => dnaV2Api.get(date);
  return useApi(fetcher, [isToday, date], {
    cacheKey: isToday ? "dna-v2:latest" : `dna-v2:${date}`,
    fallback: MOCK_DNA_V2,
  });
}
