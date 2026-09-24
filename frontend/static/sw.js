/* NIECP-AI service worker (spec §40).
 * Strategy:
 *  - app shell & static assets: cache-first, refreshed in background
 *  - API GETs: network-first with cache fallback (read-only offline access)
 *  - API writes while offline: rejected here; the app queues them in
 *    localStorage and replays on reconnect (see src/lib/api.ts)
 */
const VERSION = "niecp-v1";
const SHELL = ["/", "/index.html", "/manifest.webmanifest"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(VERSION).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k)))).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET") return;

  if (url.pathname.startsWith("/api/")) {
    // network-first for API reads, cached fallback for offline
    event.respondWith(
      fetch(event.request)
        .then((res) => {
          const copy = res.clone();
          caches.open(VERSION).then((cache) => cache.put(event.request, copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match(event.request).then((hit) => hit || new Response(JSON.stringify({ detail: "You are offline. Showing cached information where available." }), { status: 503, headers: { "Content-Type": "application/json" } })))
    );
    return;
  }

  // static: cache-first with background refresh
  event.respondWith(
    caches.match(event.request).then((hit) => {
      const refresh = fetch(event.request)
        .then((res) => {
          if (res.ok) caches.open(VERSION).then((cache) => cache.put(event.request, res.clone())).catch(() => {});
          return res;
        })
        .catch(() => hit);
      return hit || refresh;
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(clients.openWindow("/#/dashboard"));
});
