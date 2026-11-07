import re
from urllib.request import Request, urlopen
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
def get(url, t=60):
    try:
        with urlopen(Request(url, headers={"User-Agent": UA}), timeout=t) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        return f"ERR {e}"
for base in ["https://kararlarbilgibankasi.anayasa.gov.tr", "https://normkararlarbilgibankasi.anayasa.gov.tr"]:
    h = get(base + "/")
    print("==", base); print(h[:2452])
    for s in re.findall(r'src="([^"]+\.js[^"]*)"', h):
        u = s if s.startswith("http") else base + "/" + s.lstrip("/")
        js = get(u)
        print(" JS", u, len(js))
        print("  urls:", sorted(set(re.findall(r'["\'`](/?api/[^"\'`]{2,80}|https?://[a-z0-9.\-]*anayasa[^"\'`]{0,80})["\'`]', js)))[:60])
        print("  ara:", sorted(set(re.findall(r'["\'`]([^"\'`]{0,40}(?:Ara|ara|search|Search)[^"\'`]{0,40})["\'`]', js)))[:60])
