// TMPRO service worker: anlık bildirimler
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

// Sayfa her açılışta ağdan taze gelsin (eski sürüm takılı kalmasın)
self.addEventListener("fetch", e => {
  if (e.request.mode === "navigate") e.respondWith(fetch(e.request, { cache: "no-store" }).catch(() => fetch(e.request)));
});

self.addEventListener("push", event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = { body: event.data && event.data.text() }; }
  const title = data.title || "TMPRO";
  event.waitUntil(self.registration.showNotification(title, {
    body: data.body || "Yeni mevzuat kaydı var.",
    icon: "icon-192.png",
    badge: "icon-192.png",
    tag: data.tag || "tmpro",
    renotify: true,
    data: { url: data.url || "./" }
  }));
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  const url = new URL(event.notification.data.url || "./", self.registration.scope).href;
  event.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const c of all) { if (c.url.startsWith(self.registration.scope)) { await c.focus(); c.postMessage({ type: "open", url }); return; } }
    await self.clients.openWindow(url);
  })());
});
