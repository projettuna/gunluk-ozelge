"""Sohbetin uçtan uca testi: geçici bir kullanıcı açar, mesaj yazar/okur, sonra her şeyi siler.
Depo herkese açık olduğu için yalnızca durum kodları yazdırılır."""
import json, os, secrets, sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_SERVICE_KEY"]
PUB = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")


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
        return e.code, e.read().decode()[:400]


uname = "test" + secrets.token_hex(3)
pw = secrets.token_urlsafe(12)
st, u = call("POST", "/auth/v1/admin/users", {"email": f"{uname}@tmpro.app", "password": pw, "email_confirm": True,
                                              "user_metadata": {"username": uname, "full_name": "Test"}})
print("kullanıcı oluştur:", st)
uid = u["id"] if st < 300 else None
try:
    print("profil aktif:", call("PATCH", f"/rest/v1/profiles?id=eq.{uid}", {"status": "active"})[0])
    st, tok = call("POST", "/auth/v1/token?grant_type=password", {"email": f"{uname}@tmpro.app", "password": pw}, apikey=PUB)
    print("giriş:", st)
    jwt = tok["access_token"]
    for room in ("genel", f"dm:{uid}:00000000-0000-0000-0000-000000000000"):
        st, r = call("POST", "/rest/v1/messages?select=id,room", {"body": "test", "room": room}, token=jwt, apikey=PUB,
                     prefer="return=representation")
        print("yaz", "dm" if room.startswith("dm") else room, st, "" if st < 300 else r)
        st, r = call("GET", f"/rest/v1/messages?select=id&room=eq.{room}", token=jwt, apikey=PUB)
        print("oku", "dm" if room.startswith("dm") else room, st, len(r) if isinstance(r, list) else r)
    st, r = call("POST", "/rest/v1/rpc/list_groups", {}, token=jwt, apikey=PUB)
    print("list_groups:", st, "" if st < 300 else r)
    st, r = call("POST", "/rest/v1/rpc/list_members", {}, token=jwt, apikey=PUB)
    print("list_members:", st, "" if st < 300 else r)
    st, gid = call("POST", "/rest/v1/rpc/create_group", {"gname": "Test grubu", "gpass": "x1"}, token=jwt, apikey=PUB)
    print("create_group:", st, "" if st < 300 else gid)
    if st < 300:
        print("grup mesajı:", call("POST", "/rest/v1/messages", {"body": "t", "room": f"g:{gid}"}, token=jwt, apikey=PUB)[0])
        print("delete_group:", call("POST", "/rest/v1/rpc/delete_group", {"gid": gid}, token=jwt, apikey=PUB)[0])
finally:
    if uid:
        call("DELETE", f"/rest/v1/messages?user_id=eq.{uid}")
        print("temizlik:", call("DELETE", f"/auth/v1/admin/users/{uid}")[0])
