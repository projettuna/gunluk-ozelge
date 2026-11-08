"""Yeni kayıtlara "Müfettiş Notu" yazar (Claude API). Anahtar yoksa hiçbir şey yapmaz.

Not, vergi müfettişi gözüyle kısa bir değerlendirmedir; uygulamada "Yapay zekâ yorumu"
etiketiyle, tam metnin üstünde gösterilir. Depo herkese açık: içerik yazdırılmaz.
"""
import json
from urllib.parse import quote
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


def fill(db, limit=6, budget=150):
    if not KEY:
        print("Müfettiş notu: ANTHROPIC_API_KEY tanımlı değil, atlandı")
        return
    # Maliyeti sınırlamak için yalnızca son 30 günde eklenen kayıtlar
    since = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = db("GET", f"items?select=id,tur,title,meta,metin&yorum=is.null&metin=neq.&eklendi=gte.{since}&order=id.desc&limit={limit}") or []
    if len(rows) < limit:  # Yargıtay ceza kararları (toplu yüklenenler dahil) da sırayla yorumlanır
        rows += db("GET", "items?select=id,tur,title,meta,metin&yorum=is.null&metin=neq.&tur=eq."
                   + quote("Yargıtay (Ceza)") + f"&order=id.desc&limit={limit - len(rows)}") or []
    start, ok = time.time(), 0
    for r in rows:
        if time.time() - start > budget:
            break
        try:
            note = ask(r)
        except Exception as e:  # noqa: BLE001
            print(f"Müfettiş notu yazılamadı (#{r['id']}): {type(e).__name__} {getattr(e, 'code', '')}")
            if getattr(e, "code", 0) in (401, 403):
                return
            continue
        db("PATCH", f"items?id=eq.{r['id']}", {"yorum": note}, prefer="return=minimal")
        ok += 1
    print(f"Müfettiş notu: {ok} kayda yazıldı")
