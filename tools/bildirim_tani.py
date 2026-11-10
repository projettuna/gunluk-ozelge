"""Bildirim tanısı: üye başına (kimliksiz) abonelik, tür seçimi, susturma ve bekleyen kayıt sayısı. Yalnızca sayılar yazılır."""
import os
import sys
from datetime import datetime, timezone
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ozelge  # noqa: E402

db = ozelge.db
subs = db("GET", "push_subs?select=user_id,created_at") or []
users = db("GET", "profiles?select=id,role,status,expires_at,notify_types,last_notified_at,mute") or []
now = datetime.now(timezone.utc)
bugun = db("GET", "items?select=tur,created_at&eklendi=not.is.null&created_at=gte.2026-11-10T00:00:00Z&order=id") or []
print("Bugün eklenen kayıt türleri:", sorted({b["tur"] for b in bugun}), len(bugun))
for i, u in enumerate(users, 1):
    us = [s for s in subs if s["user_id"] == u["id"]]
    exp = u.get("expires_at")
    act = u["role"] == "admin" or (u["status"] == "active" and (not exp or datetime.fromisoformat(exp) > now))
    t = u.get("notify_types") or []
    m = {k: v for k, v in (u.get("mute") or {}).items() if v}
    ln = u.get("last_notified_at")
    ago = round((now - datetime.fromisoformat(ln)).total_seconds() / 60) if ln else None
    pend = len([b for b in bugun if b["tur"] in t and ln and b["created_at"] > ln])
    print(f"üye{i}: {'yönetici' if u['role'] == 'admin' else u['status']} aktif={act} abonelik={len(us)} türler={len(t)} Özelge={'Özelge' in t} Tebliğ={'Tebliğ' in t} RG={'Resmî Gazete' in t} susturma={list(m.keys())} son_bildirim_dk={ago} bekleyen={pend}")
