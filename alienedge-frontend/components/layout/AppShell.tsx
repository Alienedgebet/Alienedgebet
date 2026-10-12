"use client";

import type { ReactNode } from "react";
import Link from "next/link";
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
        {/* Legal strip - anchored at the bottom of the authenticated app (below
            every dashboard/market page), per the agreed layout. NOT in the
            sidebar. No FAQ/Settings routes exist in this app, so those are
            omitted; /support is the single help route. */}
        <footer className="mt-10 border-t border-border/40 pt-5 text-center text-[11px] text-text-dim">
          <span className="text-text-dim/60">
            &copy; {new Date().getFullYear()} AlienEdge — decision support, not betting advice.
          </span>
          <nav className="mt-2 flex flex-wrap items-center justify-center gap-x-3 gap-y-1">
            <Link href="/support" className="hover:text-text-primary">Support</Link>
            <span className="text-text-dim/40" aria-hidden>&middot;</span>
            <Link href="/terms" className="hover:text-text-primary">Terms</Link>
            <span className="text-text-dim/40" aria-hidden>&middot;</span>
            <Link href="/privacy" className="hover:text-text-primary">Privacy</Link>
            <span className="text-text-dim/40" aria-hidden>&middot;</span>
            <Link href="/cookies" className="hover:text-text-primary">Cookies</Link>
            <span className="text-text-dim/40" aria-hidden>&middot;</span>
            <Link href="/responsible-gambling" className="hover:text-text-primary">Responsible use</Link>
          </nav>
        </footer>
      </main>
    </>
  );
}
