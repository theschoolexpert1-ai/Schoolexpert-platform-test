/* The School Expert™ service worker — offline shell + fast static assets. Never caches dashboards, payments or personal data. */
const V = 'tse-v{{ version }}';
const SHELL = ['/offline', '/static/css/site.css?v=3', '/static/js/site.js?v=3', '/static/img/logo-mark.svg', '/static/img/icon-192.png'];
self.addEventListener('install', e => { e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== V).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
const PRIVATE = /^\/(dashboard|admin|pay|cart|api|register|login|logout|signup|privacy-centre|school-match\/r|shortlist)/;
self.addEventListener('fetch', e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/static/')) {
    e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(res => { const copy = res.clone(); caches.open(V).then(c => c.put(req, copy)); return res; })));
    return;
  }
  if (req.mode === 'navigate') {
    if (PRIVATE.test(url.pathname)) { e.respondWith(fetch(req).catch(() => caches.match('/offline'))); return; }
    e.respondWith(fetch(req).then(res => { if (res.ok) { const copy = res.clone(); caches.open(V).then(c => c.put(req, copy)); } return res; })
      .catch(() => caches.match(req).then(hit => hit || caches.match('/offline'))));
  }
});
