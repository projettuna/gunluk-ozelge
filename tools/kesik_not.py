"""Yarım kalmış Müfettiş Notlarını bulur. KESIK=say yalnız sayar; KESIK=sifirla notu boşaltır (yorum.py yeniden yazar). Yalnız sayı yazılır."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ozelge, yorum  # noqa: E402
ids, top, off = [], 0, 0
while True:
    rows = ozelge.db("GET", f"items?select=id,yorum,eklendi&yorum=not.is.null&order=id.desc&limit=1000&offset={off}") or []
    top += len(rows)
    ids += [r["id"] for r in rows if yorum.kesik(r["yorum"])]
    if len(rows) < 1000:
        break
    off += 1000
print(f"Kesik not: {len(ids)} / {top}")
if os.environ.get("KESIK") == "sifirla":
    for i in range(0, len(ids), 80):
        ozelge.db("PATCH", "items?id=in.(" + ",".join(map(str, ids[i:i + 80])) + ")", {"yorum": None}, prefer="return=minimal")
    print(f"Sıfırlandı: {len(ids)}")
