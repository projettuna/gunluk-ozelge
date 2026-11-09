"""Rapor taslağı uçtan uca testi: geçici kullanıcı açar, /api/taslak'ı dener, kullanıcıyı siler.
Depo herkese açık olduğu için yalnızca durum kodları, uzunluklar ve hata metni yazdırılır."""
import json, os, secrets, time
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


try:
    with urlopen(Request(SITE + "/?v=" + secrets.token_hex(3), headers={"User-Agent": "TMPRO-test"}), timeout=30) as r_:
        page = r_.read().decode()
    print("site sürümü: PDF düğmesi", "tsPdf" in page, "| Word", "taslakDoc" in page, "| taslak", "toolTaslak" in page)
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
    st, r = call("POST", SITE + "/api/taslak", {"tur": "inceleme", "konu": "sahte_kullanma", "aciklama": "ABC Gıda A.Ş."}, A)
    print("kimlik bilgisiyle:", st, (r or {}).get("error", "")[:80] if isinstance(r, dict) else r, "(beklenen 422)")
    t0 = time.time()
    st, r = call("POST", SITE + "/api/taslak", {"tur": "inceleme", "konu": "sahte_kullanma", "donem": "2024", "aciklama": ""}, A, timeout=540)
    print("taslak:", st, f"{time.time() - t0:.0f} sn")
    if isinstance(r, dict):
        print("hata:", r.get("error"))
        print("uzunluk:", len(r.get("draft") or ""), "kaynak:", len(r.get("sources") or []), "düşülen hak:", r.get("cost"), "kota:", r.get("quota"))
        print("model:", r.get("model"), r.get("stop"), r.get("usage")); print("yer tutucu sayısı:", (r.get("draft") or "").count("[")); print("kaynak türleri:", [x.get("tur") for x in r.get("sources") or []]); d_ = (r.get("draft") or "").replace("İ", "i").replace("I", "ı").lower()
        for k in ("ikmalen", "re'sen", "353", "7326", "tek başına"):
            at = d_.find(k); print(f"{k}:", d_.count(k), "|", d_[max(0, at - 60):at + 60].replace("\n", " ") if at >= 0 else "")
        print("kesildi:", "kesildi" in (r.get("draft") or "")); print("ön not:", (r.get("draft") or "")[:60].count("not"))
    else:
        print("yanıt:", str(r)[:200])
finally:
    print("silindi:", call("DELETE", f"{URL}/auth/v1/admin/users/{uid}", None, S)[0])
