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


def piyasa():
    code, body, _ = http(APP + "api/kur")
    try:
        n = len(json.loads(body).get("kurlar") or [])
    except Exception:  # noqa: BLE001
        n = 0
    if code != 200 or n < 5:
        bad("kur", "uyari", f"Döviz kurları alınamıyor (HTTP {code}); TCMB kaynağı değişmiş olabilir")
    code, body, _ = http(APP + "api/altin")
    try:
        ok = bool(json.loads(body).get("onsUsd"))
    except Exception:  # noqa: BLE001
        ok = False
    if code != 200 or not ok:
        bad("altin", "uyari", f"Altın fiyatı alınamıyor (HTTP {code}); fiyat kaynağı değişmiş olabilir")
    print(f"  kur: {n} döviz, altın: {'var' if ok else 'yok'}")


def zamanlayici():
    code, body, _ = http(APP + "api/zaman")
    try:
        j = json.loads(body)
    except Exception:  # noqa: BLE001
        j = {}
    if code == 200 and not j.get("anahtar"):
        bad("zaman_anahtar", "kritik", "Cloudflare'de GH_DISPATCH_TOKEN yok; taramalar zamanında başlamaz. Cloudflare → tmpro → Ayarlar → Değişkenler'e 'Secret' olarak yeniden ekleyin")
    elif code == 200 and j.get("github") not in (200,):
        bad("zaman_anahtar", "kritik", f"GH_DISPATCH_TOKEN GitHub'da geçersiz (HTTP {j.get('github')}); süresi dolmuş olabilir, yenisini oluşturun")
    print(f"  zamanlayıcı anahtarı: {'var' if j.get('anahtar') else 'YOK'}, GitHub: {j.get('github')}")


def database():
    rows, _ = db("items?select=created_at,tur&order=created_at.desc&limit=1")
    last = ts(rows[0]["created_at"]) if rows else None
    if not last or NOW - last > timedelta(days=4):
        bad("tazelik", "uyari", "4 gündür hiç yeni kayıt eklenmedi; kaynak siteler değişmiş olabilir")


def setup():
    for col, what in (("friend_code", "arkadaş sistemi"), ("avatar", "profil fotoğrafı"), ("email", "üye e-postası"), ("watch_words", "takip listesi")):
        try:
            db(f"profiles?select={col}&limit=1")
        except RuntimeError:
            bad("kurulum_" + col, "uyari", f"Veritabanında {what} kurulumu eksik görünüyor")
    try:
        db("news?select=ozet&limit=1")
    except RuntimeError:
        bad("kurulum_haber_ozet", "uyari", "Veritabanında haber özeti kurulumu eksik (haber_ozet.sql çalıştırılmalı)")
    try:
        db("news?select=image&limit=1")
    except RuntimeError:
        bad("kurulum_haber_gorsel", "uyari", "Veritabanında haber görseli kurulumu eksik (haber_gorsel.sql çalıştırılmalı)")
    for tbl, what in (("feedback", "Sorun Bildir"), ("usage_daily", "kullanım istatistiği"), ("password_resets", "şifre sıfırlama"), ("watch_hits", "takip listesi"), ("item_notes", "kişisel notlar")):
        try:
            db(f"{tbl}?select=*&limit=1")
        except RuntimeError:
            bad("kurulum_" + tbl, "uyari", f"Veritabanında {what} kurulumu eksik ({ {'watch_hits': 'takip', 'item_notes': 'yeni_ozellikler'}.get(tbl, 'destek') }.sql çalıştırılmalı)")
    for path, key, what in (("profiles?select=weekly_on,referred_by", "yeni_profil", "haftalık özet/davet"), ("user_events?select=remind", "yeni_takvim", "takvim hatırlatıcısı")):
        try:
            db(path + "&limit=1")
        except RuntimeError:
            bad("kurulum_" + key, "uyari", f"Veritabanında {what} kurulumu eksik (yeni_ozellikler.sql çalıştırılmalı)")


def auto(r):
    """Zamanlanmış tur: GitHub zamanlayıcısı ya da Cloudflare tetikleyicisinin başlattığı otomatik tur."""
    return r["event"] == "schedule" or r.get("display_title") == "Özelge bildirimi (otomatik)"


def main_job():
    if not GH or not REPO:
        return
    code, body, _ = http(f"https://api.github.com/repos/{REPO}/actions/workflows/gunluk.yml/runs?per_page=20&status=completed",
                         headers={"Authorization": f"Bearer {GH}", "Accept": "application/vnd.github+json"})
    if code != 200:
        raise RuntimeError(f"github {code}")
    runs = [r for r in json.loads(body)["workflow_runs"] if auto(r)]
    tr = NOW.astimezone(TR)
    if tr.weekday() < 5 and 8 <= tr.hour < 19 and tr.hour * 60 + tr.minute >= 8 * 60 + 30:
        last = max((ts(r["created_at"]) for r in runs), default=None)
        if not last or NOW - last > timedelta(minutes=30):
            bad("zamanlayici", "uyari", "Mesai saatinde 30 dakikadır tarama başlamadı; zamanlayıcı gecikiyor")
    if len(runs) >= 3 and all(r["conclusion"] == "failure" for r in runs[:3]):
        bad("tarama", "kritik", "Otomatik tarama son 3 denemede hata verdi; yeni mevzuat gelmiyor")
    ok = [ts(r["created_at"]) for r in runs if r["conclusion"] == "success"]
    if not ok or NOW - max(ok) > timedelta(hours=3):
        bad("tarama_gecikme", "kritik", "Otomatik tarama 3 saattir başarıyla çalışmadı")


def sources():
    """Son 4 zamanlanmış taramanın hepsinde aynı kaynak alınamadıysa uyarır (Özelge/Resmî Gazete acil)."""
    if not GH or not REPO:
        return
    h = {"Authorization": f"Bearer {GH}", "Accept": "application/vnd.github+json"}
    code, body, _ = http(f"https://api.github.com/repos/{REPO}/actions/workflows/gunluk.yml/runs?per_page=10&status=completed", headers=h)
    if code != 200:
        raise RuntimeError(f"github {code}")
    runs = [r for r in json.loads(body)["workflow_runs"] if auto(r) and r["conclusion"] == "success"][:4]
    if len(runs) < 4:
        return
    fails = None
    for r in runs:
        code, body, _ = http(r["jobs_url"], headers=h)
        if code != 200:
            return
        jid = json.loads(body)["jobs"][0]["id"]
        code, log, _ = http(f"https://api.github.com/repos/{REPO}/actions/jobs/{jid}/logs", headers=h)
        if code != 200:
            return
        names = set()
        for line in log.splitlines():
            line = line.split(" ", 1)[-1]
            if " alınamadı" in line and not line.startswith(("Metin", "Müfettiş")):
                names.add(line.split(" alınamadı")[0].strip())
        fails = names if fails is None else fails & names
    for n in sorted(fails or []):
        crit = any(k in n for k in ("Özelge", "Resmî Gazete", "Tebliğ"))
        bad("kaynak_" + n[:30], "kritik" if crit else "uyari", f"{n} son 4 taramada alınamadı; kaynak site değişmiş veya kapalı olabilir")


ANON = "sb_publishable_tlfwqtscxxv2vdSHe3PstQ_XO1db8p9"  # docs/config.js'teki herkese açık anahtar
PROBE = "nobetci"


def probe_login():
    """Test hesabı ('nobetci', ilk çalışmada kendiliğinden açılır) ile gerçek kullanıcı gibi giriş yapar."""
    import secrets
    rows, _ = db("private_settings?key=eq.probe_pw&select=value")
    pw = rows[0]["value"] if rows else None
    if not pw:
        pw = secrets.token_urlsafe(24)
        code, body, _ = http(f"{SB}/auth/v1/admin/users", {"email": f"{PROBE}@tmpro.app", "password": pw, "email_confirm": True,
                             "user_metadata": {"username": PROBE, "full_name": "Sistem Kontrol"}}, sbh(), "POST")
        if code >= 300:
            raise RuntimeError(f"test hesabı açılamadı {code}")
        uid = json.loads(body)["id"]
        db(f"profiles?id=eq.{uid}", {"status": "active", "expires_at": None, "notify_types": []}, "PATCH", {"Prefer": "return=minimal"})
        db("private_settings?on_conflict=key", {"key": "probe_pw", "value": pw}, "POST", {"Prefer": "resolution=merge-duplicates,return=minimal"})
    code, body, _ = http(f"{SB}/auth/v1/token?grant_type=password", {"email": f"{PROBE}@tmpro.app", "password": pw},
                         {"apikey": ANON, "Content-Type": "application/json"}, "POST")
    if code != 200:
        bad("giris", "kritik", f"Üyeler giriş yapamıyor (test hesabı HTTP {code})")
        return None
    return json.loads(body)


def e2e():
    tok = probe_login()
    if not tok:
        return
    uid, h = tok["user"]["id"], {"apikey": ANON, "Authorization": f"Bearer {tok['access_token']}", "Content-Type": "application/json"}

    def get(path, label, level="kritik"):
        code, body, _ = http(f"{SB}/rest/v1/{path}", headers=h)
        if code != 200:
            bad("e2e_" + label, level, f"{label} çalışmıyor (HTTP {code})")
            return None
        return json.loads(body or "null")

    def rpc(fn, args, label, level="kritik"):
        code, body, _ = http(f"{SB}/rest/v1/rpc/{fn}", args, h, "POST")
        if code >= 300:
            bad("e2e_" + label, level, f"{label} çalışmıyor (HTTP {code})")
        return code

    prof = get(f"profiles?select=id,status&id=eq.{uid}", "Profil yükleme")
    if prof is not None and not prof:
        bad("e2e_profil", "kritik", "Giriş sonrası profil okunamıyor; üyeler uygulamaya giremez")
    rpc("touch_ip", {}, "Giriş kontrolü (IP)")
    items = get("items?select=id&order=id.desc&limit=5", "Akış (mevzuat listesi)")
    if items is not None and not items:
        bad("e2e_akis", "kritik", "Akış boş geliyor; üyeler kayıtları göremiyor")
    get("messages?select=id&order=id.desc&limit=5", "Sohbet mesajları")
    rpc("list_groups", {}, "Sohbet grupları")
    rpc("list_friends", {}, "Arkadaş listesi")
    get("room_reads?select=room&limit=1", "Sohbet okundu bilgisi", "uyari")
    get("user_events?select=id&limit=1", "Takvim etkinlikleri")
    get("settings?select=key&limit=1", "Ayarlar", "uyari")
    get("news?select=id&limit=1", "Haberler", "uyari")
    for f, label in (("tatiller.json", "Takvim tatil listesi"), ("oranlar.json", "Araçlar oranları"), ("sw.js", "Bildirim servisi (sw.js)")):
        code, body, _ = http(APP + f)
        if code != 200:
            bad("dosya_" + f, "kritik" if f == "sw.js" else "uyari", f"{label} açılmıyor (HTTP {code})")
    code, body, _ = http(APP + "tatiller.json")
    if code == 200 and str(datetime.now(TR).year + 1) not in body and datetime.now(TR).month >= 11:
        bad("tatil_yili", "uyari", "Takvimde gelecek yılın resmî tatilleri yok; tatiller.json güncellenmeli")


def backup():
    if not GH or not REPO:
        return
    code, body, _ = http(f"https://api.github.com/repos/{REPO}/actions/workflows/yedek.yml/runs?per_page=5&status=success",
                         headers={"Authorization": f"Bearer {GH}", "Accept": "application/vnd.github+json"})
    if code != 200:
        return
    runs = json.loads(body).get("workflow_runs", [])
    if not runs or NOW - ts(runs[0]["created_at"]) > timedelta(hours=30):
        bad("yedek", "uyari", "Gece yedeği 30 saattir alınamadı")


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


def news_fresh():
    rows, _ = db("news?select=published&order=published.desc.nullslast&limit=1")
    last = ts(rows[0]["published"]) if rows and rows[0].get("published") else None
    if not last or NOW - last > timedelta(hours=24):
        bad("haberler", "uyari", "24 saattir yeni haber gelmedi; haber kaynağı değişmiş olabilir")


def phone():
    # arşive giden eski kararlar da telefonun çalıştığını gösterir, bu yüzden created_at
    rows, _ = db("items?select=created_at&tur=eq.Yarg%C4%B1tay%20(Ceza)&order=created_at.desc&limit=1")
    last = ts(rows[0]["created_at"]) if rows else None
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
                     ("tarama", main_job), ("kaynaklar", sources), ("üye girişi ve ekranlar", e2e), ("e-posta", mails), ("yedek", backup), ("yapay zekâ", ai), ("haberler", news_fresh), ("döviz ve altın", piyasa), ("zamanlayıcı", zamanlayici), ("telefon", phone)):
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
    print(f"Sorun: {len(problems)} (yeni {len(new)}, düzelen {len(fixed)})" + (f" · {', '.join(sorted(problems))}" if problems else ""))

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
    # Üye e-postaları (şifre sıfırlama, onay) 15 dakikayı geçmeden gitsin
    if os.environ.get("SMTP_USER"):
        try:
            import ozelge
            ozelge.send_member_mails()
        except Exception as e:  # noqa: BLE001
            print(f"Üye e-postaları gönderilemedi: {type(e).__name__}")
