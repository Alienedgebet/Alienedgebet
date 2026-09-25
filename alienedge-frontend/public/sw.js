/*
 * AlienEdge push service worker.
 *
 * Scope note: this worker only handles PUSH and NOTIFICATIONCLICK. It
 * deliberately does NOT cache or intercept fetches, so it can never serve
 * stale match data or shadow the app's own loading states.
 *
 * iOS: requires the site to be added to the Home Screen (iOS 16.4+). Without
 * that, web push is unavailable on iPhone and the in-app list is the fallback.
 */

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    if (event.data) {
      payload = event.data.json();
    }
  } catch (err) {
    // A malformed payload must not break the notification.
    payload = {};
  }

  const title = payload.title || "AlienEdge";
  const options = {
    body: payload.body || "",
    icon: "/icon-192.png",
    badge: "/badge-72.png",
    tag: payload.tag || "alienedge",
    renotify: true,
    requireInteraction: false,
    silent: false,
    data: payload.data || {},
    actions: [{ action: "open", title: "Open match" }],
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/live/edges";

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      // Focus an existing tab if the app is already open, otherwise open one.
      for (const client of clientList) {
        if (client.url && "focus" in client) {
          client.navigate(target);
          return client.focus();
        }
      }
      return self.clients.openWindow(target);
    })
  );
});
