"use client";

import * as React from "react";
import { AlertTriangle, ShieldAlert, Trophy, Handshake } from "lucide-react";

import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
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

function humanizeRiskValue(value?: string | null): string | null {
  if (!value || value.trim().toLowerCase() === "unknown") return null;
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function FixtureRiskTag({
  row,
  label,
  className,
  textClassName,
  showLabel = true,
}: {
  row?: FixtureRiskRow | null;
  label: React.ReactNode;
  className?: string;
  textClassName?: string;
  showLabel?: boolean;
}) {
  const risky = isRiskFixture(row);
  const isFriendly = Boolean(row?.is_friendly);
  const isCup = Boolean(row?.is_cup);

  if (!risky) {
    return <span className={className}>{showLabel ? label : null}</span>;
  }

  const kind = isFriendly ? "friendly" : isCup ? "cup" : "general";
  const title = isFriendly ? "Friendly match" : isCup ? "Cup match" : "High-risk fixture";
  const headline = isFriendly ? "Friendly match" : isCup ? "Cup match" : "High-risk fixture";
  const explanation = isFriendly
    ? "Friendly fixtures often involve rotated squads, late lineup decisions, and uncertain motivation. Historical form and team-strength signals carry less predictive weight here."
    : isCup
      ? "Cup fixtures can reward rotation, tactical variation, and late lineup decisions. Treat the model output as informational rather than a high-confidence selection."
      : "This fixture carries a higher uncertainty profile. Lineups, tactical intent, and motivation can change late, reducing the reliability of form-based signals.";
  const competition = row?.league_name || row?.competition;
  const riskValue = humanizeRiskValue(row?.risk_label) || humanizeRiskValue(row?.risk_level);
  const metadata = [
    competition ? { label: "Competition", value: competition } : null,
    riskValue ? { label: "Risk profile", value: riskValue } : null,
  ].filter((item): item is { label: string; value: string } => Boolean(item));
  const Icon = isFriendly ? Handshake : isCup ? Trophy : ShieldAlert;
  const chipLabel = isFriendly ? "Friendly" : isCup ? "Cup" : "Risk";

  const chip = (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-1.5 py-px align-middle font-mono text-[9px] font-black uppercase tracking-wider transition-colors",
        !showLabel && "ml-0",
        isFriendly
          ? "border-rose-500/50 bg-rose-950/60 text-rose-300 group-hover:bg-rose-900/60"
          : isCup
            ? "border-amber-500/50 bg-amber-950/60 text-amber-300 group-hover:bg-amber-900/60"
            : "border-rose-500/50 bg-rose-950/60 text-rose-300 group-hover:bg-rose-900/60"
      )}
    >
      <Icon className="h-2.5 w-2.5" />
      {chipLabel}
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
            aria-label={`${title}. ${String(label ?? "")} — open risk warning`}
          >
            <span className={cn("truncate group-hover:underline", !showLabel && "sr-only", textClassName)}>{label}</span>
            {chip}
          </button>
        }
      />
      <DialogContent
        className={cn(
          "max-w-[calc(100%-2rem)] gap-0 overflow-hidden rounded-2xl border bg-bg-elevated/95 p-0 text-text-primary shadow-elevated ring-0 backdrop-blur-xl sm:max-w-lg",
          kind === "cup"
            ? "border-amber-400/30"
            : "border-rose-400/30"
        )}
      >
        <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-accent-cyan/70 to-transparent" />
        <DialogHeader className="relative gap-0 border-b border-border-bright/70 bg-gradient-card p-6">
          <div className="flex items-center gap-4">
            <div
              className={cn(
                "flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border shadow-inner",
                kind === "cup"
                  ? "border-amber-400/35 bg-amber-400/10 text-amber-300"
                  : "border-rose-400/35 bg-rose-400/10 text-rose-300"
              )}
            >
              <Icon className="h-5 w-5" aria-hidden />
            </div>
            <div className="min-w-0">
              <p className="text-[10px] font-bold uppercase tracking-[0.24em] text-text-muted">
                Fixture intelligence
              </p>
              <DialogTitle className="mt-1 text-xl font-bold tracking-tight text-text-primary">
                {headline}
              </DialogTitle>
              <p className="mt-1 truncate text-sm font-semibold text-text-secondary">
                {String(label ?? "")}
              </p>
            </div>
          </div>
        </DialogHeader>

        <DialogDescription className="block px-6 py-5 text-sm leading-relaxed text-text-secondary">
          <span className="block">{explanation}</span>
          {metadata.length > 0 && (
            <span className="mt-5 grid grid-cols-1 gap-3 border-t border-border-bright/60 pt-4 sm:grid-cols-2">
              {metadata.map((item) => (
                <span key={item.label} className="min-w-0">
                  <span className="block text-[10px] font-bold uppercase tracking-[0.18em] text-text-muted">
                    {item.label}
                  </span>
                  <span className="mt-1 block truncate text-sm font-semibold text-text-primary">
                    {item.value}
                  </span>
                </span>
              ))}
            </span>
          )}
        </DialogDescription>

        <DialogFooter className="mx-0 mb-0 rounded-b-2xl border-t border-border-bright/70 bg-bg-card/35 px-6 py-4 sm:justify-end">
          <DialogClose
            render={
              <Button
                className={cn(
                  "min-w-28 rounded-lg font-semibold text-white shadow-inner",
                  kind === "cup"
                    ? "bg-accent-amber text-black hover:bg-amber-400"
                    : "bg-accent-indigo hover:bg-indigo-400"
                )}
              />
            }
          >
            Understood
          </DialogClose>
        </DialogFooter>
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

