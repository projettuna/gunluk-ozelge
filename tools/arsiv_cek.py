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


def main():
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
        p, n, kisa, fail, t0 = 0, 0, 0, 0, time.time()
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
                ozelge.db("POST", "mevzuat_arsiv?on_conflict=tur,gid", rows, prefer="resolution=merge-duplicates,return=minimal")
                n += len(rows)
            p += 1
            if p >= (d.get("totalPages") or 1):
                break
        print(f"{tur}: {n} kayıt yüklendi, {kisa} kısa metinli, {fail} sayfa alınamadı, {time.time() - t0:.0f} sn")


if __name__ == "__main__":
    main()
