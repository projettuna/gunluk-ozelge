import re, sys
sys.path.insert(0, ".")
import metin
def get(u):
    try:
        raw, ct = metin.fetch(u, timeout=30); return metin.decode(raw, ct)
    except Exception as e:
        print("HATA", u, e); return ""
for q in ['"vergi müfettişi"', '"Vergi Denetim Kurulu"', '"Hazine ve Maliye Bakanlığı" vergi', '"Gelir İdaresi" vergi']:
    from urllib.parse import quote
    x = get("https://news.google.com/rss/search?q=" + quote(q + " when:7d") + "&hl=tr&gl=TR&ceid=TR:tr")
    its = re.findall(r"<item>.*?<title>(.*?)</title>.*?<link>(.*?)</link>.*?<pubDate>(.*?)</pubDate>.*?<source[^>]*>(.*?)</source>", x, re.S)
    print("GN", q, len(its)); [print("  ", t[:110], "|", d, "|", s) for t, l, d, s in its[:4]]
for u in ("https://www.hmb.gov.tr/haberler", "https://www.hmb.gov.tr/duyurular", "https://vdk.hmb.gov.tr/duyurular", "https://vdk.hmb.gov.tr/haberler", "https://www.gib.gov.tr/duyurular", "https://gib.gov.tr/api/gibportal/duyuru/list?page=0&size=5", "https://www.hmb.gov.tr/rss"):
    x = get(u); t = metin.html_to_text(x)
    print("SITE", u, len(x), "|", re.sub(r"\s+", " ", t)[:400])
    print("   links", re.findall(r'href="([^"]*(?:haber|duyuru)[^"]*)"', x)[:8])
