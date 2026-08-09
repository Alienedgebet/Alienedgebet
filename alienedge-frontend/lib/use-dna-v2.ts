"use client";

import { dnaV2Api, type DnaV2Response } from "@/lib/api";
import { useApi, type UseApiResult } from "@/lib/use-api";

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
 */
export function useDnaV2(): UseApiResult<DnaV2Response> {
  return useApi(() => dnaV2Api.getLatest(), [], {
    cacheKey: "dna-v2:latest",
    fallback: {
      dna_profiles: {},
      fixture_clashes: [],
      market_factors: {},
    },
  });
}
