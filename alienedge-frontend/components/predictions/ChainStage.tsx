"use client";

import type { AxiosResponse } from "axios";
import type { DependencyList } from "react";
import { useApi } from "@/lib/use-api";
import { ChainBranch } from "@/components/predictions/ChainBranch";
import { type PredictionColumn } from "@/components/predictions/PredictionTable";

interface ChainStageProps<T> {
  title: string;
  description?: string;
  fetcher: () => Promise<AxiosResponse<T[]>>;
  deps: DependencyList;
  columns: PredictionColumn<T>[];
  rowKey: (row: T, index: number) => string;
  emptyMessage?: string;
  defaultOpen?: boolean;
  /**
   * Typed demo rows. Used ONLY when demo is explicitly enabled — either
   * this `demo` prop or the global NEXT_PUBLIC_DEMO_MODE=1 switch. The API
   * call still always runs; a real empty response stays a real empty state
   * and a failure stays an error — demo never replaces them silently.
   */
  fallbackData?: T[];
  /**
   * Explicit opt-in for demo fallback rendering for this stage.
   * Defaults to the global NEXT_PUBLIC_DEMO_MODE switch.
   */
  demo?: boolean;
}

/**
 * One engine stage, end to end: fetch -> loading/error/empty -> table.
 * Covers every endpoint that responds with a plain array. Endpoints with
 * composite responses (e.g. `{ gg, o15 }`, `{ u25, u35 }`) should call
 * `useApi` directly on the page and render one <ChainBranch> per branch.
 *
 * Demo data (fallbackData) renders only when it is actually being shown,
 * and is always tagged via the "· Demo" description suffix.
 */
export function ChainStage<T>({
  title,
  description,
  fetcher,
  deps,
  columns,
  rowKey,
  emptyMessage,
  defaultOpen,
  fallbackData,
  demo,
}: ChainStageProps<T>) {
  // Cache key = stable stage title + serialised deps (includes date).
  // Means: navigate away → come back → instant paint from cache (no spinner).
  const cacheKey = `${title}:${JSON.stringify(deps)}`;

  const { data, loading, error, isRefetching, isMock } = useApi(fetcher, deps, {
    fallback: fallbackData,
    cacheKey,
    demo,
  });

  const liveRows = Array.isArray(data) ? data : [];
  const hasLiveRows = liveRows.length > 0;
  const hasFallback = Boolean(fallbackData && fallbackData.length > 0);

  // Settled + empty → REAL EMPTY; settled + error → error state; demo rows
  // only when useApi actually flagged them (isMock). While loading, show
  // whatever useApi seeded (real cache hit or explicit demo seed) — or the
  // skeleton — so tables never flash fake rows in strict mode.
  const displayData: T[] | null = (() => {
    if (loading) return hasLiveRows ? liveRows : Array.isArray(data) ? data : null;
    if (hasLiveRows) return liveRows;
    if (isMock && hasFallback) return fallbackData!;
    return data;
  })();

  const displayHasRows = Array.isArray(displayData) && displayData.length > 0;
  const displayError = displayHasRows ? null : error;
  // isMock is TRUE only while actual mock data is displayed.
  const displayIsMock = isMock && displayHasRows;

  const demoDescription =
    displayIsMock && description
      ? `${description} · Demo`
      : displayIsMock
        ? "Demo"
        : description;

  return (
    <ChainBranch
      title={title}
      description={demoDescription}
      data={displayData}
      loading={loading}
      error={displayError}
      columns={columns}
      rowKey={rowKey}
      emptyMessage={emptyMessage}
      defaultOpen={defaultOpen}
      isRefetching={isRefetching}
    />
  );
}
