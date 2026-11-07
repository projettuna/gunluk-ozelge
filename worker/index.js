// TMPRO Cloudflare Worker: statik uygulama (docs/) + anlık bildirim aktarıcısı (/api/push).
// Aktarıcı, yalnızca VAPID özel anahtarını bilen çağıranın (veritabanı tetikleyicisi) bildirimlerini gönderir;
// Apple/Google bu anahtarla imzalanmamış bildirimleri reddeder, bu yüzden ayrıca gizli anahtar gerekmez.

const enc = new TextEncoder();
const b64u = buf => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const unb64u = s => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4)), c => c.charCodeAt(0));
const concat = (...a) => { const o = new Uint8Array(a.reduce((n, x) => n + x.length, 0)); let i = 0; for (const x of a) { o.set(x, i); i += x.length; } return o; };

async function hkdf(salt, ikm, info, len) {
  const key = await crypto.subtle.importKey("raw", ikm, "HKDF", false, ["deriveBits"]);
  return new Uint8Array(await crypto.subtle.deriveBits({ name: "HKDF", hash: "SHA-256", salt, info }, key, len * 8));
}

// RFC 8291 (aes128gcm) şifreleme
export async function encryptPayload(sub, plaintext) {
  const uaPub = unb64u(sub.p256dh), authSecret = unb64u(sub.auth);
  const asKeys = await crypto.subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]);
  const asPub = new Uint8Array(await crypto.subtle.exportKey("raw", asKeys.publicKey));
  const uaKey = await crypto.subtle.importKey("raw", uaPub, { name: "ECDH", namedCurve: "P-256" }, false, []);
  const shared = new Uint8Array(await crypto.subtle.deriveBits({ name: "ECDH", public: uaKey }, asKeys.privateKey, 256));
  const ikm = await hkdf(authSecret, shared, concat(enc.encode("WebPush: info\0"), uaPub, asPub), 32);
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const cek = await hkdf(salt, ikm, enc.encode("Content-Encoding: aes128gcm\0"), 16);
  const nonce = await hkdf(salt, ikm, enc.encode("Content-Encoding: nonce\0"), 12);
  const key = await crypto.subtle.importKey("raw", cek, "AES-GCM", false, ["encrypt"]);
  const data = concat(enc.encode(plaintext), new Uint8Array([2]));
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce }, key, data));
  const header = new Uint8Array(21); header.set(salt); new DataView(header.buffer).setUint32(16, 4096); header[20] = 65;
  return concat(header, asPub, ct);
}

async function vapidHeader(endpoint, privB64, pubB64, subject) {
  const pub = unb64u(pubB64);
  const jwk = { kty: "EC", crv: "P-256", d: privB64, x: b64u(pub.slice(1, 33)), y: b64u(pub.slice(33, 65)) };
  const key = await crypto.subtle.importKey("jwk", jwk, { name: "ECDSA", namedCurve: "P-256" }, false, ["sign"]);
  const head = b64u(enc.encode(JSON.stringify({ typ: "JWT", alg: "ES256" })));
  const body = b64u(enc.encode(JSON.stringify({ aud: new URL(endpoint).origin, exp: Math.floor(Date.now() / 1000) + 12 * 3600, sub: subject })));
  const sig = await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, key, enc.encode(`${head}.${body}`));
  return `vapid t=${head}.${body}.${b64u(sig)}, k=${pubB64}`;
}

async function sendOne(sub, payload, vapid) {
  const body = await encryptPayload(sub, payload);
  const r = await fetch(sub.endpoint, { method: "POST", body, headers: {
    "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", TTL: "86400", Urgency: "high",
    Authorization: await vapidHeader(sub.endpoint, vapid.private, vapid.public, vapid.subject || "mailto:bildirim@tmpro.app") } });
  return r.status;
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (url.pathname === "/api/push" && req.method === "POST") {
      let j; try { j = await req.json(); } catch { return new Response("bad json", { status: 400 }); }
      if (!j?.vapid?.private || !j?.vapid?.public || !Array.isArray(j.subs)) return new Response("bad request", { status: 400 });
      const payload = JSON.stringify(j.payload || {});
      const res = await Promise.all(j.subs.slice(0, 500).map(s => sendOne(s, payload, j.vapid).catch(() => 0)));
      return Response.json({ sent: res.filter(x => x >= 200 && x < 300).length, statuses: res });
    }
    return env.ASSETS.fetch(req);
  }
};
