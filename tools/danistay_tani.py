"""Danıştay karar arama tanısı: adreslerin durum kodu, izin verilen yöntem ve yanıtın başı (herkese açık site)."""
import json
import os
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ozelge  # noqa: E402

B = ozelge.DANISTAY
body = json.dumps({"data": {"andKelimeler": ozelge.DANISTAY_WORDS, "pageSize": 5, "pageNumber": 1}}).encode()
H = {"User-Agent": ozelge.UA, "Accept": "application/json, text/html"}
J = dict(H, **{"Content-Type": "application/json; charset=UTF-8"})
X = dict(J, **{"X-Requested-With": "XMLHttpRequest", "Origin": B, "Referer": B + "/"})
for label, url, data, hd in (("GET /", B + "/", None, H), ("POST /aramalist", B + "/aramalist", body, J),
                             ("POST /aramalist (tarayıcı başlıkları)", B + "/aramalist", body, X),
                             ("GET /aramalist", B + "/aramalist", None, H),
                             ("POST /aramadetaylist", B + "/aramadetaylist", body, X)):
    try:
        with urlopen(Request(url, data=data, headers=hd, method="POST" if data else "GET"), timeout=60) as r:
            t = r.read().decode("utf-8", "replace")
            print(label, r.status, r.headers.get("Content-Type"), r.geturl(), len(t), "|", " ".join(t[:400].split()))
            if data is None and url.endswith("/"):
                import re
                print("  script/uç:", sorted(set(re.findall(r'(?:src|action|url)\s*[=:]\s*["\']([^"\']{3,80})["\']', t)))[:40])
    except HTTPError as e:
        t = e.read().decode("utf-8", "replace")
        print(label, e.code, "Allow=", e.headers.get("Allow"), "Server=", e.headers.get("Server"), "|", " ".join(t[:300].split()))
    except Exception as e:  # noqa: BLE001
        print(label, "hata", type(e).__name__, e)
