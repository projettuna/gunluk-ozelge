"""Sohbetin uçtan uca testi: geçici kullanıcılar açar; oda, özel mesaj ve şifreli grup akışını dener, sonra her şeyi siler.
Depo herkese açık olduğu için yalnızca durum kodları ve sayılar yazdırılır."""
import json, os, secrets
from urllib.request import Request, urlopen
from urllib.error import HTTPError

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_SERVICE_KEY"]
PUB = os.environ["SUPABASE_PUBLISHABLE_KEY"]


def call(method, path, body=None, token=None, apikey=None, prefer=None):
    h = {"apikey": apikey or KEY, "Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if prefer:
        h["Prefer"] = prefer
    req = Request(URL + path, data=json.dumps(body).encode() if body is not None else None, headers=h, method=method)
    try:
        with urlopen(req, timeout=30) as r:
            t = r.read().decode()
            return r.status, (json.loads(t) if t else None)
    except HTTPError as e:
        return e.code, e.read().decode()[:300]


def user():
    name, pw = "test" + secrets.token_hex(3), secrets.token_urlsafe(12)
    st, u = call("POST", "/auth/v1/admin/users", {"email": f"{name}@tmpro.app", "password": pw, "email_confirm": True,
                                                  "user_metadata": {"username": name, "full_name": "Test"}})
    call("PATCH", f"/rest/v1/profiles?id=eq.{u['id']}", {"status": "active"})
    st2, tok = call("POST", "/auth/v1/token?grant_type=password", {"email": f"{name}@tmpro.app", "password": pw}, apikey=PUB)
    print("kullanıcı:", st, "giriş:", st2)
    return u["id"], tok["access_token"]


def as_(tok, method, path, body=None):
    return call(method, path, body, token=tok, apikey=PUB, prefer="return=representation")


def count(tok, room):
    st, r = as_(tok, "GET", f"/rest/v1/messages?select=id&room=eq.{room}")
    return len(r) if isinstance(r, list) else f"hata {st}"


ids = []
try:
    a, ta = user(); ids.append(a)
    b, tb = user(); ids.append(b)
    c, tc = user(); ids.append(c)
    # Özel mesaj: arkadaş olmadan yazılamaz; kodla istek + kabul sonrası yazılır
    dm = "dm:" + ":".join(sorted([a, b]))
    print("dm arkadaş değilken A yazar:", as_(ta, "POST", "/rest/v1/messages", {"body": "x", "room": dm})[0], "(beklenen 403)")
    st, code = as_(tb, "POST", "/rest/v1/rpc/my_friend_code", {})
    print("B kodu alındı:", st, "uzunluk:", len(code or "") if isinstance(code, str) else code)
    print("A istek:", as_(ta, "POST", "/rest/v1/rpc/friend_request", {"code": code})[1], "(beklenen gonderildi)")
    print("A tekrar istek:", as_(ta, "POST", "/rest/v1/rpc/friend_request", {"code": code})[1], "(beklenen bekliyor)")
    print("C yanlış kod:", as_(tc, "POST", "/rest/v1/rpc/friend_request", {"code": "000000"})[1], "(beklenen bulunamadi)")
    print("istek kabul edilmeden A yazar:", as_(ta, "POST", "/rest/v1/messages", {"body": "x", "room": dm})[0], "(beklenen 403)")
    print("B kabul:", as_(tb, "POST", "/rest/v1/rpc/friend_respond", {"other": a, "accept": True})[0])
    st, fl = as_(ta, "POST", "/rest/v1/rpc/list_friends", {})
    print("A arkadaş listesinde B:", isinstance(fl, list) and any(x["id"] == b and x["kind"] == "friend" for x in fl),
          "arkadaşın adı açık:", isinstance(fl, list) and any(x["id"] == b and x["name"] == "Test" for x in fl), "(beklenen True)")
    st, mu = as_(ta, "POST", "/rest/v1/rpc/set_mute", {"k": "sohbet", "saat": 1})
    print("susturma:", st, isinstance(mu, dict) and "sohbet" in mu, "kaldır:", as_(ta, "POST", "/rest/v1/rpc/set_mute", {"k": "sohbet", "saat": 0})[1], "(beklenen 200 True {})")
    print("ekrandaki sohbet:", as_(ta, "POST", "/rest/v1/rpc/set_active_room", {"r": "genel"})[0], "(beklenen 204)")
    print("dm yaz A:", as_(ta, "POST", "/rest/v1/messages", {"body": "x", "room": dm})[0], "(beklenen 201)")
    print("dm oku A/B/C:", count(ta, dm), count(tb, dm), count(tc, dm), "(beklenen 1 1 0)")
    st, ms = as_(tb, "GET", f"/rest/v1/messages?select=username&room=eq.{dm}")
    print("mesajda gönderen adı yıldızlı:", isinstance(ms, list) and all("*" in (m.get("username") or "") for m in ms))
    print("C (arkadaş değil) dm'ye yazar:", as_(tc, "POST", "/rest/v1/messages", {"body": "x", "room": dm})[0], "(beklenen 403)")
    print("arkadaşlıktan çık:", as_(ta, "POST", "/rest/v1/rpc/friend_remove", {"other": b})[0],
          "sonra A yazar:", as_(ta, "POST", "/rest/v1/messages", {"body": "x", "room": dm})[0], "(beklenen 403)")
    # Şifreli grup
    st, gid = as_(ta, "POST", "/rest/v1/rpc/create_group", {"gname": "Test", "gpass": "gizli1"})
    print("grup kur:", st)
    g = f"g:{gid}"
    print("grup yaz A:", as_(ta, "POST", "/rest/v1/messages", {"body": "x", "room": g})[0])
    print("üye olmayan B okur:", count(tb, g), "(beklenen 0)")
    print("üye olmayan B yazar:", as_(tb, "POST", "/rest/v1/messages", {"body": "x", "room": g})[0], "(beklenen 403/401)")
    print("B yanlış şifre:", as_(tb, "POST", "/rest/v1/rpc/join_group", {"gid": gid, "gpass": "yanlis"})[1], "(beklenen false)")
    print("B doğru şifre:", as_(tb, "POST", "/rest/v1/rpc/join_group", {"gid": gid, "gpass": "gizli1"})[1], "(beklenen true)")
    print("grup yaz B:", as_(tb, "POST", "/rest/v1/messages", {"body": "y", "room": g})[0])
    print("grup oku A/B/C:", count(ta, g), count(tb, g), count(tc, g), "(beklenen 2 2 0)")
    st, lst = as_(tb, "POST", "/rest/v1/rpc/list_groups", {})
    me = [x for x in lst if x["id"] == gid] if isinstance(lst, list) else []
    print("B listede üye mi:", me and me[0]["is_member"], "üye sayısı:", me and me[0]["members"])
    print("B ayrıl:", as_(tb, "POST", "/rest/v1/rpc/leave_group", {"gid": gid})[0], "sonra B okur:", count(tb, g))
    print("grup sil (A):", as_(ta, "POST", "/rest/v1/rpc/delete_group", {"gid": gid})[0])
finally:
    for uid in ids:
        call("DELETE", f"/rest/v1/messages?user_id=eq.{uid}")
        call("DELETE", f"/auth/v1/admin/users/{uid}")
    print("temizlik tamam:", len(ids))
