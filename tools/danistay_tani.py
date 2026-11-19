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
for sf, sd in (("KARAR_TARIHI", "desc"), ("KARAR_TARIHI", "DESC"), ("kararTarihi", "desc"), ("1", "desc")):
    d = {"itemTypeList": ["DANISTAYKARAR"], "andKelimeler": ["vergi usul kanunu", "359"], "orKelimeler": [], "notKelimeler": [], "pageSize": 10, "pageNumber": 1,
         "sortFieldKod": sf, "sortDirection": sd}
    try:
        with urlopen(Request(S + "getEmsalKarar", data=json.dumps({"data": d}).encode(), headers=H, method="POST"), timeout=90) as r:
            j = json.loads(r.read().decode("utf-8", "replace"))
        lst = j["data"]["emsalKararList"]
        print(sf, sd, "toplam", j["data"].get("total"), [(x["kararTarihiStr"], x["documentId"]) for x in lst[:6]])
    except HTTPError as e:
        print(sf, sd, e.code, e.read().decode("utf-8", "replace")[:200])
    except Exception as e:  # noqa: BLE001
        print(sf, sd, "hata", e)
page = urlopen(Request(B + "/", headers={"User-Agent": ozelge.UA}), timeout=60).read().decode("utf-8", "replace")
for src in re.findall(r'src="(/static/js/[^"]+)"', page):
    js = urlopen(Request(B + src, headers={"User-Agent": ozelge.UA}), timeout=120).read().decode("utf-8", "replace")
    for key in (":documentId", "sortFieldKod", "?aranacakKelimeler=", "pageNumber"):
        hits = [m.start() for m in re.finditer(re.escape(key), js)]
        print("##", key, len(hits))
        for h in hits[:5]:
            print("  ..", " ".join(js[max(0, h - 300):h + 300].split()))
