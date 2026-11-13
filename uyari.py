"""Meteorolojik uyarılar (MGM) ve iş dünyasını etkileyen hizmet kesintileri.

Her taramada:
- MGM'nin il/ilçe bazlı sarı/turuncu/kırmızı uyarılarını (bugün + yarın) alır,
- Microsoft 365 (kurumsal + Outlook.com) durum sayfalarını ve GİB e-hizmetlerinin erişilebilirliğini kontrol eder,
- Özeti herkesin okuyabildiği settings.uyarilar anahtarına yazar; uygulama (ana ekran) ve 08:30 Günaydın
  bildirimi buradan okur. Ayrı anlık bildirim GÖNDERİLMEZ (Tuna, 2026-11-13: "tek bildirim", Günaydın'ın içinde).
Konumu olmayan üye Ankara sayılır.

Depo herkese açık: loglara ve seen.json'a kimlik yazılmaz (yalnızca il plakası ve sayılar).
"""
import json
import math
import os
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.request import Request, urlopen

TR = timezone(timedelta(hours=3))
QUIET = (22, 8)
APP_URL = "https://tmpro.tmproapp.workers.dev/"
UA = {"User-Agent": "Mozilla/5.0 (TMPRO uyari)"}
MGM_H = {**UA, "Origin": "https://www.mgm.gov.tr", "Referer": "https://www.mgm.gov.tr/"}
ANKARA = 6

RENK = {"yellow": "Sarı", "orange": "Turuncu", "red": "Kırmızı"}
RENK_SIRA = {"yellow": 1, "orange": 2, "red": 3}
RENK_IKON = {"yellow": "🟡", "orange": "🟠", "red": "🔴"}
HADISE = {"rain": "Kuvvetli yağış", "snow": "Kar", "wind": "Kuvvetli rüzgâr ve fırtına", "fog": "Sis",
          "thunderstorm": "Gök gürültülü sağanak", "hot": "Aşırı sıcak", "cold": "Aşırı soğuk", "ice": "Buzlanma ve don",
          "agricultural": "Zirai don", "frost": "Zirai don", "dust": "Toz taşınımı", "avalanche": "Çığ", "lightning": "Yıldırım"}

KISA = {"rain": "kuvvetli yağış", "snow": "kar", "wind": "fırtına", "fog": "sis", "thunderstorm": "sağanak ve fırtına",
        "hot": "aşırı sıcak", "cold": "aşırı soğuk", "ice": "buzlanma", "agricultural": "zirai don", "frost": "zirai don",
        "dust": "toz taşınımı", "avalanche": "çığ", "lightning": "yıldırım"}

# Kendimiz ölçtüğümüz kamu e-hizmetleri (resmî durum sayfaları yok). Ard arda DOWN_AFTER tur hata = kesinti.
PROBES = [("gib_dvd", "GİB Dijital Vergi Dairesi", "https://dijital.gib.gov.tr/"),
          ("earsiv", "e-Arşiv Portal", "https://earsivportal.efatura.gov.tr/intragiris.html")]
DOWN_AFTER = 4
UP_AFTER = 2
GONE_AFTER = 2  # resmî kaynakta kaybolan kesinti bu kadar tur görünmezse "giderildi"
CONSUMER_KEEP = {"Outlook.com": "Outlook.com", "Microsoft 365 (Consumer)": "Microsoft 365 (bireysel)",
                 "OneDrive": "OneDrive", "Microsoft Teams Free": "Teams", "Office for the web (Consumer)": "Office (web)"}
MS_DURUM = {"servicedegradation": "aksama", "service degradation": "aksama", "serviceinterruption": "kesinti",
            "service interruption": "kesinti", "restoringservice": "düzeltiliyor", "restoring service": "düzeltiliyor",
            "extendedrecovery": "düzeltiliyor", "extended recovery": "düzeltiliyor", "investigating": "inceleniyor",
            "investigation suspended": "inceleniyor"}


def get(url, headers=UA, timeout=20):
    with urlopen(Request(url, headers=headers), timeout=timeout) as r:
        return r.status, r.read(600000).decode("utf-8", "replace")


def _load(name):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", name)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def load_iller():
    """İl merkezleri + ilçe merkezleri: [[plaka, ad, enlem, boylam], ...] (önce iller)."""
    return _load("iller.json") + _load("ilceler.json")


def tr_low(s):
    return (s or "").replace("I", "ı").replace("İ", "i").lower().strip()


def plaka_of(lat, lon, city, pts):
    """Üyenin ili: şehir adı bir il ya da tek bir ilçe adıysa o; değilse en yakın il/ilçe merkezi; konum yoksa Ankara."""
    c = tr_low(city)
    if c:
        hits = {p for p, ad, _, _ in pts if tr_low(ad) == c and ad != "Merkez"}
        il_hit = [p for p, ad, _, _ in pts[:81] if tr_low(ad) == c]
        if il_hit:
            return il_hit[0]
        if len(hits) == 1:
            return hits.pop()
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return ANKARA
    best, bd = ANKARA, 1e9
    for p, _, la, lo in pts:
        d = (la - lat) ** 2 + ((lo - lon) * math.cos(math.radians(lat))) ** 2
        if d < bd:
            best, bd = p, d
    return best


# ---------------------------------------------------------------- MGM

def first_sentences(t, n=220):
    t = re.sub(r"\s+", " ", t or "").strip()
    if len(t) <= n:
        return t
    cut = t[:n]
    return (cut[: cut.rfind(" ")] if " " in cut else cut) + "…"


def fetch_meteo():
    """{plaka: [ {n, r, h[], m, b, e}, ... ]} — her uyarı için ildeki en yüksek seviye."""
    alerts = {}
    for day in ("today", "tomorrow"):
        _, body = get(f"https://servis.mgm.gov.tr/web/meteoalarm/{day}", MGM_H)
        for a in json.loads(body) or []:
            alerts[a.get("alertNo") or a.get("_id")] = a
    out = {}
    for no, a in alerts.items():
        for color in ("red", "orange", "yellow"):  # en yüksekten başla
            for town in (a.get("towns") or {}).get(color) or []:
                p = int(town) // 100 - 900
                if not 1 <= p <= 81:
                    continue
                lst = out.setdefault(str(p), [])
                if any(x["n"] == str(no) for x in lst):
                    continue  # bu ilde daha yüksek seviyesi zaten eklendi
                kinds = (a.get("weather") or {}).get(color) or []
                lst.append({"n": str(no), "r": color, "h": [HADISE.get(k, k) for k in kinds], "k": [KISA.get(k, HADISE.get(k, k)) for k in kinds],
                            "m": first_sentences((a.get("text") or {}).get(color), 400),
                            "b": a.get("begin"), "e": a.get("end")})
    for lst in out.values():
        lst.sort(key=lambda x: -RENK_SIRA[x["r"]])
    return out


def tr_time(iso):
    if not iso:
        return ""
    d = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TR)
    ay = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"][d.month - 1]
    return f"{d.day} {ay} {d:%H:%M}"


def meteo_line(x, il):
    return f"{RENK_IKON[x['r']]} {il}: {RENK[x['r']]} uyarı · {', '.join(x['h']) or 'Meteorolojik uyarı'}"


# ---------------------------------------------------------------- hizmet kesintileri

def ms_status(s):
    k = (s or "").strip().lower()
    if k in ("", "operational", "serviceoperational", "service restored", "servicerestored", "falsepositive",
             "false positive", "postincidentreviewpublished", "post-incident report published", "resolved"):
        return None
    return MS_DURUM.get(k, "aksama")


APPS = [("Outlook", ("Outlook", "Exchange")), ("Teams", ("Teams",)), ("OneDrive", ("OneDrive",)), ("SharePoint", ("SharePoint",)),
        ("OneNote", ("OneNote",)), ("Word/Excel/PowerPoint", ("Microsoft 365 for the web", "Office for the web", "Microsoft 365 apps")),
        ("Copilot", ("Copilot",)), ("To Do", ("To Do", "To-Do"))]


def apps_in(text):
    return [name for name, keys in APPS if any(k in text for k in keys)]


def fetch_outages():
    """Resmî durum sayfalarındaki etkin kesintiler: {anahtar: {s, d, a}} (servis, durum, ayrıntı)."""
    out, errors = {}, 0
    try:
        _, body = get("https://status.office365.com/api/feed/mac")
        for item in re.findall(r"<item>(.*?)</item>", body, re.S):
            st = ms_status(unescape((re.search(r"<status>(.*?)</status>", item) or [None, ""])[1]))
            if not st:
                continue
            desc = re.sub(r"<[^>]+>", " ", unescape(unescape((re.search(r"<description>(.*?)</description>", item, re.S) or [None, ""])[1])))
            guid = (re.search(r"<guid[^>]*>(.*?)</guid>", item) or [None, "x"])[1]
            exch = "Exchange" in desc or "Outlook" in desc
            apps = apps_in(desc)
            out["ms365:" + guid] = {"s": "Microsoft 365 (kurumsal)" + (" · Outlook/Exchange" if exch else ""), "d": st,
                                    "a": ("Kurumsal e-posta (Outlook/Exchange) ve bağlı Microsoft 365 hizmetlerinde" if exch
                                          else "Kurumsal Microsoft 365 hizmetlerinde") + " erişim sorunu bildiriliyor (Microsoft durum sayfası).",
                                    "p": "Microsoft", "apps": apps}
    except Exception as e:  # noqa: BLE001
        errors += 1
        print("Uyarı: Microsoft 365 durumu alınamadı", type(e).__name__)
    try:
        _, body = get("https://status.cloud.microsoft/api/posts/m365Consumer")
        for x in json.loads(body) or []:
            name = CONSUMER_KEEP.get(x.get("ServiceDisplayName"))
            st = ms_status(x.get("Status"))
            if name and st:
                out["msc:" + name] = {"s": name, "d": st, "a": f"{name} hizmetinde erişim sorunu bildiriliyor (Microsoft durum sayfası).",
                                      "p": "Microsoft", "apps": apps_in(f"{name} {x.get('Title', '')} {x.get('Message', '')}")}
    except Exception as e:  # noqa: BLE001
        errors += 1
        print("Uyarı: Outlook.com durumu alınamadı", type(e).__name__)
    return out, errors


def probe_ok(url):
    for _ in range(2):
        try:
            code, body = get(url, timeout=20)
            if 200 <= code < 400 and len(body) > 10:
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


def run(db, state, muted=None, dry=False):
    now_tr = datetime.now(TR)
    utc_now = datetime.now(timezone.utc)
    iller = load_iller()
    il_ad = {str(p): ad for p, ad, _, _ in iller[:81]}
    st = state.setdefault("uyari", {})

    # 1) MGM
    meteo = None
    try:
        meteo = fetch_meteo()
        st.pop("meteo_err", None)
    except Exception as e:  # noqa: BLE001
        st["meteo_err"] = st.get("meteo_err", 0) + 1
        print("Meteorolojik uyarılar alınamadı", type(e).__name__)
    if meteo is None:
        meteo = (state.get("uyari_son") or {}).get("meteo") or {}

    # 2) Kesintiler (resmî kaynaklar + kendi ölçümümüz)
    found, errs = fetch_outages()
    probes = st.setdefault("probe", {})
    for key, name, url in PROBES:
        p = probes.setdefault(key, {"fail": 0, "ok": 0, "down": False})
        if probe_ok(url):
            p["ok"], p["fail"] = p["ok"] + 1, 0
            if p["down"] and p["ok"] >= UP_AFTER:
                p["down"] = False
        else:
            p["fail"], p["ok"] = p["fail"] + 1, 0
            if p["fail"] >= DOWN_AFTER:
                p["down"] = True
        if p["down"]:
            found["tr:" + key] = {"s": name, "d": "erişilemiyor", "a": "Site birkaç denemedir yanıt vermiyor; işlemlerinizi sonraya bırakmanız gerekebilir.",
                                  "p": name, "apps": []}
    outs = st.setdefault("kesinti", {})  # anahtar -> {s,d,a,t(başlangıç),gone,pushed}
    resolved = []
    known = st.get("init")  # ilk turda zaten süren kesintilerin başlangıç saati bilinmez
    st["init"] = True
    for k, v in found.items():
        o = outs.get(k)
        if o:
            o.update(s=v["s"], d=v["d"], a=v["a"], p=v["p"], apps=v["apps"], gone=0)
            o.setdefault("tb", False)
        else:
            outs[k] = {**v, "t": utc_now.isoformat(timespec="minutes"), "tb": bool(known), "gone": 0}
    for k in list(outs):
        if k in found:
            continue
        if errs and not k.startswith("tr:"):
            continue  # kaynak alınamadıysa giderildi sayma
        outs[k]["gone"] = outs[k].get("gone", 0) + 1
        if outs[k]["gone"] >= (1 if k.startswith("tr:") else GONE_AFTER):
            resolved.append(outs.pop(k))

    # 3) Herkese açık özet (uygulama + Günaydın)
    summary = {"t": utc_now.isoformat(timespec="minutes"), "meteo": meteo,
               "kesinti": [{"s": o["s"], "d": o["d"], "a": o["a"], "t": o["t"], "tb": o.get("tb", False),
                            "p": o.get("p") or o["s"], "apps": o.get("apps") or []} for o in outs.values()]}
    state["uyari_son"] = {"meteo": meteo}
    if not dry:
        try:
            db("POST", "settings?on_conflict=key", {"key": "uyarilar", "value": json.dumps(summary, ensure_ascii=False)},
               prefer="resolution=merge-duplicates,return=minimal")
        except Exception as e:  # noqa: BLE001
            print("Uyarı özeti kaydedilemedi", type(e).__name__, getattr(e, "code", ""))
    print(f"Uyarılar: meteorolojik uyarılı il {len(meteo)}, etkin kesinti {len(outs)}, giderilen {len(resolved)}")

    return summary

if __name__ == "__main__":  # deneme: kaynakları okur, yazmaz ve bildirim göndermez
    m = fetch_meteo()
    il = {str(p): ad for p, ad, _, _ in load_iller()[:81]}
    print("Meteorolojik uyarılı iller:", ", ".join(f"{il[p]} ({RENK[v[0]['r']]})" for p, v in sorted(m.items(), key=lambda x: int(x[0]))))
    for p in ("6", "34", "35"):
        for x in m.get(p, []):
            print(" ", meteo_line(x, il[p]), "|", tr_time(x["b"]), "-", tr_time(x["e"]))
    o, e = fetch_outages()
    print("Kesintiler:", json.dumps(o, ensure_ascii=False)[:1500], "hata:", e)
    for key, name, url in PROBES:
        print("Erişim", name, probe_ok(url))
