"use client";
import React, { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

export interface AuthUser {
  user_id: string;
  email: string;
  created_at?: number;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    fetch("/api/auth/me", { credentials: "include", cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) return null;
        return (await response.json()) as { user?: AuthUser };
      })
      .then((result) => {
        if (active) setUser(result?.user ?? null);
      })
      .catch(() => {
        if (active) setUser(null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, loading, setUser, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

const AuthContext = React.createContext<{
  user: AuthUser | null;
  loading: boolean;
  setUser: (user: AuthUser | null) => void;
  logout: () => Promise<void>;
}>({ user: null, loading: true, setUser: () => {}, logout: async () => {} });

export function useAuth() {
  return React.useContext(AuthContext);
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname() || "";
  const isAuthPage = pathname === "/login" || pathname === "/signup";

  useEffect(() => {
    if (!loading && !user && !isAuthPage) {
      router.replace(`/login?next=${encodeURIComponent(pathname || "/dashboard")}`);
    }
  }, [isAuthPage, loading, pathname, router, user]);

  if (loading && !isAuthPage) {
    return <div className="flex min-h-screen items-center justify-center bg-bg-primary text-sm text-text-secondary">Checking your session…</div>;
  }
  if (!isAuthPage && !user) return null;
  return <>{children}</>;
}
