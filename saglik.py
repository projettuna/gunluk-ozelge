#!/usr/bin/env python3
"""TMPRO nöbetçisi: sistemin parçalarını düzenli kontrol eder, sorun çıkınca yöneticinin telefonuna bildirim yollar.

Kontroller: site, bildirim aktarıcısı, veritabanı, veri tazeliği, ana tarama işi, üye e-postaları,
yapay zekâ anahtarı/kredisi, Yargıtay telefonu, veritabanı kurulumu.
Depo herkese açık: yalnızca kontrol adları ve sayılar yazdırılır.
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

APP = "https://tmpro.tmproapp.workers.dev/"
SB = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
AI_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GH = os.environ.get("GITHUB_TOKEN", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "")
TR = timezone(timedelta(hours=3))
NOW = datetime.now(timezone.utc)
REMIND = timedelta(hours=6)
TEST = "--test-alert" in sys.argv


def http(url, data=None, headers=None, method=None, timeout=30):
    req = Request(url, data=json.dumps(data).encode() if data is not None else None,
                  headers={"User-Agent": "TMPRO-nobetci/1.0", **(headers or {})}, method=method)
    try:
        with urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), dict(e.headers or {})


def sbh(extra=None):
    h = {"apikey": KEY, "Content-Type": "application/json"}
    if KEY.startswith("eyJ"):
        h["Authorization"] = f"Bearer {KEY}"
    return {**h, **(extra or {})}


def db(path, data=None, method=None, extra=None):
    code, body, hdr = http(f"{SB}/rest/v1/{path}", data, sbh(extra), method)
    if code >= 300:
        raise RuntimeError(f"db {code}")
    return (json.loads(body) if body else None), hdr


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


problems = {}  # anahtar -> (seviye, mesaj); seviye: "kritik" | "uyari"


def check(name, fn):
    try:
        fn()
        print(f"✓ {name}")
    except Exception as e:  # noqa: BLE001
        problems.setdefault(name, ("kritik", f"{name}: kontrol hatası ({type(e).__name__})"))
        print(f"✗ {name}: {type(e).__name__}")


def bad(name, level, msg):
    problems[name] = (level, msg)


# ---------------------------------------------------------------- kontroller

def site():
    code, body, _ = http(APP)
    if code != 200 or "TMPRO" not in body:
        bad("site", "kritik", f"Uygulama açılmıyor (HTTP {code})")
    code, _, _ = http(APP + "surum.json?t=" + str(int(time.time())))
    if code != 200:
        bad("surum", "uyari", "Sürüm dosyası okunamıyor")


def relay():
    code, _, _ = http(APP + "api/push", {}, {"Content-Type": "application/json"}, "POST")
    if code >= 500 or code == 404:
        bad("relay", "kritik", f"Bildirim aktarıcısı çalışmıyor (HTTP {code}); sohbet ve onay bildirimleri gitmez")


def database():
    rows, _ = db("items?select=created_at,tur&order=created_at.desc&limit=1")
    last = ts(rows[0]["created_at"]) if rows else None
    if not last or NOW - last > timedelta(days=4):
        bad("tazelik", "uyari", "4 gündür hiç yeni kayıt eklenmedi; kaynak siteler değişmiş olabilir")


def setup():
    for col, what in (("friend_code", "arkadaş sistemi"), ("avatar", "profil fotoğrafı"), ("email", "üye e-postası")):
        try:
            db(f"profiles?select={col}&limit=1")
        except RuntimeError:
            bad("kurulum_" + col, "uyari", f"Veritabanında {what} kurulumu eksik görünüyor")


def main_job():
    if not GH or not REPO:
        return
    code, body, _ = http(f"https://api.github.com/repos/{REPO}/actions/workflows/gunluk.yml/runs?per_page=20&status=completed",
                         headers={"Authorization": f"Bearer {GH}", "Accept": "application/vnd.github+json"})
    if code != 200:
        raise RuntimeError(f"github {code}")
    runs = [r for r in json.loads(body)["workflow_runs"] if r["event"] == "schedule"]
    if len(runs) >= 3 and all(r["conclusion"] == "failure" for r in runs[:3]):
        bad("tarama", "kritik", "Otomatik tarama son 3 denemede hata verdi; yeni mevzuat gelmiyor")
    ok = [ts(r["created_at"]) for r in runs if r["conclusion"] == "success"]
    if not ok or NOW - max(ok) > timedelta(hours=3):
        bad("tarama_gecikme", "kritik", "Otomatik tarama 3 saattir başarıyla çalışmadı")


def mails():
    since = (NOW - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows, _ = db(f"mail_queue?select=id&error=not.is.null&created_at=gte.{since}")
    if rows:
        bad("eposta", "uyari", f"Son 24 saatte {len(rows)} üye e-postası gönderilemedi")
    old = (NOW - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows, _ = db(f"mail_queue?select=id&sent_at=is.null&error=is.null&created_at=lt.{old}")
    if rows:
        bad("eposta_bekleyen", "uyari", f"{len(rows)} üye e-postası 2 saattir gönderilmeyi bekliyor")


def ai():
    if not AI_KEY:
        bad("yapay_zeka", "kritik", "Yapay zekâ anahtarı tanımlı değil")
        return
    code, body, _ = http("https://api.anthropic.com/v1/messages",
                         {"model": "claude-haiku-5-5", "max_tokens": 1, "messages": [{"role": "user", "content": "1"}]},
                         {"x-api-key": AI_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}, "POST")
    if code == 200:
        return
    msg = ""
    try:
        msg = json.loads(body).get("error", {}).get("message", "")
    except ValueError:
        pass
    if "credit balance" in msg:
        bad("yapay_zeka", "kritik", "Anthropic kredisi bitti; Asistan ve Müfettiş Notu çalışmıyor. console.anthropic.com → Billing")
    elif code in (401, 403):
        bad("yapay_zeka", "kritik", "Yapay zekâ anahtarı geçersiz; Asistan çalışmıyor")
    elif code >= 500 or code == 429:
        bad("yapay_zeka_gecici", "uyari", f"Yapay zekâ servisi yanıt vermiyor (HTTP {code})")


def phone():
    rows, _ = db("items?select=eklendi&tur=eq.Yarg%C4%B1tay%20(Ceza)&eklendi=not.is.null&order=eklendi.desc&limit=1")
    last = ts(rows[0]["eklendi"]) if rows else None
    if last and NOW - last > timedelta(days=10):
        bad("telefon", "uyari", "10 gündür telefondan yeni Yargıtay kararı gelmedi; telefon/Termux açık mı?")


# ---------------------------------------------------------------- bildirim

def push_admins(title, body):
    from pywebpush import webpush, WebPushException
    vapid = db("private_settings?key=eq.vapid_private&select=value")[0][0]["value"]
    admins = [p["id"] for p in db("profiles?select=id&role=eq.admin")[0]]
    subs = db("push_subs?select=id,user_id,endpoint,p256dh,auth")[0] or []
    payload = json.dumps({"title": title, "body": body[:220], "url": APP, "tag": "tmpro-nobet"})
    n = 0
    for s in subs:
        if s["user_id"] not in admins:
            continue
        try:
            webpush({"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}}, payload,
                    vapid_private_key=vapid, vapid_claims={"sub": "mailto:bildirim@tmpro.app"}, ttl=86400)
            n += 1
        except WebPushException:
            pass
    print(f"Yöneticiye bildirim: {n} cihaz")


def main():
    if not SB or not KEY:
        print("Supabase ayarı yok")
        return
    for name, fn in (("site", site), ("aktarıcı", relay), ("veritabanı", database), ("kurulum", setup),
                     ("tarama", main_job), ("e-posta", mails), ("yapay zekâ", ai), ("telefon", phone)):
        check(name, fn)
    if TEST:
        bad("deneme", "kritik", "Bu bir deneme uyarısıdır, nöbetçi çalışıyor")

    try:
        st = json.loads(db("private_settings?key=eq.health_state&select=value")[0][0]["value"])
    except Exception:  # noqa: BLE001
        st = {}
    old = st.get("open", {})
    hour = datetime.now(TR).hour
    night = hour >= 23 or hour < 7
    new = {k: v for k, v in problems.items() if k not in old}
    fixed = [k for k in old if k not in problems]
    due = problems and (NOW - (ts(st.get("last_alert")) or NOW - REMIND - timedelta(1))) >= REMIND
    send = [v for k, v in problems.items() if (k in new or due) and (v[0] == "kritik" or not night)]
    print(f"Sorun: {len(problems)} (yeni {len(new)}, düzelen {len(fixed)})")

    if send:
        crit = [m for lv, m in send if lv == "kritik"]
        title = "⚠️ TMPRO: " + ("acil sorun" if crit else "dikkat") + (f" ({len(send)})" if len(send) > 1 else "")
        push_admins(title, " • ".join(m for _, m in send))
        st["last_alert"] = NOW.isoformat()
    if fixed and not problems:
        push_admins("✅ TMPRO: sorun giderildi", "Tüm kontroller yeniden normal.")
    # gece bekletilen uyarılar sabah gönderilsin diye "yeni" sayılmaya devam eder
    st["open"] = {k: old.get(k, NOW.isoformat()) for k, v in problems.items()
                  if k in old or v[0] == "kritik" or not night}
    st["checked"] = NOW.isoformat()
    db("private_settings?on_conflict=key", {"key": "health_state", "value": json.dumps(st)}, "POST",
       {"Prefer": "resolution=merge-duplicates,return=minimal"})


if __name__ == "__main__":
    main()
