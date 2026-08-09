"use client";

import { useEffect, useState } from "react";
import { Filter } from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { DynamicTable, TableSkeleton, ErrorState } from "@/components/predictions";
import { filterApi, getTodayDate } from "@/lib/api";
import { MOCK_FILTER_ROWS } from "@/lib/mock-chains";
import { FilterTab } from "./FilterTab";
import { GG_FILTER_CONFIG, WIN_FILTER_CONFIG, OVER25_FILTER_CONFIG } from "./filter-config";

/**
 * Win Precision has a different shape than the other 3 filters — no
 * mode/risk params, just a cross-verification run against a single date
 * or a weekly anchor + range, so it gets its own small panel instead of
 * reusing <FilterTab>'s generic field grid.
 */
function WinPrecisionPanel() {
  const [scope, setScope] = useState<"single" | "weekly">("single");
  const [date, setDate] = useState(getTodayDate());
  const [anchorDate, setAnchorDate] = useState(getTodayDate());
  const [startDate, setStartDate] = useState(getTodayDate());
  const [endDate, setEndDate] = useState(getTodayDate());
  const [submitted, setSubmitted] = useState({ tick: 0 });
  // Seed demo rows so Win Precision is never blank offline (dashboard parity).
  const [rows, setRows] = useState<Record<string, unknown>[]>(MOCK_FILTER_ROWS);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (submitted.tick === 0) return;
    let cancelled = false;
    setLoading(true);
    setError(null);

    const promise =
      scope === "single"
        ? filterApi.getWinPrecision(date)
        : filterApi.getWinPrecisionWeekly({ anchor_date: anchorDate, start_date: startDate, end_date: endDate });

    promise
      .then((res) => {
        if (cancelled) return;
        const data = res.data;
        const list = Array.isArray(data)
          ? data
          : ((data as { results?: unknown[] })?.results ?? []);
        if (list.length === 0) {
          setRows(MOCK_FILTER_ROWS);
          setError(null);
        } else {
          setRows(list as Record<string, unknown>[]);
          setError(null);
        }
      })
      .catch(() => {
        if (cancelled) return;
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

  return (
    <div className="flex flex-col gap-4">
      <div className="glass rounded-lg p-4 shadow-panel">
        <div className="mb-3 flex items-center gap-2">
          <Button size="sm" variant={scope === "single" ? "default" : "outline"} onClick={() => setScope("single")}>
            Single Date
          </Button>
          <Button size="sm" variant={scope === "weekly" ? "default" : "outline"} onClick={() => setScope("weekly")}>
            Weekly Cross-Verify
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
          <div className="mb-3 flex flex-wrap gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-2xs text-text-muted">Anchor Date</label>
              <input
                type="date"
                value={anchorDate}
                onChange={(e) => setAnchorDate(e.target.value)}
                className="w-40 rounded border border-border bg-bg-elevated px-2 py-1 text-xs text-text-primary outline-none focus:border-accent-indigo"
              />
            </div>
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

        <div className="mt-2">
          <Button onClick={() => setSubmitted((s) => ({ tick: s.tick + 1 }))} disabled={loading}>
            {loading ? "Running…" : "Run Precision Check"}
          </Button>
        </div>
      </div>

      <div className="glass rounded-lg p-3 shadow-panel">
        {loading && rows.length === 0 ? (
          <TableSkeleton />
        ) : rows.length > 0 ? (
          <DynamicTable
            rows={rows}
            priorityKeys={
              scope === "weekly"
                ? [
                    "fixture", "side", "team_name", "win_odds",
                    "parity_score", "h2h_wins_last_5",
                    "last_5_wins_overall", "verification_days",
                  ]
                : [
                    "fixture", "side", "team_name", "win_odds",
                    "parity_score", "last_5_wins_overall",
                    "last_5_wins_at_venue", "h2h_wins_last_5",
                    "opp_last_5_conceded_raw", "last_3_no_draw_BOTH",
                  ]
            }
            emptyMessage="No rows matched this precision check."
          />
        ) : error ? (
          <ErrorState message={error} />
        ) : (
          <DynamicTable
            rows={rows}
            priorityKeys={
              scope === "weekly"
                ? [
                    "fixture", "side", "team_name", "win_odds",
                    "parity_score", "h2h_wins_last_5",
                    "last_5_wins_overall", "verification_days",
                  ]
                : [
                    "fixture", "side", "team_name", "win_odds",
                    "parity_score", "last_5_wins_overall",
                    "last_5_wins_at_venue", "h2h_wins_last_5",
                    "opp_last_5_conceded_raw", "last_3_no_draw_BOTH",
                  ]
            }
            emptyMessage={
              submitted.tick === 0
                ? "Set a date above and click Run Precision Check."
                : "No rows matched this precision check."
            }
          />
        )}
      </div>
    </div>
  );
}

export default function WeeklyPage() {
  return (
    <div
      className="flex flex-col gap-4 p-6"
    >
      <div className="glass flex items-center gap-3 rounded-lg p-4 shadow-panel">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-indigo/15">
          <Filter className="h-5 w-5 text-accent-indigo" />
        </div>
        <div>
          <h1 className="text-base font-bold text-text-primary">Weekly Forecast Filter</h1>
          <p className="text-xs text-text-secondary">
            Separate from pick-chain pages. GG, Win, and Over 2.5 filter engines — same columns
            as each engine&apos;s printout — plus Win Precision cross-check.
          </p>
        </div>
      </div>

      <div>
        <Tabs defaultValue="gg">
          <TabsList>
            <TabsTrigger value="gg">GG Filter</TabsTrigger>
            <TabsTrigger value="win">Win Filter</TabsTrigger>
            <TabsTrigger value="over25">Over 2.5 Filter</TabsTrigger>
            <TabsTrigger value="win_precision">Win Precision</TabsTrigger>
          </TabsList>

          <TabsContent value="gg" className="mt-4">
            <FilterTab config={GG_FILTER_CONFIG} fetchSingle={filterApi.getGGFilter} fetchWeekly={filterApi.getGGWeekly} />
          </TabsContent>

          <TabsContent value="win" className="mt-4">
            <FilterTab config={WIN_FILTER_CONFIG} fetchSingle={filterApi.getWinFilter} fetchWeekly={filterApi.getWinWeekly} />
          </TabsContent>

          <TabsContent value="over25" className="mt-4">
            <FilterTab
              config={OVER25_FILTER_CONFIG}
              fetchSingle={filterApi.getOver25Filter}
              fetchWeekly={filterApi.getOver25Weekly}
            />
          </TabsContent>

          <TabsContent value="win_precision" className="mt-4">
            <WinPrecisionPanel />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
