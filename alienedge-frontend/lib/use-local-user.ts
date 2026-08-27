"use client";

import { useEffect, useState } from "react";

const STORAGE_KEY = "alienedge:anon-user-id";

function generateId(): string {
  return `u_${Math.random().toString(36).slice(2, 10)}${Date.now().toString(36)}`;
}

/**
 * Until real auth (Phase 13) lands, every browser gets a stable anonymous
 * id persisted in localStorage. This id ties a saved alert rule and its
 * fired alerts back to "you" on this device. Swapping in real auth later
 * just means replacing this hook's source with the logged-in user's id —
 * every call site downstream (userRulesApi.*) stays identical.
 */
export function useLocalUserId(): string | null {
  const [userId, setUserId] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    let id = window.localStorage.getItem(STORAGE_KEY);
    if (!id) {
      id = generateId();
      window.localStorage.setItem(STORAGE_KEY, id);
    }
    setUserId(id);
  }, []);

  return userId;
}