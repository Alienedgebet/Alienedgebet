"use client";

import { useMemo } from "react";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { ProbCell } from "@/components/predictions/ProbCell";
import { cn } from "@/lib/utils";

interface DynamicTableProps {
  rows: Record<string, unknown>[];
  /** Keys to surface first, in order, when present in the data — everything else fills remaining slots alphabetically. */
  priorityKeys?: string[];
  maxColumns?: number;
  emptyMessage?: string;
}

function humanizeKey(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .trim();
}

function isProbLikeKey(key: string): boolean {
  const k = key.toLowerCase();
  return (
    k.endsWith("prob") ||
    k.endsWith("pct") ||
    k.endsWith("%") ||
    k.includes("prob_")
  );
}

function renderCell(key: string, value: unknown) {
  if (value == null) return <span className="text-text-dim">—</span>;

  if (typeof value === "boolean") {
    return (
      <span className={value ? "text-accent-green" : "text-text-dim"}>
        {value ? "Yes" : "No"}
      </span>
    );
  }

  if (
    isProbLikeKey(key) &&
    (typeof value === "number" || typeof value === "string")
  ) {
    const num =
      typeof value === "number"
        ? value
        : parseFloat(String(value).replace("%", ""));
    if (!Number.isNaN(num)) {
      const scaled = Math.abs(num) <= 1 ? num * 100 : num;
      return <ProbCell value={scaled} showBar={false} />;
    }
  }

  if (typeof value === "number") {
    return (
      <span className="font-mono">
        {Number.isInteger(value) ? value : value.toFixed(2)}
      </span>
    );
  }

  return <span className="truncate">{String(value)}</span>;
}

/**
 * Infers columns from row data. Static DOM — no per-row opacity stagger
 * (that was a major source of weekly/filter click lag).
 */
export function DynamicTable({
  rows,
  priorityKeys = [],
  maxColumns = Number.POSITIVE_INFINITY,
  emptyMessage = "No rows matched this filter.",
}: DynamicTableProps) {
  const columns = useMemo(() => {
    if (!rows.length) return [];
    const allKeys = new Set<string>();
    rows.forEach((r) => Object.keys(r).forEach((k) => allKeys.add(k)));

    const prioritized = priorityKeys.filter((k) => allKeys.has(k));
    const rest = [...allKeys].filter((k) => !prioritized.includes(k)).sort();

    const ordered = [...prioritized, ...rest];
    return Number.isFinite(maxColumns)
      ? ordered.slice(0, maxColumns)
      : ordered;
  }, [rows, priorityKeys, maxColumns]);

  if (rows.length === 0) {
    return (
      <div className="flex items-center justify-center py-10 text-center text-xs text-text-dim">
        {emptyMessage}
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-md">
      <Table>
        <TableHeader className="sticky top-0 z-10 bg-bg-card/80 backdrop-blur-md">
          <TableRow className="border-border hover:bg-transparent">
            {columns.map((col) => (
              <TableHead
                key={col}
                className="whitespace-nowrap font-mono text-2xs uppercase tracking-wider text-text-muted"
              >
                {humanizeKey(col)}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, i) => (
            <TableRow
              key={i}
              className={cn(
                "pred-row border-border hover:bg-accent-indigo/[0.06]"
              )}
            >
              {columns.map((col) => (
                <TableCell
                  key={col}
                  className="max-w-[220px] text-xs text-text-secondary"
                >
                  {renderCell(col, row[col])}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
