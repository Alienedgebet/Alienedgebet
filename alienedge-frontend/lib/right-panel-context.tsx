"use client";

import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";

interface RightPanelCtx {
  mobileOpen: boolean;
  toggle: () => void;
  close: () => void;
}

const RightPanelContext = createContext<RightPanelCtx>({
  mobileOpen: false,
  toggle: () => {},
  close: () => {},
});

/**
 * Mirrors `sidebar-context.tsx` for the right-hand War Room / Leaderboard
 * panel: on mobile it renders as a collapsible off-canvas drawer (closed by
 * default) instead of the desktop's always-docked 320px column, so it never
 * permanently covers the page on small screens.
 */
export function RightPanelProvider({ children }: { children: ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const toggle = useCallback(() => setMobileOpen((v) => !v), []);
  const close = useCallback(() => setMobileOpen(false), []);

  return (
    <RightPanelContext.Provider value={{ mobileOpen, toggle, close }}>
      {children}
    </RightPanelContext.Provider>
  );
}

export const useRightPanel = () => useContext(RightPanelContext);
