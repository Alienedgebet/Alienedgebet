"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import type { LiveBoard } from "@/lib/api";

/**
 * Manual refresh for the live pages, with a cooldown.
 *
 * Why a cooldown rather than a plain button: these pages sit behind an
 * authenticated API rate limit (`check_rate_limit("api:<user>", 180, 60)`),
 * and — more importantly — the data behind them is only rewritten once per
 * scanner cycle (~40s of work + 45s sleep on the current box). Clicking
 * refresh ten times in five seconds cannot produce ten fresher boards; it just
 * fires ten identical requests and makes the page look like it is thrashing.
 * So the button disables itself and counts down, which both protects the API and
 * tells the user, honestly, when the next genuinely-new data can appear.
 *
 * The countdown is wall-clock (not "is a request in flight") on purpose: a
 * request can complete in 30ms and still have returned data identical to what
 * was already on screen, because the scanner has not written since.
 */

/** Seconds the button stays locked after a press. Tuned to ~1 scanner cycle. */
const COOLDOWN_SECONDS = 30;

export interface LiveRefreshButtonProps {
  /** Trigger the refetch. Should be stable (wrap in useCallback). */
  onRefresh: () => void;
  /** True while any feed on the page is loading or revalidating. */
  refreshing?: boolean;
  /** Override the cooldown length (seconds). */
  cooldownSeconds?: number;
  className?: string;
}

export function LiveRefreshButton({
  onRefresh,
  refreshing = false,
  cooldownSeconds = COOLDOWN_SECONDS,
  className,
}: LiveRefreshButtonProps) {
  const [secondsLeft, setSecondsLeft] = useState(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // One interval for the whole countdown, cleared as soon as it hits zero, so
  // an idle button costs nothing.
  useEffect(() => {
    if (secondsLeft <= 0) return;
    const id = window.setInterval(() => {
      if (!mountedRef.current) return;
      setSecondsLeft((s) => (s <= 1 ? 0 : s - 1));
    }, 1000);
    return () => window.clearInterval(id);
  }, [secondsLeft]);

  const locked = secondsLeft > 0;

  const handleClick = useCallback(() => {
    if (locked || refreshing) return;
    onRefresh();
    setSecondsLeft(cooldownSeconds);
  }, [locked, refreshing, onRefresh, cooldownSeconds]);

  const label = locked ? `Refreshed · ${secondsLeft}s` : "Refresh";
  const spinnerActive = refreshing || locked;

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={locked || refreshing}
      aria-live="polite"
      title={
        locked
          ? "Waiting for the scanner's next write. The live scanner rewrites these feeds about once every 85 seconds."
          : "Fetch the latest live data now."
      }
      className={cn(
        "flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-bold transition-all",
        locked || refreshing
          ? "cursor-not-allowed border-white/5 bg-white/[0.02] text-slate-500"
          : "border-white/10 bg-white/5 text-slate-300 hover:text-white active:scale-95",
        className
      )}
    >
      <RefreshCw
        className={cn(
          "h-3.5 w-3.5",
          spinnerActive && "animate-spin text-cyan-400"
        )}
      />
      <span className="hidden sm:inline">{label}</span>
      <span className="sm:hidden" aria-hidden="true">
        {locked ? `${secondsLeft}s` : "↻"}
      </span>
    </button>
  );
}

export default LiveRefreshButton;


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
  className,
}: {
  rows: LiveBoard["matches"];
  loading?: boolean;
  withPicks: number;
  withoutPicks: number;
  className?: string;
}) {
  return (
    <section
      className={cn(
        "rounded-2xl border border-accent-cyan/20 bg-nebula shadow-elevated",
        className
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 px-5 py-3">
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
        <p className="text-[11px] text-text-dim">
          {withPicks} analysed · {withoutPicks} without lineup data
        </p>
      </div>

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
              lineups for those leagues, so the forensic engines above have
              nothing to analyse. They are shown here rather than hidden, so
              this page never implies a match is not in play.
            </p>
          )}
        </>
      )}
    </section>
  );
}