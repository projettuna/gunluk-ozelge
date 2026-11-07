import json
from urllib.request import Request, urlopen
UA = "Mozilla/5.0 ozelge-bildirim/1.0"
def call(url, body=None):
    try:
        data = json.dumps(body).encode() if body is not None else None
        with urlopen(Request(url, data=data, headers={"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json"}, method="POST" if data else "GET"), timeout=60) as r:
            return r.read().decode()
    except Exception as e:
        rd = getattr(e, "read", None)
        return f"ERR {e} {rd().decode()[:200] if rd else ''}"
A = "https://gib.gov.tr/api/gibportal/"
for path, body in [("search/mevzuatLastAdded", None), ("search/mevzuatLastAdded", {}), ("search/mevzuatLastAdded?page=0&size=20", {}),
                   ("search/mevzuatLastAdded?page=0&size=20", None), ("mevzuat/teblig/list?page=0&size=5", {"lastAddedStatus": True})]:
    t = call(A + path, body)
    print("==", path, body, len(t)); print(t[:2500])
