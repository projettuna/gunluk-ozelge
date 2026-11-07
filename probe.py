"""Geçici teşhis: Yargıtay ve Emsal'de vergi kaçakçılığı aramaları."""
import json, time, http.cookiejar
from urllib.request import Request, build_opener, HTTPCookieProcessor
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
op = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
def call(url, body=None, t=200):
    h = {"User-Agent": UA, "Accept": "application/json, text/plain, */*", "Content-Type": "application/json; charset=UTF-8",
         "X-Requested-With": "XMLHttpRequest", "Origin": url.split("/aramalist")[0].rstrip("/"), "Referer": url.rsplit("/", 1)[0] + "/"}
    t0 = time.time()
    try:
        data = json.dumps(body).encode() if body is not None else None
        with op.open(Request(url, data=data, headers=h, method="POST" if data else "GET"), timeout=t) as r:
            out = r.read().decode("utf-8", "replace")
    except Exception as e:
        out = f"ERR {e}"
    return round(time.time() - t0, 1), out
def show(tag, res):
    sec, t = res
    try:
        d = json.loads(t)["data"]
        print(tag, sec, "s", d["recordsTotal"], [(x["id"], x["kararTarihi"], x.get("daire")) for x in d["data"]])
    except Exception:
        print(tag, sec, "s", t[:300])
Y = "https://karararama.yargitay.gov.tr"
print("Y home", call(Y + "/", t=60)[0])
for kw in ["kaçakçılığı", "vergi kaçakçılığı", "\"vergi kaçakçılığı\""]:
    show(f"Y {kw}", call(Y + "/aramalist", {"data": {"arananKelime": kw, "pageSize": 10, "pageNumber": 1}}))
show("Y detayli", call(Y + "/aramadetaylist", {"data": {"arananKelime": "vergi kaçakçılığı", "birimYrgCezaDaire": "11. Ceza Dairesi", "baslangicTarihi": "01.09.2026", "bitisTarihi": "07.11.2026", "siralama": "3", "siralamaDirection": "desc", "pageSize": 10, "pageNumber": 1}}))
E = "https://emsal.uyap.gov.tr"
show("E vk", call(E + "/aramalist", {"data": {"arananKelime": "vergi kaçakçılığı", "pageSize": 10, "pageNumber": 1}}))
show("E detay", call(E + "/aramadetaylist", {"data": {"arananKelime": "vergi kaçakçılığı", "Bam Ceza Mahkemesi": "all", "baslangicTarihi": "01.09.2026", "bitisTarihi": "07.11.2026", "siralama": "1", "siralamaDirection": "desc", "pageSize": 10, "pageNumber": 1}}))
