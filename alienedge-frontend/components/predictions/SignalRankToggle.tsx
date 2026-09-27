"use client";

import { ArrowDownWideNarrow, Info } from "lucide-react";

interface SignalRankToggleProps {
  /** Whether the ranking is currently applied to the table. */
  active: boolean;
  onChange: (next: boolean) => void;
  /** Short label for the applied state, e.g. "Highest volume first". */
  activeLabel: string;
  inactiveLabel: string;
  /** Tooltip text stating the evidence status and how to re-check it. */
  help: string;
  /** Amber accent for a ranking that is not yet evidence-backed. */
  tentative?: boolean;
}

/**
 * Display-only switch for the backtested front-of-list ordering.
 *
 * It only reorders rows the API already returned — it never filters, hides or
 * re-grades a pick, and it never changes what the Verify column settles. The
 * state is local to the page, so switching back to "As served" always restores
 * the exact order the engine produced.
 */
export function SignalRankToggle({
  active,
  onChange,
  activeLabel,
  inactiveLabel,
  help,
  tentative = false,
}: SignalRankToggleProps) {
  const on = active ? "border-accent-cyan/40 bg-accent-cyan/10 text-accent-cyan" : "border-white/10 text-text-secondary";
  const warn = tentative && active ? "border-accent-amber/40 bg-accent-amber/10 text-accent-amber" : on;

  return (
    <div className="flex items-center gap-2">
      {tentative && active ? (
        <span
          className="hidden items-center gap-1 text-2xs text-accent-amber sm:inline-flex"
          title="This ordering is not yet supported by the backtest."
        >
          <Info className="h-3 w-3" />
          Unproven
        </span>
      ) : null}
      <button
        type="button"
        onClick={() => onChange(!active)}
        aria-pressed={active}
        title={help}
        className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-2xs font-semibold uppercase tracking-wide transition-colors hover:border-white/25 ${warn}`}
      >
        <ArrowDownWideNarrow className="h-3.5 w-3.5" />
        {active ? activeLabel : inactiveLabel}
      </button>
    </div>
  );
}
