#!/usr/bin/env python3
"""TMPRO · Yargıtay ceza kararları toplayıcı.

Kararlar Adalet Bakanlığı Mevzuat sitesinin (mevzuat.adalet.gov.tr) herkese açık karar
arama servisinden, karar tarihine göre yeniden eskiye alınır. Servis yurt dışından erişime
kapalı olduğu için bu betik Türkiye'de duran bir cihazda (telefon/sunucu) çalışır.
Vergi suçlarıyla ilgili ceza dairesi kararlarını bulur, tam metnini alır ve TMPRO
veritabanına gönderir. Yeni kayıtların bildirimi mevcut otomatik tarama tarafından yapılır.

Ayarlar ortam değişkenlerinden okunur: TMPRO_SUPABASE_URL, TMPRO_ANON_KEY, TMPRO_INGEST_TOKEN
Kullanım:
  python yargitay.py --test   # yalnızca dener, veritabanına yazmaz
  python yargitay.py --seed   # ilk çalıştırma: son kararları bildirim göndermeden yükler
  python yargitay.py          # normal çalışma (cron, saatte bir)
"""
import base64
import html
import json
import os
import re
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

API = "https://bedesten.adalet.gov.tr/emsal-karar"
SITE = "https://mevzuat.adalet.gov.tr/ictihat/"
QUERIES = [
    '"vergi kaçakçılığı"',
    '"sahte fatura"',
    '"yanıltıcı belge"',
    '"Vergi Usul Kanunu" 359',
    '"naylon fatura"',
    '"defter ve belgeleri" ibraz',
]
VERGI = re.compile(r"vergi usul|213 sayılı|vuk|359|sahte fatura|yanıltıcı belge|vergi kaçakçılığı|naylon fatura", re.I)
STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yargitay_mevzuat_gorulen.json")
HEADERS = {"Content-Type": "application/json; charset=utf-8", "AdaletApplicationName": "UyapMevzuat",
           "User-Agent": "TMPRO-karar-takip/1.0"}
PAUSE = 6
TEST, SEED = "--test" in sys.argv, "--seed" in sys.argv


def post(path, body, timeout=60):
    for wait in (30, 90, 240, None):
        try:
            req = Request(f"{API}/{path}", data=json.dumps(body).encode(), method="POST", headers=HEADERS)
            with urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except HTTPError as e:
            if e.code != 429 or wait is None:
                raise
            print(f"Servis yavaşla dedi (429), {wait} sn bekleniyor…", flush=True)
            time.sleep(wait)


def html_to_text(s):
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()


def search(q, page=1):
    body = {"data": {"pageSize": 10, "pageNumber": page, "itemTypeList": ["YARGITAYKARARI"], "phrase": q,
                     "sortFields": ["KARAR_TARIHI"], "sortDirection": "desc"},
            "applicationName": "UyapMevzuat", "paging": True}
    rows = ((post("searchDocuments", body).get("data") or {}).get("emsalKararList")) or []
    return [{"id": str(r.get("documentId")), "daire": r.get("birimAdi") or "Yargıtay",
             "esas": r.get("esasNo") or "", "karar": r.get("kararNo") or "", "tarih": r.get("kararTarihiStr") or ""}
            for r in rows if r.get("documentId")]


def document(did):
    d = post("getDocumentContent", {"data": {"documentId": did}, "applicationName": "UyapMevzuat"}).get("data") or {}
    if "html" not in (d.get("mimeType") or "html"):
        return ""  # PDF kararlar şimdilik atlanır
    return html_to_text(base64.b64decode(d.get("content") or "").decode("utf-8", "replace"))


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


def tarih_key(r):
    t = r["tarih"]
    return t[6:10] + t[3:5] + t[0:2]


def main():
    try:
        with open(STATE, encoding="utf-8") as f:
            seen = set(json.load(f))
    except (FileNotFoundError, ValueError):
        seen = set()
    found = {}
    for q in QUERIES:
        res = []
        for page in range(1, (6 if SEED else 3)):
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
        print(f"{q}: {len(res)} sonuç, {len(ceza)} ceza")
        for r in ceza:
            found.setdefault(r["id"], r)
    new = sorted((r for k, r in found.items() if k not in seen), key=tarih_key, reverse=True)
    print(f"Yeni karar adayı: {len(new)}")
    if TEST:
        for r in new[:6]:
            try:
                t = document(r["id"])
            except Exception as e:  # noqa: BLE001
                print(f"Metin alınamadı: {e}")
                break
            print(f"{r['daire']} E.{r['esas']} K.{r['karar']} ({r['tarih']}): {len(t)} krk, vergi: {bool(VERGI.search(t))}")
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
        time.sleep(PAUSE)
        if not t or not VERGI.search(t):
            continue
        rows.append({"title": f"Yargıtay {r['daire']} E. {r['esas']}, K. {r['karar']}", "meta": r["tarih"],
                     "url": SITE + r["id"], "ozet": ozet(t), "metin": t})
    if rows:
        print(f"Veritabanına eklenen: {send(rows)} / {len(rows)}")
    else:
        print("Eklenecek yeni vergi kararı yok")
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f)


if __name__ == "__main__":
    main()
