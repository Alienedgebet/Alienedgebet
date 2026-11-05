"use client";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

export interface AuthUser {
  user_id: string;
  email: string;
  created_at?: number;
}

const SESSION_CHECK_TIMEOUT_MS = 3_000;

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUserState] = useState<AuthUser | null>(null);
  const userRef = useRef<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timeout = window.setTimeout(
      () => controller.abort(),
      SESSION_CHECK_TIMEOUT_MS,
    );

    fetch("/api/auth/me", {
      credentials: "include",
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (response) => {
        // A 401 is the only definitive signed-out response. Other failures are
        // transient session-check failures and must not destroy the current
        // session or redirect a logged-in user to the login page.
        if (response.status === 401) return null;
        if (!response.ok) {
          throw new Error(
            response.status === 503
              ? "The session service is temporarily unavailable."
              : "Unable to verify your session right now.",
          );
        }
        return (await response.json()) as { user?: AuthUser };
      })
      .then((result) => {
        if (!active) return;
        // A login can complete while the initial session check is still in
        // flight. Never let that older 401 response erase the fresh user.
        if (userRef.current) {
          setSessionError(null);
          return;
        }
        userRef.current = result?.user ?? null;
        setUserState(userRef.current);
        setSessionError(null);
      })
      .catch((error: unknown) => {
        if (!active) return;
        setSessionError(
          error instanceof Error
            ? error.message
            : "Unable to verify your session right now.",
        );
      })
      .finally(() => {
        window.clearTimeout(timeout);
        if (active) setLoading(false);
      });

    return () => {
      active = false;
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [retryToken]);

  const setUser = useCallback((nextUser: AuthUser | null) => {
    userRef.current = nextUser;
    setUserState(nextUser);
    if (nextUser) setSessionError(null);
  }, []);

  const retrySession = useCallback(() => {
    setSessionError(null);
    setLoading(true);
    setRetryToken((token) => token + 1);
  }, []);

  async function logout() {
    try {
      await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
    } finally {
      userRef.current = null;
      setUserState(null);
      setSessionError(null);
    }
  }

  return (
    <AuthContext.Provider
      value={{ user, loading, sessionError, setUser, retrySession, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

const AuthContext = React.createContext<{
  user: AuthUser | null;
  loading: boolean;
  sessionError: string | null;
  setUser: (user: AuthUser | null) => void;
  retrySession: () => void;
  logout: () => Promise<void>;
}>({
  user: null,
  loading: true,
  sessionError: null,
  setUser: () => {},
  retrySession: () => {},
  logout: async () => {},
});

export function useAuth() {
  return React.useContext(AuthContext);
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, loading, sessionError, retrySession } = useAuth();
  const router = useRouter();
  const pathname = usePathname() || "";
  const isAuthPage = pathname === "/login" || pathname === "/signup";

  useEffect(() => {
    // Redirect only after a definitive unauthenticated response. Transient
    // session-check failures are handled by the recovery state below.
    if (!loading && !sessionError && !user && !isAuthPage) {
      router.replace(`/login?next=${encodeURIComponent(pathname || "/dashboard")}`);
    }
  }, [isAuthPage, loading, pathname, router, sessionError, user]);

  if (loading && !isAuthPage && !user) {
    return <div className="flex min-h-screen items-center justify-center bg-bg-primary text-sm text-text-secondary">Checking your session…</div>;
  }

  if (!isAuthPage && !user && sessionError) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-bg-primary px-6 text-center">
        <div className="max-w-md space-y-3">
          <p className="text-sm font-semibold text-text-primary">
            We couldn&apos;t verify your session
          </p>
          <p className="text-xs leading-5 text-text-secondary">
            Your session is still safe. The data service is catching up, so retry
            without signing in again.
          </p>
          <button
            type="button"
            onClick={retrySession}
            className="rounded-lg border border-accent-cyan/40 bg-accent-cyan/10 px-4 py-2 text-xs font-semibold text-accent-cyan transition-colors hover:bg-accent-cyan/20"
          >
            Retry session check
          </button>
        </div>
      </div>
    );
  }

  if (!isAuthPage && !user) return null;
  return <>{children}</>;
}
