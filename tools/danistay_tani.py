"""Danıştay yeni arama ucunun doğrulaması ve eski (artık açılmayan) karar bağlantılarının yeni adrese çevrilmesi. Yalnızca sayılar yazılır."""
import json
import os
import sys
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ozelge  # noqa: E402

ks = ozelge.get_kararlar()
with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "seen.json"), encoding="utf-8") as f:
    seen = set(json.load(f).get("karar_seen", []))
print(f"Liste: {len(ks)} karar, daha önce görülen {len([k for k in ks if k['id'] in seen])}, en yeni tarih {ks[0]['tarih'] if ks else '-'}")
if ks:
    snip, doc = ozelge.karar_snippet(ks[0]["id"])
    print(f"İlk karar: özet {len(snip or '')} karakter, metin {len(doc or '')} karakter")

if os.environ.get("BAGLANTI") == "1":
    for tablo, anahtar in (("items", "id"), ("mevzuat_arsiv", "gid")):
        n, son = 0, 0
        while True:
            rows = ozelge.db("GET", f"{tablo}?select={anahtar},url&url=like.*getDokuman*&{anahtar}=gt.{son}&order={anahtar}&limit=500") or []
            for r in rows:
                son = r[anahtar]
                kid = ozelge.karar_id_of(r["url"])
                if not kid:
                    continue
                kw = (parse_qs(urlparse(r["url"]).query).get("arananKelime") or [""])[0]
                ozelge.db("PATCH", f"{tablo}?{anahtar}=eq.{r[anahtar]}&url=like.*getDokuman*", {"url": ozelge.karar_link(kid, [w for w in kw.split(",") if w] or None)})
                n += 1
            if len(rows) < 500:
                break
        print(f"{tablo}: {n} bağlantı yeni adrese çevrildi")
