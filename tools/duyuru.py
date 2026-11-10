"""Tek seferlik duyuru: aktif üyelere (test hesabı hariç) anlık bildirim. Yönetici isteğiyle elle çalıştırılır. Yalnızca sayı yazılır."""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ozelge  # noqa: E402

BASLIK = "Bugün VDK için ne yaptın? 🕵️"
METIN = "Bir özelge mi okudun, yoksa üçüncü çayı mı demledin? ☕ Yeni özelge ve kararlar TMPRO'da seni bekliyor."
now = datetime.now(timezone.utc)
users = ozelge.db("GET", "profiles?select=id,role,status,expires_at,mute") or []
n = 0
for u in users:
    exp = u.get("expires_at")
    if ozelge.muted(u, "duyuru"):
        continue
    if not (u["role"] == "admin" or (u["status"] == "active" and (not exp or datetime.fromisoformat(exp) > now))):
        continue
    try:
        ozelge.db("POST", "rpc/notify_user_url", {"uid": u["id"], "title": BASLIK, "body": METIN, "link": "/"})
        n += 1
    except Exception:  # noqa: BLE001
        pass
print(f"Duyuru: {n} üyeye gönderildi")
