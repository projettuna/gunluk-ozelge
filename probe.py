import re, json
from urllib.request import Request, urlopen
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
def get(url, body=None, t=60):
    try:
        data = json.dumps(body).encode() if body is not None else None
        with urlopen(Request(url, data=data, headers={"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json"}, method="POST" if data else "GET"), timeout=t) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        rd = getattr(e, "read", None)
        return f"ERR {e} {rd().decode('utf-8','replace')[:300] if rd else ''}"
B = "https://kararlarbilgibankasi.anayasa.gov.tr"
print("CFG", get(B + "/kbb/network-config.js"))
js = get(B + "/kbb/assets/index-DJw1O8y-.js")
for pat in [r'\$\{[A-Za-z_$]{1,4}\}/[A-Za-z0-9_/\-${}.?=&]{2,80}', r'[A-Za-z_$]{1,4}=window\.[A-Za-z_]+[^,;]{0,80}', r'baseURL[^,;]{0,100}', r'NETWORK[^,;]{0,100}']:
    print(pat, sorted(set(re.findall(pat, js)))[:80])
for k in ["Ms=", "/arama", "/search", "kararlar/ara", "pageSize", "siralama", "sortBy", "orderBy"]:
    i = js.find(k)
    print("CTX", k, js[max(0, i-300):i+400].replace("\n", " ") if i >= 0 else None)
