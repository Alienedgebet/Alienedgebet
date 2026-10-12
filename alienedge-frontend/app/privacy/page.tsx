"use client";

import { PublicShell, Prose } from "@/components/public/PublicShell";

export default function PrivacyPage() {
  return (
    <PublicShell kicker="Legal" title="Privacy Policy">
      <Prose>
        <p className="text-xs text-text-dim">Last updated: 12 October 2026</p>

        <h2>1. What we collect</h2>
        <ul>
          <li><strong>Account data:</strong> your email address, password (stored only as a salted cryptographic hash) and account creation date.</li>
          <li><strong>Session data:</strong> an anonymous session cookie that keeps you signed in for up to 7 days.</li>
          <li><strong>Your settings:</strong> alert rules and notification preferences you choose to create.</li>
          <li><strong>Push subscriptions:</strong> browser notification endpoints, only if you opt in.</li>
          <li><strong>Operational logs:</strong> security rate-limit counters and server logs used to keep the service safe and reliable.</li>
        </ul>

        <h2>2. What we do NOT do</h2>
        <ul>
          <li>No selling, renting or sharing of personal data with advertisers — ever.</li>
          <li>No behavioural tracking or advertising cookies (see the{" "}
            <a href="/cookies">cookie notice</a>).</li>
          <li>No payment details — the platform does not process payments.</li>
        </ul>

        <h2>3. Why we process it</h2>
        <p>
          To run your account (login, password reset), deliver the alerts you asked for, keep the
          service secure (rate limiting, abuse prevention) and fix bugs. The legal basis is the
          performance of our contract with you and legitimate interests in running a safe service.
        </p>

        <h2>4. Football data and providers</h2>
        <p>
          Match data comes from licensed sports data providers. Engine outputs are derived
          statistics about public sporting events, not about you.
        </p>

        <h2>5. Retention</h2>
        <p>
          Account data lives while your account exists. If you ask us to delete your account, we
          delete your email, sessions, alert rules and push subscriptions, and keep only the
          minimum operational records required for security and legal obligations.
        </p>

        <h2>6. Security</h2>
        <p>
          Passwords are hashed with scrypt; sessions are opaque server-side tokens; all traffic is
          encrypted in transit (HTTPS); administrative access is restricted to the server itself.
          No system is perfectly secure, but we design every part of this one to resist misuse.
        </p>

        <h2>7. Your rights</h2>
        <p>
          You may request a copy of your personal data, correction of inaccuracies, or deletion of
          your account at any time by emailing <strong>Alienedgebet@gmail.com</strong> or messaging
          WhatsApp <strong>+234 916 804 1864</strong>.
        </p>

        <h2>8. Changes</h2>
        <p>
          If this policy changes materially, we will announce it in the app before it takes effect.
        </p>
      </Prose>
    </PublicShell>
  );
}
