// AstroWebEngine Service Worker — minimal, enables PWA install
const CACHE_NAME = 'awe-v1';

self.addEventListener('install', (e) => {
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(clients.claim());
});

// Network-first strategy: always try network, fall back to cache
self.addEventListener('fetch', (e) => {
  // Skip non-GET and API requests
  if (e.request.method !== 'GET' || e.request.url.includes('/api/')) return;

  e.respondWith(
    fetch(e.request)
      .then((res) => {
        // Cache static assets for offline fallback
        if (res.ok && (e.request.url.includes('/static/') || e.request.url.endsWith('/'))) {
          const clone = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(e.request, clone));
        }
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});
