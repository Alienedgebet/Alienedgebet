"use client";

import dynamic from "next/dynamic";

/**
 * Right panel is mock social UI (Phase 13) and is not needed for market
 * page interactivity — defer its JS until after first paint so route
 * navigations pay less for the shell.
 */
export const RightPanelLazy = dynamic(
  () => import("@/components/layout/RightPanel").then((m) => m.RightPanel),
  {
    ssr: false,
    loading: () => (
      <aside className="fixed right-0 top-[56px] z-[50] h-[calc(100vh-56px)] w-[320px] border-l border-border bg-bg-primary" />
    ),
  }
);
