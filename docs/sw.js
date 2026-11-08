// TMPRO service worker: anlık bildirimler
const APP = "https://tmpro.tmproapp.workers.dev/";
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

// Sayfa her açılışta ağdan taze gelsin (eski sürüm takılı kalmasın)
self.addEventListener("fetch", e => {
  if (e.request.mode === "navigate") e.respondWith(fetch(e.request, { cache: "no-store" }).catch(() => fetch(e.request)));
});

// Gelen bildirimler uygulama içinde de görünsün diye IndexedDB'ye yazılır
function inboxDb() {
  return new Promise((ok, no) => {
    const q = indexedDB.open("tmpro", 1);
    q.onupgradeneeded = () => q.result.createObjectStore("inbox", { keyPath: "id", autoIncrement: true });
    q.onsuccess = () => ok(q.result); q.onerror = () => no(q.error);
  });
}
async function saveInbox(n) {
  try {
    const db = await inboxDb();
    await new Promise((ok, no) => {
      const tx = db.transaction("inbox", "readwrite"), st = tx.objectStore("inbox");
      st.add(n);
      const c = st.count(); c.onsuccess = () => { if (c.result > 150) st.openCursor().onsuccess = e => { const cur = e.target.result; if (cur) cur.delete(); }; };
      tx.oncomplete = ok; tx.onerror = () => no(tx.error);
    });
    const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    all.forEach(c => c.postMessage({ type: "inbox", n }));
  } catch (e) {}
}

self.addEventListener("push", event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = { body: event.data && event.data.text() }; }
  const title = data.title || "TMPRO";
  const n = { title, body: data.body || "Yeni mevzuat kaydı var.", url: data.url || "./", tag: data.tag || "tmpro", at: Date.now(), read: false };
  event.waitUntil(Promise.all([saveInbox(n), self.registration.showNotification(title, {
    body: data.body || "Yeni mevzuat kaydı var.",
    icon: "icon-192.png",
    badge: "icon-192.png",
    tag: data.tag || "tmpro",
    renotify: true,
    data: { url: data.url || "./" }
  })]));
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  // Bildirim her zaman uygulamanın kendi adresinde açılır (eski adreslere yönlenmesin)
  const url = new URL(event.notification.data.url || "/", APP).href;
  event.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const c of all) { if (c.url.startsWith(APP)) { await c.focus(); c.postMessage({ type: "open", url }); return; } }
    await self.clients.openWindow(url);
  })());
});
