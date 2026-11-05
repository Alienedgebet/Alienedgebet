"use client";

import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

interface ChainSectionProps {
  title: string;
  count?: number;
  description?: string;
  /** Sections default to expanded — chain stages must never be hidden by default. */
  defaultOpen?: boolean;
  children: ReactNode;
}

/**
 * Accordion shell for one engine stage.
 * Height/opacity Framer animations were removed — animating height:auto across
 * several large tables on mount was a major source of click-to-freeze lag.
 */
export function ChainSection({
  title,
  count,
  description,
  defaultOpen = true,
  children,
}: ChainSectionProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <section
      className={cn(
        "glass relative overflow-hidden rounded-lg shadow-panel transition-shadow duration-200",
        open && "shadow-glow"
      )}
    >
      <div
        aria-hidden
        className={cn(
          "absolute inset-x-0 top-0 h-px bg-gradient-ae-blue transition-opacity duration-200",
          open ? "opacity-100" : "opacity-0"
        )}
      />

      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors hover:bg-bg-elevated/30"
      >
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="truncate text-sm font-semibold text-text-primary">{title}</span>
          {typeof count === "number" && (
            <span className="shrink-0 rounded border border-border-bright bg-bg-elevated px-1.5 py-0.5 font-mono text-2xs text-text-muted">
              {count}
            </span>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-3">
          {description && (
            <span className="hidden text-2xs text-text-dim sm:block">{description}</span>
          )}
          <ChevronDown
            className={cn(
              "h-4 w-4 text-text-muted transition-transform duration-150",
              open && "rotate-180"
            )}
          />
        </div>
      </button>

      {open && <div className="border-t border-border p-3">{children}</div>}
    </section>
  );
}
