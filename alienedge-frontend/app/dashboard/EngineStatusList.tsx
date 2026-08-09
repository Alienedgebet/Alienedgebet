"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";
import type { UseApiResult } from "@/lib/use-api";
import type { MarketConfig, MarketPick } from "./market-config";

interface EngineStatusListProps {
  configs: MarketConfig[];
  results: UseApiResult<MarketPick[]>[];
}

/** Vertical engine status — static rows, no mount fade. */
export function EngineStatusList({ configs, results }: EngineStatusListProps) {
  const online = results.filter((r) => r.error === null).length;

  return (
    <div className="glass flex flex-1 flex-col overflow-hidden rounded-lg shadow-panel">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold text-text-primary">Engine Status</h2>
        <span className="font-mono text-2xs text-accent-green">
          {online}/{configs.length} operational
        </span>
      </div>
      <div className="flex-1 divide-y divide-border/60 overflow-y-auto">
        {configs.map((config, i) => {
          const r = results[i];
          const status = r.loading
            ? "checking"
            : r.error
              ? "offline"
              : "online";
          return (
            <Link
              key={config.key}
              href={config.href}
              prefetch
              className="flex items-center justify-between gap-2 px-4 py-2 text-xs transition-colors hover:bg-bg-elevated/50"
            >
              <span className="truncate text-text-secondary">{config.label}</span>
              <span className="flex shrink-0 items-center gap-1.5">
                <span
                  className={cn(
                    "h-1.5 w-1.5 rounded-full",
                    status === "online" && "bg-accent-green animate-live-pulse",
                    status === "offline" && "bg-accent-red",
                    status === "checking" && "animate-pulse-slow bg-accent-amber"
                  )}
                />
                <span
                  className={cn(
                    "font-mono text-2xs capitalize",
                    status === "online" && "text-accent-green",
                    status === "offline" && "text-accent-red",
                    status === "checking" && "text-accent-amber"
                  )}
                >
                  {status}
                </span>
              </span>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
