"use client";

import Link from "next/link";
import { useLinkStatus } from "next/link";
import { usePathname } from "next/navigation";
import { memo, useCallback, useEffect, useState, type ElementType } from "react";
import {
  Bell,
  ChevronDown,
  ChevronRight,
  CornerUpRight,
  Cpu,
  Crosshair,
  Filter,
  Flame,
  Hourglass,
  Inbox,
  LayoutDashboard,
  Loader2,
  Radio,
  Scale,
  Shield,
  SlidersHorizontal,
  Swords,
  Target,
  TimerReset,
  TrendingDown,
  TrendingUp,
  Trophy,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useSidebar } from "@/lib/sidebar-context";

interface NavItem {
  label: string;
  href: string;
  icon: ElementType;
  badge?: string;
}

interface NavSection {
  title?: string;
  items: NavItem[];
}

// ── 1. LIVE SUB-MENU ───────────────────────────────────────────────
const LIVE_CHILDREN: NavItem[] = [
  { label: "Live Match Edges", href: "/live/edges", icon: Shield },
  { label: "Incoming Live Matches", href: "/live/incoming", icon: Inbox },
  { label: "Live Alert Scanner", href: "/live/alerts", icon: Bell },
  { label: "Build My Alert", href: "/live/rules", icon: SlidersHorizontal },
];

// ── 2. WEEKLY FORECASTS SUB-MENU ───────────────────────────────────
const WEEKLY_CHILDREN: NavItem[] = [
  { label: "GG Precision Filter", href: "/weekly/gg", icon: Zap },
  { label: "Over 2.5 Filter", href: "/weekly/over25", icon: TrendingUp },
  { label: "Win Poisson Filter", href: "/weekly/win", icon: Trophy },
  { label: "Win Cross-Check", href: "/weekly/precision", icon: Target },
];

const NAV: NavSection[] = [
  {
    items: [{ label: "Dashboard", href: "/dashboard", icon: LayoutDashboard }],
  },
  {
    title: "Prediction Markets",
    items: [
      { label: "Win", href: "/win", icon: Trophy },
      { label: "GG / BTTS", href: "/gg", icon: Zap },
      { label: "Over 2.5", href: "/over25", icon: TrendingUp },
      { label: "Over 1.5", href: "/over15", icon: Flame },
      { label: "Draw", href: "/draw", icon: Scale },
      { label: "Unders", href: "/unders", icon: TrendingDown },
      { label: "Corners", href: "/corners", icon: CornerUpRight },
      { label: "SOT", href: "/sot", icon: Crosshair },
      { label: "FHVI", href: "/fhvi", icon: Hourglass },
      { label: "SHVI", href: "/shvi", icon: TimerReset },
      { label: "Underdog to Score", href: "/underdog", icon: Swords },
    ],
  },
  {
    title: "Intelligence Tools",
    items: [],
  },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/dashboard") {
    return pathname === "/" || pathname === "/dashboard";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

function NavPendingHint() {
  const { pending } = useLinkStatus();
  return (
    <Loader2
      aria-hidden
      className={cn(
        "h-3 w-3 shrink-0 text-accent-indigo transition-opacity",
        pending ? "animate-spin opacity-100" : "opacity-0"
      )}
    />
  );
}

const NavLink = memo(function NavLink({
  item,
  active,
  onNavigate,
  isSubItem = false,
}: {
  item: NavItem;
  active: boolean;
  onNavigate: (href: string) => void;
  isSubItem?: boolean;
}) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      prefetch={true}
      onClick={() => onNavigate(item.href)}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group flex items-center gap-2.5 rounded transition-colors duration-100",
        isSubItem ? "px-2.5 py-1.5 text-xs" : "px-3 py-2 text-sm",
        active
          ? "nav-active font-semibold"
          : "text-text-secondary hover:bg-bg-elevated/60 hover:text-text-primary"
      )}
    >
      <Icon
        className={cn(
          "shrink-0 transition-colors",
          isSubItem ? "h-3.5 w-3.5" : "h-4 w-4",
          active
            ? "text-accent-indigo"
            : "text-text-muted group-hover:text-text-secondary"
        )}
      />
      <span className="flex-1 truncate">{item.label}</span>
      {item.badge && (
        <span className="animate-pulse-slow rounded border border-accent-red/30 bg-accent-red/10 px-1 py-0.2 text-[9px] font-bold text-accent-red">
          {item.badge}
        </span>
      )}
      <NavPendingHint />
      {active && (
        <ChevronRight className="h-3 w-3 shrink-0 text-accent-indigo/70" />
      )}
    </Link>
  );
});

// ── EXPANDABLE LIVE ACCORDION ───────────────────────────────────────
const LiveNavGroup = memo(function LiveNavGroup({
  activePath,
  onNavigate,
}: {
  activePath: string;
  onNavigate: (href: string) => void;
}) {
  const onLive = activePath === "/live" || activePath.startsWith("/live/");
  const [open, setOpen] = useState(true);

  useEffect(() => {
    if (onLive) setOpen(true);
  }, [onLive]);

  return (
    <div className="space-y-0.5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className={cn(
          "group flex w-full items-center gap-2.5 rounded px-2.5 py-2 text-xs transition-colors duration-100",
          onLive
            ? "nav-active font-semibold"
            : "text-text-secondary hover:bg-bg-elevated/60 hover:text-text-primary"
        )}
      >
        <Radio
          className={cn(
            "h-3.5 w-3.5 shrink-0 transition-colors",
            onLive
              ? "text-accent-indigo"
              : "text-text-muted group-hover:text-text-secondary"
          )}
        />
        <span className="flex-1 text-left font-semibold">Live Monitor</span>
        <span className="animate-pulse-slow rounded border border-accent-red/30 bg-accent-red/10 px-1 py-0.2 text-[9px] font-bold text-accent-red">
          LIVE
        </span>
        {open ? (
          <ChevronDown className="h-3 w-3 shrink-0 text-accent-indigo/70" />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0 text-text-muted" />
        )}
      </button>
      {open && (
        <div className="ml-2 space-y-0.5 border-l border-border/70 pl-2">
          {LIVE_CHILDREN.map((item) => (
            <NavLink
              key={item.href}
              item={item}
              active={isActive(activePath, item.href)}
              onNavigate={onNavigate}
              isSubItem={true}
            />
          ))}
        </div>
      )}
    </div>
  );
});

// ── EXPANDABLE WEEKLY FORECAST FILTER ACCORDION ──────────────────────
const WeeklyNavGroup = memo(function WeeklyNavGroup({
  activePath,
  onNavigate,
}: {
  activePath: string;
  onNavigate: (href: string) => void;
}) {
  const onWeekly = activePath === "/weekly" || activePath.startsWith("/weekly");
  const [open, setOpen] = useState(true);

  useEffect(() => {
    if (onWeekly) setOpen(true);
  }, [onWeekly]);

  return (
    <div className="space-y-0.5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className={cn(
          "group flex w-full items-center gap-2 rounded px-2.5 py-2 text-xs transition-colors duration-100",
          onWeekly
            ? "nav-active font-semibold"
            : "text-text-secondary hover:bg-bg-elevated/60 hover:text-text-primary"
        )}
      >
        <Filter
          className={cn(
            "h-3.5 w-3.5 shrink-0 transition-colors",
            onWeekly
              ? "text-cyan-400"
              : "text-text-muted group-hover:text-text-secondary"
          )}
        />
        {/* Full Title Visible without Truncation */}
        <span className="flex-1 text-left font-semibold text-[11.5px] leading-tight">
          Weekly Forecast Filter
        </span>
        <span className="shrink-0 rounded border border-cyan-500/30 bg-cyan-500/10 px-1 py-0.2 text-[8.5px] font-bold text-cyan-300">
          WKY
        </span>
        {open ? (
          <ChevronDown className="h-3 w-3 shrink-0 text-cyan-400/70" />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0 text-text-muted" />
        )}
      </button>
      {open && (
        <div className="ml-2 space-y-0.5 border-l border-cyan-500/20 pl-2">
          {WEEKLY_CHILDREN.map((item) => (
            <NavLink
              key={item.href}
              item={item}
              active={isActive(activePath, item.href)}
              onNavigate={onNavigate}
              isSubItem={true}
            />
          ))}
        </div>
      )}
    </div>
  );
});

export function Sidebar() {
  const pathname = usePathname();
  const { mobileOpen, close } = useSidebar();

  const [optimisticPath, setOptimisticPath] = useState<string | null>(null);

  useEffect(() => {
    setOptimisticPath(null);
  }, [pathname]);

  const effectivePath = optimisticPath ?? pathname;

  const handleNavigate = useCallback(
    (href: string) => {
      setOptimisticPath(href);
      close();
    },
    [close]
  );

  return (
    <>
      {mobileOpen && (
        <div
          aria-hidden
          className="fixed inset-0 z-[49] bg-black/60 md:hidden"
          onClick={close}
        />
      )}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-sidebar flex w-sidebar flex-col border-r border-border bg-gradient-sidebar",
          "transition-transform duration-200 ease-ae-ease",
          mobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
        )}
      >
        <div className="flex h-topbar shrink-0 items-center gap-2.5 border-b border-border px-4">
          <Link
            href="/dashboard"
            prefetch
            className="flex min-w-0 flex-1 items-center gap-2.5"
          >
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-ae-blue shadow-glow">
              <Cpu className="h-4 w-4 text-white" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold leading-none">
                <span className="gradient-text">AlienEdge</span>
              </p>
              <p className="mt-0.5 truncate text-2xs text-text-dim">
                Intelligence Platform
              </p>
            </div>
          </Link>
        </div>

        <nav className="flex-1 overflow-y-auto px-2 py-3" aria-label="Primary">
          {NAV.map((section, si) => (
            <div key={si} className={si > 0 ? "mt-5" : undefined}>
              {section.title && (
                <p className="px-3 pb-2 text-2xs font-semibold uppercase tracking-widest text-text-dim">
                  {section.title}
                </p>
              )}
              <div className="space-y-0.5">
                {section.items.map((item) => (
                  <NavLink
                    key={item.href}
                    item={item}
                    active={isActive(effectivePath, item.href)}
                    onNavigate={handleNavigate}
                  />
                ))}
                {section.title === "Intelligence Tools" && (
                  <>
                    <WeeklyNavGroup
                      activePath={effectivePath}
                      onNavigate={handleNavigate}
                    />
                    <LiveNavGroup
                      activePath={effectivePath}
                      onNavigate={handleNavigate}
                    />
                  </>
                )}
              </div>
            </div>
          ))}
        </nav>

        <div className="shrink-0 border-t border-border px-4 py-3">
          <div className="flex items-center justify-between">
            <span className="font-mono text-2xs text-text-dim">v2.0.0</span>
            <span className="rounded border border-accent-indigo/20 bg-accent-indigo/10 px-1.5 py-0.5 text-2xs font-medium text-accent-indigo/70">
              Beta
            </span>
          </div>
        </div>
      </aside>
    </>
  );
}
