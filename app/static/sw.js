// Wardrobe PWA Service Worker
const CACHE_NAME = 'wardrobe-v17';

const STATIC_ASSETS = [
    '/',
    '/index.html',
    '/app.js',
    '/style.css',
    '/manifest.json',
    '/icons/icon-192.png',
    '/icons/icon-512.png',
    '/apple-touch-icon.png'
];

// Install: cache static assets
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => {
                console.log('Caching static assets');
                return cache.addAll(STATIC_ASSETS);
            })
            .then(() => self.skipWaiting())
    );
});

// Activate: clean up old caches
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys()
            .then((cacheNames) => {
                return Promise.all(
                    cacheNames
                        .filter((name) => name !== CACHE_NAME)
                        .map((name) => caches.delete(name))
                );
            })
            .then(() => self.clients.claim())
    );
});

// True for the request that loads the page itself.
// `mode: 'navigate'` covers launching the PWA and any in-app navigation.
function isDocumentRequest(request) {
    return request.mode === 'navigate' ||
        (request.method === 'GET' &&
         (request.headers.get('accept') || '').includes('text/html'));
}

// Fetch: network-first for the document, cache-first for other static assets,
// network-only for API and photos.
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Network-only for API requests
    if (url.pathname.startsWith('/api')) {
        event.respondWith(fetch(event.request));
        return;
    }

    // Network-only for photos (they can change)
    if (url.pathname.startsWith('/photos')) {
        event.respondWith(fetch(event.request));
        return;
    }

    // Never serve the worker itself from the cache: a stale copy would keep
    // re-installing the version that cached it and no deploy could land.
    if (url.pathname === '/sw.js') {
        event.respondWith(fetch(event.request));
        return;
    }

    // The document is network-first. Cache-first here is what strands a
    // deploy: the HTML is what names the ?v= of the script and stylesheet, so
    // serving it from cache pins the app to the asset versions that shipped
    // with it and the cache-busting query can never take effect. Falling back
    // to the cache keeps the app usable with no network.
    if (isDocumentRequest(event.request)) {
        event.respondWith(
            fetch(event.request)
                .then((response) => {
                    if (response && response.status === 200) {
                        const copy = response.clone();
                        caches.open(CACHE_NAME).then((cache) => {
                            cache.put(event.request, copy);
                        });
                    }
                    return response;
                })
                .catch(() => caches.match(event.request)
                    .then((cached) => cached || caches.match('/index.html')))
        );
        return;
    }

    // Cache-first for everything else. Safe because app.js and style.css are
    // requested with a ?v= that changes when they do, so a new version is a
    // cache miss and gets fetched.
    event.respondWith(
        caches.match(event.request)
            .then((cachedResponse) => {
                if (cachedResponse) {
                    return cachedResponse;
                }
                return fetch(event.request)
                    .then((response) => {
                        // Don't cache non-successful responses
                        if (!response || response.status !== 200 || response.type !== 'basic') {
                            return response;
                        }
                        // Clone and cache
                        const responseToCache = response.clone();
                        caches.open(CACHE_NAME)
                            .then((cache) => {
                                cache.put(event.request, responseToCache);
                            });
                        return response;
                    });
            })
    );
});
