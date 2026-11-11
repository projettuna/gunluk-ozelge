"""Yalnız yöneticiye: en son Danıştay kaydına giden deneme bildirimi (bildirime dokununca karar açılmalı)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ozelge  # noqa: E402
adm = ozelge.db("GET", "profiles?select=id&role=eq.admin")
it = ozelge.db("GET", "items?select=id,tur,title&tur=ilike.*Danıştay*&eklendi=not.is.null&order=id.desc&limit=1")
for a in adm:
    ozelge.db("POST", "rpc/notify_user_url", {"uid": a["id"], "title": "Deneme · " + it[0]["tur"], "body": it[0]["title"][:150],
                                              "link": "/?kayit=" + str(it[0]["id"])})
print(f"Deneme: {len(adm)} yöneticiye, kayıt {'bulundu' if it else 'yok'}")
