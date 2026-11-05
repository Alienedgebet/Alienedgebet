"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  getIntelligentPass,
  type IntelligentPassResult,
  type IntelligentPassCheck,
} from "@/lib/api";

/**
 * Team + Market Intelligent Pass report page.
 *
 * URL: /team/{team}?date=2026-09-21&market=unders&label=...
 *
 * Shows ONLY the clicked market's checks with full provenance (source, field,
 * mapping, value, threshold). Back navigation returns to the exact page the user
 * came from, preserving the selected date and relevant filters (browser history
 * state is preserved by router.back()).
 *
 * Architecture (binding):
 *   TEAM + FIXTURE + DATE + MARKET → ONE PICK → ONLY THAT MARKET'S CHECKS
 */
export default function TeamIntelligentPassPage({
  params,
}: {
  params: { team: string };
}) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const team = params.team;
  const date = searchParams.get("date") || "";
  const market = searchParams.get("market") || "";
  const label = searchParams.get("label") || undefined;

  const [result, setResult] = useState<IntelligentPassResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!team || !date || !market) {
        setError("Missing team, date or market.");
        setLoading(false);
        return;
      }
      try {
        setLoading(true);
        const data = await getIntelligentPass(team, date, market, {
          label,
        });
        if (!cancelled) setResult(data);
      } catch (e) {
        if (!cancelled)
          setError(
            e instanceof Error ? e.message : "Failed to load Intelligent Pass report.",
          );
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [team, date, market, label]);

  const handleBack = () => {
    router.back();
  };

  if (loading) {
    return (
      <div className="p-6 text-text-muted">
        Loading Intelligent Pass report for {team}…
      </div>
    );
  }
  if (error) {
    return (
      <div className="p-6 rounded-lg border border-destructive/20 bg-destructive/5 text-destructive">
        {error}
      </div>
    );
  }
  if (!result) {
    return (
      <div className="p-6 text-text-muted">No Intelligent Pass data available.</div>
    );
  }

  const pass = result.pass_count;
  const total = result.total;
  const allPass = total > 0 && pass === total;
  const anyFail = result.checks.some((c) => c.result === "FAIL");

  return (
    <div className="p-6">
      <div className="mb-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">
            Intelligent Pass — {result.market}
          </h1>
          <p className="text-text-muted">
            {result.team} &middot; {result.date} &middot; source date{" "}
            {result.source_date || "n/a"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleBack}
            className="inline-flex items-center gap-1.5 rounded-md border border-input bg-background px-3 py-1.5 text-sm font-medium text-text-primary hover:bg-accent transition"
          >
            ← Back
          </button>
          <span
            className={`inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-bold ${allPass ? "border-accent-green/40 bg-accent-green/10 text-accent-green" : anyFail ? "border-accent-red/40 bg-accent-red/10 text-accent-red" : "border-muted/40 bg-muted text-text-muted"}`}
          >
            {pass}/{total} passed
          </span>
        </div>
      </div>

      <div className="mb-4 flex items-center gap-2">
        <span className="font-medium text-text-primary">{result.market}</span>
        {result.fixture_id && (
          <span className="text-xs text-text-muted">{result.fixture_id}</span>
        )}
        {result.label && <span className="text-xs text-text-muted">· {result.label}</span>}
      </div>

      <div className="rounded-lg border border-input bg-background">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-muted/30 bg-muted/50">
              <th className="pb-2 pr-4 text-text-muted font-medium">Check</th>
              <th className="pb-2 pr-4 text-text-muted font-medium">Result</th>
              <th className="pb-2 pr-4 text-text-muted font-medium">Value</th>
              <th className="pb-2 pr-4 text-text-muted font-medium">Threshold</th>
              <th className="pb-2 pr-4 text-text-muted font-medium">Source</th>
              <th className="pb-2 pr-4 text-text-muted font-medium">Field</th>
              <th className="pb-2 pr-4 text-text-muted font-medium">Mapping</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-muted/20">
            {result.checks.map((check: IntelligentPassCheck, i: number) => (
              <tr key={i} className="hover:bg-muted/30 transition">
                <td className="py-2 pr-4 font-medium text-text-primary">{check.name}</td>
                <td className="py-2 pr-4">
                  <span
                    className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[10px] font-bold ${
                      check.result === "PASS"
                        ? "border-accent-green/40 bg-accent-green/10 text-accent-green"
                        : check.result === "FAIL"
                          ? "border-accent-red/40 bg-accent-red/10 text-accent-red"
                          : "border-muted/40 bg-muted text-text-muted"
                    }`}
                  >
                    {check.result}
                  </span>
                </td>
                <td className="py-2 pr-4 font-mono text-text-primary">
                  {check.value == null ? "—" : String(check.value)}
                </td>
                <td className="py-2 pr-4 font-mono text-text-muted">
                  {check.threshold == null ? "—" : String(check.threshold)}
                </td>
                <td className="py-2 pr-4 text-text-muted truncate max-w-[180px]">
                  {check.source}
                </td>
                <td className="py-2 pr-4 text-text-muted truncate max-w-[140px]">
                  {check.field}
                </td>
                <td className="py-2 pr-4 text-text-muted truncate max-w-[160px]">
                  {check.mapping || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-4 text-xs text-text-muted">
        Every check reads a single pre-existing engine output. No new
        mathematics, no new SportMonks calls, no change to existing predictions.
        Checks with no engine cache for the requested date (within the ±3-day
        source window) report N/A.
      </p>
    </div>
  );
}
