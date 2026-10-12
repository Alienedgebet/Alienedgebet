"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";
import { RightPanelLazy } from "@/components/layout/RightPanelLazy";
import { NavigationProgressBar } from "@/components/layout/NavigationProgressBar";
import { isPublicPath } from "@/lib/public-paths";

interface AppShellProps {
  children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const pathname = usePathname();
  // Public pages (landing, legal, support, reset flow, auth) render their own
  // header/footer — never inside the sidebar/topbar/right-panel chrome.
  if (isPublicPath(pathname)) return <>{children}</>;
  return (
    <>
      <NavigationProgressBar />
      <Sidebar />
      <TopBar />
      <RightPanelLazy />
      <main className="min-h-screen w-full overflow-x-hidden bg-bg-primary pt-[95px] pb-12 md:ml-sidebar md:mr-[320px]">
  {children}
</main>
    </>
  );
}
