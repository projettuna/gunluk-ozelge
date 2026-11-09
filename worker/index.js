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

// ---- Döviz (TCMB) ve altın: tarayıcı bu kaynaklara doğrudan erişemediği için worker üzerinden, önbellekli
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
