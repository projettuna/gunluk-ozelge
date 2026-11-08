import json, re, sys
sys.path.insert(0, ".")
import ozelge as o
def show(name, url, body=None):
    try:
        r = o.http(url, body, timeout=40)
    except Exception as e:
        print(name, "HATA", e); return None
    print(f"== {name}: {len(r)} bayt")
    try:
        d = json.loads(r)
    except ValueError:
        t = o.strip_tags(re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", r, flags=re.S | re.I))
        print("  html metin uzunluğu", len(t), "|", t[:300]); return r
    return d
for path in ("ozelge/list", "teblig/list", "kanun/filterList", "sirkuler/list", "cbk/list", "icGenelge/list"):
    d = show(path, o.GIB_API.format(path=path).replace("size=20", "size=2"), {})
    if not d: continue
    rec = d["resultContainer"]["content"][0]
    print("  alanlar:", {k: (len(v) if isinstance(v, str) else type(v).__name__) for k, v in rec.items()})
    print("  id", rec.get("id"), "siteLink", rec.get("siteLink"))
    for k, v in rec.items():
        if isinstance(v, str) and len(v) > 200:
            print("  ", k, "→", o.strip_tags(v)[:200])
    base = path.split("/")[0]
    for u in (f"https://gib.gov.tr/api/gibportal/mevzuat/{base}/{rec['id']}",
              f"https://gib.gov.tr/api/gibportal/mevzuat/{base}/detail?id={rec['id']}",
              f"https://gib.gov.tr/api/gibportal/mevzuat/{base}/get?id={rec['id']}",
              f"https://gib.gov.tr/api/gibportal/mevzuat/{base}/findById?id={rec['id']}"):
        x = show("  dene " + u, u)
        if isinstance(x, dict):
            print("    anahtarlar", list(x)[:10], str(x)[:300])
a = o.get_aym(3)
for r in a[:2]:
    show("AYM " + r["url"], r["url"])
rg = o.get_resmi_gazete() or []
print("RG eşleşme", len(rg))
x = show("RG ana", o.RG)
links = re.findall(r'href="(https://www\.resmigazete\.gov\.tr/eskiler/[^"]+)"', x or "")
print("RG link örnek", links[:3])
if links: show("RG belge", links[0])
