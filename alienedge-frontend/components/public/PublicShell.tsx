"use client";

import Link from "next/link";
import { ArrowLeft, LifeBuoy } from "lucide-react";

/**
 * Shared frame for every PUBLIC (pre-login) page: support, terms, privacy,
 * responsible gambling, cookies. Keeps one header, one footer, and one legal
 * link set so no public page can drift away from the others. Mobile-first.
 */
export function PublicShell({
  title,
  kicker,
  children,
}: {
  title: string;
  kicker: string;
  children: React.ReactNode;
}) {
  return (
    <main className="min-h-screen bg-bg-primary text-text-primary flex flex-col">
      <header className="border-b border-white/10 bg-[#0c1220]/90 backdrop-blur-md sticky top-0 z-20">
        <div className="mx-auto max-w-5xl px-4 sm:px-6 h-14 flex items-center justify-between gap-3">
          <Link href="/" className="flex items-center gap-2 font-black uppercase tracking-wider text-sm text-text-primary">
            <span className="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-accent-green/30 bg-accent-green/10">
              <LifeBuoy size={14} className="text-accent-green" />
            </span>
            AlienEdge
          </Link>
          <nav className="flex items-center gap-3 sm:gap-4 text-xs sm:text-sm">
            <Link href="/" className="text-text-secondary hover:text-text-primary inline-flex items-center gap-1">
              <ArrowLeft size={13} /> <span className="hidden sm:inline">Home</span>
            </Link>
            <Link href="/login" className="text-text-secondary hover:text-text-primary">Sign in</Link>
            <Link
              href="/signup"
              className="rounded-lg border border-accent-green/40 bg-accent-green/10 px-3 py-1.5 font-semibold text-accent-green hover:bg-accent-green/20"
            >
              Create account
            </Link>
          </nav>
        </div>
      </header>

      <div className="mx-auto w-full max-w-3xl px-4 sm:px-6 py-10 sm:py-14 flex-1">
        <p className="font-mono text-2xs uppercase tracking-widest text-accent-green mb-2">{kicker}</p>
        <h1 className="text-2xl sm:text-3xl font-black tracking-tight mb-6">{title}</h1>
        {children}
      </div>

      <footer className="border-t border-white/10 py-6 text-xs text-text-secondary">
        <div className="mx-auto max-w-5xl px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-3">
          <span>© {new Date().getFullYear()} AlienEdge — mathematical decision support.</span>
          <nav className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1">
            <Link href="/support" className="hover:text-text-primary">Support</Link>
            <Link href="/responsible-gambling" className="hover:text-text-primary">Responsible use</Link>
          </nav>
        </div>
      </footer>
    </main>
  );
}

/** Prose block used by every legal/content page — readable line length. */
export function Prose({ children }: { children: React.ReactNode }) {
  return (
    <div className="space-y-5 text-sm sm:text-base leading-relaxed text-text-secondary [&_h2]:mt-8 [&_h2]:mb-3 [&_h2]:text-base [&_h2]:font-bold [&_h2]:uppercase [&_h2]:tracking-wider [&_h2]:text-text-primary [&_strong]:text-text-primary [&_a]:text-accent-green [&_a]:underline [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:space-y-1">
      {children}
    </div>
  );
}
