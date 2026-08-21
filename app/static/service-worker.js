const SHELL = 'opsbot-v0.15.0-shell';
const ASSETS = [
  '/static/app.css?v=0.15.0',
  '/static/app.js?v=0.15.0',
  '/static/provider_cleanup.js?v=0.15.0',
  '/static/product_research.css?v=0.15.0',
  '/static/product_research.js?v=0.15.0',
  '/static/app-icon.svg',
  '/offline'
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(SHELL).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== SHELL).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== location.origin || url.pathname.startsWith('/api/') || url.pathname === '/login' || url.pathname === '/health' || url.pathname === '/') return;
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.match('/offline')));
    return;
  }
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(caches.match(request).then(cached => cached || fetch(request).then(response => {
      if (response.ok) caches.open(SHELL).then(cache => cache.put(request, response.clone()));
      return response;
    })));
  }
});
