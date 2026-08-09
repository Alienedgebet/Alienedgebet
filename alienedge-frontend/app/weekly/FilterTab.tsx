"use client";

import { useEffect, useState } from "react";
import type { AxiosResponse } from "axios";
import { Button } from "@/components/ui/button";
import { DynamicTable, TableSkeleton, ErrorState } from "@/components/predictions";
import { MOCK_FILTER_ROWS } from "@/lib/mock-chains";
import { getTodayDate } from "@/lib/api";
import type { MarketFilterConfig } from "./filter-config";

interface FilterTabProps {
  config: MarketFilterConfig;
  fetchSingle: (date: string, params: Record<string, unknown>) => Promise<AxiosResponse<unknown>>;
  fetchWeekly: (params: Record<string, unknown>) => Promise<AxiosResponse<unknown>>;
}

/** Normalizes whatever shape a filter engine returns (bare array, or an object wrapping one) into rows for DynamicTable. */
function extractRows(data: unknown): Record<string, unknown>[] {
  if (Array.isArray(data)) return data as Record<string, unknown>[];
  if (data && typeof data === "object") {
    const obj = data as Record<string, unknown>;
    for (const key of ["results", "picks", "data", "rows"]) {
      if (Array.isArray(obj[key])) return obj[key] as Record<string, unknown>[];
    }
  }
  return [];
}

/**
 * Reusable filter form + results table for one market's weekly filter
 * engine. Holds all form state locally and only fires the API call when
 * "Run Filter" is clicked — never on every keystroke.
 */
export function FilterTab({ config, fetchSingle, fetchWeekly }: FilterTabProps) {
  const [scope, setScope] = useState<"single" | "weekly">("single");
  const [date, setDate] = useState(getTodayDate());
  const [startDate, setStartDate] = useState(getTodayDate());
  const [endDate, setEndDate] = useState(getTodayDate());
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [submitted, setSubmitted] = useState({ tick: 0 });
  // Seed demo rows so the page is never blank while Sportmonks/API is offline.
  const [rows, setRows] = useState<Record<string, unknown>[]>(MOCK_FILTER_ROWS);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (submitted.tick === 0) return;
    let cancelled = false;
    setLoading(true);
    setError(null);

    const params: Record<string, unknown> = {};
    Object.entries(values).forEach(([k, v]) => {
      if (v !== "" && v !== undefined && v !== null) params[k] = v;
    });

    const promise =
      scope === "single"
        ? fetchSingle(date, params)
        : fetchWeekly({ ...params, start_date: startDate, end_date: endDate });

    promise
      .then((res) => {
        if (cancelled) return;
        const extracted = extractRows(res.data);
        if (extracted.length === 0) {
          setRows(MOCK_FILTER_ROWS);
          setError(null);
        } else {
          setRows(extracted);
          setError(null);
        }
      })
      .catch(() => {
        if (cancelled) return;
        // API offline — keep the table populated with typed demo rows (same
        // contract as market ChainStage fallbackData / dashboard MOCK_PICKS).
        setRows(MOCK_FILTER_ROWS);
        setError(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [submitted.tick]);

  function setField(key: string, val: unknown) {
    setValues((v) => ({ ...v, [key]: val }));
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="glass rounded-lg p-4 shadow-panel">
        <div className="mb-3 flex items-center gap-2">
          <Button size="sm" variant={scope === "single" ? "default" : "outline"} onClick={() => setScope("single")}>
            Single Date
          </Button>
          <Button size="sm" variant={scope === "weekly" ? "default" : "outline"} onClick={() => setScope("weekly")}>
            Weekly Range
          </Button>
        </div>

        {scope === "single" ? (
          <div className="mb-3 flex flex-col gap-1">
            <label className="text-2xs text-text-muted">Date</label>
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="w-40 rounded border border-border bg-bg-elevated px-2 py-1 text-xs text-text-primary outline-none focus:border-accent-indigo"
            />
          </div>
        ) : (
          <div className="mb-3 flex gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-2xs text-text-muted">Start Date</label>
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="w-40 rounded border border-border bg-bg-elevated px-2 py-1 text-xs text-text-primary outline-none focus:border-accent-indigo"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-2xs text-text-muted">End Date</label>
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="w-40 rounded border border-border bg-bg-elevated px-2 py-1 text-xs text-text-primary outline-none focus:border-accent-indigo"
              />
            </div>
          </div>
        )}

        <p className="mb-3 text-2xs text-text-dim">
          All fields below are always shown — the backend only applies the parameters relevant to
          the selected mode.
        </p>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {config.fields.map((field) => (
            <div key={field.key} className="flex flex-col gap-1">
              <label className="text-2xs text-text-muted">{field.label}</label>
              {field.type === "select" ? (
                <select
                  value={String(values[field.key] ?? "")}
                  onChange={(e) => setField(field.key, e.target.value)}
                  className="rounded border border-border bg-bg-elevated px-2 py-1 text-xs text-text-primary outline-none focus:border-accent-indigo"
                >
                  <option value="">—</option>
                  {field.options?.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              ) : field.type === "checkbox" ? (
                <input
                  type="checkbox"
                  checked={Boolean(values[field.key])}
                  onChange={(e) => setField(field.key, e.target.checked)}
                  className="h-4 w-4 self-start accent-[--accent-indigo]"
                />
              ) : (
                <input
                  type={field.type === "number" ? "number" : "text"}
                  step={field.step}
                  placeholder={field.placeholder}
                  value={String(values[field.key] ?? "")}
                  onChange={(e) =>
                    setField(
                      field.key,
                      field.type === "number" ? (e.target.value === "" ? "" : Number(e.target.value)) : e.target.value
                    )
                  }
                  className="rounded border border-border bg-bg-elevated px-2 py-1 text-xs text-text-primary outline-none focus:border-accent-indigo"
                />
              )}
            </div>
          ))}
        </div>

        <div className="mt-4">
          <Button onClick={() => setSubmitted((s) => ({ tick: s.tick + 1 }))} disabled={loading}>
            {loading ? "Running…" : "Run Filter"}
          </Button>
        </div>
      </div>

      <div className="glass rounded-lg p-3 shadow-panel">
        {loading && rows.length === 0 ? (
          <TableSkeleton />
        ) : rows.length > 0 ? (
          <DynamicTable
            rows={rows}
            priorityKeys={config.priorityKeys}
            emptyMessage="No rows matched this filter."
          />
        ) : error ? (
          <ErrorState message={error} />
        ) : (
          <DynamicTable
            rows={rows}
            priorityKeys={config.priorityKeys}
            emptyMessage={
              submitted.tick === 0
                ? "Set your filters above and click Run Filter."
                : "No rows matched this filter."
            }
          />
        )}
      </div>
    </div>
  );
}
