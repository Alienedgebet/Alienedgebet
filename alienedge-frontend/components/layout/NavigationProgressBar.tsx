"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";

// Upper bound so the bar can never get stuck visible forever if a
// navigation is aborted in a way that never resolves to a pathname change.
const SAFETY_TIMEOUT_MS = 6000;

/**
 * App-wide "click registered, page is on its way" indicator.
 *
 * Next's App Router calls `history.pushState`/`replaceState` the instant a
 * client-side navigation is initiated — well before the destination route's
 * JS/RSC payload has finished streaming in. Patching those two calls (plus
 * `popstate` for back/forward) is the only reliable, app-wide navigation
 * signal available without hand-wiring an onClick handler onto every
 * sidebar item, table row link, and programmatic `router.push()` call.
 *
 * The bar hides itself the moment `usePathname()` reports the destination
 * route has actually committed, so "instant" pages (served from the
 * `useApi` cache) show only a brief flash while genuinely slow ones show
 * continuous progress instead of leaving the user staring at a static page.
 */
export function NavigationProgressBar() {
  const pathname = usePathname();
  const [navigating, setNavigating] = useState(false);
  const safetyTimer = useRef<number | null>(null);
  const mounted = useRef(false);

  useEffect(() => {
    const clearSafety = () => {
      if (safetyTimer.current !== null) {
        window.clearTimeout(safetyTimer.current);
        safetyTimer.current = null;
      }
    };

    const start = () => {
      setNavigating(true);
      clearSafety();
      safetyTimer.current = window.setTimeout(() => {
        setNavigating(false);
      }, SAFETY_TIMEOUT_MS);
    };

    const originalPush = window.history.pushState.bind(window.history);
    const originalReplace = window.history.replaceState.bind(window.history);

    window.history.pushState = ((...args: Parameters<History["pushState"]>) => {
      start();
      return originalPush(...args);
    }) as History["pushState"];

    window.history.replaceState = ((...args: Parameters<History["replaceState"]>) => {
      start();
      return originalReplace(...args);
    }) as History["replaceState"];

    window.addEventListener("popstate", start);

    return () => {
      window.history.pushState = originalPush;
      window.history.replaceState = originalReplace;
      window.removeEventListener("popstate", start);
      clearSafety();
    };
  }, []);

  useEffect(() => {
    // First render is the initial page load, not a client navigation — skip it
    // so the bar never flashes on a hard refresh.
    if (!mounted.current) {
      mounted.current = true;
      return;
    }
    setNavigating(false);
    if (safetyTimer.current !== null) {
      window.clearTimeout(safetyTimer.current);
      safetyTimer.current = null;
    }
  }, [pathname]);

  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-x-0 top-0 z-toast h-[3px] overflow-hidden"
    >
      <AnimatePresence>
        {navigating && (
          <motion.div
            key="nav-progress-bar"
            className="h-full bg-gradient-ae-blue shadow-glow"
            initial={{ width: "0%", opacity: 1 }}
            animate={{ width: "82%", opacity: 1 }}
            exit={{
              width: "100%",
              opacity: 0,
              transition: {
                width: { duration: 0.15, ease: "easeOut" },
                opacity: { duration: 0.35, delay: 0.1 },
              },
            }}
            transition={{ width: { duration: 1.1, ease: "easeOut" } }}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
