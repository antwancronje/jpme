var CACHE_NAME = "jpme-v17e";
var URLS_TO_CACHE = [
  "/jpme/",
  "/jpme/index.html",
  "/jpme/manifest.json",
  "/jpme/icon-192.png",
  "/jpme/icon-512.png",
  "/jpme/invite-story.png",
  "/jpme/invite-landscape.png",
  "https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Outfit:wght@400;500;600;700;800;900&family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400;1,700;1,900&display=swap",
  "https://cdn.jsdelivr.net/npm/@emailjs/browser@4/dist/email.min.js"
];

self.addEventListener("install", function(e) {
  e.waitUntil(
    caches.open(CACHE_NAME).then(function(cache) {
      return cache.addAll(URLS_TO_CACHE);
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", function(e) {
  e.waitUntil(
    caches.keys().then(function(names) {
      return Promise.all(
        names.filter(function(n) { return n !== CACHE_NAME; })
              .map(function(n) { return caches.delete(n); })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", function(e) {
  if (e.request.url.indexOf("script.google.com") > -1) {
    return;
  }
  e.respondWith(
    caches.match(e.request).then(function(cached) {
      return cached || fetch(e.request).then(function(response) {
        if (e.request.method === "GET" && response.status === 200) {
          var clone = response.clone();
          caches.open(CACHE_NAME).then(function(cache) {
            cache.put(e.request, clone);
          });
        }
        return response;
      });
    }).catch(function() {
      if (e.request.mode === "navigate") {
        return caches.match("/jpme/index.html");
      }
    })
  );
});