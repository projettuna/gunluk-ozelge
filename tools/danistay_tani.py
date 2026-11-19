"""Danıştay karar arama tanısı: yeni (Bedesten) arama ucunun yanıt biçimi (herkese açık site)."""
import base64
import json
import os
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ozelge  # noqa: E402

S = "https://bedesten.adalet.gov.tr/emsal-karar/"
H = {"User-Agent": ozelge.UA, "Accept": "application/json, text/plain, */*", "Content-Type": "application/json; charset=UTF-8",
     "Origin": ozelge.DANISTAY, "Referer": ozelge.DANISTAY + "/"}


def post(path, body, extra=None):
    try:
        with urlopen(Request(S + path, data=json.dumps(body).encode(), headers=dict(H, **(extra or {})), method="POST"), timeout=90) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


d = {"itemTypeList": ["DANISTAYKARAR"], "andKelimeler": ozelge.DANISTAY_WORDS, "orKelimeler": [], "notKelimeler": [], "pageSize": 10, "pageNumber": 1}
doc_id = None
for label, body, extra in (("yalın", {"data": d}, None), ("uygulama adı", {"data": d, "applicationName": "UyapMevzuat"}, {"AdaletApplicationName": "UyapMevzuat"})):
    code, t = post("getEmsalKarar", body, extra)
    print(label, code, len(t), "|", t[:300])
    try:
        j = json.loads(t)
        lst = (j.get("data") or {}).get("emsalKararList") or []
        print("  üst anahtarlar:", list(j.keys()), "data:", list((j.get("data") or {}).keys()), "adet:", len(lst))
        for it in lst[:3]:
            print("  kayıt:", json.dumps(it, ensure_ascii=False)[:600])
        if lst and not doc_id:
            doc_id = lst[0].get("documentId") or lst[0].get("id")
    except ValueError:
        pass
if doc_id:
    for body in ({"data": {"documentId": str(doc_id)}}, {"data": {"documentId": str(doc_id)}, "applicationName": "UyapMevzuat"}, {"documentId": str(doc_id)}):
        code, t = post("getDocContent", body)
        print("belge", list(body.keys()), code, len(t), "|", t[:200])
        try:
            j = json.loads(t)
            dd = j.get("data") or j
            print("  anahtarlar:", list(dd.keys()) if isinstance(dd, dict) else type(dd))
            c = dd.get("content") if isinstance(dd, dict) else None
            if c:
                raw = base64.b64decode(c)
                print("  mime:", dd.get("mimeType"), "çözülmüş:", len(raw), "|", " ".join(raw[:400].decode("utf-8", "replace").split()))
                break
        except ValueError:
            pass
