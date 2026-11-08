"""Yeni kayıtlara "Müfettiş Notu" yazar (Claude API). Anahtar yoksa hiçbir şey yapmaz.

Not, vergi müfettişi gözüyle kısa bir değerlendirmedir; uygulamada "Yapay zekâ yorumu"
etiketiyle, tam metnin üstünde gösterilir. Depo herkese açık: içerik yazdırılmaz.
"""
import json
from concurrent.futures import ThreadPoolExecutor
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen

API = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("YORUM_MODEL") or "claude-sonnet-5-5"
KEY = os.environ.get("ANTHROPIC_API_KEY") or ""

SYSTEM = """Sen Türkiye'de Hazine ve Maliye Bakanlığı Vergi Denetim Kurulunda çalışan, vergi kaçakçılığı (VUK 359), sahte ve muhteviyatı itibarıyla yanıltıcı belge incelemelerinde deneyimli kıdemli bir vergi müfettişisin.
Sana yeni yayımlanmış bir mevzuat metni (özelge, tebliğ, sirküler, kanun, Cumhurbaşkanı kararı, iç genelge, Resmî Gazete metni veya yargı kararı) verilecek.
Görevin: bir meslektaşına, bu metnin vergi incelemesi ve denetim açısından ne anlama geldiğini kısaca anlatmak.

Kurallar:
- Türkçe yaz, düz metin kullan. Başlık, kalın yazı veya markdown kullanma.
- 3 ile 5 madde yaz, her madde "• " ile başlasın ve en fazla iki cümle olsun.
- İlk madde metnin özünü bir cümleyle söylesin (ne değişti / ne karara bağlandı).
- Sonraki maddeler: incelemede nelere dikkat edilmeli, hangi mükellef grupları ve işlemler riskli, sahte belge, matrah aşındırma veya istismar riski, tarihsel yürürlük ve geçiş dönemi tuzakları, olası tarhiyat ve ceza sonuçları.
- Yalnızca metinde dayanağı olan şeyleri söyle; madde numarası veya oran uydurma. Emin olmadığın yerde "metinden anlaşıldığı kadarıyla" de.
- Metin vergi denetimi açısından önemsizse tek maddede bunu söyle."""


def ask(item):
    text = (item.get("metin") or "")[:16000]
    user = f"Tür: {item['tur']}\nBaşlık: {item['title']}\nKünye: {item.get('meta') or '-'}\n\nMetin:\n{text}"
    body = {"model": MODEL, "max_tokens": 900, "system": SYSTEM, "messages": [{"role": "user", "content": user}]}
    req = Request(API, data=json.dumps(body).encode(), method="POST", headers={
        "x-api-key": KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urlopen(req, timeout=120) as r:
        d = json.loads(r.read().decode())
    return "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text").strip()


def fill(db, limit=None, budget=None):
    if not KEY:
        print("Müfettiş notu: ANTHROPIC_API_KEY tanımlı değil, atlandı")
        return
    limit = limit or int(os.environ.get("YORUM_LIMIT") or 6)
    budget = budget or max(150, limit * 6)
    sel = "items?select=id,tur,title,meta,metin&yorum=is.null&metin=neq."
    # Yalnızca son 30 günde eklenen kayıtlar (eskiler YORUM_ESKI ile elle)
    since = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = db("GET", f"{sel}&eklendi=gte.{since}&order=id.desc&limit={limit}") or []
    if len(rows) < limit and os.environ.get("YORUM_ESKI"):  # eski kayıtlar yalnızca elle istenirse (maliyet)
        have = {r["id"] for r in rows}
        rows += [r for r in (db("GET", f"{sel}&order=id.desc&limit={limit}") or []) if r["id"] not in have][:limit - len(rows)]
    start, ok, stop = time.time(), 0, False

    def one(r):
        nonlocal ok, stop
        if stop or time.time() - start > budget:
            return
        try:
            note = ask(r)
        except Exception as e:  # noqa: BLE001
            detail = ""
            try:
                detail = json.loads(e.read().decode()).get("error", {}).get("message", "")[:160]  # API hata metni (içerik değil)
            except Exception:  # noqa: BLE001
                pass
            print(f"Müfettiş notu yazılamadı (#{r['id']}): {type(e).__name__} {getattr(e, 'code', '')} {detail}")
            if getattr(e, "code", 0) in (401, 403) or "credit balance" in detail:
                stop = True
            return
        if note:
            db("PATCH", f"items?id=eq.{r['id']}", {"yorum": note}, prefer="return=minimal")
            ok += 1

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(one, rows))
    print(f"Müfettiş notu: {ok} kayda yazıldı")
