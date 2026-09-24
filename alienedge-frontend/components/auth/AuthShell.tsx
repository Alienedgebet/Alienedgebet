"use client";

import type { FormEvent } from "react";
import Image, { type ImageLoader } from "next/image";
import { useState } from "react";
import Link from "next/link";
import { Activity, ArrowRight, Check, Eye, EyeOff, LockKeyhole, Radio, ShieldCheck, Sparkles } from "lucide-react";

const authAlienImageLoader: ImageLoader = ({ width }) =>
  width <= 640 ? "/hero-alien-mascot-login-v1-540.webp" : "/hero-alien-mascot-login-v1-1024.webp";

type Props = { mode: "login" | "signup"; title: string; subtitle: string; email: string; password: string; confirm?: string; busy: boolean; error: string; onSubmit: (e: FormEvent<HTMLFormElement>) => void; setEmail: (v: string) => void; setPassword: (v: string) => void; setConfirm?: (v: string) => void };

export function AuthShell({ mode, title, subtitle, email, password, confirm = "", busy, error, onSubmit, setEmail, setPassword, setConfirm }: Props) {
  const [showPassword, setShowPassword] = useState(false);
  const signup = mode === "signup";
  return <main className="auth-page">
    <div className="auth-aurora auth-aurora-one" aria-hidden="true" /><div className="auth-aurora auth-aurora-two" aria-hidden="true" /><div className="auth-grid-overlay" aria-hidden="true" /><div className="auth-scanline" aria-hidden="true" />
    <header className="auth-topbar"><Link href="/" className="auth-brand" aria-label="AlienEdge home"><span className="auth-brand-mark" aria-hidden="true"><span /></span><span>ALIENEDGE</span></Link><div className="auth-topbar-meta"><span className="auth-secure-label"><ShieldCheck size={13} /> Private access</span><span className="auth-divider" /><span className="auth-system-status"><i /> Systems nominal</span></div></header>
    <div className="auth-layout"><section className="auth-hero" aria-label="AlienEdge intelligence">
      <div className="auth-hero-copy"><div className="auth-eyebrow"><span className="auth-eyebrow-line" /> Private football intelligence</div><h1>See the signal<br /><em>before it moves.</em></h1><p className="auth-hero-description">A private workspace for sharper match analysis, live intelligence, and the thinking behind every edge.</p><div className="auth-feature-list" aria-label="AlienEdge capabilities"><div className="auth-feature"><span className="auth-feature-icon"><Activity size={15} /></span><span><strong>Live analysis</strong><small>Signals that keep pace with the game</small></span></div><div className="auth-feature"><span className="auth-feature-icon"><Sparkles size={15} /></span><span><strong>Model transparency</strong><small>Clarity behind every prediction</small></span></div></div></div>
      <div className="auth-visual" aria-hidden="true"><div className="auth-orbit auth-orbit-outer" /><div className="auth-orbit auth-orbit-middle" /><div className="auth-orbit auth-orbit-inner" /><div className="auth-visual-glow" /><Image className="auth-mascot" loader={authAlienImageLoader} src="/hero-alien-mascot-login-v1-1024.webp" sizes="(max-width: 800px) 78vw, (max-width: 1100px) 49vw, 34vw" alt="" fill fetchPriority="high" decoding="async" /><div className="auth-visual-label auth-visual-label-top"><span>AE</span> CORE / 01</div><div className="auth-visual-label auth-visual-label-bottom"><Radio size={12} /> SIGNAL ONLINE</div></div>
      <div className="auth-hero-footer"><span><i className="auth-live-dot" /> Intelligence feed active</span><span className="auth-hero-footer-code">AE—INTELLIGENCE / 2026</span></div>
    </section>
    <section className="auth-panel-wrap"><div className="auth-panel"><div className="auth-panel-edge" aria-hidden="true" /><div className="auth-panel-header"><div className="auth-panel-icon"><LockKeyhole size={17} /></div><div className="auth-panel-kicker"><span className="auth-kicker-dot" /> Secure workspace</div></div><div className="auth-panel-content"><p className="auth-panel-overline">{signup ? "Initialize access" : "Welcome back"}</p><h2>{title}</h2><p className="auth-panel-subtitle">{subtitle}</p><form className="auth-form" onSubmit={onSubmit}><AuthField label="Email address" type="email" value={email} autoComplete="email" onChange={setEmail} /><AuthField label="Password" type={showPassword ? "text" : "password"} value={password} autoComplete={signup ? "new-password" : "current-password"} minLength={signup ? 12 : undefined} onChange={setPassword} onTogglePassword={() => setShowPassword((value) => !value)} showPassword={showPassword} />{signup && <AuthField label="Confirm password" type="password" value={confirm} autoComplete="new-password" minLength={12} onChange={setConfirm ?? (() => undefined)} />}{error && <p className="auth-error" role="alert">{error}</p>}<button className="auth-submit" type="submit" disabled={busy}><span>{busy ? "Securing your session…" : signup ? "Create private access" : "Enter workspace"}</span>{busy ? <span className="auth-submit-loader" aria-hidden="true" /> : <ArrowRight size={17} aria-hidden="true" />}</button></form><div className="auth-panel-rule"><span>Protected by secure session controls</span></div><div className="auth-panel-footer"><span>{signup ? "Already have access?" : "New to the network?"}</span><Link href={signup ? "/login" : "/signup"}>{signup ? "Sign in" : "Create an account"}<ArrowRight size={13} /></Link></div></div><div className="auth-panel-footnote"><Check size={13} /> No prediction logic is exposed to this screen.</div></div></section></div>
    <footer className="auth-footer"><span>© {new Date().getFullYear()} AlienEdge</span><span>Built for the serious analyst</span></footer>
  </main>;
}

function AuthField({ label, type, value, autoComplete, minLength, onChange, onTogglePassword, showPassword }: { label: string; type: "email" | "password" | "text"; value: string; autoComplete: string; minLength?: number; onChange: (v: string) => void; onTogglePassword?: () => void; showPassword?: boolean }) {
  return <label className="auth-field"><span className="auth-label">{label}</span><span className="auth-input-shell"><input required type={type} value={value} minLength={minLength} autoComplete={autoComplete} onChange={(event) => onChange(event.target.value)} />{onTogglePassword && <button className="auth-password-toggle" type="button" onClick={onTogglePassword} aria-label={showPassword ? "Hide password" : "Show password"}>{showPassword ? <EyeOff size={16} /> : <Eye size={16} />}</button>}</span></label>;
}
