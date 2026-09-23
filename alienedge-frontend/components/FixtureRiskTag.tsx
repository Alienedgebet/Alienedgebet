"use client";

import * as React from "react";
import { AlertTriangle, ShieldAlert, Trophy, Handshake } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

/**
 * FixtureRiskTag — ONE component for every fixture label in the app.
 *
 * The API stamps the cup/friendly decision onto EVERY picks row (read() /
 * read_range()), so a page only has to hand its row to this component:
 *
 *   <FixtureRiskTag row={r} label={r.fixture} />
 *
 * Behaviour:
 *  * not a risk fixture (or unknown) → the label renders EXACTLY as before
 *    (no badge, no wrapper, no layout shift). Unknown stays unknown: this
 *    component never invents a "safe" claim.
 *  * cup / friendly → the label gains a small warning chip that is focusable
 *    and clickable (Enter/Space too) and opens a warning dialog telling the
 *    user this match is a cup / friendly and therefore highly risky and
 *    unpredictable in nature.
 *
 * Nothing is removed or renamed on the page: the fixture text is still the
 * same text — it simply becomes interactive when (and only when) the fixture
 * carries a real warning.
 */
export interface FixtureRiskRow {
  fixture_id?: string | number;
  classification?: string;
  is_cup?: boolean;
  is_friendly?: boolean;
  is_risk_fixture?: boolean;
  risk_level?: string;
  risk_label?: string;
  competition?: string | null;
  league_name?: string | null;
}

export function isRiskFixture(row?: FixtureRiskRow | null): boolean {
  if (!row) return false;
  return Boolean(row.is_risk_fixture || row.is_cup || row.is_friendly);
}

export function FixtureRiskTag({
  row,
  label,
  className,
  textClassName,
}: {
  row?: FixtureRiskRow | null;
  label: React.ReactNode;
  className?: string;
  textClassName?: string;
}) {
  const risky = isRiskFixture(row);
  const isFriendly = Boolean(row?.is_friendly);
  const isCup = Boolean(row?.is_cup);

  if (!risky) {
    return <span className={className}>{label}</span>;
  }

  const title = isFriendly ? "Friendly match" : isCup ? "Cup match" : "High-risk fixture";
  const headline = isFriendly
    ? "This is a FRIENDLY match"
    : isCup
      ? "This is a CUP match"
      : "This is a high-risk fixture";

  const chip = (
    <span
      className={cn(
        "ml-1.5 inline-flex items-center gap-1 rounded-md border px-1.5 py-px align-middle font-mono text-[9px] font-black uppercase tracking-wider transition-colors",
        isFriendly
          ? "border-rose-500/50 bg-rose-950/60 text-rose-300 group-hover:bg-rose-900/60"
          : "border-amber-500/50 bg-amber-950/60 text-amber-300 group-hover:bg-amber-900/60"
      )}
    >
      {isFriendly ? <Handshake className="h-2.5 w-2.5" /> : <Trophy className="h-2.5 w-2.5" />}
      {isFriendly ? "Friendly" : "Cup"}
    </span>
  );

  return (
    <Dialog>
      <DialogTrigger
        render={
          <button
            type="button"
            className={cn(
              "group inline-flex max-w-full items-center rounded-sm text-left align-middle outline-none",
              "focus-visible:ring-2 focus-visible:ring-rose-400/70",
              className
            )}
            title={`${title} — tap for details`}
            aria-label={`${title}. ${String(label ?? "")} — open risk warning`}
          >
            <span className={cn("truncate group-hover:underline", textClassName)}>{label}</span>
            {chip}
          </button>
        }
      />
      <DialogContent className="max-w-md border-rose-500/40 bg-[#120a12] text-slate-100 ring-rose-500/30">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base font-black uppercase tracking-wide text-rose-300">
            <ShieldAlert className="h-4 w-4" />
            {headline}
          </DialogTitle>
          <DialogDescription className="space-y-3 text-xs leading-relaxed text-slate-300">
            <p className="text-sm font-semibold text-rose-200">
              This is {isFriendly ? "a friendly" : "a cup"} match — highly risky and
              unpredictable in nature.
            </p>
            <p>
              Squads and starting lineups are rotated and often decided late, competition
              intensity and motivation are unknown, and historical form carries far less
              predictive weight. Treat any model output for this fixture as informational only.
            </p>
            <ul className="list-disc space-y-1 pl-4 text-[11px] text-slate-400">
              <li>
                Competition:{" "}
                <span className="font-mono text-slate-300">{row?.league_name || "—"}</span>
                {row?.competition ? (
                  <>
                    {" "}
                    (<span className="font-mono">{row.competition}</span>)
                  </>
                ) : null}
              </li>
              <li>
                Risk level:{" "}
                <span className="font-mono text-slate-300">{row?.risk_level || "unknown"}</span>
              </li>
              <li className="break-all">
                Fixture ID:{" "}
                <span className="font-mono text-slate-400">{row?.fixture_id ?? "—"}</span>
              </li>
            </ul>
          </DialogDescription>
        </DialogHeader>
      </DialogContent>
    </Dialog>
  );
}

/** Small standalone chip for places that show flags without a fixture label. */
export function FixtureRiskBadge({ row }: { row?: FixtureRiskRow | null }) {
  if (!isRiskFixture(row)) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 font-mono text-[9px] font-black uppercase tracking-wider",
        row?.is_friendly
          ? "border-rose-500/50 bg-rose-950/60 text-rose-300"
          : "border-amber-500/50 bg-amber-950/60 text-amber-300"
      )}
    >
      <AlertTriangle className="h-2.5 w-2.5" />
      {row?.is_friendly ? "Friendly" : "Cup"}
    </span>
  );
}

