"""Emsal Bul / İçtihat uçtan uca testi: geçici kullanıcı açar, /api/emsal'ı dener, kullanıcıyı siler.
Depo herkese açık olduğu için yalnızca durum kodları, uzunluklar ve hata metni yazdırılır."""
import json, os, re, secrets, time
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_SERVICE_KEY"]
PUB = os.environ["SUPABASE_PUBLISHABLE_KEY"]
SITE = "https://tmpro.tmproapp.workers.dev"


def call(method, url, body=None, h=None, timeout=30):
    req = Request(url, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json", **(h or {})}, method=method)
    try:
        with urlopen(req, timeout=timeout) as r:
            t = r.read().decode()
            return r.status, (json.loads(t) if t else None)
    except HTTPError as e:
        t = e.read().decode()
        try:
            return e.code, json.loads(t)
        except ValueError:
            return e.code, t[:300]


if os.environ.get("KONTROL"):
    S0 = {"apikey": KEY, "Authorization": f"Bearer {KEY}"} if KEY.startswith("eyJ") else {"apikey": KEY}
    for name_, path_ in [("sinav_until kolonu (silinmiş olmalı)", "profiles?select=sinav_until&limit=1"), ("sinav_sorular (silinmiş olmalı)", "sinav_sorular?select=id&limit=1"),
                         ("SINAV paketi", "ai_packages?select=code&code=eq.SINAV"), ("mevzuat_arsiv", "mevzuat_arsiv?select=gid&limit=1")]:
        st_, r_ = call("GET", f"{URL}/rest/v1/{path_}", None, S0)
        print(name_, ":", st_, ("var" if st_ == 200 else "yok"), (len(r_) if isinstance(r_, list) else ""))
    for q_ in ("sahte:* & (fatura:* | belge:*)", "örtülü:* & sermaye:*", "iade:* & (kdv:* | katma:*)"):
        t0_ = time.time(); st_, r_ = call("POST", f"{URL}/rest/v1/rpc/arsiv_ara", {"q": q_, "turler": ["Özelge"], "lim": 30}, {**S0, "Content-Type": "application/json"}, timeout=60)
        print("arşiv arama", q_, ":", st_, f"{time.time() - t0_:.1f} sn", len(r_) if isinstance(r_, list) else str(r_)[:200])
    for tur_ in ("Özelge", "Tebliğ", "Sirküler"):
        req_ = Request(f"{URL}/rest/v1/mevzuat_arsiv?select=gid&tur=eq.{quote(tur_)}", headers={**S0, "Prefer": "count=exact", "Range": "0-0"})
        try:
            with urlopen(req_, timeout=30) as r__:
                print("arşiv", tur_, ":", r__.headers.get("Content-Range"))
        except HTTPError as e:
            print("arşiv", tur_, ":", e.code)
    raise SystemExit
try:
    with urlopen(Request(SITE + "/?v=" + secrets.token_hex(3), headers={"User-Agent": "TMPRO-test"}), timeout=30) as r_:
        page = r_.read().decode()
    print("site sürümü: emsal", "toolEmsal" in page)
except Exception as e:  # noqa: BLE001
    print("site okunamadı:", e)
S = {"apikey": KEY, "Authorization": f"Bearer {KEY}"} if KEY.startswith("eyJ") else {"apikey": KEY}
name, pw = "test" + secrets.token_hex(3), secrets.token_urlsafe(12)
st, u = call("POST", URL + "/auth/v1/admin/users", {"email": f"{name}@tmpro.app", "password": pw, "email_confirm": True, "user_metadata": {"username": name, "full_name": "Test"}}, S)
uid = u["id"]
try:
    call("PATCH", f"{URL}/rest/v1/profiles?id=eq.{uid}", {"status": "active"}, S)
    st2, tok = call("POST", URL + "/auth/v1/token?grant_type=password", {"email": f"{name}@tmpro.app", "password": pw}, {"apikey": PUB})
    print("kullanıcı:", st, "giriş:", st2)
    A = {"Authorization": "Bearer " + tok["access_token"], "User-Agent": "TMPRO-test"}
    if os.environ.get("ICTIHAT"):
        for k in ["sahte_kullanma", "kdv_iade", "ortulu_sermaye", "transfer", "ibraz"]:
            t0 = time.time(); st, r = call("GET", f"{SITE}/api/ictihat?konu={k}", None, A, timeout=60)
            r = r if isinstance(r, dict) else {"error": str(r)[:120]}
            print("içtihat", k, st, f"{time.time() - t0:.1f} sn", "karar:", r.get("n"), "canlı:", r.get("canli"), "özet:", r.get("ozet"), "sonuç:", r.get("sonuc"), "hata:", r.get("error"))
            if r.get("dbg"): print("dbg:", r.get("dbg"))
        raise SystemExit
    st, r = call("POST", SITE + "/api/emsal", {"konu": "sahte_kullanma", "aciklama": "ABC Gıda A.Ş."}, A)
    print("kimlik bilgisiyle:", st, "(beklenen 422)")
    for konu_ in (os.environ.get("TK") or "sahte_kullanma,kdv_iade,ortulu_sermaye").split(","):
        t0 = time.time()
        st, r = call("POST", SITE + "/api/emsal", {"konu": konu_, "aciklama": ""}, A, timeout=180)
        r = r if isinstance(r, dict) else {"error": str(r)[:120]}
        L = r.get("list") or []
        print("emsal", konu_, st, f"{time.time() - t0:.0f} sn", "karar:", sum(1 for x in L if x.get("karar")), "idari:", sum(1 for x in L if not x.get("karar")),
              "türler:", sorted({x.get("tur") for x in L}), "sonuçlu:", sum(1 for x in L if x.get("sonuc") and x["sonuc"] != "Belirsiz"),
              "özetli:", sum(1 for x in L if x.get("ozet")), "kullanım:", sum(1 for x in L if x.get("kullanim")), "elenen:", r.get("elenen"), "aday:", r.get("aday"),
              "madde:", len(r.get("maddeler") or []), "hak:", r.get("cost"), "özetsiz:", r.get("ozetsiz"), "hata:", r.get("error"))
finally:
    print("silindi:", call("DELETE", f"{URL}/auth/v1/admin/users/{uid}", None, S)[0])
