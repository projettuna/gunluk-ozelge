"""Danıştay karar arama tanısı: yeni site betiğinde arama uçlarının geçtiği yerler (herkese açık site)."""
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
    for key in sys.argv[1:]:
        hits = [m.start() for m in re.finditer(re.escape(key), js)]
        print("##", key, len(hits))
        last = -9999
        n = 0
        for h in hits:
            if h - last < 500:
                continue
            last = h
            n += 1
            if n > 6:
                break
            print("  ..", " ".join(js[max(0, h - 350):h + 450].split()))
