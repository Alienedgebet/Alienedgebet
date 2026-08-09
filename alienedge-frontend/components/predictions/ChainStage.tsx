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
   * Typed demo rows when the live fetch fails or returns [].
   * API call still always runs — same pattern as dashboard MOCK_PICKS.
   */
  fallbackData?: T[];
}

/**
 * One engine stage, end to end: fetch -> loading/error/empty -> table.
 * Covers every endpoint that responds with a plain array. Endpoints with
 * composite responses (e.g. `{ gg, o15 }`, `{ u25, u35 }`) should call
 * `useApi` directly on the page and render one <ChainBranch> per branch.
 *
 * Render-time fallback mirrors dashboard `withFallback`: even if useApi
 * surfaces a Network Error, demo rows still paint when provided.
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
}: ChainStageProps<T>) {
  // Cache key = stable stage title + serialised deps (includes date).
  // Means: navigate away → come back → instant paint from cache (no spinner).
  const cacheKey = `${title}:${JSON.stringify(deps)}`;

  const { data, loading, error, isRefetching, isMock } = useApi(fetcher, deps, {
    fallback: fallbackData,
    cacheKey,
  });

  const liveRows = Array.isArray(data) ? data : [];
  const hasLiveRows = liveRows.length > 0;
  const hasFallback = Boolean(fallbackData && fallbackData.length > 0);

  // Settled + empty/error → demo rows (dashboard parity). While loading,
  // keep whatever useApi already seeded so tables don't flash empty.
  const displayData: T[] | null = (() => {
    if (loading) return hasLiveRows ? liveRows : hasFallback ? fallbackData! : data;
    if (hasLiveRows) return liveRows;
    if (hasFallback) return fallbackData!;
    return data;
  })();

  const displayHasRows = Array.isArray(displayData) && displayData.length > 0;
  const displayError = displayHasRows ? null : error;
  const displayIsMock =
    isMock ||
    (displayHasRows && hasFallback && (!hasLiveRows || Boolean(error)));

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
