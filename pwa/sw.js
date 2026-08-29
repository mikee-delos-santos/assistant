// Minimal service worker so the app is installable and shell-cached.
// Real caching strategy comes later; keep this deliberately small.
const CACHE = "assistant-shell-v1";
const SHELL = ["./", "index.html", "styles.css", "app.js", "manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  // Never cache the brain API; always go to network for it.
  if (e.request.url.includes("/api/")) return;
  e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
});
