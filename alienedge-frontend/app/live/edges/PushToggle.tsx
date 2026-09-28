"use client";

import { useCallback, useState } from "react";
import api from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";

/**
 * Web Push opt-in — covers both the system predictions and the user's own
 * "Setup my alert" rules.
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
  /** The user's own alerts, including the scoreline gate. */
  userAlert: boolean;
  /** How many of this user's devices are registered. */
  devices: number;
  /** Why push is unavailable, or "ok". Drives the message shown to the user. */
  blocker: PushBlocker;
};

function urlBase64ToUint8Array(base64String: string) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  return Uint8Array.from([...rawData].map((char) => char.charCodeAt(0)));
}

/**
 * WHY push is unavailable, stated precisely.
 *
 * The original component collapsed every failure into one "unavailable here,
 * on iPhone add to the Home Screen" message. That is wrong whenever the real
 * cause is something else — most often an insecure origin — so a user on
 * desktop Chrome over HTTP was told to install an iPhone app. Each cause needs
 * its own instruction, and the user has to be able to act on it.
 */
export type PushBlocker =
  | "ok"
  | "insecure-origin"
  | "no-push-api"
  | "permission-denied"
  | "ios-not-installed"
  | "server-no-key";

/** Is this a context the browser will grant a service worker to? */
function isSecureOrigin(): boolean {
  if (typeof window === "undefined") return false;
  // localhost counts as secure by definition, which is precisely why a
  // developer's own machine can work when the deployed site cannot.
  return window.isSecureContext === true;
}

function isIos(): boolean {
  if (typeof navigator === "undefined") return false;
  return (
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    // iPadOS 13+ reports as a Mac; the touch-point count is the tell.
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
  );
}

/**
 * iOS only exposes the Push API to a web app installed from the Home Screen
 * and opened from there. In an ordinary Safari tab the API is simply absent,
 * which is indistinguishable from an ancient browser unless you check the
 * platform too.
 */
function isStandalone(): boolean {
  if (typeof window === "undefined") return false;
  return (
    window.matchMedia?.("(display-mode: standalone)").matches === true ||
    (navigator as { standalone?: boolean }).standalone === true
  );
}

export function diagnosePush(opts: {
  hasSw: boolean;
  hasPushApi: boolean;
  secureOrigin: boolean;
  permission: NotificationPermission | "unsupported";
  serverSupported: boolean | undefined;
  isIos: boolean;
  standalone: boolean;
}): PushBlocker {
  // Checked FIRST. Over plain HTTP the Push API is simply not exposed, and
  // blaming the browser or the platform there sends the user chasing the
  // wrong problem entirely.
  if (!opts.secureOrigin) return "insecure-origin";
  if (!opts.hasSw || !opts.hasPushApi) {
    if (opts.isIos && !opts.standalone) return "ios-not-installed";
    return "no-push-api";
  }
  if (opts.permission === "denied") return "permission-denied";
  if (opts.serverSupported === false) return "server-no-key";
  return "ok";
}

/** Plain-English fix for each blocker. Deliberately actionable. */
export const PUSH_BLOCKER_HELP: Record<Exclude<PushBlocker, "ok">, string> = {
  "insecure-origin":
    "This page is not on HTTPS, and browsers only allow push on a secure connection. Open the app over https:// and this button will appear.",
  "no-push-api":
    "This browser does not offer push notifications here. Chrome, Edge, Firefox and Safari on macOS all do. Your alerts still show up in the app.",
  "permission-denied":
    "Notifications are blocked for this site. Re-allow them in your browser's site settings, then reload this page.",
  "ios-not-installed":
    "On iPhone, web push only works from an app added to the Home Screen. Tap Share → Add to Home Screen, then open AlienEdge from there and this button will appear.",
  "server-no-key":
    "The server has no push key configured, so alerts cannot be sent yet. They are still recorded and shown in the app.",
};

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
  const hasPushApi =
    typeof window !== "undefined" && "PushManager" in window;
  const hasSw = typeof window !== "undefined" && "serviceWorker" in navigator;
  const permission: NotificationPermission | "unsupported" = hasPushApi
    ? Notification.permission
    : "unsupported";

  const server = (prefs.data ?? {}) as {
    supported?: boolean;
    subscribed?: boolean;
    vapid_public_key?: string;
    triggered?: boolean;
    settled?: boolean;
    user_alert?: boolean;
    devices?: number;
  };

  const blocker = diagnosePush({
    hasSw,
    hasPushApi,
    secureOrigin: isSecureOrigin(),
    permission,
    serverSupported: server.supported,
    isIos: isIos(),
    standalone: isStandalone(),
  });

  const state: PushState = {
    // Derived from the diagnosis, not computed separately, so the toggle and
    // the message can never disagree about why push is unavailable.
    supported: blocker === "ok",
    permission,
    subscribed: Boolean(server.subscribed),
    vapidPublicKey: server.vapid_public_key ?? null,
    triggered: server.triggered !== false,
    settled: server.settled !== false,
    userAlert: server.user_alert !== false,
    devices: server.devices ?? (server.subscribed ? 1 : 0),
    blocker,
  };

  const refresh = useCallback(async () => {
    await prefs.refetch();
  }, [prefs]);


  const enable = useCallback(async () => {
    setError(null);
    if (typeof window === "undefined" || !("serviceWorker" in navigator)) {
      // Use the same diagnosis the UI shows, so a failure here can never
      // contradict the message the user was just looking at.
      setError(
        PUSH_BLOCKER_HELP[blocker === "ok" ? "no-push-api" : blocker]
      );
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
    // `blocker` is declared so the guard message can never lag behind the
    // diagnosis the user is currently looking at.
  }, [refresh, blocker]);

  const disable = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      if ("serviceWorker" in navigator) {
        const registration = await navigator.serviceWorker.getRegistration("/sw.js");
        const subscription = await registration?.pushManager.getSubscription();
        if (subscription) {
          // Send THIS device's endpoint so only it is removed. Without it the
          // server clears every device the user owns, so turning push off on a
          // laptop would silently stop alerts reaching their phone too.
          await api.post(
            "/api/notifications/unsubscribe",
            undefined,
            { params: { endpoint: subscription.endpoint } }
          );
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
    async (
      name: "triggered" | "settled" | "user_alert",
      value: boolean
    ) => {
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
        {/* ONE reason and one reassurance. The previous version stacked three
            paragraphs, two of which said the same thing ("your alerts still
            appear in the app"), plus a further duplicate on the setup page.
            A user who cannot get a push has one question — how do I fix it —
            and one fact they need not lose: the alert still works. */}
        <p className="mt-1">
          {PUSH_BLOCKER_HELP[state.blocker === "ok" ? "no-push-api" : state.blocker]}
        </p>
        <p className="mt-1 text-slate-500">Your alerts still appear in the app.</p>
        {/* A concrete address beats a vague complaint when the cause is the
            deployment rather than the user's own device. */}
        {state.blocker === "insecure-origin" && (
          <p className="mt-2 text-slate-500">
            Current address: <span className="text-slate-400">{window.location.origin}</span>
          </p>
        )}
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
        <>
          <ul className="mt-2 space-y-1 text-slate-400">
            {(
              [
                // [preference key sent to the API, readable label, PushState field]
                ["user_alert", "My alerts (Setup my alert)", "userAlert"],
                ["triggered", "Prediction armed", "triggered"],
                ["settled", "Final result", "settled"],
              ] as const
            ).map(([key, label, field]) => (
              <li key={key} className="flex items-center justify-between gap-2">
                <span>{label}</span>
                <input
                  type="checkbox"
                  checked={state[field]}
                  onChange={(e) => void setPref(key, e.target.checked)}
                  className="accent-cyan-400"
                  aria-label={label}
                />
              </li>
            ))}
          </ul>
          {state.devices > 1 && (
            <p className="mt-1.5 text-[10px] text-slate-500">
              Sending to {state.devices} of your devices.
            </p>
          )}
        </>
      )}

      {error && <p className="mt-2 text-[10px] text-rose-300">{error}</p>}

      <p className="mt-2 text-[10px] leading-relaxed text-slate-500">
        Your own alerts fire the moment their conditions are met. Predictions are only
        announced when armed or finally settled &mdash; one that is merely
        &ldquo;building&rdquo; is never sent, because that state can still reverse.
      </p>
    </div>
  );
}
