"use client";

import { AlertTriangle, CalendarCheck, CircleDollarSign, HeartHandshake } from "lucide-react";
import { PublicShell, Prose } from "@/components/public/PublicShell";

export default function ResponsibleGamblingPage() {
  return (
    <PublicShell kicker="Responsible use" title="Use AlienEdge responsibly">
      <div className="mb-8 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 flex items-start gap-3">
        <AlertTriangle size={18} className="text-amber-300 mt-0.5 shrink-0" />
        <p className="text-sm text-amber-100/90">
          <strong>18+ only.</strong> AlienEdge is analytical decision support — it is not a
          bookmaker and does not take bets. No prediction is a guarantee; you can lose money when
          you gamble. Never stake more than you can afford to lose.
        </p>
      </div>

      <Prose>
        <h2>What this platform is (and is not)</h2>
        <p>
          We publish model probabilities, edges and rankings so you can make <em>informed</em>
          decisions. We do not encourage betting, we do not promise profit, and we do not hide
          behind hype: experimental models carry a visible badge until they are proven against
          settled results.
        </p>

        <h2>Warning signs to take seriously</h2>
        <ul>
          <li>Chasing losses with bigger stakes.</li>
          <li>Spending more time or money than you intended — again and again.</li>
          <li>Hiding your activity from people close to you, or borrowing to keep going.</li>
          <li>Feeling restless, anxious or irritable when not betting.</li>
        </ul>

        <h2>Practical safeguards</h2>
        <ul>
          <li><strong>Set a fixed budget</strong> before you start — a weekly limit you treat as spent.</li>
          <li><strong>Take breaks.</strong> The daily pipeline refreshes at night; you do not need to check every hour.</li>
          <li><strong>Never bet under the influence</strong> of alcohol, emotion or desperation.</li>
          <li><strong>Treat every model as fallible.</strong> Even a 70% probability fails 3 times in 10.</li>
        </ul>

        <h2>Get help</h2>
        <p>
          If gambling is no longer under your control, stop and talk to someone. Free, confidential
          support is available in most countries through local problem-gambling helplines and
          organisations such as Gamblers Anonymous. Search for your country's helpline, or contact
          us and we will help you find one.
        </p>
        <p>
          You can also ask us to <strong>close your AlienEdge account</strong> at any time — email{" "}
          <strong>Alienedgebet@gmail.com</strong> or WhatsApp <strong>+234 916 804 1864</strong>.
          We will do it without argument.
        </p>
      </Prose>

      <div className="mt-8 grid sm:grid-cols-3 gap-3">
        {[
          { icon: CalendarCheck, t: "Set limits", d: "Time and money — written down before you play." },
          { icon: CircleDollarSign, t: "Never chase", d: "Losses recovered with bigger stakes are how it spirals." },
          { icon: HeartHandshake, t: "Ask early", d: "Talking to someone is a strength, not a weakness." },
        ].map(({ icon: Icon, t, d }) => (
          <div key={t} className="rounded-xl border border-white/10 bg-[#0c1220]/90 p-4">
            <Icon size={16} className="text-accent-green mb-2" />
            <p className="text-sm font-semibold text-text-primary">{t}</p>
            <p className="text-xs text-text-secondary mt-1">{d}</p>
          </div>
        ))}
      </div>
    </PublicShell>
  );
}
