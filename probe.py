"""Geçici teşhis: Yargıtay sıralama + Danıştay doküman."""
import json
from urllib.parse import quote
from urllib.request import Request, urlopen
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
def call(url, body=None, t=120):
    h = {"User-Agent": UA, "Accept": "application/json", "Content-Type": "application/json; charset=UTF-8", "X-Requested-With": "XMLHttpRequest"}
    try:
        data = json.dumps(body).encode() if body is not None else None
        with urlopen(Request(url, data=data, headers=h, method="POST" if data else "GET"), timeout=t) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        return f"ERR {e}"
t = call("https://karararama.danistay.gov.tr/getDokuman?id=1231539100&arananKelime=" + quote("vergi usul kanunu,359"))
print("DANDOC", t[:400]); import re; print("DANDOC359", [t[max(0,m.start()-150):m.end()+80] for m in re.finditer("359", t)][:3])
Y = "https://karararama.yargitay.gov.tr/aramalist"
for body in [
    {"data": {"andKelimeler": ["vergi usul kanunu", "359"], "pageSize": 10, "pageNumber": 1}},
    {"data": {"arananKelime": "vergi usul kanunu 359", "pageSize": 10, "pageNumber": 1}},
    {"data": {"arananKelime": "vergi usul kanunu 359", "pageSize": 10, "pageNumber": 1, "siralama": "3", "siralamaDirection": "desc"}},
    {"data": {"arananKelime": "vergi usul kanunu 359", "pageSize": 10, "pageNumber": 1, "siralama": "1", "siralamaDirection": "desc"}},
]:
    r = call(Y, body)
    try:
        d = json.loads(r)["data"]; print("Y", body["data"], d["recordsTotal"], [(x["id"], x["kararTarihi"], x["daire"]) for x in d["data"]])
    except Exception:
        print("Y", body["data"], r[:300])
