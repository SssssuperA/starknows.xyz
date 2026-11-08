/* Browser-only cache. PDF requests always use the normal network/HTTP cache. */
const VERSION = '__BUILD_VERSION__';
const PREFIX = 'starknows-v1-';
const CACHE = PREFIX + VERSION;
const HOME = new URL('/', self.location.origin).href;
const MAX_JSON = 220;

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const response = await fetch(HOME, {cache: 'no-store'});
    if (!response.ok) throw new Error('Homepage unavailable');
    const html = await response.clone().text();
    if (!html.includes('name="starknows-cache-version" content="' + VERSION + '"')) {
      throw new Error('Deployment changed during cache installation');
    }
    const cache = await caches.open(CACHE);
    await cache.put(HOME, response);
    // Updates wait until existing tabs close, or the user presses "立即更新".
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const names = (await caches.keys()).filter(name => name.startsWith(PREFIX));
    const previous = names.filter(name => name !== CACHE);
    await Promise.all(previous.slice(0, -1).map(name => caches.delete(name)));
    await self.clients.claim();
  })());
});

self.addEventListener('message', event => {
  if (event.data?.type === 'ACTIVATE_UPDATE') self.skipWaiting();
});

async function saveJSON(request, response) {
  try {
    const cache = await caches.open(CACHE);
    await cache.put(request, response);
    const keys = (await cache.keys()).filter(key => new URL(key.url).pathname.startsWith('/library/'));
    await Promise.all(keys.slice(0, Math.max(0, keys.length - MAX_JSON)).map(key => cache.delete(key)));
  } catch {
    // A full or disabled browser cache must not prevent reading a report.
  }
}

self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (request.mode === 'navigate' && (url.pathname === '/' || url.pathname === '/index.html')) {
    event.respondWith((async () => {
      try {
        const cached = await (await caches.open(CACHE)).match(HOME);
        if (cached) return cached;
      } catch {}
      return fetch(request);
    })());
  } else if (/^\/library\/[a-z0-9-]+\.json$/.test(url.pathname) && !url.search) {
    let save = Promise.resolve();
    const response = (async () => {
      try {
        const cached = await (await caches.open(CACHE)).match(request);
        if (cached) return cached;
      } catch {}
      const result = await fetch(request);
      if (result.ok && result.headers.get('content-type')?.includes('application/json')) {
        save = saveJSON(request, result.clone());
      }
      return result;
    })();
    event.respondWith(response);
    event.waitUntil(response.then(() => save).catch(() => {}));
  }
});
