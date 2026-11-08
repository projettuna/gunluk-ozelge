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

// ---------------------------------------------------------------- günaydın bildirimi (/api/morning)
const WMO = c => c === 0 ? "Açık" : c <= 2 ? "Az bulutlu" : c === 3 ? "Kapalı" : c <= 48 ? "Sisli" : c <= 57 ? "Çisentili"
  : c <= 67 ? "Yağmurlu" : c <= 77 ? "Karlı" : c <= 82 ? "Sağanak yağışlı" : c <= 86 ? "Kar sağanaklı" : "Gök gürültülü";

export function holidaysOn(hol, iso) {
  return [...hol.sabit.filter(h => h.g === iso.slice(5)), ...hol.degisken.filter(h => h.t === iso)];
}

async function fetchWx(lat, lon) {
  const r = await fetch(`https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&current=temperature_2m`
    + `&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,snowfall_sum`
    + `&timezone=Europe%2FIstanbul&forecast_days=1`);
  if (!r.ok) throw new Error("wx " + r.status);
  const j = await r.json(), d = j.daily;
  return { cur: j.current?.temperature_2m, code: d.weather_code[0], max: d.temperature_2m_max[0], min: d.temperature_2m_min[0],
           pop: d.precipitation_probability_max?.[0] ?? 0, rain: d.precipitation_sum?.[0] ?? 0, snow: d.snowfall_sum?.[0] ?? 0 };
}

export function weatherAdvice(w) {
  const c = w.code;
  const snow = w.snow > 0 || (c >= 71 && c <= 77) || c === 85 || c === 86;
  const rain = !snow && (c >= 95 || (c >= 51 && c <= 67) || (c >= 80 && c <= 82) || (w.pop >= 50 && w.rain >= 0.5));
  // En önemli tek uyarı
  if (snow) return "🌨️ Kar bekleniyor, yollar kaygan olabilir.";
  if (w.min <= 0) return "🧊 Buzlanma riski var, yollarda dikkatli olun.";
  if (rain && w.min < 3) return "☂️ Yağış ve soğuk var, şemsiyenizi alın, yollarda dikkatli olun.";
  if (rain) return "☂️ Yağmur bekleniyor, şemsiyenizi almayı unutmayın.";
  if (w.min < 3) return "❄️ Hava soğuk, yerler kaygan olabilir.";
  if (c === 45 || c === 48) return "🌫️ Sis var, araçla dikkatli olun.";
  if (w.max >= 35) return "🥵 Çok sıcak, bol su için.";
  return "";
}

export function composeMorning(u, w, hol, today, tomorrow) {
  const city = u.city || "Ankara", first = String(u.name || "").trim().split(/\s+/)[0];
  const th = holidaysOn(hol, today), tm = holidaysOn(hol, tomorrow);
  const special = th.find(h => h.mesaj);
  const lines = [];
  if (special) lines.push(special.mesaj);
  if (w) {
    lines.push(`${city} · ${WMO(w.code)} · ${Math.round(w.min)}° / ${Math.round(w.max)}°`);
    const a = weatherAdvice(w); if (a) lines.push(a);
  }
  const nt = tm.find(h => h.tur !== "anma");
  if (nt && !th.some(h => h.tur === "tatil")) lines.push(`📅 Yarın ${nt.ad}${nt.tur === "yarim" ? " (yarım gün)" : ""}`);
  if (u.events?.length) lines.push("📌 " + u.events.join(", "));
  const title = special ? special.ad : `Günaydın${first ? " " + first : ""} ☀️`;
  return { title, body: (lines.join("\n") || "İyi çalışmalar.").slice(0, 400), url: "/", tag: "tmpro-gunaydin" };
}

async function morning(j, env) {
  const hol = await (await env.ASSETS.fetch(new Request("https://assets.local/tatiller.json"))).json();
  const now = new Date(Date.now() + 3 * 3600e3), today = now.toISOString().slice(0, 10);
  const tomorrow = new Date(now.getTime() + 864e5).toISOString().slice(0, 10);
  const wx = {}, out = [];
  let sent = 0;
  for (const u of (j.users || []).slice(0, 1000)) {
    const lat = Number.isFinite(u.lat) ? u.lat : 39.93, lon = Number.isFinite(u.lon) ? u.lon : 32.86;
    if (!Number.isFinite(u.lat)) u.city = "Ankara";
    const k = lat.toFixed(2) + "," + lon.toFixed(2);
    wx[k] ||= fetchWx(lat, lon).catch(() => null);
    const msg = composeMorning(u, await wx[k], hol, today, tomorrow);
    if (j.preview) { out.push(msg); continue; }
    const res = await Promise.all((u.subs || []).map(s => sendOne(s, JSON.stringify(msg), j.vapid).catch(() => 0)));
    sent += res.filter(x => x >= 200 && x < 300).length;
  }
  return j.preview ? { today, preview: out } : { today, users: (j.users || []).length, sent };
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
    if (url.pathname === "/api/morning" && req.method === "POST") {
      let j; try { j = await req.json(); } catch { return new Response("bad json", { status: 400 }); }
      if (!Array.isArray(j?.users) || (!j.preview && (!j?.vapid?.private || !j?.vapid?.public))) return new Response("bad request", { status: 400 });
      return Response.json(await morning(j, env));
    }
    return env.ASSETS.fetch(req);
  }
};
