"""Haberler sekmesi: Hazine ve Maliye Bakanlığı, GİB, VDK ve vergi müfettişlerini ilgilendiren haberler.

Kaynak: yayıncıların kendi RSS akışları. Uygulamada kısa özet gösterilir (tam metin kopyalanmaz), en altta kaynağa bağlantı.
Depo herkese açık: haber başlıkları yazdırılmaz, yalnızca sayılar.
"""
import html
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import metin

# Başlık yabancı bir ülkeyi/kurumu anıyorsa "Dünya" başlığına alınır
FOREIGN = re.compile(r"\b(ABD|Amerika|Avrupa|AB'|AB |Avrupa Birliği|Britanya|İngiltere|Almanya|Fransa|İtalya|İspanya|Hollanda|Belçika|İsviçre|Avusturya|Yunanistan|Rusya|Ukrayna|Çin|Japonya|Hindistan|Kanada|Avustralya|Brezilya|Arjantin|Meksika|Malezya|Endonezya|Kore|İsrail|İran|Irak|Suriye|Mısır|Suudi|Katar|Dubai|BAE|Azerbaycan|Kazakistan|Özbekistan|Gürcistan|Bulgaristan|Romanya|Polonya|Macaristan|Trump|Biden|Washington|Londra|Berlin|Paris|Brüksel|Moskova|Pekin|OECD|IMF|G20|G7|Dünya Bankası|BM |Birleşmiş Milletler|küresel|uluslararası|global)", re.I)

# Yayıncıların kendi RSS akışları (bağlantılar doğrudan habere gider; Google Haberler bağlantıları çözülemiyor)
FEEDS = [
    ("TRT Haber", "https://www.trthaber.com/ekonomi_articles.rss"), ("Milliyet", "https://www.milliyet.com.tr/rss/rssnew/ekonomirss.xml"),
    ("NTV", "https://www.ntv.com.tr/ekonomi.rss"), ("Sözcü", "https://www.sozcu.com.tr/feeds-rss-category-ekonomi"),
    ("Habertürk", "https://www.haberturk.com/rss/ekonomi.xml"), ("Anadolu Ajansı", "https://www.aa.com.tr/tr/rss/default?cat=ekonomi"),
    ("Sabah", "https://www.sabah.com.tr/rss/ekonomi.xml"), ("CNN Türk", "https://www.cnnturk.com/feed/rss/ekonomi/news"),
    ("Yeni Akit", "https://www.yeniakit.com.tr/rss/haber/ekonomi"), ("Bloomberg HT", "https://www.bloomberght.com/rss"),
    ("Star", "https://www.star.com.tr/rss/ekonomi.xml"), ("Dünya", "https://www.dunya.com/rss"),
    ("Ekonomim", "https://www.ekonomim.com/rss"), ("MuhasebeTR", "https://www.muhasebetr.com/rss/"),
]
KEY = re.compile(r"vergi|maliye|gelir idaresi|\bGİB\b|müfettiş|kaçakçılı|sahte fatura|naylon fatura|beyanname|\bKDV\b|\bÖTV\b|"
                 r"yapılandırma|matrah|stopaj|tahsilat|Hazine ve Maliye|Vergi Denetim|kayıt dışı|e-fatura|e-defter", re.I)
KONU = [("VDK", re.compile(r"müfettiş|Vergi Denetim|VDK", re.I)), ("GİB", re.compile(r"Gelir İdaresi|\bGİB\b", re.I)),
        ("Kaçakçılık", re.compile(r"kaçakçılı|sahte fatura|naylon fatura|kayıt dışı|operasyon|vergi incelemesi|gözaltı", re.I)),
        ("Bakanlık", re.compile(r"Hazine ve Maliye|Maliye Bakan", re.I))]
SKIP = re.compile(r"\b(burç|maç|transfer|dizi|magazin|altın fiyat|hava durumu)\b", re.I)
JUNK = re.compile(r"abone ol|tıklay|haberin devamı|©|tüm hakları|çerez|cookie|whatsapp|google news|takip edin|reklam", re.I)


def clean(t):
    t = html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", t or ""))
    t = re.sub(r"\[(?:Fotoğraf|Fotograf|Foto|Video)[^\]]*\]", " ", t, flags=re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)).strip()


def lead(page):
    """Haber sayfasından giriş: og:description ve ilk birkaç temiz paragraf."""
    og = re.search(r'<meta[^>]+(?:property|name)=["\'](?:og:description|description)["\'][^>]+content=["\']([^"\']+)', page, re.I)
    body = re.search(r"<article.*?</article>", page, re.S | re.I)
    ps = [clean(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", body.group(0) if body else page, re.S | re.I)]
    ps = [p for p in ps if 60 < len(p) < 1200 and "{" not in p and not JUNK.search(p)]
    return (clean(og.group(1)) if og else ""), ps


def og_image(page):
    m = re.search(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+content=["\'](https?://[^"\']+)', page, re.I) \
        or re.search(r'<meta[^>]+content=["\'](https?://[^"\']+)["\'][^>]+(?:property|name)=["\']og:image', page, re.I)
    return html.unescape(m.group(1))[:500] if m else ""


def ozet_of(url, desc):
    """Kısa alıntı: başlık altı özet + ilk 3 paragraf, en çok ~1400 karakter (tam metin kopyalanmaz). (özet, görsel) döner."""
    parts, img = [], ""
    try:
        raw, ct = metin.fetch(url, timeout=20)
        page = metin.decode(raw, ct)
        og, ps = lead(page)
        img = og_image(page)
    except Exception:  # noqa: BLE001
        og, ps = "", []
    for p in [og or desc] + ps:
        if p and not any(p[:60] in q or q[:60] in p for q in parts):
            parts.append(p)
        if sum(len(q) for q in parts) > 1100 or len(parts) >= 4:
            break
    out = "\n\n".join(parts)
    return (out[:1400].rsplit(" ", 1)[0] + "…" if len(out) > 1400 else out), img


def fetch_news(known=frozenset(), max_pages=30):
    out, seen, pages = [], set(), 0
    for src, feed in FEEDS:
        try:
            raw, ct = metin.fetch(feed, timeout=25)
        except Exception as e:  # noqa: BLE001
            print(f"Haber kaynağı okunamadı ({src}): {type(e).__name__} {getattr(e, 'code', '')}")
            continue
        for it in re.findall(r"<item>(.*?)</item>", metin.decode(raw, ct), re.S):
            g = lambda tag: (re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", it, re.S) or [None, ""])[1]
            rimg = re.search(r'<(?:enclosure|media:content|media:thumbnail)[^>]+url=["\'](https?://[^"\']+)', it) or re.search(r'<img[^>]+src=["\'](https?://[^"\']+)', html.unescape(it))
            title, link, desc = clean(g("title")), clean(g("link")), clean(g("description"))[:600]
            key = re.sub(r"\W+", "", title.lower())[:80]
            if not title or not link.startswith("http") or key in seen or SKIP.search(title) or not KEY.search(title + " " + desc):
                continue
            seen.add(key)
            try:
                when = parsedate_to_datetime(clean(g("pubDate"))).astimezone(timezone.utc)
            except (TypeError, ValueError):
                when = datetime.now(timezone.utc)
            if datetime.now(timezone.utc) - when > timedelta(days=4):
                continue
            konu = next((k for k, rx in KONU if rx.search(title + " " + desc)), "Vergi")
            if konu not in ("VDK", "GİB") and FOREIGN.search(title):
                konu = "Dünya"
            row = {"title": title[:300], "url": link[:500], "source": src, "konu": konu, "published": when.isoformat()}
            if link not in known and pages < max_pages:
                row["ozet"], img = ozet_of(link, desc)
                row["image"] = img or (html.unescape(rimg.group(1))[:500] if rimg else "")
                pages += 1
            elif link not in known:
                row["ozet"] = desc or None
                row["image"] = html.unescape(rimg.group(1))[:500] if rimg else ""
            out.append(row)
    return out


def run(db):
    since = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        db("GET", "news?select=image&limit=1")
        has_img = True
    except Exception:  # noqa: BLE001  (haber_gorsel.sql henüz çalıştırılmadı)
        has_img = False
    try:
        known = {r["url"] for r in db("GET", f"news?select=url&ozet=not.is.null{'&image=not.is.null' if has_img else ''}&published=gte.{since}&limit=2000") or []}
        has_ozet = True
    except Exception:  # noqa: BLE001  (haber_ozet.sql henüz çalıştırılmadı)
        known, has_ozet = set(), False
    items = fetch_news(known if has_ozet else frozenset(), 30 if has_ozet else 0)
    groups = [[x for x in items if "ozet" in x], [x for x in items if "ozet" not in x]]
    for grp in groups:
        drop = ({"ozet"} if not has_ozet else set()) | ({"image"} if not has_img else set())
        if drop:
            grp = [{k: v for k, v in x.items() if k not in drop} for x in grp]
        for i in range(0, len(grp), 200):
            db("POST", "news?on_conflict=url", grp[i:i + 200], prefer="resolution=merge-duplicates,return=minimal")
    db("DELETE", "news?url=like.https://news.google.com/*", prefer="return=minimal")
    old = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    db("DELETE", f"news?published=lt.{old}", prefer="return=minimal")
    print(f"Haberler: {len(items)} bulundu, özetli yeni {sum(1 for x in items if x.get('ozet'))}, Dünya: {sum(1 for x in items if x['konu'] == 'Dünya')}"
          + f", görselli {sum(1 for x in items if x.get('image'))}" + ("" if has_ozet else " (özet kolonu yok: haber_ozet.sql)") + ("" if has_img else " (görsel kolonu yok: haber_gorsel.sql)"))



def diag():
    items = fetch_news(frozenset(), 3)
    print(f"Haber teşhis: {len(items)} haber, kaynak sayısı {len({x['source'] for x in items})}, "
          f"özet uzunlukları {[len(x.get('ozet') or '') for x in items if 'ozet' in x][:3]}")
    for x in [x for x in items if x.get("ozet")][:3]:  # kamuya açık haber metninden kısa örnek
        print("  örnek:", x["source"], "·", x["konu"], "·", x["ozet"][:220].replace("\n", " / "))
