"use client";

import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";

interface SidebarCtx {
  mobileOpen: boolean;
  toggle: () => void;
  close: () => void;
}

const SidebarContext = createContext<SidebarCtx>({
  mobileOpen: false,
  toggle: () => {},
  close: () => {},
});

export function SidebarProvider({ children }: { children: ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const toggle = useCallback(() => setMobileOpen((v) => !v), []);
  const close = useCallback(() => setMobileOpen(false), []);

  return (
    <SidebarContext.Provider value={{ mobileOpen, toggle, close }}>
      {children}
    </SidebarContext.Provider>
  );
}

export const useSidebar = () => useContext(SidebarContext);
