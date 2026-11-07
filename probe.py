"""Geçici teşhis: yargı kararı API sıralaması ve detay."""
import json
from urllib.request import Request, urlopen
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
def call(url, body=None):
    h = {"User-Agent": UA, "Accept": "application/json", "Content-Type": "application/json; charset=UTF-8", "X-Requested-With": "XMLHttpRequest"}
    try:
        data = json.dumps(body).encode() if body is not None else None
        with urlopen(Request(url, data=data, headers=h, method="POST" if data else "GET"), timeout=90) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        return f"ERR {e}"
for base in ["https://karararama.danistay.gov.tr", "https://karararama.yargitay.gov.tr", "https://emsal.uyap.gov.tr"]:
    for extra in [{}, {"siralama": "1", "siralamaDirection": "desc"}, {"siralama": "2", "siralamaDirection": "desc"}, {"siralama": "3", "siralamaDirection": "desc"}]:
        body = {"data": {"andKelimeler": ["vergi usul kanunu", "359"], "pageSize": 10, "pageNumber": 1, **extra}}
        t = call(base + "/aramalist", body)
        try:
            d = json.loads(t)["data"]
            rows = d["data"]
            print(base, extra, d["recordsTotal"], [(r["id"], r["kararTarihi"], r.get("daire") or r.get("daireKurul")) for r in rows])
        except Exception:
            print(base, extra, "->", t[:300])
    t = call(base + "/getDokuman?id=" + ("1231539100" if "danistay" in base else "1069946700" if "yargitay" in base else "1231351800"))
    print("DOC", base, t[:700])
