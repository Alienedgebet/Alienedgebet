"use client";

import { PublicShell, Prose } from "@/components/public/PublicShell";

export default function TermsPage() {
  return (
    <PublicShell kicker="Legal" title="Terms of Service">
      <Prose>
        <p className="text-xs text-text-dim">Last updated: 12 October 2026</p>

        <h2>1. What AlienEdge is</h2>
        <p>
          AlienEdge is a <strong>mathematical decision-support platform</strong>. It runs statistical
          models over football data and displays the results — probabilities, edges, rankings and
          live match forensics. AlienEdge is <strong>not</strong> a bookmaker, casino, wallet,
          payment service or financial product, and it does not accept or place bets on your behalf.
        </p>

        <h2>2. Accounts</h2>
        <ul>
          <li>You must be at least 18 years old to use AlienEdge.</li>
          <li>You must provide a real email address and keep your password confidential.</li>
          <li>You are responsible for everything that happens under your account.</li>
          <li>One person per account; do not share credentials or resell access.</li>
        </ul>

        <h2>3. Acceptable use</h2>
        <ul>
          <li>Do not attempt to probe, scrape, overload or bypass the service.</li>
          <li>Do not reverse-engineer or republish engine output as a competing service.</li>
          <li>Do not use the platform for any unlawful purpose.</li>
          <li>Automated access is only permitted through interfaces we publish.</li>
        </ul>

        <h2>4. No advice, no guarantees</h2>
        <p>
          Everything AlienEdge displays is a <strong>model output based on historical data</strong>.
          Football is uncertain; past performance never guarantees future results. Nothing on this
          platform is financial, betting or any other professional advice. You make your own
          decisions and accept your own outcomes.
        </p>

        <h2>5. Data and availability</h2>
        <p>
          We strive for complete, accurate and timely data, but third-party data feeds can be
          delayed, corrected or unavailable. Engines may be paused, re-run or removed while we
          improve them. Experimental features are clearly labelled as such.
        </p>

        <h2>6. Intellectual property</h2>
        <p>
          The platform, its design, engines and text are owned by AlienEdge. Your account gives you
          a personal, non-transferable licence to use the service. You may not redistribute
          substantial portions of the output.
        </p>

        <h2>7. Suspension and termination</h2>
        <p>
          We may suspend or close accounts that break these terms, put the service at risk, or abuse
          support channels. You may close your account at any time by contacting support.
        </p>

        <h2>8. Limitation of liability</h2>
        <p>
          To the maximum extent permitted by law, AlienEdge is provided "as is" without warranties
          of any kind, and we are not liable for losses arising from use of, or inability to use,
          the platform or any decision made on the basis of its output.
        </p>

        <h2>9. Changes</h2>
        <p>
          We may update these terms as the product evolves. Continued use after an update means you
          accept the revised terms. Material changes will be announced in the app.
        </p>

        <h2>10. Contact</h2>
        <p>
          Questions about these terms: <strong>Alienedgebet@gmail.com</strong> or WhatsApp{" "}
          <strong>+234 916 804 1864</strong>.
        </p>
      </Prose>
    </PublicShell>
  );
}
