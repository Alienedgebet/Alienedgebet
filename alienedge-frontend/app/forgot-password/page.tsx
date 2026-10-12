"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { ArrowLeft, LockKeyhole, MailCheck } from "lucide-react";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/auth/forgot-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        cache: "no-store",
        body: JSON.stringify({ email }),
      });
      const data = (await response.json().catch(() => null)) as { detail?: string } | null;
      if (!response.ok) throw new Error(data?.detail || "Unable to send the reset link.");
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to send the reset link.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-page">
      <div className="auth-aurora auth-aurora-one" aria-hidden="true" />
      <div className="auth-aurora auth-aurora-two" aria-hidden="true" />
      <div className="auth-grid-overlay" aria-hidden="true" />
      <div className="auth-scanline" aria-hidden="true" />
      <header className="auth-topbar">
        <Link href="/" className="auth-brand" aria-label="AlienEdge home">
          <span className="auth-brand-mark" aria-hidden="true"><span /></span>
          <span>ALIENEDGE</span>
        </Link>
      </header>
      <div className="auth-layout">
        <section className="auth-panel-wrap">
          <div className="auth-panel">
            <div className="auth-panel-edge" aria-hidden="true" />
            <div className="auth-panel-header">
              <div className="auth-panel-icon"><LockKeyhole size={17} /></div>
              <div className="auth-panel-kicker"><span className="auth-kicker-dot" /> Account recovery</div>
            </div>
            <div className="auth-panel-content">
              {sent ? (
                <>
                  <p className="auth-panel-overline">Check your inbox</p>
                  <h2>Reset link sent</h2>
                  <p className="auth-panel-subtitle">
                    If an account exists for <strong>{email}</strong>, a reset link is on its way.
                    The link is valid for 1 hour and can be used once.
                  </p>
                  <p className="auth-panel-subtitle" style={{ marginTop: 10 }}>
                    Did not get it? Check spam, or wait a minute and try again — then contact support
                    if it still does not arrive.
                  </p>
                  <div className="auth-panel-footer">
                    <span>Remembered it?</span>
                    <Link href="/login">Back to sign in<ArrowLeft size={13} /></Link>
                  </div>
                </>
              ) : (
                <>
                  <p className="auth-panel-overline">Password recovery</p>
                  <h2>Reset your password</h2>
                  <p className="auth-panel-subtitle">
                    Enter the email you signed up with. We will send a link to choose a new password.
                  </p>
                  <form className="auth-form" onSubmit={submit}>
                    <label className="auth-field">
                      <span className="auth-label">Email address</span>
                      <span className="auth-input-shell">
                        <input
                          required
                          type="email"
                          value={email}
                          autoComplete="email"
                          onChange={(event) => setEmail(event.target.value)}
                        />
                      </span>
                    </label>
                    {error && <p className="auth-error" role="alert">{error}</p>}
                    <button className="auth-submit" type="submit" disabled={busy}>
                      <span>{busy ? "Sending…" : "Send reset link"}</span>
                      {busy ? <span className="auth-submit-loader" aria-hidden="true" /> : <MailCheck size={17} aria-hidden="true" />}
                    </button>
                  </form>
                  <div className="auth-panel-footer">
                    <span>Remembered it?</span>
                    <Link href="/login">Back to sign in<ArrowLeft size={13} /></Link>
                  </div>
                </>
              )}
            </div>
            <div className="auth-panel-footnote">
              <LockKeyhole size={13} /> Reset links are single-use and expire after 1 hour.
            </div>
          </div>
        </section>
      </div>
      <footer className="auth-footer"><span>© {new Date().getFullYear()} AlienEdge</span><span>Built for the serious analyst</span></footer>
    </main>
  );
}
