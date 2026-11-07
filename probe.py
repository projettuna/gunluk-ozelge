import json, re
from urllib.request import Request, urlopen
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
def call(url, body=None, t=60):
    try:
        data = json.dumps(body).encode() if body is not None else None
        with urlopen(Request(url, data=data, headers={"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json, text/html"}, method="POST" if data else "GET"), timeout=t) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        return f"ERR {e}"
A = "https://gib.gov.tr/api/gibportal/mevzuat/"
for ep in ["cbk/list", "bkk/list", "genelYazilar/list", "icGenelge/list", "yonetmelikler/list", "taslak/list", "kanun/filterList"]:
    t = call(A + ep + "?page=0&size=3&sortFieldName=id&sortType=DESC", {})
    try:
        d = json.loads(t)["resultContainer"]
        print("==", ep, d.get("totalElements"))
        for r in d["content"]:
            print("  ", r.get("id"), r.get("ts", "")[:10], {k: r.get(k) for k in r if any(x in k.lower() for x in ("tarih", "sayi", "no"))}, "|", (r.get("title") or "")[:100], "|", r.get("siteLink"))
    except Exception:
        print("==", ep, t[:200])
rg = call("https://www.resmigazete.gov.tr/")
print("RG", rg[:80] if rg.startswith("ERR") else len(rg))
if not rg.startswith("ERR"):
    print(re.findall(r'href="([^"]*eskiler[^"]*)"', rg)[:30])
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "\n", rg))
    i = txt.find("YASAMA"); print(txt[i:i+2500] if i >= 0 else txt[:2500])
an = call("https://kararlarbilgibankasi.anayasa.gov.tr/")
print("AYM", an[:80] if an.startswith("ERR") else len(an))
