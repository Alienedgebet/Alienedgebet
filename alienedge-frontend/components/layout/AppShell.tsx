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
      <main className="min-h-screen w-full overflow-x-hidden bg-bg-primary pt-[95px] pb-12 md:ml-sidebar md:mr-[320px]">
  {children}
</main>
    </>
  );
}
