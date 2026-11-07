import json, time
from urllib.request import Request, urlopen
UA = "Mozilla/5.0 ozelge-bildirim/1.0"
def post(url):
    t0 = time.time()
    with urlopen(Request(url, data=b"{}", headers={"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json"}, method="POST"), timeout=120) as r:
        b = r.read()
    return round(time.time() - t0, 1), len(b), json.loads(b)
B = "https://gib.gov.tr/api/gibportal/mevzuat/teblig/list?page=0&size={n}"
for q in ["&sortFieldName=ts&sortType=DESC", "&sortFieldName=resmiGazeteTarih&sortType=DESC", "&sortFieldName=id&sortType=ASC", "&sortFieldName=updated_at&sortType=DESC", "&sortFieldName=priority&sortType=DESC"]:
    try:
        s, n, d = post(B.format(n=5) + q)
        print(q, [(r["id"], (r.get("resmiGazeteTarih") or "")[:10], r["title"][:50]) for r in d["resultContainer"]["content"]])
    except Exception as e:
        print(q, "ERR", e)
s, n, d = post(B.format(n=3000))
c = d["resultContainer"]["content"]
print("FULL", s, "s", n, "bytes", len(c))
c.sort(key=lambda r: r["id"], reverse=True)
for r in c[:12]:
    print(r["id"], (r.get("resmiGazeteTarih") or "")[:10], r.get("resmiGazeteSayi"), r.get("ts", "")[:10], r.get("kanunTitle"), "|", r["title"][:90], "|", r.get("siteLink"))
