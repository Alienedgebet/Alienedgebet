import type { Metadata } from "next";
import "./globals.css";
import { AppShell } from "@/components/layout/AppShell";
import { DateProvider } from "@/lib/date-context";
import { SidebarProvider } from "@/lib/sidebar-context";
import { RightPanelProvider } from "@/lib/right-panel-context";
import { AuthGate, AuthProvider } from "@/lib/auth-context";

export const metadata: Metadata = {
  title: "AlienEdge — Football Intelligence Platform",
  description:
    "Institutional-grade football intelligence. Multi-engine prediction analysis and live match forensics.",
  // Web Push needs a service worker, and iOS only grants the Push API to a
  // web app installed from the Home Screen. The manifest is what makes that
  // install offer a proper name, icon and standalone window instead of a
  // letterboxed screenshot.
  manifest: "/manifest.webmanifest",
  icons: {
    icon: [
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180" }],
  },
  appleWebApp: {
    capable: true,
    title: "AlienEdge",
    statusBarStyle: "black-translucent",
  },
  formatDetection: { telephone: false },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark h-full">
      <head>
        {/* iOS reads these before the manifest is parsed; without them the
            Home Screen install gets a generic name and a blank icon. */}
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <meta name="apple-mobile-web-app-title" content="AlienEdge" />
        <meta name="theme-color" content="#060912" />
      </head>
      <body className="min-h-full bg-bg-primary text-text-primary antialiased">
        <AuthProvider>
          <AuthGate>
            <DateProvider>
              <SidebarProvider>
                <RightPanelProvider>
                  <AppShell>{children}</AppShell>
                </RightPanelProvider>
              </SidebarProvider>
            </DateProvider>
          </AuthGate>
        </AuthProvider>
      </body>
    </html>
  );
}
