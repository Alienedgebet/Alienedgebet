"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

export default function LoginPage() {
  const router = useRouter();
  const params = useSearchParams();
  const { setUser } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        credentials: "include", body: JSON.stringify({ email, password }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Unable to sign in.");
      setUser(data.user);
      router.replace(params.get("next") || "/dashboard");
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to sign in."); }
    finally { setBusy(false); }
  }

  return <AuthForm title="Sign in to AlienEdge" subtitle="Access your real prediction and live intelligence workspace." onSubmit={submit} busy={busy} error={error} email={email} password={password} setEmail={setEmail} setPassword={setPassword} footer={<><span>Need an account?</span> <Link href="/signup" className="text-accent-cyan hover:underline">Create one</Link></>} />;
}

function AuthForm({ title, subtitle, onSubmit, busy, error, email, password, setEmail, setPassword, footer }: {
  title: string; subtitle: string; onSubmit: (event: FormEvent<HTMLFormElement>) => void; busy: boolean; error: string; email: string; password: string; setEmail: (v: string) => void; setPassword: (v: string) => void; footer: React.ReactNode;
}) {
  return <main className="flex min-h-screen items-center justify-center bg-bg-primary px-4 py-10"><div className="w-full max-w-md rounded-2xl border border-border bg-bg-elevated/70 p-7 shadow-panel"><p className="mb-2 text-xs font-bold uppercase tracking-[0.25em] text-accent-cyan">AlienEdge</p><h1 className="text-2xl font-semibold text-text-primary">{title}</h1><p className="mt-2 text-sm text-text-secondary">{subtitle}</p><form className="mt-7 space-y-4" onSubmit={onSubmit}><label className="block text-xs text-text-secondary">Email<input required type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} className="mt-1 w-full rounded border border-border bg-bg-primary px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-cyan" /></label><label className="block text-xs text-text-secondary">Password<input required type="password" minLength={12} autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1 w-full rounded border border-border bg-bg-primary px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-cyan" /></label>{error && <p role="alert" className="rounded border border-red-500/30 bg-red-950/30 px-3 py-2 text-xs text-red-300">{error}</p>}<button disabled={busy} className="w-full rounded bg-accent-cyan px-3 py-2 text-sm font-semibold text-bg-primary disabled:opacity-50">{busy ? "Please wait…" : "Continue"}</button></form><div className="mt-5 flex justify-center gap-1 text-xs text-text-secondary">{footer}</div></div></main>;
}
