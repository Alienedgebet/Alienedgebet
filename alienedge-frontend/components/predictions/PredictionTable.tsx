"use client";

import type { ReactNode } from "react";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

export interface PredictionColumn<T> {
  key: string;
  header: string | ReactNode;
  align?: "left" | "right" | "center";
  className?: string;
  render: (row: T, index: number) => ReactNode;
}

interface PredictionTableProps<T> {
  columns: PredictionColumn<T>[];
  data: T[];
  rowKey: (row: T, index: number) => string;
  emptyMessage?: string;
}

/**
 * Renders one cell, isolating any throw from its renderer.
 *
 * WHY THIS EXISTS
 * ---------------
 * A column `render` is just a function typed `(row, index) => ReactNode`.
 * TypeScript checks that signature but says NOTHING about what the value
 * inside `row` actually is at runtime, so `render: (r) => r.Odds.toFixed(2)`
 * type-checks cleanly and then throws at runtime when `Odds` is the string
 * '1.41' (CSV-recovered) or `null` (never measured).
 *
 * When that throw escaped, React unmounted the entire subtree and
 * app/error.tsx replaced the WHOLE market page with "Something went wrong —
 * Try again". One malformed cell in one row of one stage took down every
 * other stage on the page. That is what happened to the Win page
 * (`Market_Power_Scores.Win_Dominance.toFixed`) and the Over 2.5 page
 * (`Odds.toFixed is not a function`) on 2026-10-04.
 *
 * A failed cell now degrades to a single "—" cell and leaves the rest of the
 * table — and every other stage on the page — completely intact. That turns
 * a total outage into a visible gap in one cell, and it is deliberately
 * silent about the cause in the UI so a render exception never becomes a
 * whole-page failure mode again.
 */
function SafeCell({
  render,
  row,
  index,
}: {
  render: (row: unknown, index: number) => ReactNode;
  row: unknown;
  index: number;
}) {
  try {
    return <>{render(row, index)}</>;
  } catch {
    // Swallowed deliberately: the cell shows the same "not available"
    // placeholder as an absent measurement. The underlying data defect is
    // still visible as a missing value and is diagnosable server-side.
    return <span className="text-text-dim">—</span>;
  }
}

/**
 * Static table — no per-row framer-motion. Market pages can render hundreds
 * of cells across many stages; motion.tr + whileHover previously allocated
 * one animation controller per row and tanked scroll/compile performance.
 */
export function PredictionTable<T>({
  columns,
  data,
  rowKey,
  emptyMessage = "No picks available for this date.",
}: PredictionTableProps<T>) {
  if (data.length === 0) {
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
                key={col.key}
                className={cn(
                  "font-mono text-2xs uppercase tracking-wider text-text-muted",
                  col.align === "right" && "text-right",
                  col.align === "center" && "text-center",
                  col.className
                )}
              >
                {col.header}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.map((row, i) => (
            <TableRow key={rowKey(row, i)} className="pred-row border-border">
              {columns.map((col) => (
                <TableCell
                  key={col.key}
                  className={cn(
                    "text-xs text-text-secondary",
                    col.align === "right" && "text-right",
                    col.align === "center" && "text-center",
                    col.className
                  )}
                >
                  <SafeCell
                    render={col.render as (row: unknown, index: number) => ReactNode}
                    row={row}
                    index={i}
                  />
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
