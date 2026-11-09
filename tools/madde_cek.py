"""Rapor taslağı için temel vergi kanunlarının seçili maddelerini mevzuat.gov.tr'den alıp worker/maddeler.json'a yazar.
Kanun metinleri kamuya açıktır. Elle çalıştırılır (gunluk.yml madde_cek), madde değişikliklerinde yeniden çalıştırılabilir."""
import html, json, re, sys
from urllib.request import Request, urlopen

KANUNLAR = {
    "VUK": (213, 4, ["3", "11", "29", "30", "114", "134", "135", "138", "139", "140", "141", "227", "229", "230", "231", "232", "258", "336", "339", "341", "344", "353", "359", "367", "370", "371", "376", "Ek 1"]),
    "KDVK": (3065, 5, ["8", "9", "29", "30", "32", "34"]),
    "KVK": (5520, 5, ["11", "12", "13"]),
    "GVK": (193, 4, ["40", "41", "94", "Mükerrer 80", "Mükerrer 81"]),
}
UA = {"User-Agent": "Mozilla/5.0 (TMPRO mevzuat)"}


def get(url):
    with urlopen(Request(url, headers=UA), timeout=90) as r:
        return r.read().decode("utf-8", "replace")


def text_of(no, tertip):
    h = get(f"https://www.mevzuat.gov.tr/anasayfa/MevzuatFihristDetayIframe?MevzuatTur=1&MevzuatNo={no}&MevzuatTertip={tertip}")
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S | re.I)
    h = re.sub(r"<br\s*/?>|</p>|</div>|</tr>", "\n", h, flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " ", h)).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t)


HEAD = re.compile(r"^\s*((?:Mükerrer|Ek)\s+)?Madde\s+(\d+)\s*[–—-]", re.I | re.M)


def split(t):
    ms = list(HEAD.finditer(t))
    out = {}
    for i, m in enumerate(ms):
        key = ((m.group(1) or "").strip().capitalize() + " " + m.group(2)).strip()
        body = t[m.start(): ms[i + 1].start() if i + 1 < len(ms) else len(t)]
        # madde başlığı: başlangıçtan önceki son kısa satır
        before = t[max(0, m.start() - 300): m.start()].strip().split("\n")
        title = before[-1].strip() if before and 2 < len(before[-1].strip()) < 120 else ""
        body = re.sub(r"\s*\[\d+\]", "", body)
        body = re.sub(r"\n(?=[a-zçğıöşü0-9(,;.])", " ", body)  # satır içi kırılmaları birleştir
        body = re.sub(r"[ \t]+", " ", re.sub(r"\s+\n", "\n", body)).strip()
        title = re.sub(r"\s*\[\d+\]", "", title).strip(" :")
        if key not in out:  # ilk geçen (geçici maddeler sonra gelir)
            out[key] = {"baslik": title, "metin": body[:5000] + ("…" if len(body) > 5000 else "")}
    return out


def main():
    res, eksik = {}, []
    for kod, (no, tertip, keys) in KANUNLAR.items():
        try:
            allm = {}
            for tt in dict.fromkeys([tertip, 4, 3, 5]):
                allm = split(text_of(no, tt))
                if allm:
                    break
        except Exception as e:  # noqa: BLE001
            print(kod, "alınamadı:", e)
            eksik.append(kod)
            continue
        print(kod, "toplam madde:", len(allm))
        for k in keys:
            m = allm.get(k)
            if m:
                res[f"{kod} {k}"] = m
            else:
                eksik.append(f"{kod} {k}")
    print("alınan:", len(res), "| eksik:", eksik)
    if len(res) < 25:
        sys.exit("Yeterli madde alınamadı; dosya yazılmadı")
    json.dump(res, open("worker/maddeler.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print("yazıldı: worker/maddeler.json")


if __name__ == "__main__":
    main()
