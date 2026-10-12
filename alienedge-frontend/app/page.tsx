"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Activity, ArrowRight, BarChart3, BrainCircuit, CalendarRange, Dna,
  Gauge, Radar, ShieldCheck, Sparkles, Target,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";

/**
 * Public landing page — the product's front door.
 * Logged-in users keep the old behaviour (straight to /dashboard);
 * visitors see what AlienEdge is before being asked to sign in.
 */

const ENGINES = [
  { icon: Target, name: "Win Forecast", desc: "Poisson win probabilities with venue and H2H breakdown, plus a ranked apex board." },
  { icon: BrainCircuit, name: "DNA Profiles", desc: "Team-level tactical DNA — goal intent, win dominance, BTTS friction, corner power." },
  { icon: BarChart3, name: "Goals Markets", desc: "Over 1.5 / Over 2.5 / Unders / GG chains with multi-stage audits." },
  { icon: Sparkles, name: "Corners & Specials", desc: "Corner empire, SOT, FHVI, SHVI and specialist engines." },
  { icon: Radar, name: "Live Forensics", desc: "24/7 live scanner with alerts while matches are in play." },
  { icon: CalendarRange, name: "Weekly Board", desc: "A rolling 7-day window refreshed nightly alongside tomorrow's picks." },
];

const STEPS = [
  { n: "00:00", t: "The nightly pipeline runs", d: "Every engine recomputes tomorrow's fixtures from scratch — history, odds, league priors." },
  { n: "02:00", t: "Results are archived", d: "Finished matches settle so every pick keeps a permanent WON/LOST record." },
  { n: "06:00", t: "Safety net re-checks", d: "Anything that failed or degraded overnight is re-run before you wake up." },
  { n: "All day", t: "Live while it happens", d: "The live scanner tracks in-play matches and pushes alerts you configure." },
];

export default function Home() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && user) router.replace("/dashboard");
  }, [loading, user, router]);

  if (loading || user) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-bg-primary text-sm text-text-secondary">
        Loading AlienEdge…
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-bg-primary text-text-primary">
      {/* ── Header ── */}
      <header className="sticky top-0 z-20 border-b border-white/10 bg-[#0c1220]/90 backdrop-blur-md">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 h-14 flex items-center justify-between gap-3">
          <span className="flex items-center gap-2 font-black uppercase tracking-wider text-sm">
            <span className="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-accent-green/30 bg-accent-green/10">
              <Activity size={14} className="text-accent-green" />
            </span>
            AlienEdge
          </span>
          <nav className="flex items-center gap-3 sm:gap-4 text-sm">
            <Link href="/support" className="hidden sm:inline text-text-secondary hover:text-text-primary">Support</Link>
            <Link href="/login" className="text-text-secondary hover:text-text-primary">Sign in</Link>
            <Link href="/signup" className="rounded-lg border border-accent-green/40 bg-accent-green/10 px-3 py-1.5 font-semibold text-accent-green hover:bg-accent-green/20">
              Create account
            </Link>
          </nav>
        </div>
      </header>

      {/* ── Hero ── */}
      <section className="relative overflow-hidden">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_50%_at_50%_0%,rgba(16,185,129,0.12),transparent_70%)]" />
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16 sm:py-24 relative">
          <p className="font-mono text-2xs sm:text-xs uppercase tracking-[0.25em] text-accent-green mb-4">
            Institutional-grade football intelligence
          </p>
          <h1 className="text-3xl sm:text-5xl font-black tracking-tight leading-[1.1] max-w-3xl">
            See the signal <span className="text-accent-green">before it moves.</span>
          </h1>
          <p className="mt-5 max-w-2xl text-sm sm:text-base text-text-secondary leading-relaxed">
            A private workspace of prediction engines, tactical DNA and live match forensics —
            rebuilt from scratch every night, verified every morning, and honest about what is
            proven versus experimental.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link
              href="/signup"
              className="inline-flex items-center gap-2 rounded-xl bg-accent-green px-5 py-3 font-bold text-black hover:brightness-110 transition"
            >
              Create your account <ArrowRight size={16} />
            </Link>
            <Link
              href="/login"
              className="inline-flex items-center gap-2 rounded-xl border border-white/15 px-5 py-3 font-semibold text-text-secondary hover:text-text-primary hover:border-white/30 transition"
            >
              Sign in
            </Link>
          </div>
          <p className="mt-4 flex items-center gap-2 text-xs text-text-dim">
            <ShieldCheck size={13} className="text-accent-green" /> Private sessions, no advertising trackers, 18+.
          </p>
        </div>
      </section>

      {/* ── Engines grid ── */}
      <section className="mx-auto max-w-6xl px-4 sm:px-6 pb-14">
        <h2 className="text-xs font-bold uppercase tracking-[0.2em] text-text-dim mb-5">The engine family</h2>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {ENGINES.map(({ icon: Icon, name, desc }) => (
            <div key={name} className="glass rounded-xl border border-white/10 bg-[#0c1220]/90 p-5 hover:border-accent-green/30 transition-colors">
              <div className="flex items-center gap-2 mb-2">
                <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-accent-green/30 bg-accent-green/10">
                  <Icon size={15} className="text-accent-green" />
                </span>
                <span className="font-bold text-sm">{name}</span>
              </div>
              <p className="text-xs sm:text-sm text-text-secondary leading-relaxed">{desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── How it works ── */}
      <section className="mx-auto max-w-6xl px-4 sm:px-6 pb-14">
        <h2 className="text-xs font-bold uppercase tracking-[0.2em] text-text-dim mb-5">Fresh data, every morning</h2>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {STEPS.map(({ n, t, d }) => (
            <div key={n} className="rounded-xl border border-white/10 bg-[#0c1220]/60 p-5">
              <p className="font-mono text-accent-green text-xs mb-2">{n}</p>
              <p className="font-bold text-sm mb-1">{t}</p>
              <p className="text-xs text-text-secondary leading-relaxed">{d}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Honesty note ── */}
      <section className="mx-auto max-w-6xl px-4 sm:px-6 pb-16">
        <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-5 flex items-start gap-3">
          <Gauge size={18} className="text-amber-300 mt-0.5 shrink-0" />
          <div className="text-sm text-amber-100/90">
            <p className="font-semibold mb-1">Transparency by design</p>
            <p className="text-xs sm:text-sm leading-relaxed">
              Models that are still being validated carry a visible <strong>EXPERIMENTAL</strong>{" "}
              badge on every row, and each prediction records the exact model and calibration version
              that produced it. You always know what you are looking at.
            </p>
          </div>
        </div>
      </section>

      {/* ── CTA ── */}
      <section className="border-t border-white/10 bg-[#0c1220]/70">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-12 text-center">
          <h2 className="text-xl sm:text-2xl font-black">Ready to see tomorrow&apos;s board?</h2>
          <p className="mt-2 text-sm text-text-secondary">Create an account — it takes seconds.</p>
          <Link href="/signup" className="mt-5 inline-flex items-center gap-2 rounded-xl bg-accent-green px-6 py-3 font-bold text-black hover:brightness-110 transition">
            Create account <ArrowRight size={16} />
          </Link>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="border-t border-white/10 py-6 text-xs text-text-secondary">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-3">
          <span className="flex items-center gap-2"><Dna size={13} className="text-accent-green" /> © {new Date().getFullYear()} AlienEdge — decision support, not betting advice.</span>
          <nav className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1">
            <Link href="/support" className="hover:text-text-primary">Support</Link>
            <Link href="/terms" className="hover:text-text-primary">Terms</Link>
            <Link href="/privacy" className="hover:text-text-primary">Privacy</Link>
            <Link href="/responsible-gambling" className="hover:text-text-primary">Responsible use</Link>
            <Link href="/cookies" className="hover:text-text-primary">Cookies</Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}
