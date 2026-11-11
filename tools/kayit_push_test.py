"""Yalnız hesaba: en son Danıştay kaydına giden deneme bildirimi (bildirime dokununca karar açılmalı)."""
import os, sys
from urllib.parse import quote
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ozelge  # noqa: E402
adm = ozelge.db("GET", "profiles?select=id&role=eq.admin")
sur = ozelge.db("GET", "profiles?select=id&role=neq.admin&status=eq.active&ai_unlimited=is.true&username=neq.nobetci")
if len(sur) == 1:  # yalnız tek süresiz hesap varsa (kurucu üye) denemeye eklenir
    adm += sur
it = ozelge.db("GET", "items?select=id,tur,title&tur=ilike." + quote("*Danıştay*") + "&eklendi=not.is.null&order=id.desc&limit=1")
for a in adm:
    ozelge.db("POST", "rpc/notify_user_url", {"uid": a["id"], "title": "Deneme · " + it[0]["tur"], "body": it[0]["title"][:150],
                                              "link": "/?kayit=" + str(it[0]["id"])})
print(f"Deneme: {len(adm)} hesaba, kayıt {'bulundu' if it else 'yok'}")
