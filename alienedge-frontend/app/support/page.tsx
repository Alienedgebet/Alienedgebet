"use client";

import Link from "next/link";
import { Mail, MessageCircle, Clock, ShieldQuestion } from "lucide-react";
import { PublicShell, Prose } from "@/components/public/PublicShell";

const SUPPORT_EMAIL = "Alienedgebet@gmail.com";
const WHATSAPP_DISPLAY = "+234 916 804 1864";
const WHATSAPP_LINK = "https://wa.me/2349168041864";

const FAQ = [
  {
    q: "What is AlienEdge?",
    a: "A mathematical football intelligence platform — a private workspace that runs a family of prediction engines (Win, Corners, GG, Over/Under markets, DNA profiles and a 24/7 live forensics scanner) and visualises their output. It is decision support for serious analysis, not a bookmaker, wallet or betting service.",
  },
  {
    q: "How often is the data refreshed?",
    a: "Every night at 00:00 a pipeline runs all engines for the next day's fixtures, including a 7-day Weekly board. A safety net at 06:00 re-runs anything that failed overnight, so you wake up to fresh, complete data. Live pages update continuously while matches are in play.",
  },
  {
    q: "What does the amber EXPERIMENTAL badge mean?",
    a: "Experimental engines (currently Win Forecast v2) publish alongside the production engines but are explicitly marked: their probabilities are not yet calibrated against settled results and their thresholds are unvalidated starting defaults. The badge travels with every row so nothing experimental can be mistaken for a proven signal.",
  },
  {
    q: "Is this betting advice?",
    a: "No. AlienEdge presents model probabilities, edges and market comparisons as analytical information. You decide what to do with it. No outcome is guaranteed — see our responsible-use policy.",
  },
  {
    q: "I forgot my password — what do I do?",
    a: "Use the Forgot your password? link on the sign-in page. The reset link is valid for one hour and can only be used once. If it does not arrive (or you need it delivered another way), contact us through the channels below and we will send it to you.",
  },
  {
    q: "How do I turn on push notifications for alerts?",
    a: "Open the Alerts page while signed in and allow notifications when prompted. You can also disable them again from the same page at any time.",
  },
  {
    q: "I found a bug or a wrong number — how do I report it?",
    a: "Email or WhatsApp us with the date, the market/page, and the fixture if relevant. Include a screenshot when you can — it makes the fix much faster.",
  },
];

export default function SupportPage() {
  return (
    <PublicShell kicker="Support" title="Contact us & common questions">
      <div className="grid sm:grid-cols-2 gap-4 mb-10">
        <a
          href={`mailto:${SUPPORT_EMAIL}`}
          className="glass rounded-xl border border-white/10 bg-[#0c1220]/90 p-5 flex items-start gap-3 hover:border-accent-green/40 transition-colors"
        >
          <span className="mt-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-accent-green/30 bg-accent-green/10">
            <Mail size={16} className="text-accent-green" />
          </span>
          <span>
            <span className="block font-semibold text-text-primary">Email</span>
            <span className="block text-sm text-accent-green break-all">{SUPPORT_EMAIL}</span>
            <span className="mt-1 block text-xs text-text-dim">Best for account issues, bug reports and attachments.</span>
          </span>
        </a>
        <a
          href={WHATSAPP_LINK}
          target="_blank"
          rel="noopener noreferrer"
          className="glass rounded-xl border border-white/10 bg-[#0c1220]/90 p-5 flex items-start gap-3 hover:border-accent-green/40 transition-colors"
        >
          <span className="mt-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-accent-green/30 bg-accent-green/10">
            <MessageCircle size={16} className="text-accent-green" />
          </span>
          <span>
            <span className="block font-semibold text-text-primary">WhatsApp</span>
            <span className="block text-sm text-accent-green">{WHATSAPP_DISPLAY}</span>
            <span className="mt-1 block text-xs text-text-dim">Fastest replies for quick questions and password resets.</span>
          </span>
        </a>
      </div>

      <div className="flex items-center gap-2 text-xs text-text-dim mb-8">
        <Clock size={13} /> <span>Replies within a day, usually much sooner — West Africa Time (WAT).</span>
      </div>

      <h2 className="flex items-center gap-2 text-base font-bold uppercase tracking-wider text-text-primary mb-4">
        <ShieldQuestion size={17} className="text-accent-green" /> Frequently asked
      </h2>
      <div className="space-y-3">
        {FAQ.map((item) => (
          <details
            key={item.q}
            className="group rounded-xl border border-white/10 bg-[#0c1220]/90 px-4 py-3 open:border-accent-green/30"
          >
            <summary className="cursor-pointer list-none flex items-center justify-between gap-3 text-sm font-semibold text-text-primary">
              {item.q}
              <span className="text-accent-green text-lg leading-none transition-transform group-open:rotate-45">+</span>
            </summary>
            <Prose>
              <p className="pt-3 text-text-secondary">{item.a}</p>
            </Prose>
          </details>
        ))}
      </div>

      <div className="mt-10 rounded-xl border border-white/10 bg-[#0c1220]/60 p-4 text-xs text-text-dim">
        Need your account password reset? Use{" "}
        <Link href="/forgot-password" className="text-accent-green underline">Forgot your password?</Link>{" "}
        — or message us on WhatsApp and we will send you a fresh link.
      </div>
    </PublicShell>
  );
}
