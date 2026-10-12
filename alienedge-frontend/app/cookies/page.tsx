"use client";

import { PublicShell, Prose } from "@/components/public/PublicShell";

export default function CookiesPage() {
  return (
    <PublicShell kicker="Legal" title="Cookie Notice">
      <Prose>
        <p className="text-xs text-text-dim">Last updated: 12 October 2026</p>

        <p>
          AlienEdge keeps cookie usage to the absolute minimum. There are no advertising cookies,
          no cross-site trackers, and no third-party analytics scripts on this platform.
        </p>

        <h2>Cookies we set</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm border border-white/10 rounded-lg overflow-hidden">
            <thead className="bg-[#0c1220] text-text-primary text-xs uppercase tracking-wider">
              <tr><th className="text-left p-3">Name</th><th className="text-left p-3">Purpose</th><th className="text-left p-3">Duration</th></tr>
            </thead>
            <tbody className="text-text-secondary">
              <tr className="border-t border-white/10">
                <td className="p-3 font-mono text-xs">alienedge_session</td>
                <td className="p-3">Keeps you signed in after login. Set only when you create an account or sign in; it is HttpOnly (no script can read it), Secure, and tied to your server-side session.</td>
                <td className="p-3">7 days</td>
              </tr>
            </tbody>
          </table>
        </div>

        <h2>Cookies we do NOT set</h2>
        <ul>
          <li>No advertising or remarketing cookies.</li>
          <li>No third-party analytics (no Google Analytics, no trackers).</li>
          <li>No social-media plugins.</li>
        </ul>

        <h2>Service workers</h2>
        <p>
          The app registers a small service worker so push notifications can reach you after you
          opt in on the Alerts page. It is part of the app, runs only with your permission, and
          does not track you.
        </p>

        <h2>Controlling cookies</h2>
        <p>
          The session cookie is required to stay signed in — if you block it, you will be asked to
          log in on every page visit. You can remove it at any time by signing out, or from your
          browser's site-data settings.
        </p>

        <h2>Questions</h2>
        <p>
          Email <strong>Alienedgebet@gmail.com</strong> or WhatsApp <strong>+234 916 804 1864</strong>.
        </p>
      </Prose>
    </PublicShell>
  );
}
