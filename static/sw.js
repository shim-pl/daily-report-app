// Service Worker - オフラインキャッシュ（基本版）
const CACHE_NAME = 'daily-report-v1';
const STATIC_ASSETS = [
  '/',
  '/static/manifest.json'
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
});

self.addEventListener('fetch', e => {
  // POSTリクエストはキャッシュしない
  if (e.request.method !== 'GET') return;
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
