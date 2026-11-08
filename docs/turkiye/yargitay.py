#!/usr/bin/env python3
"""TMPRO · Yargıtay ceza kararları toplayıcı.

Yargıtay karar arama sitesi yurt dışından erişime kapalı olduğu için bu betik
Türkiye'de duran bir bilgisayarda/sunucuda çalışır. Vergi suçlarıyla ilgili ceza
dairesi kararlarını bulur, tam metnini alır ve TMPRO veritabanına gönderir.
Yeni kayıtların bildirimi mevcut otomatik tarama tarafından yapılır.

Ayarlar ortam değişkenlerinden okunur (bkz. KURULUM.md):
  TMPRO_SUPABASE_URL, TMPRO_ANON_KEY, TMPRO_INGEST_TOKEN
Kullanım:
  python3 yargitay.py --test   # yalnızca bağlantıyı dener, veritabanına yazmaz
  python3 yargitay.py --seed   # ilk çalıştırma: eski kararları bildirim göndermeden yükler
  python3 yargitay.py          # normal çalışma (cron)
"""
import html
import json
import os
import re
import sys
import time
from urllib.parse import quote
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = "https://karararama.yargitay.gov.tr"
QUERIES = [
    "vergi kaçakçılığı",
    "sahte fatura",
    "muhteviyatı itibariyle yanıltıcı belge",
    "213 sayılı Vergi Usul Kanunu 359",
    "naylon fatura",
    "defter ve belgeleri ibraz etmeme",
]
VERGI = re.compile(r"vergi usul|213 sayılı|vuk|359|sahte fatura|yanıltıcı belge|vergi kaçakçılığı|naylon fatura", re.I)
STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yargitay_gorulen.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
PAUSE = 6
TEST, SEED = "--test" in sys.argv, "--seed" in sys.argv


def http(url, body=None, timeout=60):
    for wait in (30, 90, 240, None):
        try:
            return _http(url, body, timeout)
        except HTTPError as e:
            if e.code != 429 or wait is None:
                raise
            print(f"Site yavaşla dedi (429), {wait} sn bekleniyor…", flush=True)
            time.sleep(wait)


def _http(url, body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = Request(url, data=data, method="POST" if data else "GET", headers={
        "User-Agent": UA, "Accept": "application/json, text/plain, */*", "Content-Type": "application/json; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest", "Origin": BASE, "Referer": BASE + "/"})
    with urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def html_to_text(s):
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()


def search(q, page=1, size=10):
    # siralama "3" + desc: karar tarihine göre yeniden eskiye (telefonda --diag ile doğrulandı)
    body = {"data": {"aranan": q, "arananKelime": q, "siralama": "3", "siralamaDirection": "desc",
                     "pageSize": size, "pageNumber": page}}
    data = json.loads(http(BASE + "/aramalist", body, timeout=90))
    rows = ((data.get("data") or {}).get("data")) or []
    return [{"id": str(r.get("id")), "daire": r.get("daire") or r.get("daireKurul") or "Yargıtay",
             "esas": r.get("esasNo") or "", "karar": r.get("kararNo") or "", "tarih": r.get("kararTarihi") or ""} for r in rows]


def document(kid):
    raw = http(f"{BASE}/getDokuman?id={quote(kid)}", timeout=90)
    try:
        raw = json.loads(raw).get("data") or raw
    except ValueError:
        pass
    return html_to_text(raw)


def ozet(text):
    m = VERGI.search(text)
    if not m:
        return text[:600]
    a = max(0, m.start() - 250)
    return ("… " if a else "") + text[a:a + 900].strip() + "…"


def send(rows):
    url = os.environ["TMPRO_SUPABASE_URL"].rstrip("/") + "/rest/v1/rpc/ingest_items"
    key = os.environ["TMPRO_ANON_KEY"]
    body = json.dumps({"token": os.environ["TMPRO_INGEST_TOKEN"], "rows": rows, "seed": SEED}).encode()
    req = Request(url, data=body, method="POST", headers={"apikey": key, "Content-Type": "application/json"})
    with urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"0")


def diag():
    from datetime import date, timedelta
    bas, bit = (date.today() - timedelta(days=365)).strftime("%d.%m.%Y"), date.today().strftime("%d.%m.%Y")
    bos = {"birimYrgKurulDaire": "ALL", "esasYil": "", "esasIlkSiraNo": "", "esasSonSiraNo": "", "kararYil": "",
           "kararIlkSiraNo": "", "kararSonSiraNo": "", "baslangicTarihi": "", "bitisTarihi": "", "pageSize": 10, "pageNumber": 1}
    denemeler = [
        ("A detay, düz", "/aramadetaylist", dict(bos, arananKelime="sahte fatura")),
        ("B detay, düz+tarih", "/aramadetaylist", dict(bos, arananKelime="sahte fatura", baslangicTarihi=bas, bitisTarihi=bit)),
        ("C detay, tırnak", "/aramadetaylist", dict(bos, arananKelime='"sahte fatura"')),
        ("D detay, düz+sıralı", "/aramadetaylist", dict(bos, arananKelime="sahte fatura", siralama="3", siralamaDirection="desc")),
        ("E detay, yıl 2025", "/aramadetaylist", dict(bos, arananKelime="sahte fatura", kararYil="2025")),
        ("F liste, sıralı", "/aramalist", {"aranan": "sahte fatura", "arananKelime": "sahte fatura", "siralama": "3",
                                          "siralamaDirection": "desc", "pageSize": 10, "pageNumber": 1}),
    ]
    for ad, yol, d in denemeler:
        try:
            raw = http(BASE + yol, {"data": d}, timeout=90)
            j = json.loads(raw)
            inner = j.get("data") or {}
            rows = inner.get("data") or []
            tarihler = ", ".join((r.get("kararTarihi") or "?") for r in rows[:4])
            print(f"{ad}: {len(rows)} sonuç, toplam {inner.get('recordsTotal')} | {tarihler}")
            if not rows:
                print("   yanıt: " + raw[:160])
        except Exception as e:  # noqa: BLE001
            print(f"{ad}: HATA {e}")
        time.sleep(PAUSE)


def main():
    if "--diag" in sys.argv:
        return diag()
    try:
        with open(STATE, encoding="utf-8") as f:
            seen = set(json.load(f))
    except (FileNotFoundError, ValueError):
        seen = set()
    found = {}
    for q in QUERIES:
        res = []
        for page in range(1, (6 if SEED else 2)):
            try:
                part = search(q, page)
            except Exception as e:  # noqa: BLE001
                print(f"Arama hatası ({q}, sayfa {page}): {e}")
                break
            res += part
            time.sleep(PAUSE)
            if len(part) < 10:
                break
        ceza = [r for r in res if "ceza" in r["daire"].lower()]
        print(f"{q}: {len(res)} sonuç, {len(ceza)} ceza dairesi")
        for r in ceza:
            found.setdefault(r["id"], r)
        time.sleep(PAUSE)
    new = [r for k, r in found.items() if k not in seen]
    print(f"Yeni karar adayı: {len(new)}")
    if TEST:
        shown = False
        for r in new[:6]:
            try:
                t = document(r["id"])
            except Exception as e:  # noqa: BLE001
                print(f"Metin alınamadı: {e}")
                break
            ok = bool(VERGI.search(t))
            print(f"{r['daire']} E.{r['esas']} K.{r['karar']} ({r['tarih']}): {len(t)} krk, vergi: {ok}")
            if not ok and not shown:
                shown = True
                print("   Örnek: " + t[:200].replace("\n", " "))
            time.sleep(PAUSE)
        return
    rows = []
    for r in (new if SEED else new[:40]):
        try:
            t = document(r["id"])
        except Exception as e:  # noqa: BLE001
            print(f"Metin alınamadı: {e}")
            continue
        seen.add(r["id"])
        if not VERGI.search(t):
            continue
        rows.append({"title": f"Yargıtay {r['daire']} E. {r['esas']}, K. {r['karar']}", "meta": r["tarih"],
                     "url": f"{BASE}/getDokuman?id={r['id']}", "ozet": ozet(t), "metin": t})
        time.sleep(PAUSE)
    if rows:
        print(f"Veritabanına eklenen: {send(rows)} / {len(rows)}")
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f)


if __name__ == "__main__":
    main()
