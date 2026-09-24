"use client";

import { FormEvent, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AuthShell } from "@/components/auth/AuthShell";
import { useAuth, type AuthUser } from "@/lib/auth-context";

const LOGIN_TIMEOUT_MS = 8_000;

function isAuthUser(value: unknown): value is AuthUser {
  if (!value || typeof value !== "object") return false;
  const user = value as Record<string, unknown>;
  return (
    typeof user.user_id === "string" &&
    user.user_id.length > 0 &&
    typeof user.email === "string" &&
    user.email.length > 0
  );
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    error.name === "AbortError"
  );
}

function safeDestination(value: string | null): string {
  return value && value.startsWith("/") && !value.startsWith("//")
    ? value
    : "/dashboard";
}

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
    setBusy(true);
    setError("");

    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), LOGIN_TIMEOUT_MS);

    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        cache: "no-store",
        signal: controller.signal,
        body: JSON.stringify({ email, password }),
      });
      const data = (await response.json().catch(() => null)) as {
        detail?: string;
        user?: unknown;
      } | null;
      if (!response.ok) throw new Error(data?.detail || "Unable to sign in.");
      if (!data || !isAuthUser(data.user)) {
        throw new Error("The sign-in response did not include a valid session. Please try again.");
      }
      setUser(data.user);
      router.replace(safeDestination(params.get("next")));
    } catch (err) {
      setError(
        isAbortError(err)
          ? "Sign-in took too long. Check your connection and try again."
          : err instanceof Error
            ? err.message
            : "Unable to sign in.",
      );
    } finally {
      window.clearTimeout(timeout);
      setBusy(false);
    }
  }

  return <AuthShell mode="login" title="Sign in to AlienEdge" subtitle="Access your private prediction and live intelligence workspace." email={email} password={password} busy={busy} error={error} onSubmit={submit} setEmail={setEmail} setPassword={setPassword} />;
}
