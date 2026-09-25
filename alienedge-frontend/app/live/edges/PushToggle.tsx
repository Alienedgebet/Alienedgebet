"use client";

import { useCallback, useState } from "react";
import api from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";

/**
 * Web Push opt-in for Code 2 alerts.
 *
 * Deliberately opt-in: the permission prompt is NEVER requested automatically.
 * A user who declines is not nagged, and unsupported browsers (or iOS without
 * the app installed to the Home Screen) degrade quietly to the in-app list.
 */
type PushState = {
  supported: boolean;
  permission: NotificationPermission | "unsupported";
  subscribed: boolean;
  vapidPublicKey: string | null;
  triggered: boolean;
  settled: boolean;
};

function urlBase64ToUint8Array(base64String: string) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  return Uint8Array.from([...rawData].map((char) => char.charCodeAt(0)));
}

export function usePushNotifications() {
  // Initial load uses the app's own useApi hook (the same pattern the rest of
  // the codebase uses) rather than a hand-rolled effect that sets state.
  const prefs = useApi(() => api.get("/api/notifications/prefs"), [], {
    cacheKey: "notifications-prefs",
  });

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Browser capability is a pure derivation from globals, not state: it does
  // not change during a session, so it needs no effect and no re-render.
  const hasSw =
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window;
  const permission: NotificationPermission | "unsupported" =
    typeof window !== "undefined" && "PushManager" in window
      ? Notification.permission
      : "unsupported";

  const server = (prefs.data ?? {}) as {
    supported?: boolean;
    subscribed?: boolean;
    vapid_public_key?: string;
    triggered?: boolean;
    settled?: boolean;
  };

  const state: PushState = {
    supported: Boolean(server.supported) && hasSw,
    permission,
    subscribed: Boolean(server.subscribed),
    vapidPublicKey: server.vapid_public_key ?? null,
    triggered: server.triggered !== false,
    settled: server.settled !== false,
  };

  const refresh = useCallback(async () => {
    await prefs.refetch();
  }, [prefs]);


  const enable = useCallback(async () => {
    setError(null);
    if (typeof window === "undefined" || !("serviceWorker" in navigator)) {
      setError("This browser does not support push notifications.");
      return;
    }
    setBusy(true);
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setError(
          permission === "denied"
            ? "Notifications are blocked for this site in your browser settings."
            : "Permission was not granted."
        );
        await refresh();
        return;
      }
      const registration = await navigator.serviceWorker.register("/sw.js");
      await navigator.serviceWorker.ready;
      const config = await api.get("/api/notifications/prefs");
      const key = config.data.vapid_public_key;
      if (!key) throw new Error("Server has no VAPID public key configured.");
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(key) as BufferSource,
      });
      await api.post("/api/notifications/subscribe", {
        endpoint: subscription.endpoint,
        keys: subscription.toJSON().keys as Record<string, string>,
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not enable notifications.");
    } finally {
      setBusy(false);
    }
  }, [refresh]);

  const disable = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      if ("serviceWorker" in navigator) {
        const registration = await navigator.serviceWorker.getRegistration("/sw.js");
        const subscription = await registration?.pushManager.getSubscription();
        if (subscription) {
          await api.post("/api/notifications/unsubscribe");
          await subscription.unsubscribe();
        }
      } else {
        await api.post("/api/notifications/unsubscribe");
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not disable notifications.");
    } finally {
      setBusy(false);
    }
  }, [refresh]);

  const setPref = useCallback(
    async (name: "triggered" | "settled", value: boolean) => {
      setError(null);
      try {
        await api.patch("/api/notifications/prefs", { [name]: value });
        await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not update preference.");
      }
    },
    [refresh]
  );

  return { state, busy, error, enable, disable, setPref, refresh };
}

/** Compact opt-in control. Renders an honest state when unsupported. */
export function PushToggle({ className }: { className?: string }) {
  const { state, busy, error, enable, disable, setPref } = usePushNotifications();

  if (typeof window !== "undefined" && !state.supported) {
    return (
      <div
        className={cn(
          "rounded-xl border border-white/10 bg-black/40 p-3 font-mono text-[11px] text-slate-400",
          className
        )}
      >
        <p className="font-bold uppercase text-slate-300">Match alerts</p>
        <p className="mt-1">
          Push notifications are unavailable here. On iPhone they require adding
          this site to the Home Screen. Live alerts stay visible in the app.
        </p>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "rounded-xl border border-white/10 bg-black/40 p-3 font-mono text-[11px]",
        className
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="font-bold uppercase text-slate-300">Match alerts</p>
        <button
          type="button"
          disabled={busy}
          onClick={() => (state.subscribed ? disable() : enable())}
          className={cn(
            "rounded-md border px-2 py-0.5 text-[10px] font-bold transition-colors disabled:opacity-50",
            state.subscribed
              ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
              : "border-cyan-500/40 bg-cyan-500/10 text-cyan-300"
          )}
        >
          {busy ? "WORKING…" : state.subscribed ? "ON" : "TURN ON"}
        </button>
      </div>

      {state.subscribed && (
        <ul className="mt-2 space-y-1 text-slate-400">
          {(
            [
              ["triggered", "Prediction armed"],
              ["settled", "Final result"],
            ] as const
          ).map(([key, label]) => (
            <li key={key} className="flex items-center justify-between gap-2">
              <span>{label}</span>
              <input
                type="checkbox"
                checked={state[key]}
                onChange={(e) => void setPref(key, e.target.checked)}
                className="accent-cyan-400"
                aria-label={label}
              />
            </li>
          ))}
        </ul>
      )}

      {error && <p className="mt-2 text-[10px] text-rose-300">{error}</p>}

      {state.permission === "denied" && (
        <p className="mt-2 text-[10px] text-amber-300">
          Notifications are blocked. Re-enable them for this site in your browser
          settings.
        </p>
      )}

      <p className="mt-2 text-[10px] leading-relaxed text-slate-500">
        Alerts fire only when a prediction is armed or reaches a final result. A
        prediction that is merely &ldquo;building&rdquo; is never sent, because that
        state can still reverse.
      </p>
    </div>
  );
}
