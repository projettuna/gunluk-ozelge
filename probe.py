import json
from urllib.request import Request, urlopen
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
B = "https://kararlarbilgibankasi.anayasa.gov.tr"
def post(body):
    try:
        with urlopen(Request(B + "/api/core/public/search", data=json.dumps(body).encode(), headers={"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json", "Origin": B, "Referer": B + "/"}, method="POST"), timeout=60) as r:
            return r.read().decode()
    except Exception as e:
        rd = getattr(e, "read", None)
        return f"ERR {e} {rd().decode('utf-8','replace')[:300] if rd else ''}"
for body in [{"query": "\"Vergi Usul Kanunu\" 359", "page": 1, "size": 5, "sort": "yayinTarihi", "order": "desc"},
             {"query": "vergi kaçakçılığı", "page": 1, "size": 5, "sort": "yayinTarihi", "order": "desc"},
             {"query": "213 sayılı 359", "page": 1, "size": 5, "sort": "yayinTarihi", "order": "desc", "kararTipi": "NormDenetimi"}]:
    t = post(body)
    print("==", body)
    try:
        d = json.loads(t); print("total", d.get("total"))
        for r in d.get("data", [])[:5]:
            print(json.dumps({k: (v[:200] if isinstance(v, str) else v) for k, v in r.items()}, ensure_ascii=False)[:1500])
    except Exception:
        print(t[:500])
