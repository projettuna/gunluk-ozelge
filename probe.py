import re, html
from urllib.request import Request, urlopen
from urllib.parse import quote
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
def get(url, t=60):
    try:
        with urlopen(Request(url, headers={"User-Agent": UA, "Accept": "text/html"}), timeout=t) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        return f"ERR {e}"
def txt(s): return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()
rg = get("https://www.resmigazete.gov.tr/")
print("RG anchors:")
for href, inner in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', rg, re.S)[:200]:
    t = txt(inner)
    if "eskiler" in href or len(t) > 40:
        print("  ", href[:90], "|", t[:160])
i = rg.find("fihrist"); print("fihrist idx", i)
for name, base in [("AYM-BB", "https://kararlarbilgibankasi.anayasa.gov.tr"), ("AYM-NORM", "https://normkararlarbilgibankasi.anayasa.gov.tr")]:
    h = get(base + "/")
    print("==", name, len(h))
    print("  forms:", re.findall(r'<form[^>]*>', h)[:5])
    print("  inputs:", sorted(set(re.findall(r'name="([^"]+)"', h)))[:80])
    for q in ["/Ara?KelimeAra%5B%5D=" + quote("vergi usul kanunu 359"), "/Ara?KelimeAra[]=" + quote("359") + "&SiralamaAnahtari=KararTarihi"]:
        r = get(base + q)
        print("  Q", q, len(r), r[:80] if r.startswith("ERR") else "")
        if not r.startswith("ERR"):
            items = re.findall(r'<a[^>]+href="(/(?:BB|ND)/[^"]+)"[^>]*>(.*?)</a>', r, re.S)
            print("   items:", [(a, txt(b)[:120]) for a, b in items[:8]])
            j = r.find("sonuç"); print("   ", txt(r[max(0,j-300):j+1500])[:1200] if j>=0 else txt(r)[:800])
