const SHELL = 'opsbot-v0.25.4-shell';
const ASSETS = [
  '/static/app.css?v=0.25.4',
  '/static/brand.css?v=ops-swoosh-1',
  '/static/simple_ui.css?v=0.25.4',
  '/static/simple_ui.js?v=0.25.4',
  '/static/app-icon.svg?v=ops-swoosh-1',
  '/offline'
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(SHELL).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(key => key !== SHELL).map(key => caches.delete(key))))
      .then(() => self.clients.claim())
  );
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
    event.respondWith(
      fetch(request)
        .then(response => {
          if (response.ok) caches.open(SHELL).then(cache => cache.put(request, response.clone()));
          return response;
        })
        .catch(() => caches.match(request))
    );
  }
});
