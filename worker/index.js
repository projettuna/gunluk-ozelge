// TMPRO Cloudflare Worker: statik uygulama (docs/) + anlık bildirim aktarıcısı (/api/push).
// Aktarıcı, yalnızca VAPID özel anahtarını bilen çağıranın (veritabanı tetikleyicisi) bildirimlerini gönderir;
// Apple/Google bu anahtarla imzalanmamış bildirimleri reddeder, bu yüzden ayrıca gizli anahtar gerekmez.

import MADDELER from "./maddeler.json";  // tools/madde_cek.py ile mevzuat.gov.tr'den alınan güncel madde metinleri

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
  const gun = new Date(today + "T12:00:00Z").toLocaleDateString("tr-TR", { day: "numeric", month: "long", weekday: "long", timeZone: "UTC" });
  lines.splice(special ? 1 : 0, 0, `📆 ${gun}`);
  if (u.news && typeof u.news === "object") {
    const ent = Object.entries(u.news), n = ent.reduce((a, [, c]) => a + c, 0);
    lines.push(n ? `📰 Son 24 saatte ${n} yeni kayıt: ${ent.slice(0, 4).map(([t, c]) => `${c} ${t}`).join(", ")}${ent.length > 4 ? "…" : ""}` : "📰 Son 24 saatte yeni mevzuat yok");
  } else if (u.news === null) lines.push("📰 Son 24 saatte yeni mevzuat yok");
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
const KARAR = /Danıştay|Anayasa|Yargıtay/i;
const stripHtml = h => String(h || "").replace(/<(script|style)[^>]*>[\s\S]*?<\/\1>/gi, " ").replace(/<br\s*\/?>|<\/p>|<\/div>/gi, "\n").replace(/<[^>]+>/g, " ")
  .replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/[ \t]+/g, " ").replace(/\n\s*\n+/g, "\n\n").trim();
// Danıştay karar arama (canlı). Erişilemezse sessizce boş döner.
async function danistayLive(q) {
  const words = [...new Set(q.toLocaleLowerCase("tr").replace(/[^a-zçğıöşü0-9 ]/g, " ").split(/\s+/).filter(w => w.length >= 5 && !STOP.has(w)))];
  const tries = [words.slice(0, 3), words.slice(0, 2)].filter(t => t.length);
  for (const kw of tries) {
    try {
      const r = await fetch("https://karararama.danistay.gov.tr/aramalist", { method: "POST", headers: { "Content-Type": "application/json; charset=UTF-8", "User-Agent": "Mozilla/5.0" },
        body: JSON.stringify({ data: { andKelimeler: kw, pageSize: 4, pageNumber: 1 } }), signal: AbortSignal.timeout(7000) });
      if (!r.ok) continue;
      const list = ((await r.json())?.data?.data || []).slice(0, 3);
      if (!list.length) continue;
      const docs = await Promise.all(list.map(async k => {
        const url = `https://karararama.danistay.gov.tr/getDokuman?id=${k.id}&arananKelime=${encodeURIComponent(kw.join(","))}`;
        try { const d = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0" }, signal: AbortSignal.timeout(7000) }); let t = await d.text(); try { t = JSON.parse(t).data || t; } catch {}
          return { tur: "Danıştay kararı", title: `${k.daireKurul || k.daire || "Danıştay"} E. ${k.esasNo || ""}, K. ${k.kararNo || ""}`, meta: k.kararTarihi || "", url, metin: stripHtml(t) }; } catch { return null; }
      }));
      return docs.filter(Boolean);
    } catch {}
  }
  return [];
}
// Danıştay karar aramasından birden çok kararın tam metni (içtihat yönü için)
async function danistayList(q, n) {
  try {
    const r = await fetch("https://karararama.danistay.gov.tr/aramalist", { method: "POST", headers: { "Content-Type": "application/json; charset=UTF-8", "User-Agent": "Mozilla/5.0" },
      body: JSON.stringify({ data: { andKelimeler: q.split(/\s+/).filter(w => w.length >= 3), pageSize: Math.min(20, n), pageNumber: 1 } }), signal: AbortSignal.timeout(8000) });
    if (!r.ok) return [];
    const list = ((await r.json())?.data?.data || []).slice(0, Math.min(20, n));
    const docs = await Promise.all(list.map(async k => {
      try { const d = await fetch(`https://karararama.danistay.gov.tr/getDokuman?id=${k.id}&arananKelime=${encodeURIComponent(q.split(/\s+/).join(","))}`, { headers: { "User-Agent": "Mozilla/5.0" }, signal: AbortSignal.timeout(8000) }); let t = await d.text(); try { t = JSON.parse(t).data || t; } catch {}
        return { title: `${k.daireKurul || k.daire || "Danıştay"} E. ${k.esasNo || ""}, K. ${k.kararNo || ""}`, meta: k.kararTarihi || "", metin: stripHtml(t) }; } catch { return null; }
    }));
    return docs.filter(Boolean);
  } catch { return []; }
}
async function ask(req, env) {
  if (!env.ANTHROPIC_API_KEY) return Response.json({ error: "API anahtarı tanımlı değil" }, { status: 503 });
  const token = (req.headers.get("Authorization") || "").replace(/^Bearer /, "");
  let j; try { j = await req.json(); } catch { return Response.json({ error: "bad json" }, { status: 400 }); }
  const hist = (Array.isArray(j.messages) ? j.messages : j.q ? [{ role: "user", content: j.q }] : []).slice(-10)
    .map((m, i, a) => ({ role: m.role === "assistant" ? "assistant" : "user", content: String(m.content || "").slice(0, i === a.length - 1 ? 8000 : 3000) })).filter(m => m.content);
  const last = hist[hist.length - 1];
  const files = (Array.isArray(j.files) ? j.files : []).slice(0, 4);
  if (!token || !last || last.role !== "user" || (last.content.length < 2 && !files.length)) return Response.json({ error: "Soru eksik" }, { status: 400 });
  const H = { apikey: SB_KEY, Authorization: "Bearer " + token };
  const me = await fetch(SB_URL + "/rest/v1/rpc/is_active", { method: "POST", headers: { ...H, "Content-Type": "application/json" }, body: "{}" });
  if (!me.ok || (await me.json()) !== true) return Response.json({ error: "Yetkisiz" }, { status: 401 });
  const qr = await fetch(SB_URL + "/rest/v1/rpc/ai_quota", { method: "POST", headers: { ...H, "Content-Type": "application/json" }, body: "{}" });
  const quota = qr.ok ? await qr.json() : null;
  if (quota && quota.limit != null && quota.used >= quota.limit)
    return Response.json({ error: `Bu ayki ${quota.limit} soru hakkınız doldu. Hakkınız ay başında yenilenir`, quota }, { status: 429 });
  const qText = hist.filter(m => m.role === "user").slice(-2).map(m => m.content).join(" ");
  const ws = stems(qText);
  let rows = [];
  if (ws.length) {
    const or = ws.flatMap(w => [`title.ilike.*${w}*`, `metin.ilike.*${w}*`]).join(",");
    const r = await fetch(`${SB_URL}/rest/v1/items?select=id,tur,title,meta,url,metin,ozet&or=(${encodeURIComponent(or)})&order=id.desc&limit=60`, { headers: H });
    rows = r.ok ? await r.json() : [];
  }
  const live = ws.length ? await danistayLive(qText) : [];
  const score = x => { const tl = (x.title || "").toLocaleLowerCase("tr"), ml = (x.metin || x.ozet || "").toLocaleLowerCase("tr");
    const hit = ws.filter(w => tl.includes(w) || ml.includes(w)).length;
    return ws.reduce((a, w) => a + 6 * (tl.split(w).length - 1) + Math.min(15, ml.split(w).length - 1), 0) + hit * 10 + (KARAR.test(x.tur || "") ? 40 : 0); };
  const local = rows.map(x => ({ x, sc: score(x) })).sort((a, b) => b.sc - a.sc).map(o => o.x);
  const nSrc = files.length ? 5 : 7;  // belge varsa daha az kaynak (maliyet)
  const picked = [...live.slice(0, 3), ...local.filter(x => KARAR.test(x.tur)).slice(0, 3), ...local.filter(x => !KARAR.test(x.tur)).slice(0, 3)].slice(0, nSrc);
  const sources = picked.map((x, i) => ({ n: i + 1, id: x.id || null, url: x.id ? null : x.url, tur: x.tur, title: x.title, meta: x.meta }));
  const ctx = picked.map((x, i) => `[${i + 1}] ${x.tur} · ${x.title}${x.meta ? " · " + x.meta : ""}\n${excerpt(x.metin || x.ozet || "", ws, 3000)}`).join("\n\n---\n\n");
  const system = `Sen Türkiye vergi mevzuatında ve vergi ceza hukukunda uzman, vergi müfettişlerine yardım eden bir asistansın. Kullanıcı bir vergi müfettişidir.
Öncelik sırası: önce yargı kararları (vergi suçları ve vergi kaçakçılığı/VUK 359 için Yargıtay ceza daireleri; vergi tarhiyatı ve cezalar için Danıştay; Anayasa Mahkemesi), sonra kanun, tebliğ, sirküler ve özelgeler. Kararlarda esas/karar numarasını ve kararın sonucunu belirt.
Verilen kaynaklara dayan ve her bilginin sonuna kaynağını [1], [2] biçiminde ekle. Kaynaklarda olmayan genel bilgiyi kullanırsan bunu "kaynaklarda yer almıyor, genel bilgi:" diye açıkça ayır; madde numarası, oran veya karar numarası uydurma.
Gizlilik: Yüklenen belge resmî yazı, inceleme raporu, tutanak, "gizli"/"hizmete özel" ibareli bir belge ise ya da gerçek bir mükellefin ad/unvan, TCKN/VKN, adres gibi kimlik bilgilerini içeriyorsa, yanıtının başına kısa bir uyarı ekle ("Bu belge vergi mahremiyeti kapsamında olabilir; bu tür belgeleri yüklemeyiniz.") ve yanıtında bu kişisel bilgileri asla tekrar etme, yalnızca genel mevzuat değerlendirmesi yap.
Kullanıcı fotoğraf veya belge yüklerse içeriğini müfettiş gözüyle incele: belge türü, tarih, taraflar, tutarlar, sahte veya muhteviyatı itibarıyla yanıltıcı belge işaretleri, eksik zorunlu bilgiler (VUK 230), tutarsızlıklar.
Bu bir sohbettir: önceki mesajları dikkate al, kısa ve net yaz, gerektiğinde maddeler kullan. Markdown başlığı ve kalın yazı kullanma.`;
  const lastBlocks = [];
  for (const f of files) {
    const data = String(f.data || "");
    if (!data || data.length > 7_000_000) continue;
    if (f.kind === "image" && /^image\/(jpeg|png|webp|gif)$/.test(f.media_type)) lastBlocks.push({ type: "image", source: { type: "base64", media_type: f.media_type, data } });
    else if (f.kind === "pdf") lastBlocks.push({ type: "document", source: { type: "base64", media_type: "application/pdf", data } });
  }
  lastBlocks.push({ type: "text", text: `${last.content || "Yüklediğim belgeyi incele."}\n\n(Uygulamadaki ilgili kaynaklar:)\n${ctx || "(Eşleşen kaynak bulunamadı.)"}` });
  const messages = [...hist.slice(0, -1), { role: "user", content: lastBlocks }];
  while (messages.length && messages[0].role !== "user") messages.shift();
  const body = { model: env.ASK_MODEL || "claude-sonnet-5-5", max_tokens: 1800, cache_control: { type: "ephemeral" }, system, messages };
  const call = b => fetch("https://api.anthropic.com/v1/messages", { method: "POST", headers: { "x-api-key": env.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json" }, body: JSON.stringify(b) });
  let r = await call(body);
  if (r.status === 400) { delete body.cache_control; r = await call(body); }  // önbellek desteklenmezse önbelleksiz dene
  if (!r.ok) { let m = ""; try { m = (await r.json())?.error?.message || ""; } catch {} return Response.json({ error: "Yapay zekâ yanıt vermedi (" + r.status + ") " + m.slice(0, 120) }, { status: 502 }); }
  const d = await r.json();
  const answer = (d.content || []).filter(b => b.type === "text").map(b => b.text).join("").trim();
  const used = await fetch(SB_URL + "/rest/v1/rpc/use_ai_quota", { method: "POST", headers: { ...H, "Content-Type": "application/json" }, body: "{}" }).catch(() => null);
  if (quota && quota.limit != null && used?.ok) quota.used += 1;
  return Response.json({ answer, sources, live: live.length, quota });
}

// ---- Rapor taslağı asistanı (/api/taslak): yalnızca konu + genel açıklama alır, mükellef bilgisi engellenir, taslak saklanmaz.
const TASLAK_COST = 6;
const TASLAK_TURLER = { inceleme: "Vergi İnceleme Raporu (tarhiyat)", vtr: "Vergi Tekniği Raporu (VTR)", suc: "Vergi Suçu Raporu (VUK 359, suç duyurusu)", bolum: "Tek bölüm / değerlendirme notu" };
const TASLAK_KONULAR = {
  sahte_kullanma: "sahte belge kullanımı, KDV indirimlerinin reddi",
  sahte_duzenleme: "sahte belge düzenleme",
  yaniltici: "muhteviyatı itibarıyla yanıltıcı belge düzenleme veya kullanma",
  kdv_iade: "KDV iadesi incelemesi",
  ortulu_sermaye: "örtülü sermaye",
  transfer: "transfer fiyatlandırması yoluyla örtülü kazanç dağıtımı",
  hasilat: "kayıt dışı hasılat, satış hasılatının gizlenmesi",
  ibraz: "defter ve belgelerin ibraz edilmemesi, takdir",
  ortaklar_cari: "ortaklar cari hesabı, adat hesaplaması",
  kkeg: "kanunen kabul edilmeyen giderler",
  degerleme: "değerleme hataları",
  gayrimenkul: "gayrimenkul satış kazancı, değer artışı kazancı",
  stopaj: "eksik tevkifat (stopaj) uygulaması",
  diger: "",
};
// Konu bazında kaynak arama ifadeleri (ilike kalıbı; "_" tek harf yerine geçer). Yargıtay ceza kararları yalnız suçla ilgili konularda.
const TASLAK_ARA = {
  sahte_kullanma: { p: ["sahte fatura", "sahte belge", "sahte_belge", "sahte faturalar"], ceza: true },
  sahte_duzenleme: { p: ["sahte fatura d_zenle", "sahte belge d_zenle", "sahte fatura", "sahte belge"], ceza: true },
  yaniltici: { p: ["muhteviyat_ _tibar", "yan_lt_c_ belge", "yan_lt_c_ fatura"], ceza: true },
  kdv_iade: { p: ["kdv iade", "katma de_er vergisi iade", "iade talebi", "iade alaca__"] },
  ortulu_sermaye: { p: ["_rt_l_ sermaye"] },
  transfer: { p: ["transfer fiyatland_rmas_", "_rt_l_ kazan_"] },
  hasilat: { p: ["kay_t d___", "has_lat_n", "has_lat gizle", "_effaf olmayan"] },
  ibraz: { p: ["ibraz edilme", "defter ve belgelerin ibraz", "takdir komisyon", "re'sen takdir"] },
  ortaklar_cari: { p: ["ortaklar cari", "adat", "_rt_l_ kazan_"] },
  kkeg: { p: ["kanunen kabul edilmeyen gider"] },
  degerleme: { p: ["de_erleme", "de_erlenmesi"] },
  gayrimenkul: { p: ["de_er art___ kazanc_", "gayrimenkul sat__", "ta__nmaz sat__"] },
  stopaj: { p: ["tevkifat", "stopaj"] },
};
// Konuya göre yapay zekâya verilecek güncel kanun maddeleri
const TASLAK_MADDE_ORTAK = ["VUK 3", "VUK 29", "VUK 30", "VUK 114", "VUK 134", "VUK 341", "VUK 344", "VUK 376", "VUK Ek 1"];
const TASLAK_MADDE = {
  sahte_kullanma: ["KDVK 29", "KDVK 34", "VUK 227", "VUK 230", "VUK 359", "VUK 367", "VUK 339", "VUK 336", "VUK 370"],
  sahte_duzenleme: ["VUK 227", "VUK 229", "VUK 230", "VUK 359", "VUK 367", "VUK 339", "KDVK 8"],
  yaniltici: ["KDVK 29", "KDVK 34", "VUK 230", "VUK 359", "VUK 367", "VUK 339"],
  kdv_iade: ["KDVK 29", "KDVK 30", "KDVK 32", "KDVK 34", "KDVK 9", "VUK 359"],
  ortulu_sermaye: ["KVK 12", "KVK 11"],
  transfer: ["KVK 13", "KVK 11"],
  hasilat: ["VUK 227", "VUK 359", "VUK 370", "VUK 371"],
  ibraz: ["VUK 139", "VUK 140", "VUK 141", "VUK 359"],
  ortaklar_cari: ["KVK 13", "KVK 11", "KVK 12"],
  kkeg: ["KVK 11", "GVK 41", "GVK 40"],
  degerleme: ["VUK 258"],
  gayrimenkul: ["GVK Mükerrer 80", "GVK Mükerrer 81"],
  stopaj: ["GVK 94", "VUK 11"],
  diger: [],
};
const ilike2re = p => new RegExp(p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/_/g, "."), "giu");
// Kimlik/mahremiyet bilgisi yakalayıcı (uygulamadaki ile aynı kurallar)
function piiFound(t) {
  const s = String(t || "");
  if (/(?<!\d)\d{10,11}(?!\d)/.test(s.replace(/(\d) (?=\d)/g, "$1"))) return "10-11 haneli numara (VKN/TCKN)";
  if (/\bTR\s?\d{2}(\s?\d{4}){5}\s?\d{2}\b/i.test(s) || /\bTR\d{24}\b/i.test(s.replace(/\s/g, ""))) return "IBAN";
  if (/[\w.+-]+@[\w-]+\.[\w.]+/.test(s)) return "e-posta adresi";
  if (/(\+?90|0)?\s?5\d{2}\s?\d{3}\s?\d{2}\s?\d{2}\b/.test(s)) return "telefon numarası";
  if (/\b(a\.?\s?ş\.?|ltd\.?|şti\.?|koll\.?|kom\.?)(?=\s|$|[,.;])/iu.test(s)) return "şirket unvanı";
  if (/\b(0[1-9]|[1-7]\d|8[01])\s?[A-ZÇĞİÖŞÜ]{1,3}\s?\d{2,4}\b/u.test(s)) return "araç plakası";
  if (/\b(mahalle|mah\.|sokak|sok\.|cadde|cad\.|bulvar|apt\.?)\b|\bno\s?:\s?\d/iu.test(s)) return "adres";
  return "";
}
async function taslak(req, env) {
  if (!env.ANTHROPIC_API_KEY) return Response.json({ error: "API anahtarı tanımlı değil" }, { status: 503 });
  const token = (req.headers.get("Authorization") || "").replace(/^Bearer /, "");
  let j; try { j = await req.json(); } catch { return Response.json({ error: "bad json" }, { status: 400 }); }
  const tur = TASLAK_TURLER[j.tur] ? j.tur : "inceleme", konuKey = j.konu in TASLAK_KONULAR ? j.konu : "diger";
  const donem = /^\d{4}$/.test(String(j.donem || "")) ? String(j.donem) : "";
  const aciklama = String(j.aciklama || "").slice(0, 800).trim();
  const konu = TASLAK_KONULAR[konuKey] || aciklama.slice(0, 120);
  if (!token) return Response.json({ error: "Yetkisiz" }, { status: 401 });
  if (!konu) return Response.json({ error: "Konu seçin ya da kısa bir açıklama yazın" }, { status: 400 });
  const pii = piiFound(aciklama);
  if (pii) return Response.json({ error: `Açıklamada ${pii} olabilecek bir bilgi var. Mükellefe ait hiçbir bilgi yazmayınız; genel ifade kullanın.` }, { status: 422 });
  const H = { apikey: SB_KEY, Authorization: "Bearer " + token }, J = { ...H, "Content-Type": "application/json" };
  const me = await fetch(SB_URL + "/rest/v1/rpc/is_active", { method: "POST", headers: J, body: "{}" });
  if (!me.ok || (await me.json()) !== true) return Response.json({ error: "Yetkisiz" }, { status: 401 });
  const qr = await fetch(SB_URL + "/rest/v1/rpc/ai_quota", { method: "POST", headers: J, body: "{}" });
  const quota = qr.ok ? await qr.json() : null;
  if (quota && quota.limit != null && Math.max(0, quota.limit - quota.used) + (quota.credits || 0) < TASLAK_COST)
    return Response.json({ error: `Taslak için ${TASLAK_COST} hak gerekir. Kalan hakkınız yetmiyor; Asistan bölümünden kredi yükleyebilirsiniz.`, quota }, { status: 429 });
  const qText = `${konu} ${aciklama}`;
  const ws = stems(qText), ara = TASLAK_ARA[konuKey];
  const cezaOk = tur === "suc" || !!ara?.ceza;
  let rows = [], res = [];
  if (ara) {
    res = ara.p.map(ilike2re);
    const or = ara.p.flatMap(w => [`title.ilike.*${w}*`, `metin.ilike.*${w}*`]).join(",");
    const r = await fetch(`${SB_URL}/rest/v1/items?select=id,tur,title,meta,url,metin,ozet&or=(${encodeURIComponent(or)})&order=id.desc&limit=120`, { headers: H });
    rows = r.ok ? await r.json() : [];
  } else if (ws.length) {
    const or = ws.flatMap(w => [`title.ilike.*${w}*`, `metin.ilike.*${w}*`]).join(",");
    const r = await fetch(`${SB_URL}/rest/v1/items?select=id,tur,title,meta,url,metin,ozet&or=(${encodeURIComponent(or)})&order=id.desc&limit=80`, { headers: H });
    rows = r.ok ? await r.json() : [];
  }
  if (!cezaOk) rows = rows.filter(x => !/Yargıtay/i.test(x.tur || ""));
  const live = await danistayLive(ara ? ara.p.filter(x => !x.includes("_")).slice(0, 1).join(" ") || konu : konu);
  // Puan: konu ifadelerinin başlık ve metinde geçme sayısı; ifadesi az geçen (ilgisiz) kayıtlar elenir
  const score = x => { const tl = x.title || "", ml = x.metin || x.ozet || "";
    if (res.length) return res.reduce((a, re) => a + 8 * (tl.match(re) || []).length + Math.min(12, (ml.match(re) || []).length), 0) + (KARAR.test(x.tur || "") ? 6 : 0);
    const tll = tl.toLocaleLowerCase("tr"), mll = ml.toLocaleLowerCase("tr");
    return ws.reduce((a, w) => a + 6 * (tll.split(w).length - 1) + Math.min(15, mll.split(w).length - 1), 0); };
  const MIN = res.length ? 9 : 20;
  const local = rows.map(x => ({ x, sc: score(x) })).filter(o => o.sc >= MIN).sort((a, b) => b.sc - a.sc).map(o => o.x);
  const yg = x => /Yargıtay/i.test(x.tur || "");  // inceleme raporu/VTR'de ceza kararı en fazla 1, suç raporunda öncelikli
  const kar = local.filter(x => KARAR.test(x.tur) && !yg(x)), ceza = local.filter(yg);
  const picked = [...(tur === "suc" ? ceza.slice(0, 4) : []), ...live.slice(0, 3), ...kar.slice(0, 4), ...(tur === "suc" ? [] : ceza.slice(0, 1)), ...local.filter(x => !KARAR.test(x.tur)).slice(0, 2)].slice(0, 8);
  const sources = picked.map((x, i) => ({ n: i + 1, id: x.id || null, url: x.id ? null : x.url, tur: x.tur, title: x.title, meta: x.meta }));
  const exWs = res.length ? ara.p.map(p => p.split("_")[0].toLocaleLowerCase("tr")).filter(w => w.length > 3) : ws;
  // Her karar için konuyla ilgili bölüm + kararın sonuç (hüküm) kısmı: onama/bozma/red bilgisi doğrudan metinden gelsin
  const sonuc = t => { t = String(t || "").trim(); if (t.length < 4500) return ""; const tail = t.slice(-1800); const at = tail.search(/(açıklanan nedenlerle|sonuç ?:|bu nedenlerle|hüküm ?:|gerekçeyle)/i); return tail.slice(at > 0 ? at : 0).trim(); };
  const ctx = picked.map((x, i) => { const t = x.metin || x.ozet || "", son = KARAR.test(x.tur || "") ? sonuc(t) : "";
    return `[${i + 1}] ${x.tur} · ${x.title}${x.meta ? " · " + x.meta : ""}\n${excerpt(t, exWs, son ? 4000 : 4500)}${son ? `\n[Kararın sonuç kısmı:] …${son}` : ""}`; }).join("\n\n---\n\n");
  const mKeys = [...new Set([...(TASLAK_MADDE[konuKey] || []), ...TASLAK_MADDE_ORTAK, ...(tur === "suc" ? ["VUK 359", "VUK 367"] : [])])].filter(k => MADDELER[k]);
  const mText = mKeys.map(k => `${k}${MADDELER[k].baslik ? " (" + MADDELER[k].baslik + ")" : ""}:\n${MADDELER[k].metin}`).join("\n\n---\n\n");
  const system = `Sen Türkiye vergi mevzuatında uzman, vergi müfettişlerine rapor yazımında yardımcı olan bir asistansın. Görevin, verilen konu için kullanılabilir bir RAPOR TASLAĞI İSKELETİ hazırlamaktır.
Kurallar:
- Gerçek bir mükellef hakkında hiçbir bilgi bilmiyorsun ve uydurmayacaksın. Mükellefe, döneme, tutara, tarihe, belgeye ilişkin her somut bilgi yerine KÖŞELİ PARANTEZ içinde BÜYÜK HARFLE yer tutucu kullan: [MÜKELLEF], [VKN], [DÖNEM], [TUTAR], [FATURA SAYISI], [TESPİT TARİHİ], [TUTANAK TARİHİ] gibi.
- Yasal dayanakları (kanun ve madde), tebliğ ve sirkülerleri, yargı kararlarını esas al. Verilen kaynaklara dayandığın yerde [1], [2] biçiminde kaynak göster. Kaynaklarda olmayan bir madde, karar numarası veya oran yazarsan sonuna "(teyit ediniz)" ekle; karar numarası uydurma, emin değilsen numara yazma.
- Yapı: numaralı ana başlıklar (1., 2., ...) ve alt başlıklar (1.1, 1.2) kullan; her başlık altında müfettişin doldurabileceği kalıp paragraflar ve gerekli yerlerde doldurulacak boş tablo satırları (sütunları | ile ayırarak) yaz.
- Bölüm düzeni: aşağıda "Rapor düzeni" olarak verilen ana bölümleri bu sırayla ve bu adlarla kullan.
- Raporun bitiminden sonra "KONTROL LİSTESİ (rapora dahil değildir)" başlığı altında raporu tamamlamadan önce müfettişin teyit etmesi gereken 6-10 maddelik kısa bir liste ver (zamanaşımı, tebliğ, ilgili dönem mevzuatı, kurumun güncel rapor yazım esasları vb.).
- Kaynakların ilgili olup olmadığı hakkında yorum veya ön not yazma; konuyla ilgisiz bir kaynak varsa hiç anma. Doğrudan rapor başlığıyla başla.
- Vergi İnceleme Raporu ve VTR'de vergi suçu değerlendirmesini ayrı bölüm olarak yazma; yalnızca sonuç bölümünde "VUK 359 kapsamındaki fiiller için ayrıca Vergi Suçu Raporu düzenlenmiştir/düzenlenecektir (VUK 367)" cümlesine yer ver.
- Taslak eksiksiz bitmeli: toplam uzunluğu yaklaşık 9.000 karakteri geçmesin, tabloları 1-2 örnek satırla sınırla, tekrar yapma. Kontrol listesini mutlaka tamamla.
- Sana "Güncel kanun metinleri" başlığı altında mevzuat.gov.tr'deki güncel madde metinleri verilecek. Bu maddelerin içeriğini, fıkra ve bentlerini, oranlarını ve istisnalarını yalnızca bu metinlere dayanarak yaz; bu maddeler için "(teyit ediniz)" ekleme. Metni verilmeyen maddeler için hafızana dayanıyorsan "(teyit ediniz)" ekle.
- Yargı kararları bölümünde, verilen kaynaklardaki konuyla ilgili her yargı kararını ayrı bir alt başlıkta ([n] numarasıyla) kısaca özetle ve somut olaya nasıl uygulanacağını belirt; bu kararları değerlendirme bölümünde de ilgili yerde [n] ile an. Konuyla gerçekten ilgisiz bir karar varsa hiç anma.
- Kararlarda "[Kararın sonuç kısmı:]" verilmişse kararın sonucunu (onama, bozma, kabul, red, ısrar vb.) bu kısımdan açıkça yaz; bu durumda sonuç için "(teyit ediniz)" ekleme. Sonuç kısmı verilmemişse sonucu tahmin etme.
- Madde atıflarında aşağıdaki doğru eşleştirmelerle çelişme:
  VUK 3/B gerçek mahiyet ve ispat; VUK 30 re'sen takdir; VUK 114 tarh zamanaşımı; VUK 134-141 vergi incelemesi (135 yetkililer, 139 işyerinde inceleme, 140 inceleme esasları, 141 tutanak); VUK 227 ve 229-232 belge düzeni/fatura; VUK 336 cezaların içtimaı; VUK 339 tekerrür; VUK 341 vergi ziyaı; VUK 344/1 bir kat, 344/2 VUK 359'daki fiillerle ziyada üç kat vergi ziyaı cezası; VUK 359/a-1 defter ve kayıt hileleri, 359/a-2 muhteviyatı itibarıyla yanıltıcı belge düzenleme veya kullanma, 359/b sahte belge düzenleme veya kullanma; VUK 367 suç duyurusu; VUK 370 izaha davet; VUK 371 pişmanlık ve ıslah; VUK 376 ceza indirimi; VUK Ek 1 vd. uzlaşma; İYUK 7 dava açma süresi. KDVK 29/1 indirim, 34/1 indirimin belgeye dayanması, 32 iade. KVK 11 kanunen kabul edilmeyen giderler, KVK 12 örtülü sermaye, KVK 13 transfer fiyatlandırması yoluyla örtülü kazanç dağıtımı. GVK 41 kabul edilmeyen giderler, GVK 94 tevkifat, GVK mükerrer 80-81 değer artışı kazançları. VUK 258 vd. değerleme.
- Uygulama gerçekliği: beyanname verilmiş dönemde inceleme sonucu bulunan fark için tarh türü kural olarak ikmalen tarhtır (VUK 29); re'sen tarhı (VUK 30) yalnızca defter ve belgelerin ibraz edilmemesi gibi takdir hâllerinde öner. Sahte veya yanıltıcı belge konularında "Düzenleyici hakkındaki tespitlerin kullanıcı nezdinde somutlaştırılması" başlıklı ayrı bir alt bölüm yaz: Danıştay'ın yerleşik içtihadına göre düzenleyici hakkındaki vergi tekniği raporu tek başına yeterli değildir; kullanıcı nezdinde karşıt inceleme, mal hareketi, stok ve üretim kayıtları, sevk ve taşıma belgeleri, ödemenin akıbeti gibi somut tespitler gerekir. Sahte belge kullanımında özel usulsüzlük cezasını (VUK 353) ayrı başlık yapma. VUK 359'daki fiillerle vergi ziyaına sebebiyet verilmesi hâlinde (üç kat vergi ziyaı cezası) tarhiyat sonrası uzlaşma yapılamaz (VUK Ek 1); bu durumda sonuç bölümünde uzlaşma hakkından söz etme, yalnızca dava yolunu (İYUK 7) belirt. Kaynakta geçse bile konuya özgü olmayan af, yapılandırma veya matrah artırımı kanunlarına değinme.
- Düz metin yaz; Markdown işareti (#, **, *) kullanma. Resmî ve sade bir dil kullan.`;
  const zorunlu = [
    tur !== "bolum" && konuKey !== "ibraz" ? "Tarhiyat önerisinde \"ikmalen tarh (VUK 29)\" ifadesini kullan; re'sen tarh önerme." : "",
    ["sahte_kullanma", "sahte_duzenleme", "yaniltici"].includes(konuKey) ? "\"Düzenleyici hakkındaki tespitlerin kullanıcı nezdinde somutlaştırılması\" başlıklı alt bölüm yaz ve içinde düzenleyici hakkındaki raporun tek başına yeterli olmadığını belirten Danıştay ilkesini açıkla." : "",
    ["sahte_kullanma", "sahte_duzenleme", "yaniltici"].includes(konuKey) ? "Özel usulsüzlük cezasına (VUK 353) yer verme." : "",
  ].filter(Boolean);
  // Vergi İncelemelerinde Uyulacak Usul ve Esaslar Hakkında Yönetmelik md. 19/4: tarhiyat/ceza önerili raporlar giriş, usul incelemeleri, hesap incelemeleri, eleştirilen hususlar ve sonuç bölümlerinden oluşur
  const DUZEN = {
    inceleme: `1. GİRİŞ: inceleme nedeni ve görevlendirme, incelenen vergi türü ve dönem (rapor vergi türü ve dönemi itibarıyla ayrı düzenlenir), mükellef hakkında genel bilgiler (yer tutucularla), incelemenin yapılışı
2. USUL İNCELEMELERİ: defter ve belgelerin istenmesi ve ibrazı, defterlerin tasdiki ve kayıt düzeni, beyannamelerin verilme durumu, belge düzenine uygunluk
3. HESAP İNCELEMELERİ: konuyla ilgili hesapların ve kayıtların incelenmesi, tespitler, karşıt inceleme ve yoklama sonuçları (tablolar)
4. ELEŞTİRİLEN HUSUSLAR: eleştiri konusu tespitler, yasal dayanak, yargı kararları, mükellefin itiraz ve mülahazaları ile bunların değerlendirilmesi, matrah ve vergi farkının hesaplanması
5. SONUÇ: önerilen vergi ve ceza tutarları tereddüde yer vermeyecek açıklıkta (tablo), tarh şekli, ceza türü ve oranı, raporun rapor değerlendirme komisyonuna sunulacağı, varsa ayrıca düzenlenecek Vergi Suçu Raporu`,
    vtr: `1. GİRİŞ: raporun düzenlenme nedeni, incelenen kişi ve dönem (yer tutucularla)
2. TESPİTLER: yoklama, karşıt inceleme, banka ve ödeme, kapasite, beyan ve bildirim analizleri
3. DEĞERLENDİRME: yasal dayanak, yargı kararları, belgelerin niteliği (sahte / muhteviyatı itibarıyla yanıltıcı) ve dönem bazında sonuçlar
4. SONUÇ: düzenlenen/kullanılan belgelerin niteliği ve dönemleri, ilgili birimlere gönderilecek bilgiler (tablo)`,
    suc: `1. GİRİŞ: raporun düzenlenme nedeni, ilgili inceleme veya vergi tekniği raporu (yer tutucularla)
2. FAİL VE FİİLLER: fail(ler), sorumlu kişiler, fiiller ve dönemleri
3. TESPİTLER VE DELİLLER
4. SUÇUN YASAL UNSURLARI VE DEĞERLENDİRME: VUK 359 ilgili bent, maddi ve manevi unsur (kast), fiil-dönem ilişkisi, yargı kararları
5. SONUÇ: suç duyurusu önerisi (VUK 367), ilgili Cumhuriyet başsavcılığı`,
    bolum: `Yalnızca tek bir "ELEŞTİRİLEN HUSUSLAR / DEĞERLENDİRME" bölümü: tespit, yasal dayanak, yargı kararları, itiraz ve mülahazaların değerlendirmesi, sonuç paragrafı`,
  };
  const user = `Rapor türü: ${TASLAK_TURLER[tur]}\nRapor düzeni:\n${DUZEN[tur]}\nKonu: ${konu}${donem ? `\nİncelenen dönem: ${donem}` : ""}${aciklama ? `\nGenel açıklama (mükellef bilgisi içermez): ${aciklama}` : ""}${zorunlu.length ? "\nZorunlu kurallar:\n- " + zorunlu.join("\n- ") : ""}${mText ? `\n\n(Güncel kanun metinleri, mevzuat.gov.tr:)\n${mText}` : ""}\n\n(Uygulamadaki ilgili kaynaklar:)\n${ctx || "(Eşleşen kaynak bulunamadı.)"}`;
  // En yüksek doğruluk: Opus 5.5, uyarlamalı düşünme, yüksek efor. Uzun sürebildiği için akış (stream) ile alınır.
  const body = { model: env.TASLAK_MODEL || "claude-opus-5-5", max_tokens: 32000, stream: true, output_config: { effort: env.TASLAK_EFFORT || "high" }, system, messages: [{ role: "user", content: user }] };
  const call = b => fetch("https://api.anthropic.com/v1/messages", { method: "POST", headers: { "x-api-key": env.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json" }, body: JSON.stringify(b) });
  let r = await call(body);
  if (r.status === 400) { delete body.output_config; r = await call(body); }
  if (!r.ok) { let m = ""; try { m = (await r.json())?.error?.message || ""; } catch {} return Response.json({ error: "Yapay zekâ yanıt vermedi (" + r.status + ") " + m.slice(0, 120) }, { status: 502 }); }
  const d = { content: [{ type: "text", text: "" }], model: "", stop_reason: "", usage: {} }, kinds = new Set();
  { const rd = r.body.getReader(), dec = new TextDecoder(); let buf = "";
    for (;;) { const { value, done } = await rd.read(); if (done) break; buf += dec.decode(value, { stream: true });
      let k; while ((k = buf.indexOf("\n\n")) >= 0) { const ev = buf.slice(0, k); buf = buf.slice(k + 2);
        const line = ev.split("\n").find(x => x.startsWith("data: ")); if (!line) continue; let e; try { e = JSON.parse(line.slice(6)); } catch { continue; }
        if (e.type === "message_start") { d.model = e.message?.model; d.usage.input_tokens = e.message?.usage?.input_tokens; }
        else if (e.type === "content_block_start") kinds.add(e.content_block?.type);
        else if (e.type === "content_block_delta" && e.delta?.type === "text_delta") d.content[0].text += e.delta.text;
        else if (e.type === "message_delta") { d.stop_reason = e.delta?.stop_reason || d.stop_reason; d.usage.output_tokens = e.usage?.output_tokens; }
        else if (e.type === "error") return Response.json({ error: "Yapay zekâ yanıtı yarıda kesildi, tekrar deneyin (" + (e.error?.type || "hata") + ")" }, { status: 502 }); } } }
  if (!d.content[0].text) d.content = [...kinds].map(t => ({ type: t }));
  let draft = (d.content || []).filter(b => b.type === "text").map(b => b.text).join("").replace(/\*\*|^#+\s*/gm, "").trim();
  // Atıf denetimi: taslaktaki her esas/karar numarası (2024/123 biçimi) verilen kaynaklarda geçmiyorsa işaretlenir
  let unverified = 0;
  if (draft) {
    const known = ctx + " " + mText + " " + picked.map(x => `${x.title || ""} ${x.meta || ""}`).join(" ");
    // yalnızca esas/karar numarası bağlamındakiler (E. 2024/12, K. 2025/5, 2024/11-280 E.); dönem ifadeleri (2024/12 dönemi) denetlenmez
    const flag = (m0, num) => known.includes(num) ? m0 : (unverified++, `${m0} [KAYNAKTA YOK, TEYİT EDİNİZ]`);
    draft = draft.replace(/\b(?:E|K|Esas|Karar)(?:\s*No)?\s*[.:]?\s*((?:19|20)\d{2}\/\d{1,6}(?:-\d{1,6})?)\b(?![^\n]{0,40}teyit)/g, flag)
                 .replace(/\b((?:19|20)\d{2}\/\d{1,6}(?:-\d{1,6})?)\s*(?:E|K)\.(?![^\n]{0,40}(?:teyit|KAYNAKTA))/g, flag);
  }
  // Kaynakça yalnızca metinde atıf yapılan kaynakları gösterir
  const cited = new Set([...draft.matchAll(/\[(\d{1,2})\]/g)].map(m => +m[1]));
  const shown = cited.size ? sources.filter(x => cited.has(x.n)) : sources;
  if (draft && d.stop_reason === "max_tokens") draft += "\n\n(Taslak uzunluk sınırında kesildi; kalan kısmı için konuyu daraltıp \"Tek Bölüm\" seçeneğiyle tekrar deneyebilirsiniz.)";
  if (!draft) return Response.json({ error: `Taslak üretilemedi, tekrar deneyin (${d.stop_reason || "?"}; ${(d.content || []).map(b => b.type).join(",") || "boş"})` }, { status: 502 });
  let n = 0;
  for (let i = 0; i < TASLAK_COST; i++) { const u = await fetch(SB_URL + "/rest/v1/rpc/use_ai_quota", { method: "POST", headers: J, body: "{}" }).catch(() => null); if (u?.ok && (await u.json()) === true) n++; }
  if (quota && quota.limit != null) { const free = Math.max(0, quota.limit - quota.used), f = Math.min(free, n); quota.used += f; quota.credits = Math.max(0, (quota.credits || 0) - (n - f)); }
  return Response.json({ draft, sources: shown, quota, cost: n, unverified, maddeler: mKeys.length, model: d.model, stop: d.stop_reason, usage: d.usage && { in: d.usage.input_tokens, out: d.usage.output_tokens } });
}

// ---- Döviz (TCMB) ve altın: tarayıcı bu kaynaklara doğrudan erişemediği için worker üzerinden, önbellekli
// ---- İçtihat yönü (/api/ictihat): konudaki Danıştay kararlarının sonucu ve kimin lehine olduğu (metinden kural tabanlı; yapay zekâ yok)
function hukumOf(t) {
  t = String(t || "").trim();
  const ko = t.search(/\n\s*(\(x\)\s*)?(karşı oy|ayrışık oy|azlık oyu)/i); if (ko > 0) t = t.slice(0, ko);
  const re = /(açıklanan nedenlerle|sonuç ?:|bu nedenlerle|hüküm ?:|gerekçelerle)/gi; let at = -1, m;
  while ((m = re.exec(t))) at = m.index;
  return at >= 0 && t.length - at < 4000 ? t.slice(at).trim() : "";
}
function kararYonu(h) {
  const l = h.toLocaleLowerCase("tr").replace(/\s+/g, " ");
  let sonuc = "Belirsiz";
  if (/kısmen (kabul|bozul|onan)/.test(l)) sonuc = "Kısmen";
  else if (/bozulmasına/.test(l)) sonuc = "Bozma";
  else if (/onanmasına|temyiz (istem|talep)\w* reddine/.test(l)) sonuc = "Onama";
  else if (/ısrar/.test(l)) sonuc = "Israr";
  let lehine = null;
  const ms = [...l.matchAll(/(davacı\w*|davalı\w*(?: idare\w*)?)[^.;:]{0,70}?temyiz (?:istem|talep)\w* (kısmen )?(kabulüne|reddine)/g)];
  const ls = [...new Set(ms.map(m => m[2] ? "kismen" : (m[3] === "kabulüne") === /davacı/.test(m[1]) ? "mukellef" : "idare"))];
  if (ls.length) lehine = ls.length === 1 ? ls[0] : "kismen";
  return { sonuc, lehine };
}
async function ictihat(req, env, url) {
  const token = (req.headers.get("Authorization") || "").replace(/^Bearer /, "");
  if (!token) return Response.json({ error: "Yetkisiz" }, { status: 401 });
  const H = { apikey: SB_KEY, Authorization: "Bearer " + token };
  const me = await fetch(SB_URL + "/rest/v1/rpc/is_active", { method: "POST", headers: { ...H, "Content-Type": "application/json" }, body: "{}" });
  if (!me.ok || (await me.json()) !== true) return Response.json({ error: "Yetkisiz" }, { status: 401 });
  const konu = url.searchParams.get("konu") || "";
  const ifade = (url.searchParams.get("ifade") || "").replace(/[^\p{L}\p{N} ]/gu, " ").replace(/\s+/g, " ").trim().slice(0, 40);
  const ps = TASLAK_ARA[konu]?.p || (ifade.length >= 4 ? [ifade] : null);
  if (!ps) return Response.json({ error: "Konu seçin ya da en az 4 harflik bir ifade yazın" }, { status: 400 });
  return cached("ictihat6:" + (TASLAK_ARA[konu] ? konu : "q:" + ifade.toLocaleLowerCase("tr")), 1800, async () => {
    const or = ps.flatMap(w => [`title.ilike.*${w}*`, `metin.ilike.*${w}*`]).join(",");
    const r = await fetch(`${SB_URL}/rest/v1/items?select=id,tur,title,meta,metin&tur=ilike.Dan*&or=(${encodeURIComponent(or)})&order=id.desc&limit=160`, { headers: H });
    if (!r.ok) return { error: "Kararlar alınamadı" };
    const res = ps.map(ilike2re);
    const rows = (await r.json()).map(x => {
      const ml = x.metin || "", hits = res.reduce((a, re) => a + (ml.match(re) || []).length + 3 * ((x.title || "").match(re) || []).length, 0);
      const h = hukumOf(ml);
      return { id: x.id, tur: x.tur, title: x.title, meta: x.meta, hits, hukum: h.slice(0, 700), ...kararYonu(h) };
    }).filter(x => x.hits >= 2 && x.hukum);
    // Veritabanındaki kararlar azsa Danıştay karar aramasından güncel kararlarla tamamla
    let canli = 0;
    if (rows.length < 25) {
      const q = ps.find(x => !x.includes("_")) || ps[0].replace(/_/g, "");
      const live = await danistayList(q, 25 - rows.length); canli = live.length;
      const seen = new Set(rows.map(x => (x.title || "").replace(/\s+/g, "")));
      for (const x of live) { const h = hukumOf(x.metin); if (!h || seen.has(x.title.replace(/\s+/g, ""))) continue;
        rows.push({ id: null, tur: "Danıştay kararı", title: x.title, meta: x.meta, hukum: h.slice(0, 700), ...kararYonu(h) }); }
    }
    const say = k => rows.filter(x => x.lehine === k).length;
    return { n: rows.length, canli, ozet: { mukellef: say("mukellef"), idare: say("idare"), kismen: say("kismen"), belirsiz: say(null) },
      sonuc: ["Onama", "Bozma", "Kısmen", "Israr", "Belirsiz"].map(k => [k, rows.filter(x => x.sonuc === k).length]),
      list: rows.slice(0, 40).map(({ hits, ...x }) => x) };
  });
}
async function cached(key, ttl, make) {
  const c = caches.default, k = new Request("https://cache.tmpro/" + key);
  const hit = await c.match(k); if (hit) return hit;
  const body = await make();
  const res = new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json", "Cache-Control": `public, max-age=${ttl}` } });
  if (!body.error) await c.put(k, res.clone());
  return res;
}
const num = v => { const n = parseFloat(String(v || "").replace(",", ".")); return isFinite(n) && n > 0 ? n : null; };
async function tcmb(iso) {
  // Hafta sonu / tatil: geriye doğru en fazla 10 gün aranır
  const d0 = iso ? new Date(iso + "T12:00:00Z") : null;
  for (let i = 0; i < 11; i++) {
    let u;
    if (!d0 && i === 0) u = "https://www.tcmb.gov.tr/kurlar/today.xml";
    else { const d = new Date((d0 || new Date()).getTime() - (d0 ? i : i) * 864e5); const dd = String(d.getUTCDate()).padStart(2, "0"), mm = String(d.getUTCMonth() + 1).padStart(2, "0"), yy = d.getUTCFullYear();
      u = `https://www.tcmb.gov.tr/kurlar/${yy}${mm}/${dd}${mm}${yy}.xml`; }
    let r; try { r = await fetch(u, { headers: { "User-Agent": "TMPRO-kur" }, cf: { cacheTtl: 900 } }); } catch { continue; }
    if (!r.ok) continue;
    const x = await r.text(); const t = (x.match(/Tarih="([\d.]+)"/) || [])[1]; if (!t) continue;
    const kurlar = [...x.matchAll(/<Currency[^>]*Kod="([A-Z]+)"[^>]*>([\s\S]*?)<\/Currency>/g)].map(([, kod, b]) => {
      const g = tag => (b.match(new RegExp(`<${tag}>([^<]*)</${tag}>`)) || [])[1];
      return { kod, ad: g("Isim"), birim: +g("Unit") || 1, alis: num(g("ForexBuying")), satis: num(g("ForexSelling")), efAlis: num(g("BanknoteBuying")), efSatis: num(g("BanknoteSelling")) };
    }).filter(k => k.alis || k.satis);
    if (kurlar.length) return { tarih: t, kurlar };
  }
  return { error: "kur alınamadı" };
}
async function metal(sym) {
  try { const r = await fetch(`https://api.gold-api.com/price/${sym}`, { headers: { "User-Agent": "TMPRO-kur" } }); if (!r.ok) return null; const j = await r.json(); return num(j.price) ? { usd: num(j.price), at: j.updatedAt || null } : null; } catch { return null; }
}

// ---- Zamanlayıcı: GitHub Actions taramalarını zamanında başlatır
async function dispatch(env, wf, inputs) {
  const r = await fetch(`https://api.github.com/repos/${env.GH_REPO || "projettuna/gunluk-ozelge"}/actions/workflows/${wf}/dispatches`, {
    method: "POST",
    headers: { "Authorization": `Bearer ${env.GH_DISPATCH_TOKEN}`, "Accept": "application/vnd.github+json", "User-Agent": "TMPRO-zamanlayici", "Content-Type": "application/json" },
    body: JSON.stringify({ ref: "main", inputs: inputs || {} })
  });
  return r.status;
}
async function tick(when, env) {
  if (!env.GH_DISPATCH_TOKEN) return "token yok";
  const tr = new Date(when + 3 * 3600e3), h = tr.getUTCHours(), m = tr.getUTCMinutes(), wd = tr.getUTCDay();
  const jobs = [];
  const busy = wd >= 1 && wd <= 5 && h >= 8 && h < 19;
  if (busy) jobs.push(["gunluk.yml", { auto: "1" }]);                 // hafta içi mesai: 5 dakikada bir
  else if (h === 0) jobs.push(["gunluk.yml", { auto: "rg" }]);        // gece 00-01: Resmî Gazete
  else if (m >= 5 && m < 10) jobs.push(["gunluk.yml", { auto: "1" }]); // diğer saatler: saatte bir
  if (m % 15 >= 3 && m % 15 < 8) jobs.push(["saglik.yml", {}]);        // nöbetçi: 15 dakikada bir
  const res = await Promise.all(jobs.map(([wf, inp]) => dispatch(env, wf, inp).catch(() => 0)));
  return jobs.map((j, i) => `${j[0]}:${res[i]}`).join(" ");
}

export default {
  async scheduled(event, env, ctx) { ctx.waitUntil(tick(event.scheduledTime, env)); },
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
    if (url.pathname === "/api/taslak" && req.method === "POST") return taslak(req, env);
    if (url.pathname === "/api/ictihat") return ictihat(req, env, url);
    if (url.pathname === "/api/zaman") {  // nöbetçi için: zamanlayıcı anahtarı var mı, GitHub kabul ediyor mu (anahtarın kendisi asla dönmez)
      if (!env.GH_DISPATCH_TOKEN) return Response.json({ anahtar: false, github: 0 });
      const r = await fetch(`https://api.github.com/repos/${env.GH_REPO || "projettuna/gunluk-ozelge"}/actions/workflows/gunluk.yml`, {
        headers: { "Authorization": `Bearer ${env.GH_DISPATCH_TOKEN}`, "Accept": "application/vnd.github+json", "User-Agent": "TMPRO-zamanlayici" }
      }).catch(() => null);
      return Response.json({ anahtar: true, github: r ? r.status : 0 });
    }
    if (url.pathname === "/api/kur") {
      const t = url.searchParams.get("tarih"); const iso = /^\d{4}-\d{2}-\d{2}$/.test(t || "") ? t : null;
      return cached("kur-" + (iso || "bugun"), iso ? 86400 : 1800, () => tcmb(iso));
    }
    if (url.pathname === "/api/altin") {
      return cached("altin", 300, async () => {
        const [xau, xag, k] = await Promise.all([metal("XAU"), metal("XAG"), tcmb(null)]);
        const usd = k.kurlar?.find(x => x.kod === "USD")?.satis || null;
        if (!xau || !usd) return { error: "altın fiyatı alınamadı" };
        return { onsUsd: xau.usd, gumusOnsUsd: xag?.usd || null, usdTry: usd, kurTarih: k.tarih, at: xau.at || new Date().toISOString() };
      });
    }
    return env.ASSETS.fetch(req);
  }
};
