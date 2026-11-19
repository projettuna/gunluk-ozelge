"""Danıştay karar arama tanısı: yeni (Bedesten) arama ucunda sıralama ve ayrıntı sayfası yolu (herkese açık site)."""
import json
import os
import re
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ozelge  # noqa: E402

B = "https://karararama.danistay.gov.tr"
S = "https://bedesten.adalet.gov.tr/emsal-karar/"
H = {"User-Agent": ozelge.UA, "Accept": "application/json, text/plain, */*", "Content-Type": "application/json; charset=UTF-8"}
for sf, sd in (("1", "desc"), ("2", "desc"), ("3", "desc"), ("4", "desc"), ("5", "desc"), ("3", "asc"), (None, None)):
    d0 = {"itemTypeList": ["DANISTAYKARAR"], "andKelimeler": ["vergi usul kanunu", "359"], "orKelimeler": [], "notKelimeler": [], "pageSize": 10, "pageNumber": 1,
         "sortFieldKod": sf, "sortDirection": sd}
    d = {k: v for k, v in d0.items() if v is not None}
    d["pageSize"] = 30
    try:
        with urlopen(Request(S + "getEmsalKarar", data=json.dumps({"data": d}).encode(), headers=H, method="POST"), timeout=90) as r:
            j = json.loads(r.read().decode("utf-8", "replace"))
        lst = j["data"]["emsalKararList"]
        print(sf, sd, "toplam", j["data"].get("total"), [(x["kararTarihiStr"], x["documentId"]) for x in lst[:30]])
    except HTTPError as e:
        print(sf, sd, e.code, e.read().decode("utf-8", "replace")[:200])
    except Exception as e:  # noqa: BLE001
        print(sf, sd, "hata", e)
page = urlopen(Request(B + "/", headers={"User-Agent": ozelge.UA}), timeout=60).read().decode("utf-8", "replace")
for src in re.findall(r'src="(/static/js/[^"]+)"', page):
    js = urlopen(Request(B + src, headers={"User-Agent": ozelge.UA}), timeout=120).read().decode("utf-8", "replace")
    h = js.index("sortFieldKod:H")
    seg = js[max(0, h - 9000):h]
    for m in re.finditer(r'useState\([^)]{0,80}\)|\{(?:id|value|kod|key)\s*:[^{}]{0,120}\}', seg):
        print("  ..", m.group(0)[:200])
