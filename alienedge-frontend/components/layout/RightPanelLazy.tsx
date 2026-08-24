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
      <aside className="fixed inset-y-0 right-0 top-[80px] z-[55] hidden h-[calc(100vh-80px)] w-[320px] border-l border-border bg-bg-primary md:block" />
    ),
  }
);
