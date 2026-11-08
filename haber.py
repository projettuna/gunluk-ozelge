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
]
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
            out.append({"title": title[:300], "url": link, "source": src[:80] or None, "konu": konu, "published": when})
    return out


def run(db):
    items = fetch_news()
    added = 0
    for i in range(0, len(items), 200):
        res = db("POST", "news?on_conflict=url", items[i:i + 200], prefer="resolution=ignore-duplicates,return=representation")
        added += len(res or [])
    old = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    db("DELETE", f"news?published=lt.{old}", prefer="return=minimal")
    print(f"Haberler: {len(items)} bulundu, {added} yeni")
