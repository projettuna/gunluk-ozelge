"""Geçici teşhis: yargı kararı arama API'leri."""
import json
from urllib.request import Request, urlopen
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
def post(url, body):
    h = {"User-Agent": UA, "Accept": "application/json", "Content-Type": "application/json; charset=UTF-8", "X-Requested-With": "XMLHttpRequest"}
    try:
        with urlopen(Request(url, data=json.dumps(body).encode(), headers=h, method="POST"), timeout=60) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        rd = getattr(e, "read", None)
        return f"ERR {e} {rd().decode('utf-8','replace')[:300] if rd else ''}"
q = '"vergi usul kanunu" 359'
tries = [
  ("https://karararama.yargitay.gov.tr/aramalist", {"data": {"arananKelime": q, "pageSize": 5, "pageNumber": 1}}),
  ("https://karararama.yargitay.gov.tr/aramalist", {"data": {"arananKelime": "359", "pageSize": 5, "pageNumber": 1, "siralama": "3", "siralamaDirection": "desc"}}),
  ("https://karararama.danistay.gov.tr/aramalist", {"data": {"andKelimeler": ["vergi usul kanunu", "359"], "pageSize": 5, "pageNumber": 1}}),
  ("https://karararama.danistay.gov.tr/aramalist", {"data": {"arananKelime": q, "pageSize": 5, "pageNumber": 1}}),
  ("https://emsal.uyap.gov.tr/aramalist", {"data": {"arananKelime": q, "pageSize": 5, "pageNumber": 1}}),
]
for url, body in tries:
    print("==", url, json.dumps(body, ensure_ascii=False))
    print(post(url, body)[:1500])
