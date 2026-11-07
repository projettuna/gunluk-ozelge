import json
from urllib.request import Request, urlopen
UA = "Mozilla/5.0 ozelge-bildirim/1.0"
def post(url):
    try:
        with urlopen(Request(url, data=b"{}", headers={"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json"}, method="POST"), timeout=60) as r:
            return r.read().decode()
    except Exception as e:
        return f"ERR {e}"
B = "https://gib.gov.tr/api/gibportal/mevzuat/"
for path in ["teblig/list?page=0&size=3&sortFieldName=id&sortType=DESC", "teblig/list?page=0&size=3", "tebligler/listWithFilter?page=0&size=3&sortFieldName=id&sortType=DESC",
             "sirkuler/list?page=0&size=2&sortFieldName=id&sortType=DESC", "tum/list?page=0&size=2&sortFieldName=id&sortType=DESC"]:
    t = post(B + path)
    print("==", path)
    try:
        d = json.loads(t)["resultContainer"]
        print("toplam", d.get("totalElements"))
        for rec in d["content"]:
            r = {k: (v[:150] if isinstance(v, str) else v) for k, v in rec.items()}
            print(json.dumps(r, ensure_ascii=False)[:1800])
    except Exception:
        print(t[:500])
