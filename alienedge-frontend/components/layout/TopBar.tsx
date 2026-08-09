"use client";

import { useEffect, useState } from "react";
import { Activity, Menu, Wifi, WifiOff } from "lucide-react";
import { cn } from "@/lib/utils";
import { healthApi } from "@/lib/api";
import { DateSelector } from "@/components/layout/DateSelector";
import { useSidebar } from "@/lib/sidebar-context";

type ApiStatus = "checking" | "online" | "offline";

export function TopBar() {
  const [status, setStatus] = useState<ApiStatus>("checking");
  const { toggle } = useSidebar();

  useEffect(() => {
    let live = true;
    healthApi
      .check()
      .then(() => { if (live) setStatus("online"); })
      .catch(() => { if (live) setStatus("offline"); });
    return () => { live = false; };
  }, []);

  return (
    <header
      className={cn(
        "fixed left-0 right-0 top-0 z-[40] h-[56px] md:left-[240px]",
        "flex items-center justify-between border-b border-border px-4 md:px-6",
        "bg-bg-primary/95 backdrop-blur-md"
      )}
    >
      {/* Hamburger — mobile only */}
      <button
        type="button"
        onClick={toggle}
        aria-label="Toggle navigation"
        className="mr-3 flex h-8 w-8 shrink-0 items-center justify-center rounded border border-border text-text-secondary transition-colors hover:border-border-bright hover:text-text-primary md:hidden"
      >
        <Menu className="h-4 w-4" />
      </button>

      {/* Left — global date selector, drives every {date} endpoint */}
      <DateSelector />

      {/* Centre — platform identity */}
      <div className="absolute left-1/2 -translate-x-1/2 select-none">
        <span className="text-2xs font-medium uppercase tracking-[0.15em] text-text-dim">
          Football Intelligence Platform
        </span>
      </div>

      {/* Right — API status + user avatar placeholder */}
      <div className="flex items-center gap-3">
        {/* API status pill */}
        <div
          className={cn(
            "flex items-center gap-1.5 rounded border px-2.5 py-1 font-mono text-2xs transition-colors",
            status === "online"
              ? "border-accent-green/20 bg-accent-green/5 text-accent-green"
              : status === "offline"
              ? "border-accent-red/20 bg-accent-red/5 text-accent-red"
              : "border-border bg-bg-elevated text-text-muted"
          )}
        >
          {status === "online"   && <Wifi     className="h-3 w-3" />}
          {status === "offline"  && <WifiOff  className="h-3 w-3" />}
          {status === "checking" && <Activity className="h-3 w-3 animate-pulse" />}
          <span>
            {status === "checking" ? "API…" : status === "online" ? "Online" : "Offline"}
          </span>
          {status === "online" && (
            <span className="h-1.5 w-1.5 rounded-full bg-accent-green animate-live-pulse" />
          )}
        </div>

        {/* User avatar — placeholder until Phase 13 auth */}
        <div className="flex h-7 w-7 cursor-pointer select-none items-center justify-center rounded-full border border-border bg-bg-elevated text-xs font-semibold text-text-secondary transition-colors hover:border-border-bright hover:text-text-primary">
          A
        </div>
      </div>
    </header>
  );
}
