import type { ReactNode } from "react";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";
import { RightPanelLazy } from "@/components/layout/RightPanelLazy";
import { NavigationProgressBar } from "@/components/layout/NavigationProgressBar";

interface AppShellProps {
  children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  return (
    <>
      <NavigationProgressBar />
      <Sidebar />
      <TopBar />
      <RightPanelLazy />
      <main className="mt-topbar min-h-[calc(100vh-56px)] w-full overflow-x-hidden bg-bg-primary md:ml-sidebar md:mr-[320px]">
        {children}
      </main>
    </>
  );
}
