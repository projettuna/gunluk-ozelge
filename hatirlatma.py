"""Takvim hatırlatıcısı: üyelerin takvime eklediği günler için 3 gün ve 1 gün önce, sabah 09:00'da anlık bildirim.

Depo herkese açık: loglara yalnızca sayılar yazılır (etkinlik adları yazılmaz).
"""
import json
from datetime import date, datetime, timedelta, timezone

TR = timezone(timedelta(hours=3))
HOUR = 9
AHEAD = (3, 1)
MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


def occurs(ev, d):
    day = date.fromisoformat(ev["day"])
    if ev.get("yearly"):
        return (day.month, day.day) == (d.month, d.day)
    return day == d


def run(db, state, muted=lambda u, k: False, force=False):
    now = datetime.now(TR)
    today = now.date().isoformat()
    if not force and (now.hour != HOUR or state.get("event_remind_day") == today):
        return
    try:
        events = db("GET", "user_events?select=user_id,title,day,yearly,remind")
    except Exception:  # noqa: BLE001  takvim_hatirlat.sql henüz çalıştırılmadı
        events = db("GET", "user_events?select=user_id,title,day,yearly")
    try:
        users = {u["id"]: u for u in db("GET", "profiles?select=id,role,status,expires_at,mute")}
    except Exception:  # noqa: BLE001
        users = {u["id"]: u for u in db("GET", "profiles?select=id,role,status,expires_at")}
    utc_now = datetime.now(timezone.utc)
    msgs = {}
    for ev in events or []:
        if ev.get("remind") is False:
            continue
        u = users.get(ev["user_id"])
        if not u:
            continue
        exp = u.get("expires_at")
        if not (u["role"] == "admin" or (u["status"] == "active" and (not exp or datetime.fromisoformat(exp) > utc_now))):
            continue
        if muted(u, "takvim"):
            continue
        for n in AHEAD:
            d = now.date() + timedelta(days=n)
            if occurs(ev, d):
                when = "Yarın" if n == 1 else f"{n} gün sonra"
                msgs.setdefault(ev["user_id"], []).append((n, f"{when}: {ev['title']} ({d.day} {MONTHS[d.month - 1]} {DAYS[d.weekday()]})"))
    state["event_remind_day"] = today
    if not msgs:
        print("Takvim hatırlatıcısı: bugün hatırlatılacak gün yok")
        return
    from pywebpush import webpush, WebPushException
    vapid = db("GET", "private_settings?key=eq.vapid_private&select=value")[0]["value"]
    subs = {}
    for s in db("GET", "push_subs?select=id,user_id,endpoint,p256dh,auth") or []:
        subs.setdefault(s["user_id"], []).append(s)
    sent = 0
    for uid, lines in msgs.items():
        lines.sort()
        title = "📅 Takvim hatırlatması" if len(lines) > 1 else ("📅 Yarın" if lines[0][0] == 1 else f"📅 {lines[0][0]} gün kaldı")
        body = " · ".join(t for _, t in lines)
        payload = json.dumps({"title": title, "body": body[:220], "url": "https://tmpro.tmproapp.workers.dev/?takvim=1", "tag": "tmpro-takvim"})
        for s in subs.get(uid, []):
            try:
                webpush({"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}}, payload,
                        vapid_private_key=vapid, vapid_claims={"sub": "mailto:bildirim@tmpro.app"}, ttl=43200)
                sent += 1
            except WebPushException as e:
                if getattr(e.response, "status_code", None) in (404, 410):
                    db("DELETE", f"push_subs?id=eq.{s['id']}")
    print(f"Takvim hatırlatıcısı: {len(msgs)} üye, {sent} cihaz")
