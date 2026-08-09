"use client";

import { dnaV2Api, type DnaV2Response } from "@/lib/api";
import { useApi, type UseApiResult } from "@/lib/use-api";
import { MOCK_DNA_V2 } from "@/lib/mock-dna-v2";

/**
 * Shared DNA v2 data source for every market page + the DNA Analysis page.
 *
 * All pages call this exact same hook so they share one `useApi` cache
 * entry (`dna-v2:latest`) — whichever page loads first populates the
 * cache, and every other page (including the full-screen DNA Analysis
 * page opened from a fixture-list click) reads it back instantly with
 * zero extra network wait.
 *
 * Uses the disk-only `/api/dna/v2/latest` endpoint (no engine recompute)
 * so this is safe to call from every list page without hammering the
 * DNA v2 engine or the SportMonks API on every render.
 *
 * Falls back to MOCK_DNA_V2 (same contract as every other market's
 * MOCK_* fallback) when the backend is unreachable — e.g. this frontend
 * deployed on Vercel with no public backend configured yet — so the DNA
 * badge + full DNA Analysis page are visibly demoable instead of just
 * showing "–" everywhere.
 */
export function useDnaV2(): UseApiResult<DnaV2Response> {
  return useApi(() => dnaV2Api.getLatest(), [], {
    cacheKey: "dna-v2:latest",
    fallback: MOCK_DNA_V2,
  });
}
