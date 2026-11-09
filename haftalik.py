"""Haftalık özet: her Cuma 17:00'de, o hafta eklenen mevzuat ve kararların sayısı ve öne çıkan başlık tek bildirimde.

Depo herkese açık: loglara yalnızca sayılar yazılır.
"""
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

TR = timezone(timedelta(hours=3))
DAY, HOUR = 4, 17  # Cuma 17:00
# Öne çıkan başlık seçilirken önem sırası
PRIORITY = ["Kanun", "CB Kararı", "Tebliğ", "Sirküler", "İç Genelge", "Anayasa Mahkemesi", "Danıştay (VUK 359)",
            "Yargıtay (Ceza)", "Resmî Gazete", "Özelge"]
PLURAL = {"Özelge": "özelge", "Tebliğ": "tebliğ", "Sirküler": "sirküler", "Kanun": "kanun", "CB Kararı": "CB kararı",
          "İç Genelge": "iç genelge", "Resmî Gazete": "Resmî Gazete kaydı", "Anayasa Mahkemesi": "AYM kararı",
          "Danıştay (VUK 359)": "Danıştay kararı", "Yargıtay (Ceza)": "Yargıtay kararı"}
MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def summary(db, now):
    since = (now - timedelta(days=7)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = db("GET", f"items?select=id,tur,title&created_at=gte.{quote(since)}&eklendi=not.is.null&order=id.desc&limit=1000") or []
    counts = {}
    for r in rows:
        counts[r["tur"]] = counts.get(r["tur"], 0) + 1
    order = sorted(counts, key=lambda t: (PRIORITY.index(t) if t in PRIORITY else 99))
    top = next((r for t in order for r in rows if r["tur"] == t), None)
    start = now - timedelta(days=6)
    span = f"{start.day} {MONTHS[start.month - 1]} – {now.day} {MONTHS[now.month - 1]}" if start.month != now.month else f"{start.day}–{now.day} {MONTHS[now.month - 1]}"
    if not rows:
        return None
    parts = ", ".join(f"{counts[t]} {PLURAL.get(t, t)}" for t in order[:5])
    body = f"Bu hafta {len(rows)} yeni kayıt: {parts}." + (f" Öne çıkan: {top['title']}" if top else "")
    return {"title": f"Haftanın Özeti · {span}", "body": body[:220], "count": len(rows)}


def run(db, state, test=False, muted=lambda u, k: False):
    now = datetime.now(TR)
    week = now.strftime("%G-%V")
    if not test and (now.weekday() != DAY or now.hour != HOUR or state.get("weekly_sent") == week):
        return
    s = summary(db, now)
    if not s:
        print("Haftalık özet: bu hafta kayıt yok, gönderilmedi")
        if not test:
            state["weekly_sent"] = week
        return
    try:
        users = {u["id"]: u for u in db("GET", "profiles?select=id,role,status,expires_at,weekly_on,mute")}
    except Exception:  # noqa: BLE001  haftalik.sql henüz çalıştırılmadı
        if not test:
            print("Haftalık özet: kurulum bekleniyor (haftalik.sql)")
            return
        users = {u["id"]: u for u in db("GET", "profiles?select=id,role,status,expires_at")}
    from pywebpush import webpush, WebPushException
    vapid = db("GET", "private_settings?key=eq.vapid_private&select=value")[0]["value"]
    payload = json.dumps({"title": s["title"], "body": s["body"], "url": "https://tmpro.tmproapp.workers.dev/?hafta=1", "tag": "tmpro-hafta"})
    utc_now = datetime.now(timezone.utc)
    sent, people = 0, set()
    for sub in db("GET", "push_subs?select=id,user_id,endpoint,p256dh,auth") or []:
        u = users.get(sub["user_id"])
        if not u:
            continue
        if test:
            if u["role"] != "admin":
                continue
        else:
            exp = u.get("expires_at")
            if not (u["role"] == "admin" or (u["status"] == "active" and (not exp or datetime.fromisoformat(exp) > utc_now))):
                continue
            if u.get("weekly_on") is False or muted(u, "haftalik"):
                continue
        try:
            webpush({"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}}, payload,
                    vapid_private_key=vapid, vapid_claims={"sub": "mailto:bildirim@tmpro.app"}, ttl=86400)
            sent += 1
            people.add(sub["user_id"])
        except WebPushException as e:
            if getattr(e.response, "status_code", None) in (404, 410):
                db("DELETE", f"push_subs?id=eq.{sub['id']}")
    if not test:
        state["weekly_sent"] = week
    print(f"Haftalık özet{' (deneme, yalnızca yönetici)' if test else ''}: {s['count']} kayıt, {len(people)} üye, {sent} cihaz")
