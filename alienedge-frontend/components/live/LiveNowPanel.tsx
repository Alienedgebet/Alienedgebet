"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import type { LiveBoard } from "@/lib/api";


/**
 * "Live Now" — every fixture actually in play, including the ones the forensic
 * engines cannot analyse.
 *
 * WHY THIS PANEL EXISTS
 * ---------------------
 * The forensic tables on this page are built by engines that admit a fixture
 * only once it has an OFFICIAL LINEUP. The provider publishes no lineups for
 * several leagues, so those fixtures were being dropped silently and the page
 * looked empty while dozens of matches were in play. Measured 2026-10-03: 40
 * live, 39 of them invisible here.
 *
 * So this panel is fed by `GET /api/live/board`, which is assembled from the
 * shared in-play disk cache the API already reads for the `live` column of
 * those tables — zero extra provider calls, so it cannot compete with the
 * nightly pre-match pipeline for the shared SportMonks quota.
 *
 * A row without forensic picks is shown, not hidden, and says why. That
 * distinction matters: "live but not analysable" and "not live" are different
 * facts, and conflating them is what made this page misleading.
 */
export function LiveNowPanel({
  rows,
  loading,
  withPicks,
  withoutPicks,
  defaultOpen = true,
  className,
}: {
  rows: LiveBoard["matches"];
  loading?: boolean;
  withPicks: number;
  withoutPicks: number;
  defaultOpen?: boolean;
  className?: string;
}) {
  // Collapsible, matching ChainSection (the accordion shell the pre-match pick
  // pack already uses) so the whole live section behaves the same way: the
  // header always stays readable — name, count, freshness — and the body folds
  // away. Height/opacity animations are deliberately absent; ChainSection
  // removed them because animating height:auto across several large tables was
  // a measured source of click-to-freeze lag.
  const [open, setOpen] = useState(defaultOpen);

  return (
    <section
      className={cn(
        "rounded-2xl border border-accent-cyan/20 bg-nebula shadow-elevated",
        className
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full flex-wrap items-center justify-between gap-2 px-5 py-3 text-left transition-colors hover:bg-white/[0.03]"
      >
        <div className="flex items-center gap-2">
          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent-cyan opacity-60" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-accent-cyan" />
          </span>
          <h2 className="text-sm font-black uppercase tracking-wider text-text-primary">
            Live Now
          </h2>
          <span className="rounded-full border border-accent-cyan/30 bg-accent-cyan/10 px-2 py-0.2 font-mono text-[9px] font-bold text-accent-cyan">
            {rows.length} IN PLAY
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[11px] text-text-dim">
            {withPicks} analysed · {withoutPicks} without lineup data
          </span>
          <ChevronDown
            className={cn(
              "h-4 w-4 shrink-0 text-text-muted transition-transform duration-150",
              open && "rotate-180"
            )}
          />
        </div>
      </button>

      {open && (
        <>
          {loading && rows.length === 0 ? (
            <div className="grid gap-2 p-4 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-12 rounded-lg bg-bg-elevated" />
              ))}
            </div>
          ) : rows.length === 0 ? (
            <p className="px-5 py-6 text-center text-sm text-text-dim">
              No matches are in play right now. The scanner checks every few
              seconds, so this panel fills in as soon as the next fixture kicks off.
            </p>
          ) : (
            <>
              <ul className="grid gap-2 p-4 sm:grid-cols-2 lg:grid-cols-3">
                {rows.map((m) => (
                  <li
                    key={m.fixture_id}
                    className="flex items-center justify-between gap-3 rounded-lg border border-white/10 bg-black/30 px-3 py-2"
                    title={
                      m.has_forensic_picks
                        ? `${m.fixture} — the forensic engines produced picks for this fixture.`
                        : `${m.fixture} — live, but the provider publishes no official lineup for this league, so the forensic engines have nothing to analyse.`
                    }
                  >
                    <div className="min-w-0">
                      <p className="truncate text-[13px] font-semibold text-text-primary">
                        {m.fixture}
                      </p>
                      <p className="font-mono text-2xs text-text-dim">
                        {m.minute}&apos; · {m.state.replace(/^INPLAY_/, "").replace(/_/g, " ")}
                        {!m.has_forensic_picks && (
                          <span className="ml-1.5 text-amber-400/90">
                            · no lineup data
                          </span>
                        )}
                      </p>
                    </div>
                    <span className="shrink-0 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1 font-mono text-sm font-black text-white">
                      {m.score ?? "—"}
                    </span>
                  </li>
                ))}
              </ul>
              {withoutPicks > 0 && (
                <p className="border-t border-white/10 px-5 py-2.5 text-[11px] leading-relaxed text-text-dim">
                  Matches marked{" "}
                  <span className="font-semibold text-amber-400/90">no lineup data</span>{" "}
                  are genuinely live — the provider simply does not publish official
                  lineups for those leagues, so the forensic engines below have
                  nothing to analyse. They are shown here rather than hidden, so
                  this page never implies a match is not in play.
                </p>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
