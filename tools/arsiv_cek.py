"""GİB özelge, tebliğ ve sirküler arşivini mevzuat_arsiv tablosuna yükler (Emsal Bul için).

ARSIV=probe: yalnızca kaynakları dener (toplam sayı, metin uzunluğu), veritabanına yazmaz.
ARSIV=1    : tüm arşivi çeker; var olan kayıtları günceller. Depo herkese açık: loglara yalnızca sayılar yazılır.
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ozelge  # noqa: E402
import metin  # noqa: E402

LIST = "https://gib.gov.tr/api/gibportal/mevzuat/{path}?page={page}&size={size}&sortFieldName=id&sortType=DESC"
KINDS = [("Özelge", "ozelge/list", "ozelge"), ("Tebliğ", "teblig/list", "teblig"), ("Sirküler", "sirkuler/list", "sirkuler")]
MODE = os.environ.get("ARSIV", "probe")


def page(path, p, size):
    for k in range(4):
        try:
            return json.loads(ozelge.http(LIST.format(path=path, page=p, size=size), {}, timeout=180))["resultContainer"]
        except Exception:  # noqa: BLE001
            time.sleep(3 * (k + 1))
    return None


def tarih(v):
    v = (v or "")[:10]
    return ".".join(reversed(v.split("-"))) if re.match(r"\d{4}-\d{2}-\d{2}", v) else v


def row(tur, kind, r):
    txt = metin.html_to_text(r.get("description") or "")
    if tur == "Özelge":
        flat = re.sub(r"\s+", " ", txt)
        s = re.search(r"Sayı\s*:\s*(\S+)", flat)
        t = re.search(r"Sayı\s*:\s*\S+\s+(\d{2}\.\d{2}\.\d{4})", flat)
        meta = " · ".join(x for x in (t.group(1) if t else "", s.group(1) if s else "") if x)
    elif tur == "Tebliğ":
        meta = ozelge._teblig(r["id"], r.get("title"), r.get("kanunTitle"), r.get("resmiGazeteTarih"), r.get("resmiGazeteSayi"), "")["meta"]
    else:
        no = (r.get("sirkulerNo") or "").strip()
        meta = " · ".join(x for x in ((r.get("kanunTitle") or "").replace("(*)", "").strip(), tarih(r.get("sirkulerTarih")), f"No: {no}" if no else "") if x)
    return {"tur": tur, "gid": int(r["id"]), "title": ozelge.strip_tags(r.get("title"))[:500] or "Başlıksız", "meta": meta[:300],
            "url": r.get("siteLink") or f"https://gib.gov.tr/mevzuat/{kind}/{r['id']}", "metin": txt[:30000]}


def write(rows):
    """Toplu yazar; hata olursa parçalara böler, yine olmazsa tek tek dener (sorunlu kayıt atlanır)."""
    for x in rows:
        for k in ("title", "meta", "metin"):
            x[k] = (x.get(k) or "").replace("\x00", "")
    for k in range(3):
        try:
            ozelge.db("POST", "mevzuat_arsiv?on_conflict=tur,gid", rows, prefer="resolution=merge-duplicates,return=minimal")
            return 0
        except Exception:  # noqa: BLE001
            time.sleep(5 * (k + 1))
    if len(rows) > 1:
        h = len(rows) // 2
        return write(rows[:h]) + write(rows[h:])
    return 1


def mevcut(tur):
    try:
        req = ozelge.Request(f"{ozelge.SUPABASE_URL}/rest/v1/mevzuat_arsiv?select=gid&tur=eq.{ozelge.quote(tur)}",
                             headers={"apikey": ozelge.SUPABASE_KEY, "Authorization": f"Bearer {ozelge.SUPABASE_KEY}", "Prefer": "count=exact", "Range": "0-0"})
        with ozelge.urlopen(req, timeout=60) as r:
            return int((r.headers.get("Content-Range") or "*/0").split("/")[-1])
    except Exception:  # noqa: BLE001
        return 0


# Danıştay vergi kararları: konu başına ifade (andKelimeler); canlı arama kesintilerinden etkilenmemek için arşive alınır
DANISTAY_Q = {
    "sahte_kullanma": [["sahte", "fatura", "kullanma"], ["sahte", "belge", "indirim"]], "sahte_duzenleme": [["sahte", "fatura", "düzenleme"]],
    "yaniltici": [["yanıltıcı", "belge"]], "kdv_iade": [["katma", "değer", "vergisi", "iade"], ["kdv", "iade"]],
    "ortulu_sermaye": [["örtülü", "sermaye"]], "transfer": [["transfer", "fiyatlandırması"]], "hasilat": [["hasılat", "gizleme"], ["kayıt", "dışı", "hasılat"]],
    "ibraz": [["defter", "belge", "ibraz"]], "ortaklar_cari": [["ortaklar", "cari"]], "kkeg": [["kanunen", "kabul", "edilmeyen"]],
    "degerleme": [["değerleme", "vergi", "usul"]], "gayrimenkul": [["değer", "artışı", "kazancı"], ["gayrimenkul", "satış", "kazanç"]], "stopaj": [["tevkifat", "sorumlusu"]],
}
DANISTAY_SAYFA = int(os.environ.get("DANISTAY_SAYFA") or 4)  # sayfa başı 10 karar


def danistay(var_olan):
    import zlib
    yeni, hata, t0, hatalar = 0, 0, time.time(), {}
    for konu, qs in DANISTAY_Q.items():
        for kw in qs:
            for pg in range(1, DANISTAY_SAYFA + 1):
                lst = None
                for dn in range(4):
                    try:
                        time.sleep(1.5 + 4 * dn)
                        d = json.loads(ozelge.http(ozelge.DANISTAY + "/aramalist", {"data": {"andKelimeler": kw, "pageSize": 10, "pageNumber": pg}}, timeout=90))
                        lst = (d.get("data") or {}).get("data") or []
                        break
                    except Exception as e:  # noqa: BLE001
                        kod = f"liste:{type(e).__name__}:{getattr(e, 'code', '')}"
                        hatalar[kod] = hatalar.get(kod, 0) + 1
                if lst is None:
                    hata += 1
                    break
                rows = []
                for k in lst:
                    kid = str(k.get("id") or "")
                    gid = int(kid) if kid.isdigit() and len(kid) < 18 else zlib.crc32(kid.encode())
                    if not kid or gid in var_olan:
                        continue
                    url = f"{ozelge.DANISTAY}/getDokuman?id={kid}&arananKelime={ozelge.quote(','.join(kw))}"
                    txt = ""
                    for dn in range(3):
                        try:
                            time.sleep(0.8 + 3 * dn)
                            txt = metin.danistay_text(url)[:30000]
                            break
                        except Exception as e:  # noqa: BLE001
                            kod = f"metin:{type(e).__name__}:{getattr(e, 'code', '')}"
                            hatalar[kod] = hatalar.get(kod, 0) + 1
                    if not txt:
                        hata += 1
                        continue
                    if len(txt) < 300:
                        continue
                    var_olan.add(gid)
                    rows.append({"tur": "Danıştay kararı", "gid": gid, "title": f"{k.get('daireKurul') or k.get('daire') or 'Danıştay'} E. {k.get('esasNo') or ''}, K. {k.get('kararNo') or ''}",
                                 "meta": k.get("kararTarihi") or "", "url": url, "metin": txt})
                if rows:
                    write(rows)
                    yeni += len(rows)
                if len(lst) < 10:
                    break
    print(f"Danıştay: {yeni} yeni karar arşive alındı, {hata} hata, {time.time() - t0:.0f} sn, hata türleri: {hatalar}")


def gidler(tur):
    out, off = set(), 0
    while True:
        r = ozelge.db("GET", f"mevzuat_arsiv?select=gid&tur=eq.{ozelge.quote(tur)}&order=gid&offset={off}&limit=1000") or []
        out |= {x["gid"] for x in r}
        if len(r) < 1000:
            return out
        off += 1000


def main():
    if MODE in ("danistay", "gunluk"):
        if MODE == "gunluk":  # GİB'deki yeni özelge/tebliğ/sirküler (ilk sayfa)
            for tur, path, kind in KINDS:
                d = page(path, 0, 200)
                if d:
                    rows = [row(tur, kind, r) for r in d["content"] if not r.get("deleted")]
                    print(f"{tur}: ilk {len(rows)} kayıt güncellendi, {write(rows)} yazılamadı")
        danistay(gidler("Danıştay kararı"))
        return
    if MODE == "probe":
        for tur, path, kind in KINDS:
            d = page(path, 0, 20)
            if not d:
                print(tur, "erişilemedi"); continue
            c = [x for x in d["content"] if not x.get("deleted")]
            ls = sorted(len(metin.html_to_text(x.get("description") or "")) for x in c)
            print(tur, "toplam:", d.get("totalElements"), "sayfa(20):", d.get("totalPages"), "metin uzunlukları (min/orta/max):", ls[0] if ls else 0, ls[len(ls) // 2] if ls else 0, ls[-1] if ls else 0,
                  "kısa (<120):", sum(1 for x in ls if x < 120))
        return
    for tur, path, kind in KINDS:
        var = mevcut(tur)
        p, n, kisa, fail, atla, t0 = max(0, var // 200 - 1), 0, 0, 0, 0, time.time()  # yarım kalan yüklemeyi sürdür
        while True:
            d = page(path, p, 200)
            if d is None:
                fail += 1
                if fail > 3:
                    break
                p += 1; continue
            rows = []
            for r in d["content"]:
                if r.get("deleted"):
                    continue
                x = row(tur, kind, r)
                if len(x["metin"]) < 120 and tur != "Özelge":
                    try:
                        x["metin"] = metin.gib_text(kind, r["id"])[:30000]
                    except Exception:  # noqa: BLE001
                        pass
                if len(x["metin"]) < 120:
                    kisa += 1
                rows.append(x)
            if rows:
                atla += write(rows)
                n += len(rows)
            p += 1
            if p >= (d.get("totalPages") or 1):
                break
        print(f"{tur}: önceden {var}, bu turda {n} kayıt işlendi, {atla} kayıt yazılamadı, {kisa} kısa metinli, {fail} sayfa alınamadı, {time.time() - t0:.0f} sn")


if __name__ == "__main__":
    main()
