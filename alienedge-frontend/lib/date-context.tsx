"use client";

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { getTodayDate } from "@/lib/date-utils";

// ============================================================
// GLOBAL SELECTED DATE
// Every `{date}` endpoint in lib/api.ts is driven by this single
// piece of state (surfaced via DateSelector in TopBar) so market
// pages never manage their own date — one source of truth.
// ============================================================

interface DateContextValue {
  date: string;
  setDate: (date: string) => void;
}

const DateContext = createContext<DateContextValue | null>(null);

export function DateProvider({ children }: { children: ReactNode }) {
  const [date, setDate] = useState<string>(getTodayDate());
  const value = useMemo(() => ({ date, setDate }), [date]);

  return <DateContext.Provider value={value}>{children}</DateContext.Provider>;
}

export function useSelectedDate(): DateContextValue {
  const ctx = useContext(DateContext);
  if (!ctx) {
    throw new Error("useSelectedDate must be used within a DateProvider");
  }
  return ctx;
}
