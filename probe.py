"""Geçici teşhis: GİB mevzuat API uç noktalarını listeler."""
import json, re
from urllib.parse import urljoin
from urllib.request import Request, urlopen
UA = "Mozilla/5.0 ozelge-bildirim/1.0"
def get(url, body=None):
    h = {"User-Agent": UA, "Accept": "application/json, text/html"}
    data = None
    if body is not None:
        h["Content-Type"] = "application/json"; data = json.dumps(body).encode()
    try:
        with urlopen(Request(url, data=data, headers=h, method="POST" if data else "GET"), timeout=60) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        return f"ERR {e}"
pages = ["https://www.gib.gov.tr/mevzuat/ozelgeler", "https://www.gib.gov.tr/mevzuat/yargi-kararlari",
         "https://www.gib.gov.tr/mevzuat/tur/yargi-kararlari", "https://www.gib.gov.tr/mevzuat/danistay-kararlari"]
scripts = set()
for p in pages:
    t = get(p)
    print("PAGE", p, t[:60] if t.startswith("ERR") else len(t))
    if not t.startswith("ERR"):
        scripts.update(re.findall(r'<script[^>]+src="([^"]+)"', t))
        print("  links:", sorted(set(re.findall(r'href="(/mevzuat/[^"]+)"', t)))[:60])
eps, words = set(), set()
for s in scripts:
    js = get(urljoin("https://www.gib.gov.tr/", s))
    eps.update(re.findall(r'gibportal/[A-Za-z0-9_/\-]+', js))
    words.update(re.findall(r'[^"\'`\s]{0,60}(?:karar|KARAR|yargi|YARGI|danistay|DANISTAY)[^"\'`\s]{0,60}', js))
print("ENDPOINTS:"); [print("  ", e) for e in sorted(eps)]
print("KARAR REFS:"); [print("  ", w[:150]) for w in sorted(words)[:120]]
