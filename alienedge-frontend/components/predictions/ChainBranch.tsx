"use client";

import { ChainSection } from "@/components/predictions/ChainSection";
import { PredictionTable } from "@/components/predictions/PredictionTable";
import { TableSkeleton } from "@/components/predictions/TableSkeleton";
import { ErrorState } from "@/components/predictions/ErrorState";
import { type PredictionColumn } from "@/components/predictions/PredictionTable";

interface ChainBranchProps<T> {
  title: string;
  description?: string;
  data: T[] | null;
  loading: boolean;
  error: string | null;
  columns: PredictionColumn<T>[];
  rowKey: (row: T, index: number) => string;
  emptyMessage?: string;
  defaultOpen?: boolean;
  /** Kept for call-site compatibility — no longer dims content. */
  isRefetching?: boolean;
}

/**
 * One rendered engine branch: fetch state (loading/error/empty) -> table.
 * `ChainStage` calls this after running its own `useApi`; pages with
 * composite responses (`{ gg, o15 }`, `{ u25, u35 }`) call this directly,
 * once per branch, off a single shared `useApi` result.
 *
 * Priority (matches dashboard withFallback): usable rows always win over
 * a Network Error / API failure message. Demo/mock data must never be
 * hidden behind <ErrorState>.
 */
export function ChainBranch<T>({
  title,
  description,
  data,
  loading,
  error,
  columns,
  rowKey,
  emptyMessage,
  defaultOpen,
}: ChainBranchProps<T>) {
  const rows = data ?? [];
  const hasRows = rows.length > 0;
  const count = hasRows ? rows.length : undefined;

  return (
    <ChainSection title={title} description={description} count={count} defaultOpen={defaultOpen}>
      <div>
        {loading && !hasRows ? (
          <TableSkeleton />
        ) : hasRows ? (
          <PredictionTable
            columns={columns}
            data={rows}
            rowKey={rowKey}
            emptyMessage={emptyMessage}
          />
        ) : error ? (
          <ErrorState message={error} />
        ) : (
          <PredictionTable
            columns={columns}
            data={rows}
            rowKey={rowKey}
            emptyMessage={emptyMessage}
          />
        )}
      </div>
    </ChainSection>
  );
}
