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
const WICON = c => c === 0 ? "☀️" : c <= 2 ? "🌤️" : c === 3 ? "☁️" : c <= 48 ? "🌫️" : c <= 67 ? "🌧️" : c <= 77 ? "🌨️" : c <= 82 ? "🌧️" : c <= 86 ? "🌨️" : "⛈️";
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
  if (snow) return "Kar yağışı var, yollarda dikkatli olun.";
  if (w.min <= 0) return "Buzlanma riski var, yollarda dikkatli olun.";
  if (rain && w.min < 3) return "Yağışlı ve soğuk, şemsiyenizi alın.";
  if (rain) return "Yağmur bekleniyor, şemsiyenizi alın.";
  if (w.min < 3) return "Hava soğuk, yerler kaygan olabilir.";
  if (c === 45 || c === 48) return "Sisli, araçla dikkatli olun.";
  if (w.max >= 35) return "Çok sıcak, bol su için.";
  return "";
}

export function composeMorning(u, w, hol, today, tomorrow) {
  const city = u.city || "Ankara", first = String(u.name || "").trim().split(/\s+/)[0];
  const th = holidaysOn(hol, today), tm = holidaysOn(hol, tomorrow);
  const special = th.find(h => h.mesaj);
  const lines = [];
  if (special) lines.push(special.mesaj);
  if (w) {
    const a = weatherAdvice(w);
    lines.push(`${WICON(w.code)} ${city} ${Math.round(w.min)}°/${Math.round(w.max)}° · ${WMO(w.code)}` + (a ? `\n${a}` : ""));
  }
  const nt = tm.find(h => h.tur !== "anma");
  if (nt && !th.some(h => h.tur === "tatil")) lines.push(`📅 Yarın ${nt.ad}${nt.tur === "yarim" ? " (yarım gün)" : ""}`);
  if (u.events?.length) lines.push("📌 " + u.events.join(", "));
  const title = special ? special.ad : `Günaydın${first ? " " + first : ""}`;
  return { title, body: (lines.join("\n") || "İyi çalışmalar.").slice(0, 400), url: "https://tmpro.tmproapp.workers.dev/", tag: "tmpro-gunaydin" };
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

// ---- Mevzuat asistanı: üyenin oturumuyla kayıtları arar, Claude ile kaynaklı yanıt üretir ----
const SB_URL = "https://hnolhapzcisavhkwyzhs.supabase.co";
const SB_KEY = "sb_publishable_tlfwqtscxxv2vdSHe3PstQ_XO1db8p9";
const STOP = new Set("ve veya ile için gibi bir bu şu o da de mi mı mu mü ne nasıl hangi neler nedir olan olarak ise ki ama fakat yani daha en çok az her kadar sonra önce üzerine göre dair ilgili hakkında var yok mıdır midir edilir edilmesi yapılır".split(" "));
const stems = q => [...new Set(q.toLocaleLowerCase("tr").replace(/[^a-zçğıöşü0-9 ]/g, " ").split(/\s+/).filter(w => w.length >= 3 && !STOP.has(w)).map(w => w.length > 6 ? w.slice(0, 6) : w))].slice(0, 8);
function excerpt(text, ws, max) {
  const t = text || "", low = t.toLocaleLowerCase("tr");
  if (t.length <= max) return t;
  let best = 0, bestScore = -1;
  for (let i = 0; i < low.length; i += 800) { const win = low.slice(i, i + max); const sc = ws.reduce((a, w) => a + (win.split(w).length - 1), 0); if (sc > bestScore) { bestScore = sc; best = i; } }
  return (best ? "… " : "") + t.slice(best, best + max) + "…";
}
async function ask(req, env) {
  if (!env.ANTHROPIC_API_KEY) return Response.json({ error: "API anahtarı tanımlı değil" }, { status: 503 });
  const token = (req.headers.get("Authorization") || "").replace(/^Bearer /, "");
  let j; try { j = await req.json(); } catch { return Response.json({ error: "bad json" }, { status: 400 }); }
  const q = String(j.q || "").trim().slice(0, 600);
  if (!token || q.length < 5) return Response.json({ error: "Soru eksik" }, { status: 400 });
  const H = { apikey: SB_KEY, Authorization: "Bearer " + token };
  const me = await fetch(SB_URL + "/rest/v1/rpc/is_active", { method: "POST", headers: { ...H, "Content-Type": "application/json" }, body: "{}" });
  if (!me.ok || (await me.json()) !== true) return Response.json({ error: "Yetkisiz" }, { status: 401 });
  const ws = stems(q);
  let rows = [];
  if (ws.length) {
    const or = ws.flatMap(w => [`title.ilike.*${w}*`, `metin.ilike.*${w}*`]).join(",");
    const r = await fetch(`${SB_URL}/rest/v1/items?select=id,tur,title,meta,url,metin,ozet&or=(${encodeURIComponent(or)})&order=id.desc&limit=60`, { headers: H });
    rows = r.ok ? await r.json() : [];
  }
  const scored = rows.map(x => { const tl = (x.title || "").toLocaleLowerCase("tr"), ml = (x.metin || x.ozet || "").toLocaleLowerCase("tr");
    const hit = ws.filter(w => tl.includes(w) || ml.includes(w)).length;
    const sc = ws.reduce((a, w) => a + 6 * (tl.split(w).length - 1) + Math.min(15, ml.split(w).length - 1), 0) + hit * 10;
    return { x, sc }; }).sort((a, b) => b.sc - a.sc).slice(0, 6).map(o => o.x);
  const sources = scored.map((x, i) => ({ n: i + 1, id: x.id, tur: x.tur, title: x.title, meta: x.meta }));
  const ctx = scored.map((x, i) => `[${i + 1}] ${x.tur} · ${x.title}${x.meta ? " · " + x.meta : ""}\n${excerpt(x.metin || x.ozet || "", ws, 5000)}`).join("\n\n---\n\n");
  const system = `Sen Türkiye vergi mevzuatında uzman, vergi müfettişlerine yardım eden bir asistansın. Yalnızca verilen kaynaklara dayan.
Kurallar: Türkçe, açık ve kısa yaz (en fazla 6 kısa paragraf ya da madde). Her bilginin sonuna dayandığı kaynağı [1], [2] biçiminde ekle.
Kaynaklarda cevap yoksa bunu açıkça söyle ve hangi tür mevzuata bakılması gerektiğini belirt; tahmin yürütme, madde numarası veya oran uydurma.
Markdown başlığı ve kalın yazı kullanma. Son satırda tek cümleyle müfettiş açısından dikkat edilecek noktayı yaz.`;
  const body = { model: env.ASK_MODEL || "claude-sonnet-5-5", max_tokens: 1400, system,
    messages: [{ role: "user", content: `Soru: ${q}\n\nKaynaklar:\n${ctx || "(Uygulamada eşleşen kayıt bulunamadı.)"}` }] };
  const r = await fetch("https://api.anthropic.com/v1/messages", { method: "POST", headers: { "x-api-key": env.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) return Response.json({ error: "Yapay zekâ yanıt vermedi (" + r.status + ")" }, { status: 502 });
  const d = await r.json();
  const answer = (d.content || []).filter(b => b.type === "text").map(b => b.text).join("").trim();
  return Response.json({ answer, sources });
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
    if (url.pathname === "/api/ask" && req.method === "POST") return ask(req, env);
    return env.ASSETS.fetch(req);
  }
};
