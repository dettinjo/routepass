const SHELL_CACHE = "routepass-shell-v3";
const API_CACHE = "routepass-api-v3";
const PRECACHE_URLS = [
  "/",
  "/manifest.webmanifest",
  "/favicon.svg",
  "/icon-192.png",
  "/icon-512.png",
  "/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => k !== SHELL_CACHE && k !== API_CACHE)
            .map((k) => caches.delete(k)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") {
    self.skipWaiting();
  } else if (event.data?.type === "CLEAR_API_CACHE") {
    caches.delete(API_CACHE);
  }
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Never cache sign-in, OAuth, webhooks, imports, exports, docs or MCP
  if (
    url.pathname.startsWith("/mcp") ||
    url.pathname.startsWith("/api/v1/auth/") ||
    url.pathname.startsWith("/api/v1/import/") ||
    url.pathname.endsWith(".csv") ||
    url.pathname.endsWith("/gpx") ||
    url.pathname.startsWith("/api/docs") ||
    url.pathname.startsWith("/api/openapi.json") ||
    url.pathname.startsWith("/api/v1/webhooks/") ||
    url.pathname.startsWith("/api/v1/connections/")
  ) {
    return;
  }

  // Read-only API calls: network-first, fall back to cached response when offline
  if (url.pathname.startsWith("/api/v1/")) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(API_CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(async () => {
          const cached = await caches.match(request);
          if (cached) return cached;
          return new Response(
            JSON.stringify({ detail: "Offline and no cached data available" }),
            { status: 503, headers: { "Content-Type": "application/json" } },
          );
        }),
    );
    return;
  }

  // Hashed static assets & icons: cache-first
  if (
    url.pathname.startsWith("/assets/") ||
    url.pathname.endsWith(".png") ||
    url.pathname.endsWith(".svg")
  ) {
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ||
          fetch(request).then((response) => {
            if (response.ok) {
              const copy = response.clone();
              caches.open(SHELL_CACHE).then((cache) => cache.put(request, copy));
            }
            return response;
          }),
      ),
    );
    return;
  }

  // SPA navigation & shell: network-first, fall back to cached "/"
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(SHELL_CACHE).then((cache) => cache.put("/", copy));
          }
          return response;
        })
        .catch(async () => (await caches.match("/")) || Response.error()),
    );
  }
});
