"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, Eye, EyeOff, KeyRound, ShieldCheck } from "lucide-react";

export default function ResetPasswordPage() {
  const params = useSearchParams();
  const token = params.get("token") || "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (password !== confirm) {
      setError("The two passwords do not match.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/auth/reset-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        cache: "no-store",
        body: JSON.stringify({ token, password }),
      });
      const data = (await response.json().catch(() => null)) as { detail?: string } | null;
      if (!response.ok) throw new Error(data?.detail || "Unable to reset the password.");
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to reset the password.");
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
              <div className="auth-panel-icon"><KeyRound size={17} /></div>
              <div className="auth-panel-kicker"><span className="auth-kicker-dot" /> New credentials</div>
            </div>
            <div className="auth-panel-content">
              {done ? (
                <>
                  <p className="auth-panel-overline">All set</p>
                  <h2>Password updated</h2>
                  <p className="auth-panel-subtitle">
                    Your password has been changed and every other device was logged out.
                    Sign in with your new password.
                  </p>
                  <div className="auth-panel-footer">
                    <Link href="/login">Go to sign in<ArrowLeft size={13} /></Link>
                  </div>
                </>
              ) : !token ? (
                <>
                  <p className="auth-panel-overline">Missing link</p>
                  <h2>This page needs a reset link</h2>
                  <p className="auth-panel-subtitle">
                    Open the link from your reset email, or request a new one.
                  </p>
                  <div className="auth-panel-footer">
                    <Link href="/forgot-password">Request a reset link<ArrowLeft size={13} /></Link>
                  </div>
                </>
              ) : (
                <>
                  <p className="auth-panel-overline">Choose a new password</p>
                  <h2>Set your new password</h2>
                  <p className="auth-panel-subtitle">
                    At least 12 characters. After the reset, every other device is logged out.
                  </p>
                  <form className="auth-form" onSubmit={submit}>
                    <label className="auth-field">
                      <span className="auth-label">New password</span>
                      <span className="auth-input-shell">
                        <input
                          required
                          type={showPassword ? "text" : "password"}
                          value={password}
                          minLength={12}
                          autoComplete="new-password"
                          onChange={(event) => setPassword(event.target.value)}
                        />
                        <button
                          className="auth-password-toggle"
                          type="button"
                          onClick={() => setShowPassword((value) => !value)}
                          aria-label={showPassword ? "Hide password" : "Show password"}
                        >
                          {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                        </button>
                      </span>
                    </label>
                    <label className="auth-field">
                      <span className="auth-label">Confirm new password</span>
                      <span className="auth-input-shell">
                        <input
                          required
                          type={showPassword ? "text" : "password"}
                          value={confirm}
                          minLength={12}
                          autoComplete="new-password"
                          onChange={(event) => setConfirm(event.target.value)}
                        />
                      </span>
                    </label>
                    {error && <p className="auth-error" role="alert">{error}</p>}
                    <button className="auth-submit" type="submit" disabled={busy}>
                      <span>{busy ? "Updating…" : "Set new password"}</span>
                      {busy ? <span className="auth-submit-loader" aria-hidden="true" /> : <ShieldCheck size={17} aria-hidden="true" />}
                    </button>
                  </form>
                  <div className="auth-panel-footer">
                    <span>Link expired?</span>
                    <Link href="/forgot-password">Request a new one<ArrowLeft size={13} /></Link>
                  </div>
                </>
              )}
            </div>
            <div className="auth-panel-footnote">
              <ShieldCheck size={13} /> The link works once and expires after 1 hour.
            </div>
          </div>
        </section>
      </div>
      <footer className="auth-footer"><span>© {new Date().getFullYear()} AlienEdge</span><span>Built for the serious analyst</span></footer>
    </main>
  );
}
