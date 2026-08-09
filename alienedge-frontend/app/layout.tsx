import type { Metadata } from "next";
import "./globals.css";
import { AppShell } from "@/components/layout/AppShell";
import { DateProvider } from "@/lib/date-context";
import { SidebarProvider } from "@/lib/sidebar-context";
import { RightPanelProvider } from "@/lib/right-panel-context";

export const metadata: Metadata = {
  title: "AlienEdge — Football Intelligence Platform",
  description:
    "Institutional-grade football intelligence. Multi-engine prediction analysis and live match forensics.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark h-full">
      <body className="min-h-full bg-bg-primary text-text-primary antialiased">
        <DateProvider>
          <SidebarProvider>
            <RightPanelProvider>
              <AppShell>{children}</AppShell>
            </RightPanelProvider>
          </SidebarProvider>
        </DateProvider>
      </body>
    </html>
  );
}
