import json, re, sys
sys.path.insert(0, ".")
import ozelge as o
def get(u, body=None):
    try: return o.http(u, body, timeout=40)
    except Exception as e: print("HATA", u, e); return ""
p = get("https://kararlarbilgibankasi.anayasa.gov.tr/BB/2021/12411")
for src in re.findall(r'src="([^"]+\.js)"', p):
    js = get(src if src.startswith("http") else "https://kararlarbilgibankasi.anayasa.gov.tr" + ("" if src.startswith("/") else "/") + src)
    print("JS", src, len(js))
    print(sorted(set(re.findall(r'["`/](api/[A-Za-z0-9_/\-{}$.]+)', js)))[:80])
a = o.get_aym(3)
print("AYM ilk kayıt id", a[0]["id"] if a else None)
if a:
    i = a[0]["id"]
    for u in (f"https://kararlarbilgibankasi.anayasa.gov.tr/api/core/public/karar/{i}", f"https://kararlarbilgibankasi.anayasa.gov.tr/api/core/public/detail/{i}",
              f"https://kararlarbilgibankasi.anayasa.gov.tr/api/core/public/{i}"):
        r = get(u); print(u, len(r), r[:300])
for u in ("https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=7524&MevzuatTur=1&MevzuatTertip=5",
          "https://www.mevzuat.gov.tr/anasayfa/MevzuatFihristDetayIframe?MevzuatTur=1&MevzuatNo=7524&MevzuatTertip=5",
          "https://www.mevzuat.gov.tr/MevzuatMetin/1.5.7524.pdf"):
    r = get(u); t = o.strip_tags(re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", r, flags=re.S | re.I))
    print("MEV", u, len(r), r[:8], "|", t[:300])
d = json.loads(get(o.GIB_API.format(path="kanun/filterList").replace("size=20", "size=3"), {}))
for r in d["resultContainer"]["content"]:
    print("KANUN", {k: v for k, v in r.items() if v not in (None, "", [], {})})
d = json.loads(get(o.GIB_API.format(path="cbk/list").replace("size=20", "size=1"), {}))
r = d["resultContainer"]["content"][0]; print("CBK", r.get("description"), r.get("fileNames"), r.get("gecenkanunList"))
r = get("https://www.resmigazete.gov.tr/eskiler/2026/11/20261108-2.htm")
print("RG htm", len(r), o.strip_tags(re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", r, flags=re.S | re.I))[:400])
