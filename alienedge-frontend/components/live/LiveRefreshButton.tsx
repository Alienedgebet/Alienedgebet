"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";

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

