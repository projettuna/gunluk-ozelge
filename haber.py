"""Haberler sekmesi: Hazine ve Maliye Bakanlığı, GİB, VDK ve vergi müfettişlerini ilgilendiren haberler.

Kaynak Google Haberler RSS (bakanlık siteleri betikle yüklendiği için doğrudan okunamıyor).
Depo herkese açık: haber başlıkları yazdırılmaz, yalnızca sayılar.
"""
import html
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import metin

QUERIES = [
    ("VDK", '"vergi müfettişi" OR "vergi müfettişleri" OR "Vergi Denetim Kurulu"'),
    ("Bakanlık", '"Hazine ve Maliye Bakanlığı" OR "Hazine ve Maliye Bakanı"'),
    ("GİB", '"Gelir İdaresi Başkanlığı" OR "Gelir İdaresi"'),
    ("Kaçakçılık", '"vergi kaçakçılığı" OR "sahte fatura" OR "naylon fatura" OR "vergi incelemesi"'),
    ("Vergi", '"vergi düzenlemesi" OR "vergi paketi" OR "vergi affı" OR "yapılandırma" vergi'),
    ("Dünya", 'OECD vergi OR "küresel asgari vergi" OR "uluslararası vergi" OR "vergi cenneti" OR "dijital hizmet vergisi"'),
]
# Başlık yabancı bir ülkeyi/kurumu anıyorsa "Dünya" başlığına alınır
FOREIGN = re.compile(r"\b(ABD|Amerika|Avrupa|AB'|AB |Avrupa Birliği|Britanya|İngiltere|Almanya|Fransa|İtalya|İspanya|Hollanda|Belçika|İsviçre|Avusturya|Yunanistan|Rusya|Ukrayna|Çin|Japonya|Hindistan|Kanada|Avustralya|Brezilya|Arjantin|Meksika|Malezya|Endonezya|Kore|İsrail|İran|Irak|Suriye|Mısır|Suudi|Katar|Dubai|BAE|Azerbaycan|Kazakistan|Özbekistan|Gürcistan|Bulgaristan|Romanya|Polonya|Macaristan|Trump|Biden|Washington|Londra|Berlin|Paris|Brüksel|Moskova|Pekin|OECD|IMF|G20|G7|Dünya Bankası|BM |Birleşmiş Milletler|küresel|uluslararası|global)", re.I)

RSS = "https://news.google.com/rss/search?q={q}&hl=tr&gl=TR&ceid=TR:tr"
SKIP = re.compile(r"\b(burç|maç|transfer|dizi|magazin|altın fiyat|hava durumu)\b", re.I)


def fetch_news():
    out, seen = [], set()
    for konu, q in QUERIES:
        try:
            raw, ct = metin.fetch(RSS.format(q=quote(q + " when:3d")), timeout=30)
        except Exception as e:  # noqa: BLE001
            print(f"Haber kaynağı okunamadı ({konu}): {type(e).__name__}")
            continue
        x = metin.decode(raw, ct)
        for it in re.findall(r"<item>(.*?)</item>", x, re.S):
            g = lambda tag: html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", (re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", it, re.S) or [None, ""])[1])).strip()
            title, link, pub, src = g("title"), g("link"), g("pubDate"), g("source")
            if src and title.endswith(" - " + src):
                title = title[: -len(src) - 3].strip()
            key = re.sub(r"\W+", "", title.lower())[:80]
            if not title or not link or key in seen or SKIP.search(title):
                continue
            seen.add(key)
            try:
                when = parsedate_to_datetime(pub).astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError):
                when = None
            out.append({"title": title[:300], "url": link, "source": src[:80] or None,
                        "konu": "Dünya" if konu != "VDK" and FOREIGN.search(title) else konu, "published": when})
    return out


def run(db):
    items = fetch_news()
    added = 0
    for i in range(0, len(items), 200):
        res = db("POST", "news?on_conflict=url", items[i:i + 200], prefer="resolution=merge-duplicates,return=representation")
        added += len(res or [])
    old = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    db("DELETE", f"news?published=lt.{old}", prefer="return=minimal")
    print(f"Haberler: {len(items)} bulundu/güncellendi, Dünya: {sum(1 for x in items if x['konu'] == 'Dünya')}")


FEEDS_TRY = [
    "https://www.aa.com.tr/tr/rss/default?cat=ekonomi", "https://www.ntv.com.tr/ekonomi.rss",
    "https://www.haberturk.com/rss/ekonomi.xml", "https://www.dunya.com/rss", "https://www.ekonomim.com/rss",
    "https://www.bloomberght.com/rss", "https://www.hurriyet.com.tr/rss/ekonomi",
    "https://www.milliyet.com.tr/rss/rssnew/ekonomirss.xml", "https://www.sabah.com.tr/rss/ekonomi.xml",
    "https://www.trthaber.com/ekonomi_articles.rss", "https://www.sozcu.com.tr/feeds-rss-category-ekonomi",
    "https://www.alomaliye.com/feed/", "https://www.yeniakit.com.tr/rss/haber/ekonomi",
    "https://www.cnnturk.com/feed/rss/ekonomi/news", "https://www.star.com.tr/rss/ekonomi.xml",
    "https://www.aksam.com.tr/rss/ekonomi.xml", "https://www.paraanaliz.com/feed/", "https://www.muhasebetr.com/rss/",
]
KEY = re.compile(r"vergi|maliye|gelir idaresi|GİB|müfettiş|kaçakçılı|fatura|denetim|beyanname|KDV|ÖTV|harç|SGK prim|yapılandırma", re.I)


def lead(page):
    """Haber sayfasından giriş: og:description ve ilk paragraflar."""
    og = re.search(r'<meta[^>]+(?:property|name)=["\'](?:og:description|description)["\'][^>]+content=["\']([^"\']+)', page, re.I)
    body = re.search(r"<article.*?</article>", page, re.S | re.I)
    ps = [html.unescape(re.sub(r"<[^>]+>", " ", p)).strip() for p in re.findall(r"<p[^>]*>(.*?)</p>", body.group(0) if body else page, re.S | re.I)]
    ps = [re.sub(r"\s+", " ", p) for p in ps if len(p) > 60]
    return (html.unescape(og.group(1)).strip() if og else ""), ps


def diag():
    """Teşhis: yayıncı RSS akışları ve haber girişlerinin alınabildiği (yalnızca alan adı ve sayılar)."""
    from urllib.parse import urlparse
    for f in FEEDS_TRY:
        host = urlparse(f).netloc
        try:
            raw, ct = metin.fetch(f, timeout=20)
            x = metin.decode(raw, ct)
        except Exception as e:  # noqa: BLE001
            print(f"  {host}: akış hata {type(e).__name__} {getattr(e, 'code', '')}")
            continue
        its = re.findall(r"<item>(.*?)</item>", x, re.S) or re.findall(r"<entry>(.*?)</entry>", x, re.S)
        hits = [i for i in its if KEY.search(re.sub(r"<[^>]+>", " ", i))]
        desc = sum(1 for i in its if re.search(r"<description>.{80,}", i, re.S))
        msg = f"  {host}: {len(its)} haber, {len(hits)} vergi ilgili, açıklamalı {desc}"
        if its:
            ln = re.search(r"<link>(?:<!\[CDATA\[)?\s*([^<\]\s]+)", (hits or its)[0]) or re.search(r'<link[^>]+href="([^"]+)"', (hits or its)[0])
            if ln:
                try:
                    r2, c2 = metin.fetch(ln.group(1).strip(), timeout=20)
                    og, ps = lead(metin.decode(r2, c2))
                    msg += f" · sayfa: og {len(og)} krk, {len(ps)} paragraf, ilk3 {sum(len(p) for p in ps[:3])} krk"
                except Exception as e:  # noqa: BLE001
                    msg += f" · sayfa hata {type(e).__name__} {getattr(e, 'code', '')}"
        print(msg)
