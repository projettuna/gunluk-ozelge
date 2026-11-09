"""Fiyat ayarlarını günceller (yalnızca izin verilen anahtarlar). Kullanım: AYAR="fiyat=179,fiyat_yil=1790" python tools/ayar.py"""
import json, os
from urllib.request import Request, urlopen

URL, KEY = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_KEY"]
H = {"apikey": KEY, "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"}
if KEY.startswith("eyJ"):
    H["Authorization"] = "Bearer " + KEY
IZIN = {"fiyat", "fiyat_yil", "sure_gun", "ai_kota"}
rows = []
for part in os.environ.get("AYAR", "").split(","):
    k, _, v = part.partition("=")
    k, v = k.strip(), v.strip()
    if k in IZIN and v.isdigit():
        rows.append({"key": k, "value": v})
print("güncellenecek:", [r["key"] for r in rows])
if rows:
    with urlopen(Request(URL + "/rest/v1/settings?on_conflict=key", data=json.dumps(rows).encode(), headers=H, method="POST"), timeout=30) as r:
        print("durum:", r.status)
