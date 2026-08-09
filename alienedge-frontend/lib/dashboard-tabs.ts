/**
 * Legacy dashboard tab ids — kept so /dashboard?tab=<market> can redirect
 * to the dedicated market route (/win, /gg, …).
 */

export const DASHBOARD_OVERVIEW_TAB = "overview" as const;

export const DASHBOARD_MARKET_TABS = [
  "win",
  "gg",
  "over25",
  "over15",
  "draw",
  "unders",
  "corners",
  "sot",
  "fhvi",
  "shvi",
  "underdog",
] as const;

export type DashboardMarketTab = (typeof DASHBOARD_MARKET_TABS)[number];
export type DashboardTab = typeof DASHBOARD_OVERVIEW_TAB | DashboardMarketTab;

export function isDashboardMarketTab(
  value: string | null | undefined
): value is DashboardMarketTab {
  return (
    typeof value === "string" &&
    (DASHBOARD_MARKET_TABS as readonly string[]).includes(value)
  );
}
