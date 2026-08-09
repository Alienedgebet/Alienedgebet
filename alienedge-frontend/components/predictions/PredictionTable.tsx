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
  header: string;
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
                  {col.render(row, i)}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
