"""Yeni mevzuattan yeterlik sınavı soru TASLAĞI üretir (Claude API).

Taslaklar sinav_sorular tablosuna durum='taslak' olarak yazılır; yönetici Yönetim → Sınav'dan onaylamadan
üyelere görünmez. Günde en fazla GUNLUK kayıt işlenir (maliyet: kayıt başına ~1-3 TL).
Depo herkese açık: soru içerikleri loglara yazılmaz.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen

API = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("SORU_MODEL") or "claude-sonnet-5-5"
KEY = os.environ.get("ANTHROPIC_API_KEY") or ""
GUNLUK = 3
TURLER = ("Kanun", "Tebliğ", "Sirküler", "CB Kararı")
TR = timezone(timedelta(hours=3))

SYSTEM = """Vergi Denetim Kurulu vergi müfettiş yardımcılığı yeterlik sınavına hazırlık için soru yazıyorsun.
Sana yeni yayımlanmış bir mevzuat metni verilecek. Bu metindeki DEĞİŞİKLİĞİ ölçen çoktan seçmeli sorular yaz.

Kurallar:
- Yalnızca metinde açıkça yazan bilgiye dayan; oran, süre, madde numarası uydurma.
- Metin vergi müfettişliği açısından önemsizse (atama, tebrik, kurum içi duyuru, yalnız tutar güncellemesi gibi) boş liste döndür: []
- En fazla 2 soru. Her soru tek doğru cevaplı, 4 şıklı; yanlış şıklar makul ama açıkça yanlış olsun.
- Açıklamada doğru cevabın dayanağını metindeki madde/bent ile belirt (ör. "7555 s.K. md. 12 ile VUK 359'a eklenen fıkra").
- Konu alanı şunlardan biri: Vergi Usul, Ceza ve Suç, KDV, Gelir ve Kurumlar, Süreler ve Yargı, Diğer Vergiler.
- Yalnızca JSON döndür, başka hiçbir şey yazma. Biçim:
[{"k":"KDV","q":"Soru metni?","o":["şık A","şık B","şık C","şık D"],"a":0,"e":"Açıklama ve dayanak."}]"""


def ask(item):
    text = (item.get("metin") or "")[:20000]
    user = f"Tür: {item['tur']}\nBaşlık: {item['title']}\nKünye: {item.get('meta') or '-'}\n\nMetin:\n{text}"
    body = {"model": MODEL, "max_tokens": 8000, "system": SYSTEM, "messages": [{"role": "user", "content": user}]}
    req = Request(API, data=json.dumps(body).encode(), method="POST", headers={
        "x-api-key": KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urlopen(req, timeout=180) as r:
        d = json.loads(r.read().decode())
    out = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text").strip()
    m = re.search(r"\[.*\]", out, re.S)
    return json.loads(m.group(0)) if m else []


def valid(x):
    return (isinstance(x, dict) and isinstance(x.get("q"), str) and len(x["q"]) > 10 and isinstance(x.get("o"), list)
            and len(x["o"]) == 4 and all(isinstance(o, str) and o.strip() for o in x["o"])
            and isinstance(x.get("a"), int) and 0 <= x["a"] <= 3 and isinstance(x.get("e"), str))


def run(db, state):
    if not KEY:
        return
    today = datetime.now(TR).date().isoformat()
    if state.get("soru_taslak_gun") == today and state.get("soru_taslak_n", 0) >= GUNLUK:
        return
    if state.get("soru_taslak_gun") != today:
        state["soru_taslak_gun"], state["soru_taslak_n"] = today, 0
    since = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    last = state.get("soru_taslak_last_id") or 0
    turs = ",".join(quote(f'"{t}"') for t in TURLER)
    rows = db("GET", f"items?select=id,tur,title,meta,metin&tur=in.({turs})&id=gt.{last}&eklendi=gt.{quote(since)}"
                     f"&metin=not.is.null&order=id.asc&limit=10") or []
    rows = [r for r in rows if len(r.get("metin") or "") > 400]
    made = done = 0
    for r in rows:
        if state["soru_taslak_n"] >= GUNLUK:
            break
        try:
            qs = [x for x in ask(r) if valid(x)][:2]
        except Exception as e:  # noqa: BLE001
            print(f"Soru taslağı atlandı: {type(e).__name__} {getattr(e, 'code', '')}")
            break
        state["soru_taslak_n"] += 1
        state["soru_taslak_last_id"] = r["id"]
        done += 1
        for x in qs:
            try:
                db("POST", "sinav_sorular", {"k": str(x.get("k") or "Diğer Vergiler")[:40], "q": x["q"][:1000], "o": [o[:400] for o in x["o"]],
                                             "a": x["a"], "e": x["e"][:1500], "durum": "taslak", "kaynak": f"#{r['id']} {r['title'][:150]}"})
                made += 1
            except Exception:  # noqa: BLE001  sinav.sql henüz çalıştırılmadı
                return
    if rows and not done:
        return
    if done:
        print(f"Soru taslağı: {done} mevzuat kaydı, {made} taslak soru")
        if made:
            try:
                db("POST", "rpc/notify_admins", {"title": "Yeni soru taslakları", "body": f"{made} taslak soru onayınızı bekliyor (Yönetim → Sınav)."})
            except Exception:  # noqa: BLE001
                pass
    elif rows == [] and last == 0:
        top = db("GET", "items?select=id&order=id.desc&limit=1") or []
        if top:
            state["soru_taslak_last_id"] = top[0]["id"]  # ilk çalıştırmada geçmişi işleme
