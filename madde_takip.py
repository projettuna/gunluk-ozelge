"""Kanun maddesi takibi.

1) Her turda: yeni eklenen karar/özelge metinlerinde üyelerin takip ettiği maddelere (örn. "KDVK 29") atıf aranır;
   eşleşen kayıt üyenin Takip Listesi'ne düşer (watch_hits, word = madde kodu) ve bildirim gider.
2) Günde bir kez (08:00 TR sonrası ilk tur): takip edilen maddelerin güncel metni mevzuat.gov.tr'den alınır; metin değiştiyse
   madde_durum tablosu güncellenir (önceki metin saklanır) ve takip edenlere bildirim gider.

Depo herkese açık: loglara yalnızca sayılar yazılır.
"""
import hashlib
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

TR = timezone(timedelta(hours=3))
TEXT_HOUR = 8
# kod: (kanun no, tertip, adı, metinde aranacak adlar)
KANUN = {
    "VUK": (213, 4, "Vergi Usul Kanunu", ["vergi usul kanunu", "213 sayılı", "vuk"]),
    "GVK": (193, 4, "Gelir Vergisi Kanunu", ["gelir vergisi kanunu", "193 sayılı", "gvk"]),
    "KVK": (5520, 5, "Kurumlar Vergisi Kanunu", ["kurumlar vergisi kanunu", "5520 sayılı", "kvk"]),
    "KDVK": (3065, 5, "Katma Değer Vergisi Kanunu", ["katma değer vergisi kanunu", "3065 sayılı", "kdvk", "kdv kanunu"]),
    "ÖTVK": (4760, 5, "Özel Tüketim Vergisi Kanunu", ["özel tüketim vergisi kanunu", "4760 sayılı", "ötvk"]),
    "DVK": (488, 4, "Damga Vergisi Kanunu", ["damga vergisi kanunu", "488 sayılı", "dvk"]),
    "HK": (492, 4, "Harçlar Kanunu", ["harçlar kanunu", "492 sayılı"]),
    "AATUHK": (6183, 4, "Amme Alacaklarının Tahsil Usulü Hk. Kanun", ["amme alacaklarının tahsil usulü hakkında kanun", "6183 sayılı", "aatuhk"]),
    "İYUK": (2577, 5, "İdari Yargılama Usulü Kanunu", ["idari yargılama usulü kanunu", "2577 sayılı", "iyuk", "i̇yuk"]),
}
KOD_RE = re.compile(r"^(VUK|GVK|KVK|KDVK|ÖTVK|DVK|HK|AATUHK|İYUK) ((?:Ek |Mükerrer )?\d{1,3}(?:/[A-Z])?)$")


def norm(t):
    return (t or "").replace("İ", "i").replace("I", "ı").lower()


def madde_re(kod):
    """Metinde bu maddeye atıf: kanun adı/numarası, ardından 80 karakter içinde madde numarası."""
    m = KOD_RE.match(kod)
    if not m:
        return None
    law, no = m.group(1), m.group(2).split("/")[0]
    names = "|".join(re.escape(n) if " " in n or n[0].isdigit() else r"\b" + re.escape(n) + r"\b" for n in KANUN[law][3])
    num = re.escape(norm(no)).replace(r"\ ", r"\s*")
    suffix = r"(?:\s*['’]?\s*(?:[ıiuü]?nc[ıiuü]|nc[ıiuü])\b|\s*/\s*[a-zçğıöşü0-9(]|\.\s*madde|\s+madde|\s*(?=[,;)]|\s+ve\b|\s*$))"
    return re.compile(rf"(?:{names})[^\n]{{0,80}}?(?:(?:md\.?|madde)\s*{num}\b|(?<![\d/.,]){num}(?!\d){suffix})")


def _active(u, now):
    exp = u.get("expires_at")
    return u.get("role") == "admin" or (u.get("status") == "active" and (not exp or datetime.fromisoformat(exp) > now))


def run(db, state, muted=lambda u, k: False):
    now_utc = datetime.now(timezone.utc)
    try:
        users = db("GET", "profiles?select=id,role,status,expires_at,mute,madde_takip&madde_takip=neq.{}") or []
    except Exception:  # noqa: BLE001  madde_takip.sql henüz çalıştırılmadı
        return
    users = [u for u in users if _active(u, now_utc)]
    follow = {}
    for u in users:
        for k in u.get("madde_takip") or []:
            if KOD_RE.match(k):
                follow.setdefault(k, []).append(u)
    mentions(db, state, follow, muted)
    nt = datetime.now(TR)
    if nt.hour >= TEXT_HOUR and state.get("madde_text_day") != nt.date().isoformat():
        texts(db, state, follow, muted)
        state["madde_text_day"] = nt.date().isoformat()


def notify(db, uid, title, body, link):
    try:
        db("POST", "rpc/notify_user_url", {"uid": uid, "title": title, "body": body, "link": link})
    except Exception:  # noqa: BLE001
        pass


def mentions(db, state, follow, muted):
    six = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    pend = db("GET", f"items?select=id&metin=is.null&created_at=gt.{quote(six)}&order=id.asc&limit=1") or []
    top = db("GET", "items?select=id&order=id.desc&limit=1") or []
    if not top:
        return
    cutoff = pend[0]["id"] - 1 if pend else top[0]["id"]
    last = state.get("madde_last_id")
    if last is None or cutoff <= last:
        state["madde_last_id"] = max(last or 0, cutoff) if last is not None else cutoff
        return
    rows = db("GET", f"items?select=id,tur,title,ozet,metin&id=gt.{last}&id=lte.{cutoff}&order=id.asc&limit=300") or []
    state["madde_last_id"] = cutoff
    if not follow or not rows:
        return
    res = {k: madde_re(k) for k in follow}
    hits = {}
    for it in rows:
        t = norm(" ".join([it.get("title") or "", it.get("ozet") or "", it.get("metin") or ""]))
        for k, r in res.items():
            if r and r.search(t):
                hits.setdefault(k, []).append(it)
    n = 0
    for k, its in hits.items():
        for u in follow[k]:
            body = [{"user_id": u["id"], "item_id": it["id"], "word": k} for it in its]
            try:
                db("POST", "watch_hits?on_conflict=user_id,item_id", body, prefer="resolution=ignore-duplicates")
            except Exception:  # noqa: BLE001
                continue
            n += len(its)
            if not muted(u, "takip"):
                notify(db, u["id"], f"📜 {k}: yeni kayıt" if len(its) == 1 else f"📜 {k}: {len(its)} yeni kayıt", its[-1]["title"], "/?takip=1")
    print(f"Madde takibi: {n} yeni atıf eşleşmesi")


def texts(db, state, follow, muted):
    import sys
    sys.path.insert(0, "tools")
    from madde_cek import split, text_of
    try:
        rows = {r["kod"]: r for r in db("GET", "madde_durum?select=kod,hash") or []}
    except Exception:  # noqa: BLE001
        return
    laws = sorted({k.split(" ")[0] for k in follow})
    changed = checked = 0
    for law in laws:
        no, tertip = KANUN[law][0], KANUN[law][1]
        allm = {}
        for tt in dict.fromkeys([tertip, 4, 5, 3]):
            try:
                allm = split(text_of(no, tt))
            except Exception:  # noqa: BLE001
                allm = {}
            if len(allm) >= 5:
                break
        if len(allm) < 5:
            print(f"Madde takibi: {law} metni alınamadı")
            continue
        for kod in [k for k in follow if k.startswith(law + " ")]:
            key = KOD_RE.match(kod).group(2).split("/")[0]
            m = allm.get(key)
            if not m:
                continue
            checked += 1
            metin = m["metin"]
            h = hashlib.sha256(re.sub(r"\s+", " ", metin).strip().encode()).hexdigest()
            old = rows.get(kod)
            now = datetime.now(timezone.utc).isoformat()
            if not old:
                db("POST", "madde_durum", {"kod": kod, "baslik": m["baslik"], "metin": metin, "hash": h, "kontrol": now}, prefer="resolution=merge-duplicates")
                continue
            if old["hash"] == h:
                db("PATCH", f"madde_durum?kod=eq.{quote(kod)}", {"kontrol": now})
                continue
            prev = db("GET", f"madde_durum?select=metin&kod=eq.{quote(kod)}") or [{}]
            db("PATCH", f"madde_durum?kod=eq.{quote(kod)}", {"baslik": m["baslik"], "metin": metin, "hash": h, "onceki": prev[0].get("metin"), "degisti": now, "kontrol": now})
            changed += 1
            for u in follow[kod]:
                if not muted(u, "takip"):
                    notify(db, u["id"], f"⚖️ {kod} değişti", f"{KANUN[law][2]} {key}. madde metninde değişiklik var. Yeni ve önceki metni karşılaştırın.", "/?takip=1")
    print(f"Madde metni kontrolü: {checked} madde, {changed} değişiklik")
