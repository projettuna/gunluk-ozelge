"""Danıştay karar arama tanısı: yeni sitenin betiğindeki uç adresleri (herkese açık site)."""
import os
import re
import sys
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ozelge  # noqa: E402

B = ozelge.DANISTAY
H = {"User-Agent": ozelge.UA}
page = urlopen(Request(B + "/", headers=H), timeout=60).read().decode("utf-8", "replace")
for src in re.findall(r'src="(/static/js/[^"]+)"', page):
    js = urlopen(Request(B + src, headers=H), timeout=120).read().decode("utf-8", "replace")
    print(src, len(js))
    found = set(re.findall(r'["\'`]((?:https?://[^"\'`\s]{4,120})|(?:/?[A-Za-z0-9_\-/]*(?:api|rest|arama|karar|dokuman|Dokuman|search|emsal|ictihat)[A-Za-z0-9_\-/?=&.{}$]*))["\'`]', js))
    for f in sorted(found):
        if len(f) < 140 and not f.startswith(("http://www.w3", "https://reactjs", "https://github", "https://mui", "https://fb.me")):
            print("  ", f)
    for m in re.finditer(r'(axios|fetch)\s*[.(][^;]{0,160}', js):
        s = m.group(0)
        if re.search(r'arama|karar|okuman|api', s, re.I):
            print("  >>", " ".join(s.split())[:200])
    for m in re.finditer(r'baseURL\s*:\s*[^,}]{0,120}', js):
        print("  base:", m.group(0)[:150])
