// TMPRO service worker: anlık bildirimler
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

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
    for (const c of all) { if (c.url.startsWith(self.registration.scope)) { await c.focus(); c.postMessage({ type: "refresh" }); return; } }
    await self.clients.openWindow(url);
  })());
});
