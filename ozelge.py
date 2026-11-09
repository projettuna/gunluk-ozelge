#!/usr/bin/env python3
"""GİB'de yeni yayımlanan özelgeleri ve VUK 359'a değinen yeni Danıştay kararlarını e-postayla bildirir.

Saatlik çalışır:
  - Yeni özelge (veya yeni 359 kararı) varsa hemen e-posta atar.
  - Saat 18:00'den sonra, o gün hiç özelge maili gitmediyse "bugün özelge yok" maili atar.

Ortam değişkenleri:
  MAIL_TO      alıcı adres(ler), virgülle ayrılmış
  SMTP_HOST    örn. smtp.gmail.com (varsayılan)
  SMTP_PORT    465 (SSL, varsayılan) veya 587 (STARTTLS)
  SMTP_USER    gönderen hesap
  SMTP_PASS    uygulama şifresi (yoksa e-posta gönderilmez, sadece ekrana yazılır)
  MAIL_FROM    (isteğe bağlı) gönderen adres, varsayılan SMTP_USER
  KEYWORDS     (isteğe bağlı) özelgeler için konu filtresi, örn. "KDV,gelir vergisi"
Kullanım:
  python ozelge.py            # kontrol et, gerekirse gönder, seen.json'u güncelle
  python ozelge.py --dry-run  # gönderme, kaydetme, sadece yazdır
"""
import html
import json
import os
import re
import smtplib
import ssl
import sys
import time
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid, formataddr
from urllib.parse import quote
from urllib.request import Request, urlopen

OZELGE_API = "https://gib.gov.tr/api/gibportal/mevzuat/ozelge/list?page=0&size={size}&sortFieldName=id&sortType=DESC"
DANISTAY = "https://karararama.danistay.gov.tr"
DANISTAY_WORDS = ["vergi usul kanunu", "359"]
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen.json")
TR = timezone(timedelta(hours=3))
NO_OZELGE_HOUR = 18
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
RESEND = "--resend" in sys.argv
SEED = "--seed" in sys.argv
RESEND_KARAR = "--resend-karar" in sys.argv
DRY = "--dry-run" in sys.argv
MIGRATE = "--migrate" in sys.argv
TEST_PUSH = "--test-push" in sys.argv
DIAG = "--diag" in sys.argv
ONLY_RG = "--only-rg" in sys.argv  # gece yarısı: yalnızca Resmî Gazete
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or ""
# Gizli anahtar yoksa Supabase devre dışı (eski e-posta düzeni sürer)
SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/") if SUPABASE_KEY else ""
# Uygulama (Supabase) kuruluysa e-posta kapalı; MAIL_ENABLED=1 ile tekrar açılabilir
MAIL_ENABLED = bool(os.environ.get("SMTP_PASS")) and (os.environ.get("MAIL_ENABLED") == "1" or not SUPABASE_URL)
APP_URL = "https://tmpro.tmproapp.workers.dev/"
QUIET = (22, 8)  # 22:00-08:00 arası bildirim yok
# 359. maddeye gerçekten değinen metni yakalar (ör. "359. madde", "359 uncu maddesi", "VUK'nun 359").
MADDE_359 = re.compile(
    r"359\s*(?:\.|'?\s*(?:uncu|ncu|ıncı|inci))?\s*madde|madde(?:si|sinin|sinde)?\s*359|(?:VUK|Usul Kanunu)\S*\s+359",
    re.I,
)


def http(url, body=None, timeout=60):
    headers = {"User-Agent": UA, "Accept": "application/json, text/html"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json; charset=UTF-8"
        data = json.dumps(body).encode()
    req = Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    with urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def strip_tags(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


# ---------------------------------------------------------------- özelgeler

def get_ozelgeler(size=50):
    data = json.loads(http(OZELGE_API.format(size=size), {}))
    items = []
    for rec in data["resultContainer"]["content"]:
        if rec.get("deleted"):
            continue
        text = strip_tags(rec.get("description"))
        sayi = re.search(r"Sayı\s*:\s*(\S+)", text)
        tarih = re.search(r"Sayı\s*:\s*\S+\s+(\d{2}\.\d{2}\.\d{4})", text)
        konu = re.search(r"Konu\s*:\s*(.+?)(?:\s*\*{3,}|\s+İlgi\s*:|$)", text)
        ilgi = text.find("İlgi")
        ozet = re.sub(r"^İlgi\s*:\s*", "", text[ilgi:] if ilgi >= 0 else text)
        items.append({
            "id": int(rec["id"]),
            "title": strip_tags(rec.get("title")) or (konu.group(1) if konu else "Başlıksız özelge"),
            "meta": " · ".join(x for x in (tarih.group(1) if tarih else "", sayi.group(1) if sayi else "") if x),
            "url": rec.get("siteLink") or f"https://gib.gov.tr/mevzuat/ozelge/{rec['id']}",
            "ozet": (ozet[:280] + "…") if len(ozet) > 280 else ozet,
        })
    return items


# ---------------------------------------------------------------- tebliğler

LAST_ADDED = "https://gib.gov.tr/api/gibportal/search/mevzuatLastAdded"
TEBLIG_LIST = "https://gib.gov.tr/api/gibportal/mevzuat/teblig/list?page={page}&size=1000"
TEBLIG_FULL_HOUR = 6  # tam tarama saati (TR)


def _teblig(id_, title, kanun, rg_tarih, rg_sayi, url):
    rg_tarih = (rg_tarih or "")[:10]
    if re.match(r"\d{4}-\d{2}-\d{2}", rg_tarih):
        rg_tarih = ".".join(reversed(rg_tarih.split("-")))
    meta = " · ".join(x for x in (
        (kanun or "").replace("(*)", "").strip(),
        f"Resmî Gazete {rg_tarih}" + (f", sayı {rg_sayi}" if rg_sayi else "") if rg_tarih else "") if x)
    try:
        rg = datetime.strptime(rg_tarih, "%d.%m.%Y").replace(tzinfo=TR)
    except ValueError:
        rg = None
    return {"id": int(id_), "title": strip_tags(title), "meta": meta, "rg": rg,
            "url": url or f"https://gib.gov.tr/mevzuat/teblig/{id_}"}


def get_tebligler_last_added():
    """GİB'in "son eklenen mevzuat" listesindeki tebliğler (son 5 kayıt içinden)."""
    data = json.loads(http(LAST_ADDED))
    out = []
    for r in data["resultContainer"]["results"]:
        m = re.search(r"/teblig/(\d+)", r.get("url") or "")
        if r.get("entityType") == "TEBLIG" and m:
            out.append(_teblig(m.group(1), r.get("text"), r.get("kanunTitle"), r.get("resmiGazeteTarih"),
                               r.get("resmiGazeteSayi"), r.get("url")))
    return out


def get_tebligler_full():
    """Tüm tebliğ listesini tarar (günde bir kez; toplu yayımlarda kaçan olmasın diye)."""
    out, page = [], 0
    while page < 10:
        d = json.loads(http(TEBLIG_LIST.format(page=page), {}, timeout=180))["resultContainer"]
        for r in d["content"]:
            if not r.get("deleted"):
                out.append(_teblig(r["id"], r.get("title"), r.get("kanunTitle"), r.get("resmiGazeteTarih"),
                                   r.get("resmiGazeteSayi"), r.get("siteLink")))
        page += 1
        if page >= (d.get("totalPages") or 1):
            break
    return out


def teblig_html(items):
    return "".join(
        '<li style="margin-bottom:16px">'
        f'<a href="{html.escape(t["url"])}" style="font-weight:bold">{html.escape(t["title"])}</a><br>'
        f'<span style="color:#666;font-size:13px">{html.escape(t["meta"])}</span></li>' for t in items)


def teblig_txt(items):
    return "\n\n".join(f"- {t['title']}\n  {t['meta']}\n  {t['url']}" for t in items)


# ---------------------------------------------------------------- diğer GİB mevzuatı (id'ye göre sıralı listeler)

# (state anahtarı, API yolu, mail başlığı, tarih alanı, numara alanı, link yoksa kalıp)
GIB_LISTS = [
    ("kanun", "kanun/filterList", "Kanunlar ve kanun değişiklikleri", "resmiGazeteTarih", "kanunNo", "https://gib.gov.tr/mevzuat/kanun/{id}"),
    ("sirkuler", "sirkuler/list", "Sirküler", "sirkulerTarih", "sirkulerNo", "https://gib.gov.tr/mevzuat/sirkuler/{id}"),
    ("cbk", "cbk/list", "Cumhurbaşkanı kararları", "resmiGazeteTarih", "no", "https://gib.gov.tr/mevzuat/cbk/{id}"),
    ("icgenelge", "icGenelge/list", "İç genelgeler", "tarih", "sayi", "https://gib.gov.tr/mevzuat/icgenelge/{id}"),
]
GIB_API = "https://gib.gov.tr/api/gibportal/mevzuat/{path}?page=0&size=20&sortFieldName=id&sortType=DESC"


def get_gib_list(path, date_key, no_key, link_tpl):
    d = json.loads(http(GIB_API.format(path=path), {}))["resultContainer"]
    out = []
    for r in d["content"]:
        if r.get("deleted"):
            continue
        tarih = (r.get(date_key) or "")[:10]
        if re.match(r"\d{4}-\d{2}-\d{2}", tarih):
            tarih = ".".join(reversed(tarih.split("-")))
        no = (r.get(no_key) or "").strip()
        meta = " · ".join(x for x in (
            (r.get("kanunTitle") or "").replace("(*)", "").strip(),
            ("Resmî Gazete " if "resmiGazete" in date_key else "") + tarih + (f", sayı {r['resmiGazeteSayi']}" if r.get("resmiGazeteSayi") and "resmiGazete" in date_key else ""),
            (f"No: {no}" if no and no_key != "kanunNo" else f"Kanun No: {no}" if no else "")) if x and x.strip())
        out.append({"id": int(r["id"]), "title": strip_tags(r.get("title")), "meta": meta,
                    "url": r.get("siteLink") or link_tpl.format(id=r["id"])})
    out.sort(key=lambda x: x["id"], reverse=True)
    return out


# ---------------------------------------------------------------- Anayasa Mahkemesi

AYM = "https://kararlarbilgibankasi.anayasa.gov.tr"
AYM_QUERIES = ['"Vergi Usul Kanunu" 359', '"vergi kaçakçılığı"', '"sahte fatura"']


def get_aym(size=20):
    out, seen = [], set()
    for q in AYM_QUERIES:
        body = {"query": q, "page": 1, "size": size, "sort": "yayinTarihi", "order": "desc"}
        data = json.loads(http(AYM + "/api/core/public/search", body))
        for r in data.get("data") or []:
            if not r.get("highlightCount") or r["id"] in seen:
                continue  # aranan ifade metinde geçmiyorsa atla
            seen.add(r["id"])
            bb = r.get("kararTipi") == "BireyselBasvuru"
            no = r.get("basvuruNo") if bb else f"E.{r.get('esasNo')}, K.{r.get('kararNo')}"
            if bb and r.get("basvuruNo"):
                url = f"{AYM}/BB/{r['basvuruNo']}"
            elif r.get("esasNo"):
                url = f"https://normkararlarbilgibankasi.anayasa.gov.tr/ND/{r['esasNo']}"
            else:
                url = AYM
            tarih = (r.get("kararTarihi") or "")[:10]
            tarih = ".".join(reversed(tarih.split("-"))) if tarih else ""
            meta = " · ".join(x for x in (
                "Bireysel başvuru" if bb else "Norm denetimi", r.get("basvuruAdi") if bb else "",
                f"No: {no}", f"Karar tarihi {tarih}" if tarih else "", r.get("kararTuruBasvuruSonucuLabel") or r.get("kararTuruDosyaSonucuLabel") or "") if x)
            konu = strip_tags(r.get("kararKonusu"))
            out.append({"id": r["id"], "title": (konu[:160] + "…") if len(konu) > 160 else konu or "Anayasa Mahkemesi kararı",
                        "meta": meta, "url": url, "yayin": r.get("yayinTarihi") or ""})
    out.sort(key=lambda x: x["yayin"], reverse=True)
    return out


# ---------------------------------------------------------------- Resmî Gazete

RG = "https://www.resmigazete.gov.tr/"
RG_KEYWORDS = re.compile(
    r"vergi|harç|gümrük|gelir idaresi|hazine ve maliye|katma değer|özel tüketim|damga|tahsil usul|kaçakçılı|"
    r"mali müşavir|muhasebe|tevkifat|matrah|amme alacak|varlık barışı|ekonomiye kazandırıl|yeniden değerleme", re.I)


def get_resmi_gazete():
    page = http(RG)
    out, seen = [], set()
    for href, inner in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        title = re.sub(r"^[–\-\s]+", "", strip_tags(inner))
        if "eskiler" not in href or len(title) < 10 or href in seen:
            continue
        seen.add(href)
        if RG_KEYWORDS.search(title):
            d = re.search(r"/(\d{4})(\d{2})(\d{2})", href)
            out.append({"id": href, "title": title, "url": href,
                        "meta": f"Resmî Gazete {d.group(3)}.{d.group(2)}.{d.group(1)}" if d else "Resmî Gazete"})
    return out


# ---------------------------------------------------------------- Danıştay kararları

def get_kararlar(size=30):
    body = {"data": {"andKelimeler": DANISTAY_WORDS, "pageSize": size, "pageNumber": 1}}
    data = json.loads(http(DANISTAY + "/aramalist", body, timeout=90))
    return [{
        "id": str(r["id"]),
        "daire": r.get("daireKurul") or r.get("daire") or "Danıştay",
        "esas": r.get("esasNo", ""),
        "karar": r.get("kararNo", ""),
        "tarih": r.get("kararTarihi", ""),
    } for r in data["data"]["data"]]


def karar_link(karar_id):
    return f"{DANISTAY}/getDokuman?id={karar_id}&arananKelime={quote(','.join(DANISTAY_WORDS))}"


def karar_snippet(karar_id):
    """(359'a değinen kısım, kararın tam HTML'i) döndürür; değinmiyorsa (None, None)."""
    raw = http(karar_link(karar_id), timeout=90)
    try:
        raw = json.loads(raw).get("data") or raw
    except ValueError:
        pass
    inner = re.search(r"&lt;html.*?&lt;/html&gt;", raw, re.S | re.I)
    doc = html.unescape(inner.group(0)) if inner else raw
    text = strip_tags(re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", doc, flags=re.S | re.I))
    m = MADDE_359.search(text)
    if not m:
        return None, None
    start = max(0, text.rfind(".", 0, max(0, m.start() - 200)) + 1)
    snippet = text[start:m.end() + 250].strip()
    return snippet[:450] + ("…" if len(snippet) > 450 else ""), doc


def enrich_kararlar(kararlar):
    out = []
    for n, k in enumerate(kararlar):
        if n:
            time.sleep(2)  # Danıştay hızlı isteklerde 429 veriyor
        try:
            snip, doc = karar_snippet(k["id"])
        except Exception as e:  # noqa: BLE001
            print(f"Karar {k['id']} okunamadı: {e}")
            snip, doc = "", ""
        if snip is None:
            print(f"Karar {k['id']} 359. maddeye değinmiyor, atlandı")
            continue
        k["ozet"] = snip
        k["doc"] = doc
        k["url"] = karar_link(k["id"])
        out.append(k)
    return out


# ---------------------------------------------------------------- e-posta

def ozelge_html(items):
    return "".join(
        '<li style="margin-bottom:16px">'
        f'<a href="{html.escape(it["url"])}" style="font-weight:bold">{html.escape(it["title"])}</a><br>'
        f'<span style="color:#666;font-size:13px">{html.escape(it["meta"])}</span><br>'
        f'<span style="font-size:13px">{html.escape(it["ozet"])}</span></li>' for it in items)


def karar_html(items):
    return "".join(
        '<li style="margin-bottom:16px">'
        f'<b>Danıştay {html.escape(k["daire"])}</b> · E. {html.escape(k["esas"])}, K. {html.escape(k["karar"])} · {html.escape(k["tarih"])}<br>'
        f'<span style="font-size:13px">{html.escape(k.get("ozet", ""))}</span><br>'
        f'<a href="{html.escape(k.get("url", DANISTAY))}" style="font-size:13px">Kararın tamamını aç</a>'
        f'<span style="font-size:12px;color:#666"> (ayrıca mailin ekinde)</span></li>' for k in items)


def ozelge_txt(items):
    return "\n\n".join(f"- {it['title']}\n  {it['meta']}\n  {it['url']}" for it in items)


def karar_txt(items):
    return "\n\n".join(
        f"- Danıştay {k['daire']} · E. {k['esas']}, K. {k['karar']} · {k['tarih']}\n  {k.get('ozet', '')}\n  {k.get('url', DANISTAY)}" for k in items)


def karar_attachments(kararlar):
    files = []
    for k in kararlar:
        if not k.get("doc"):
            continue
        name = re.sub(r"[^A-Za-z0-9]+", "_", f"Danistay {k['daire']} E {k['esas']} K {k['karar']}".translate(
            str.maketrans("ıİşŞğĞüÜöÖçÇ", "iIsSgGuUoOcC"))).strip("_") + ".html"
        title = f"Danıştay {k['daire']} E. {k['esas']} K. {k['karar']} ({k['tarih']})"
        page = (f'<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
                '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
                f'<body style="font-family:Arial,sans-serif;max-width:800px;margin:16px auto;padding:0 12px">'
                f'<h3>{html.escape(title)}</h3>{re.sub(r"(?is)</?(html|head|body)[^>]*>", "", k["doc"])}</body></html>')
        files.append((name, page))
    return files


def build_mail(ozelgeler, kararlar, today, ozelge_intro=None, karar_intro=None, tebligler=(), teblig_intro=None, extra=()):
    """extra: [(başlık, kısa ad, öğeler, giriş metni veya None)]"""
    parts_subject, html_parts, txt_parts = [], [], []
    for title, short, items, intro in extra:
        if not items:
            continue
        parts_subject.append(f"{len(items)} {short}")
        intro = intro or f"GİB'de yeni yayımlanan {len(items)} kayıt:"
        html_parts.append(f"<h3>{html.escape(title)}</h3><p>{html.escape(intro)}</p><ul style='padding-left:18px'>{teblig_html(items)}</ul>")
        txt_parts.append(f"{title}\n{intro}\n\n{teblig_txt(items)}")
    if tebligler:
        parts_subject.append(f"{len(tebligler)} yeni tebliğ")
        intro = teblig_intro or f"GİB'de yeni yayımlanan {len(tebligler)} tebliğ:"
        html_parts.append(f"<h3>Tebliğler</h3><p>{html.escape(intro)}</p><ul style='padding-left:18px'>{teblig_html(tebligler)}</ul>")
        txt_parts.append(f"TEBLİĞLER\n{intro}\n\n{teblig_txt(tebligler)}")
    if ozelgeler:
        parts_subject.append(f"{len(ozelgeler)} yeni özelge")
        intro = ozelge_intro or f"GİB'de yeni yayımlanan {len(ozelgeler)} özelge:"
        html_parts.append(f"<h3>Özelgeler</h3><p>{html.escape(intro)}</p><ul style='padding-left:18px'>{ozelge_html(ozelgeler)}</ul>")
        txt_parts.append(f"ÖZELGELER\n{intro}\n\n{ozelge_txt(ozelgeler)}")
    elif ozelge_intro:
        parts_subject.append("bugün yeni özelge yok")
        html_parts.append(f"<h3>Özelgeler</h3><p>{html.escape(ozelge_intro)}</p>")
        txt_parts.append(f"ÖZELGELER\n{ozelge_intro}")
    if kararlar:
        parts_subject.append(f"{len(kararlar)} VUK 359 kararı")
        intro = karar_intro or f"VUK 359. maddeye değinen {len(kararlar)} yeni Danıştay kararı:"
        html_parts.append(
            f"<h3>VUK 359 yargı kararları</h3><p>{html.escape(intro)}</p><ul style='padding-left:18px'>{karar_html(kararlar)}</ul>"
            f'<p style="font-size:12px;color:#666">Kararın tamamı: <a href="{DANISTAY}">karararama.danistay.gov.tr</a> (esas/karar no ile aranabilir)</p>')
        txt_parts.append(f"VUK 359 YARGI KARARLARI\n{intro}\n\n{karar_txt(kararlar)}\n\nKararın tamamı: {DANISTAY}")
    subject = ", ".join(parts_subject)
    subject = subject[:1].upper() + subject[1:] + f" ({today})"
    body = ('<div style="font-family:Arial,sans-serif;max-width:680px">' + "".join(html_parts)
            + '<p style="margin-top:24px"><a href="https://tmpro.tmproapp.workers.dev/" style="background:#14284a;color:#fff;padding:10px 16px;border-radius:10px;text-decoration:none;font-weight:bold">TMPRO uygulamasında aç</a></p>'
            + '<p style="color:#999;font-size:12px">Kaynak: gib.gov.tr mevzuat, karararama.danistay.gov.tr</p></div>')
    return subject, "\n\n".join(txt_parts), body, karar_attachments(kararlar)


def send(subject, text, body, attachments=()):
    if DRY or not MAIL_ENABLED:
        print("(e-posta gönderilmedi, deneme modu)\n" + subject + "\n\n" + text)
        print("Ekler:", [(n, len(c)) for n, c in attachments])
        return
    to = [a.strip() for a in os.environ["MAIL_TO"].split(",") if a.strip()]
    user = os.environ["SMTP_USER"]
    sender = os.environ.get("MAIL_FROM") or user
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = formataddr(("TMPRO", sender))
    msg["To"] = ", ".join(to)
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1])
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(text, "plain", "utf-8"))
    alt.attach(MIMEText(body, "html", "utf-8"))
    msg.attach(alt)
    for name, content in attachments:
        part = MIMEText(content, "html", "utf-8")
        part.add_header("Content-Disposition", "attachment", filename=name)
        msg.attach(part)
    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(os.environ.get("SMTP_PORT") or "465")
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx) as s:
            s.login(user, os.environ["SMTP_PASS"])
            s.sendmail(sender, to, msg.as_string())
    else:
        with smtplib.SMTP(host, port) as s:
            s.starttls(context=ctx)
            s.login(user, os.environ["SMTP_PASS"])
            s.sendmail(sender, to, msg.as_string())
    print(f"E-posta gönderildi: {subject}")


# ---------------------------------------------------------------- Supabase ve anlık bildirim


def send_member_mails():
    """mail_queue'daki üyelik/kredi e-postalarını gönderir (MAIL_ENABLED'dan bağımsız)."""
    user, pw = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS")
    if not (user and pw):
        print("SMTP ayarı yok, üye e-postaları atlanıyor")
        return
    try:
        rows = db("GET", "mail_queue?select=id,to_email,subject,body&sent_at=is.null&error=is.null&order=id&limit=30") or []
    except Exception as e:  # noqa: BLE001  (tablo henüz yoksa)
        print(f"mail_queue okunamadı: {str(e)[:120]}")
        return
    if not rows:
        return
    sender = os.environ.get("MAIL_FROM") or user
    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(os.environ.get("SMTP_PORT") or "465")
    ctx = ssl.create_default_context()
    srv = smtplib.SMTP_SSL(host, port, context=ctx) if port == 465 else smtplib.SMTP(host, port)
    if port != 465:
        srv.starttls(context=ctx)
    srv.login(user, pw)
    ok = 0
    for r in rows:
        # Aynı e-posta iki iş tarafından gönderilmesin: önce "gönderiliyor" diye işaretle
        try:
            claimed = db("PATCH", f"mail_queue?id=eq.{r['id']}&sent_at=is.null&error=is.null",
                         {"sent_at": datetime.now(timezone.utc).isoformat()}, prefer="return=representation")
        except Exception:  # noqa: BLE001
            continue
        if not claimed:
            continue
        try:
            msg = MIMEText(r["body"] + "\n\n—\nTMPRO · Vergi Mevzuatı, Tek Ekranda\nhttps://tmpro.tmproapp.workers.dev", "plain", "utf-8")
            msg["Subject"] = r["subject"]
            msg["From"] = formataddr(("TMPRO", sender))
            msg["To"] = r["to_email"]
            msg["Date"] = formatdate(localtime=False)
            msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1])
            srv.sendmail(sender, [r["to_email"]], msg.as_string())
            ok += 1
        except Exception as e:  # noqa: BLE001
            db("PATCH", f"mail_queue?id=eq.{r['id']}", {"sent_at": None, "error": str(e)[:300]})
    srv.quit()
    print(f"Üye e-postası gönderildi: {ok}/{len(rows)}")

def db(method, path, body=None, prefer=None):
    headers = {"apikey": SUPABASE_KEY, "Content-Type": "application/json"}
    if SUPABASE_KEY.startswith("eyJ"):  # eski tip (JWT) anahtar
        headers["Authorization"] = f"Bearer {SUPABASE_KEY}"
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body).encode() if body is not None else None
    req = Request(f"{SUPABASE_URL}/rest/v1/{path}", data=data, headers=headers, method=method)
    with urlopen(req, timeout=60) as r:
        txt = r.read().decode()
        return json.loads(txt) if txt else None


def db_insert_items(rows):
    """Kayıtları items tablosuna ekler; zaten olanları atlar."""
    added = 0
    for i in range(0, len(rows), 500):
        chunk = [{k: r.get(k) for k in ("tur", "title", "meta", "url", "ozet", "eklendi")} for r in rows[i:i + 500]]
        res = db("POST", "items?on_conflict=tur,url,title", chunk,
                 prefer="resolution=ignore-duplicates,return=representation")
        added += len(res or [])
    print(f"Veritabanı: {added} yeni kayıt")


def migrate_feed():
    """Eski docs/feed.json arşivini veritabanına taşır."""
    with open(ARCHIVE_FILE, encoding="utf-8") as f:
        items = json.load(f)["items"]
    rows = [dict(r, eklendi=r.get("eklendi") or None) for r in reversed(items)]
    db_insert_items(rows)


def push_test():
    """Tüm kayıtlı cihazlara deneme bildirimi yollar."""
    from pywebpush import webpush, WebPushException
    vapid = db("GET", "private_settings?key=eq.vapid_private&select=value")[0]["value"]
    subs = db("GET", "push_subs?select=id,endpoint,p256dh,auth") or []
    payload = json.dumps({"title": "TMPRO", "body": "Bildirimler açık. Yeni mevzuat çıkınca buradan haber vereceğim.", "url": APP_URL, "tag": "tmpro-test"})
    for s in subs:
        try:
            webpush({"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}}, payload,
                    vapid_private_key=vapid, vapid_claims={"sub": "mailto:bildirim@tmpro.app"}, ttl=3600)
            print("Deneme bildirimi gönderildi:", s["endpoint"][:40])
        except WebPushException as e:
            print("Deneme bildirimi hatası:", getattr(e.response, "status_code", None), str(e)[:300])
    print(f"Cihaz sayısı: {len(subs)}")


def muted(u, k):
    """Üye bu bildirim türünü (ya da tümünü) şu an susturmuş mu?"""
    m = (u or {}).get("mute") or {}
    now = datetime.now(timezone.utc)
    for key in ("hepsi", k):
        try:
            if m.get(key) and datetime.fromisoformat(m[key]) > now:
                return True
        except ValueError:
            pass
    return False


def notify_users():
    """Aktif kullanıcılara son bildirimden beri eklenen kayıtlar için tek bir anlık bildirim yollar."""
    now = datetime.now(TR)
    if now.hour >= QUIET[0] or now.hour < QUIET[1]:
        print("Sessiz saatler, bildirim yok")
        return
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        print("pywebpush yok, bildirim atlanıyor")
        return
    key = db("GET", "private_settings?key=eq.vapid_private&select=value")
    if not key:
        print("VAPID anahtarı yok, bildirim atlanıyor")
        return
    vapid = key[0]["value"]
    subs = db("GET", "push_subs?select=id,user_id,endpoint,p256dh,auth")
    if not subs:
        return
    try:
        users = {u["id"]: u for u in db("GET", "profiles?select=id,role,status,expires_at,notify_types,last_notified_at,mute")}
    except Exception:  # noqa: BLE001  susturma sütunu henüz yok
        users = {u["id"]: u for u in db("GET", "profiles?select=id,role,status,expires_at,notify_types,last_notified_at")}
    by_user = {}
    for s in subs:
        by_user.setdefault(s["user_id"], []).append(s)
    utc_now = datetime.now(timezone.utc)
    for uid, usubs in by_user.items():
        u = users.get(uid)
        if not u:
            continue
        exp = u.get("expires_at")
        active = u["role"] == "admin" or (u["status"] == "active" and (not exp or datetime.fromisoformat(exp) > utc_now))
        if not active or not u.get("notify_types"):
            continue
        if muted(u, "mevzuat"):
            continue  # susturma bitince kaçırılanlar tek bildirimde gelir
        tlist = [t for t in u["notify_types"] if not muted(u, t)]
        if not tlist:
            continue
        since = u["last_notified_at"]
        types = ",".join('"' + t.replace('"', '') + '"' for t in tlist)
        new = db("GET", f"items?select=tur,title&created_at=gt.{quote(since)}&eklendi=not.is.null"
                        f"&tur=in.({quote(types)})&order=id.desc&limit=200")
        if not new:
            continue
        counts = {}
        for it in new:
            counts[it["tur"]] = counts.get(it["tur"], 0) + 1
        title = f"{len(new)} yeni kayıt" if len(new) > 1 else new[0]["tur"]
        body = (", ".join(f"{n} {t}" for t, n in counts.items()) + " · " + new[0]["title"]) if len(new) > 1 else new[0]["title"]
        payload = json.dumps({"title": title, "body": body[:180], "url": APP_URL, "tag": "tmpro-yeni"})
        for s in usubs:
            try:
                webpush({"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}}, payload,
                        vapid_private_key=vapid, vapid_claims={"sub": "mailto:bildirim@tmpro.app"}, ttl=86400)
            except WebPushException as e:
                code = getattr(e.response, "status_code", None)
                print(f"Bildirim hatası ({code})")
                if code in (404, 410):
                    db("DELETE", f"push_subs?id=eq.{s['id']}")
        db("PATCH", f"profiles?id=eq.{uid}", {"last_notified_at": utc_now.isoformat()})
        print(f"Bildirim: {uid[:8]} -> {len(new)} kayıt")


RELEASE_HOUR = 13  # yeni özellik duyuruları yalnızca bu saatte, günde en fazla bir kez


def release_push(state):
    """docs/surum.json'daki en yeni sürüm "bildir": true ise tüm aktif üyelere bir kez anlık bildirim yollar."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "surum.json"), encoding="utf-8") as f:
            rel = [r for r in json.load(f).get("surumler", []) if r.get("bildir")]
    except (FileNotFoundError, ValueError):
        return
    if not rel:
        return
    r = max(rel, key=lambda x: [int(n) if n.isdigit() else 0 for n in str(x["surum"]).split(".")])
    if state.get("release_notified") == r["surum"]:
        return
    now = datetime.now(TR)
    if now.hour != RELEASE_HOUR:
        print(f"Sürüm {r['surum']} bildirimi saat {RELEASE_HOUR}:00'te gönderilecek")
        return
    from pywebpush import webpush, WebPushException
    vapid = db("GET", "private_settings?key=eq.vapid_private&select=value")[0]["value"]
    try:
        users = {u["id"]: u for u in db("GET", "profiles?select=id,role,status,expires_at,mute")}
    except Exception:  # noqa: BLE001
        users = {u["id"]: u for u in db("GET", "profiles?select=id,role,status,expires_at")}
    utc_now = datetime.now(timezone.utc)
    body = r.get("baslik") or "Yeni özellikler eklendi."
    if r.get("yeniden_ekle"):
        body += " Bu sürüm için uygulamayı ana ekrana yeniden eklemeniz gerekiyor; dokunun, adımları gösterelim."
    else:
        body += " Yenilikleri görmek için uygulamayı arka plandan tamamen kapatıp yeniden açın ya da bu bildirime dokunun."
    payload = json.dumps({"title": f"TMPRO güncellendi · Sürüm {r['surum']}", "body": body[:220],
                          "url": APP_URL + "?yenilikler=1", "tag": "tmpro-surum"})
    sent = 0
    for s in db("GET", "push_subs?select=id,user_id,endpoint,p256dh,auth") or []:
        u = users.get(s["user_id"])
        exp = (u or {}).get("expires_at")
        if not u or not (u["role"] == "admin" or (u["status"] == "active" and (not exp or datetime.fromisoformat(exp) > utc_now))):
            continue
        if muted(u, "surum"):
            continue
        try:
            webpush({"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}}, payload,
                    vapid_private_key=vapid, vapid_claims={"sub": "mailto:bildirim@tmpro.app"}, ttl=86400)
            sent += 1
        except WebPushException as e:
            if getattr(e.response, "status_code", None) in (404, 410):
                db("DELETE", f"push_subs?id=eq.{s['id']}")
    state["release_notified"] = r["surum"]
    print(f"Sürüm {r['surum']} bildirimi: {sent} cihaz")


def ver_key(v):
    return [int(n) if n.isdigit() else 0 for n in str(v or "0").split(".")]


def version_remind(state):
    """Yeni sürüme geçmemiş (ya da yeni sürümle hiç açmamış) aktif üyelere, her sürüm için bir kez hatırlatma yollar.
    Duyurunun ertesi gününden itibaren, saat RELEASE_HOUR'da çalışır."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "surum.json"), encoding="utf-8") as f:
            rels = json.load(f).get("surumler", [])
    except (FileNotFoundError, ValueError):
        return
    if not rels:
        return
    r = max(rels, key=lambda x: ver_key(x["surum"]))
    latest, now = r["surum"], datetime.now(TR)
    if r.get("bildir") and state.get("release_notified") != latest:
        return  # önce duyuru gider
    days = state.setdefault("release_day", {})
    if r.get("bildir"):
        days.setdefault(latest, now.date().isoformat())
    ref = days.get(latest) or r.get("tarih") or now.date().isoformat()
    if now.date().isoformat() <= ref or now.hour != RELEASE_HOUR:
        return
    try:
        try:
            users = db("GET", "profiles?select=id,role,status,expires_at,app_version,version_reminded,mute")
        except Exception:  # noqa: BLE001
            users = db("GET", "profiles?select=id,role,status,expires_at,app_version,version_reminded")
    except Exception:  # noqa: BLE001  sütunlar henüz yok (surum_takip.sql çalıştırılmadı)
        print("Sürüm hatırlatması: kurulum bekleniyor")
        return
    utc_now = datetime.now(timezone.utc)
    targets = {}
    for u in users:
        exp = u.get("expires_at")
        if not (u["role"] == "admin" or (u["status"] == "active" and (not exp or datetime.fromisoformat(exp) > utc_now))):
            continue
        if ver_key(u.get("app_version")) >= ver_key(latest) or u.get("version_reminded") == latest or muted(u, "surum"):
            continue
        targets[u["id"]] = u
    if not targets:
        print("Sürüm hatırlatması: eski sürümde üye yok")
        return
    from pywebpush import webpush, WebPushException
    vapid = db("GET", "private_settings?key=eq.vapid_private&select=value")[0]["value"]
    payload = json.dumps({"title": f"TMPRO güncellendi · Sürüm {latest}",
                          "body": f"Hâlâ eski sürümü kullanıyorsunuz. {APP_URL.split('//')[-1].rstrip('/')} adresini tarayıcınızda "
                                  "(iPhone'da Safari, Android'de Chrome) açın ve ana ekrana yeniden ekleyin.",
                          "url": APP_URL + "?yenilikler=1", "tag": "tmpro-surum-hatirlat"})
    sent, done = 0, set()
    for s in db("GET", "push_subs?select=id,user_id,endpoint,p256dh,auth") or []:
        if s["user_id"] not in targets:
            continue
        try:
            webpush({"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}}, payload,
                    vapid_private_key=vapid, vapid_claims={"sub": "mailto:bildirim@tmpro.app"}, ttl=86400)
            sent += 1
            done.add(s["user_id"])
        except WebPushException as e:
            if getattr(e.response, "status_code", None) in (404, 410):
                db("DELETE", f"push_subs?id=eq.{s['id']}")
    for uid in targets:  # cihazı olmayan da bu sürüm için bir daha denenmez
        db("PATCH", f"profiles?id=eq.{uid}", {"version_reminded": latest})
    print(f"Sürüm hatırlatması ({latest}): {len(done)} üye, {sent} cihaz")


# ---------------------------------------------------------------- ana akış

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


ARCHIVE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "feed.json")


def archive_entries(new_oz=(), new_k=(), new_t=(), extra=(), seed=False):
    """Web uygulaması için kayıtları docs/feed.json arşivine ekler."""
    now = datetime.now(TR).isoformat(timespec="minutes")
    stamp = "" if seed else now
    rows = []
    for it in new_oz:
        rows.append({"tur": "Özelge", "title": it["title"], "meta": it["meta"], "url": it["url"], "ozet": it.get("ozet", "")})
    for t in new_t:
        rows.append({"tur": "Tebliğ", "title": t["title"], "meta": t["meta"], "url": t["url"], "ozet": ""})
    for k in new_k:
        rows.append({"tur": "Danıştay (VUK 359)", "title": f"Danıştay {k['daire']} E. {k['esas']}, K. {k['karar']}",
                     "meta": k["tarih"], "url": k.get("url", DANISTAY), "ozet": k.get("ozet", "")})
    labels = {"Kanunlar ve kanun değişiklikleri": "Kanun", "Sirküler": "Sirküler", "Cumhurbaşkanı kararları": "CB Kararı",
              "İç genelgeler": "İç Genelge", "Anayasa Mahkemesi kararları": "Anayasa Mahkemesi",
              "Resmî Gazete (vergiyle ilgili)": "Resmî Gazete"}
    for title, _short, items, _intro in extra:
        for i in items:
            rows.append({"tur": labels.get(title, title), "title": i["title"], "meta": i["meta"], "url": i["url"], "ozet": i.get("ozet", "")})
    if not rows or DRY:
        return
    if SUPABASE_URL:
        for r in rows:
            r["eklendi"] = None if seed else now
        db_insert_items(rows)
        return
    try:
        with open(ARCHIVE_FILE, encoding="utf-8") as f:
            feed = json.load(f)
    except (FileNotFoundError, ValueError):
        feed = {"items": []}
    known = {(r["tur"], r["url"], r["title"]) for r in feed["items"]}
    for r in rows:
        if (r["tur"], r["url"], r["title"]) not in known:
            r["eklendi"] = stamp
            if seed:
                feed["items"].append(r)
            else:
                feed["items"].insert(0, r)
    feed["items"] = feed["items"][:3000]
    feed["guncellendi"] = now
    os.makedirs(os.path.dirname(ARCHIVE_FILE), exist_ok=True)
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, indent=0)


def seed_archive():
    """Arşivi her kaynaktan son kayıtlarla doldurur (e-posta göndermez)."""
    oz = get_ozelgeler(50)
    tebs = sorted(get_tebligler_full(), key=lambda t: t["id"], reverse=True)[:40]
    kar = enrich_kararlar(get_kararlar()[:10])
    extra = []
    for key, path, title, date_key, no_key, link_tpl in GIB_LISTS:
        extra.append((title, "", get_gib_list(path, date_key, no_key, link_tpl), None))
    extra.append(("Anayasa Mahkemesi kararları", "", get_aym(), None))
    extra.append(("Resmî Gazete (vergiyle ilgili)", "", get_resmi_gazete(), None))
    # eskiden yeniye ekle ki en yeni en üstte kalsın
    archive_entries(oz, kar, tebs, extra, seed=True)
    print("Arşiv dolduruldu")


def save_state(state):
    if DRY:
        return
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
        f.write("\n")


def main():
    now = datetime.now(TR)
    today = now.strftime("%d.%m.%Y")
    state = load_state()

    if SEED:
        seed_archive()
        return
    if MIGRATE:
        migrate_feed()
        return
    if TEST_PUSH:
        push_test()
        return
    if DIAG:
        # Depo herkese açık: yalnızca sayılar yazdırılır, içerik/kimlik yazdırılmaz
        try:
            import haber
            haber.diag()
        except Exception as e:  # noqa: BLE001
            print("Haber teşhis hatası", type(e).__name__)
        def safe(q):
            try:
                return db("GET", q) or []
            except Exception as e:  # noqa: BLE001
                print("HATA", q.split("?")[0], getattr(e, "code", e))
                return []
        m = safe("messages?select=room,created_at&order=id.desc&limit=500")
        rooms = {}
        for r in m:
            k = "dm" if r["room"].startswith("dm:") else "grup" if r["room"].startswith("g:") else r["room"]
            rooms[k] = rooms.get(k, 0) + 1
        print("Mesaj sayısı (oda türüne göre):", rooms, "| son:", m[0]["created_at"] if m else "-")
        print("Grup:", len(safe("chat_groups?select=id")), "| grup üyeliği:", len(safe("chat_group_members?select=group_id")))
        st = {}
        for p in safe("profiles?select=role,status"):
            st[p["role"] + "/" + p["status"]] = st.get(p["role"] + "/" + p["status"], 0) + 1
        print("Profiller:", st, "| bildirim cihazı:", len(safe("push_subs?select=id")))
        # Özel mesajların tarafları (kimlik yazdırılmaz, yalnızca rol/durum)
        prof = {p["id"]: p for p in safe("profiles?select=id,role,status,chat_notify")}
        subs = {}
        for x in safe("push_subs?select=user_id"):
            subs[x.get("user_id")] = subs.get(x.get("user_id"), 0) + 1
        dmr = []
        for r in m:
            if r["room"].startswith("dm:") and r["room"] not in dmr:
                dmr.append(r["room"])
        for i, room in enumerate(dmr[:5], 1):
            side = []
            for uid in room.split(":")[1:]:
                pr = prof.get(uid)
                side.append(f"{pr['role']}/{pr['status']}/bildirim={pr.get('chat_notify')}/cihaz={subs.get(uid, 0)}" if pr else "PROFİL YOK")
            print(f"DM {i}: {len([x for x in m if x['room'] == room])} mesaj | taraflar: {side}")
        def count(q):
            try:
                req = Request(f"{SUPABASE_URL}/rest/v1/{q}&limit=1", headers={"apikey": SUPABASE_KEY, "Prefer": "count=exact",
                              **({"Authorization": f"Bearer {SUPABASE_KEY}"} if SUPABASE_KEY.startswith("eyJ") else {})})
                with urlopen(req, timeout=60) as r:
                    return r.headers.get("Content-Range", "").split("/")[-1]
            except Exception as e:  # noqa: BLE001
                return f"HATA {getattr(e, 'code', e)}"
        print("Kayıt:", count("items?select=id"), "| metin dolu:", count("items?select=id&metin=neq."),
              "| metin bekliyor:", count("items?select=id&metin=is.null"), "| not yazılmış:", count("items?select=id&yorum=not.is.null"),
              "| Yargıtay:", count("items?select=id&tur=eq." + quote("Yargıtay (Ceza)")),
              "| Yargıtay notsuz metinli:", count("items?select=id&yorum=is.null&metin=neq.&tur=eq." + quote("Yargıtay (Ceza)")))
        return

    # Özelgeler
    ozelgeler = [] if ONLY_RG else get_ozelgeler()
    if RESEND_KARAR:
        send(*build_mail([], enrich_kararlar(get_kararlar()[:5]), today, None, "VUK 359. maddeye değinen son Danıştay kararları:"))
        return
    if RESEND:
        send(*build_mail(ozelgeler[:10], [], today, "GİB'de yayımlanan son 10 özelge:"))
        return
    first_ozelge = "last_id" not in state
    last_id = state.get("last_id", 0)
    new_oz = [it for it in ozelgeler if it["id"] > last_id]
    kw = [k.strip().lower() for k in os.environ.get("KEYWORDS", "").split(",") if k.strip()]
    if kw:
        new_oz = [it for it in new_oz if any(k in (it["title"] + " " + it["ozet"]).lower() for k in kw)]
    if first_ozelge:
        new_oz = ozelgeler[:10]
    print(f"Özelge: son görülen {last_id}, yeni {len(new_oz)}")

    # Danıştay VUK 359 kararları (hata olursa özelgeleri engellemesin)
    new_k, karar_ids, karar_intro = [], None, None
    try:
        if ONLY_RG:
            raise LookupError("yalnızca Resmî Gazete turu")
        kararlar = get_kararlar()
        karar_ids = [k["id"] for k in kararlar]
        if "karar_seen" not in state:
            new_k = enrich_kararlar(kararlar[:5])
            karar_intro = "VUK 359 karar takibi başladı. Bundan sonra yeni kararlar geldikçe gönderilecek. En son yayımlanan kararlar:"
        else:
            seen = set(state["karar_seen"])
            new_k = enrich_kararlar([k for k in kararlar if k["id"] not in seen])
        print(f"Karar: listelenen {len(kararlar)}, gönderilecek {len(new_k)}")
    except Exception as e:  # noqa: BLE001
        print(f"Danıştay kararları alınamadı (sonraki saatte tekrar denenecek): {e}")

    # Tebliğler: her saat "son eklenenler", günde bir kez tam tarama
    new_t, teblig_max, teblig_intro = [], None, None
    try:
        if ONLY_RG:
            raise LookupError("yalnızca Resmî Gazete turu")
        last_t = state.get("last_teblig_id")
        full = last_t is None or (now.hour >= TEBLIG_FULL_HOUR and state.get("teblig_full_scan") != today)
        tebligler = get_tebligler_full() if full else get_tebligler_last_added()
        if full:
            state["teblig_full_scan"] = today
        tebligler.sort(key=lambda t: t["id"], reverse=True)
        if tebligler:
            teblig_max = tebligler[0]["id"]
        # Arşive sonradan eklenen eski tebliğleri (Resmî Gazete tarihi 90 günden eski) gönderme
        tebligler = [t for t in tebligler if t["rg"] is None or (now - t["rg"]).days <= 90]
        if last_t is None:
            new_t = tebligler[:3]
            teblig_intro = "Tebliğ takibi başladı. Bundan sonra yeni tebliğler geldikçe gönderilecek. En son yayımlanan tebliğler:"
        else:
            new_t = [t for t in tebligler if t["id"] > last_t]
        print(f"Tebliğ: {'tam tarama' if full else 'son eklenenler'}, listelenen {len(tebligler)}, yeni {len(new_t)}")
    except Exception as e:  # noqa: BLE001
        print(f"Tebliğler alınamadı (sonraki saatte tekrar denenecek): {e}")

    # Kanun, sirküler, Cumhurbaşkanı kararı, iç genelge
    SHORT = {"kanun": "kanun", "sirkuler": "sirküler", "cbk": "CB kararı", "icgenelge": "iç genelge"}
    extra, extra_max = [], {}
    for key, path, title, date_key, no_key, link_tpl in ([] if ONLY_RG else GIB_LISTS):
        try:
            items = get_gib_list(path, date_key, no_key, link_tpl)
        except Exception as e:  # noqa: BLE001
            print(f"{title} alınamadı: {e}")
            continue
        if not items:
            continue
        extra_max[key] = items[0]["id"]
        last = state.get(f"last_{key}_id")
        if last is None:
            new, intro = items[:2], "Takip başladı. En son yayımlananlar:"
        else:
            new, intro = [i for i in items if i["id"] > last], None
        print(f"{title}: yeni {len(new)}")
        extra.append((title, SHORT[key], new, intro))

    # Anayasa Mahkemesi ve Resmî Gazete (id kümesiyle takip)
    seen_sets = {}
    for key, title, short, fn in (("aym", "Anayasa Mahkemesi kararları", "AYM kararı", get_aym),
                                  ("rg", "Resmî Gazete (vergiyle ilgili)", "Resmî Gazete kaydı", get_resmi_gazete)):
        if ONLY_RG and key != "rg":
            continue
        try:
            items = fn()
        except Exception as e:  # noqa: BLE001
            print(f"{title} alınamadı: {e}")
            continue
        state_key = f"{key}_seen"
        if state_key not in state:
            new, intro = items[:3], "Takip başladı. En son yayımlananlar:"
        else:
            old = set(state[state_key])
            new, intro = [i for i in items if i["id"] not in old], None
        seen_sets[state_key] = [i["id"] for i in items]
        print(f"{title}: listelenen {len(items)}, yeni {len(new)}")
        extra.append((title, short, new, intro))

    # "Bugün özelge yok" bildirimi
    no_oz_intro = None
    if (not ONLY_RG and not new_oz and now.hour >= NO_OZELGE_HOUR
            and state.get("last_ozelge_mail") != today and state.get("no_ozelge_notice") != today):
        no_oz_intro = f"Bugün ({today}) GİB'de yeni yayımlanan özelge yok."

    if new_oz or new_k or no_oz_intro or new_t or any(e[2] for e in extra):
        oz_intro = ("Kurulum tamamlandı. GİB'deki son özelgeler:" if first_ozelge else None) if new_oz else no_oz_intro
        if MAIL_ENABLED:
            send(*build_mail(new_oz, new_k, today, oz_intro, karar_intro, new_t, teblig_intro, extra))
        archive_entries(new_oz, new_k, new_t, extra)
        if new_oz:
            state["last_ozelge_mail"] = today
        if no_oz_intro:
            state["no_ozelge_notice"] = today

    if ozelgeler:
        state["last_id"] = max(last_id, max(it["id"] for it in ozelgeler))
    for state_key, ids in seen_sets.items():
        state[state_key] = (state.get(state_key, []) + [i for i in ids if i not in state.get(state_key, [])])[-1000:]
    for key, mx in extra_max.items():
        state[f"last_{key}_id"] = max(state.get(f"last_{key}_id") or 0, mx)
    if teblig_max is not None:
        state["last_teblig_id"] = max(state.get("last_teblig_id") or 0, teblig_max)
    if karar_ids is not None:
        state["karar_seen"] = sorted(set(state.get("karar_seen", [])) | set(karar_ids))[-2000:]
    save_state(state)
    if SUPABASE_URL and not DRY:
        try:
            notify_users()
        except Exception as e:  # noqa: BLE001
            print(f"Bildirim gönderilemedi: {e}")
        try:
            release_push(state)
            save_state(state)
        except Exception as e:  # noqa: BLE001
            print(f"Sürüm bildirimi gönderilemedi: {type(e).__name__}")
        try:
            version_remind(state)
            save_state(state)
        except Exception as e:  # noqa: BLE001
            print(f"Sürüm hatırlatması gönderilemedi: {type(e).__name__}")
        try:
            import haftalik
            haftalik.run(db, state, test="--weekly-test" in sys.argv, muted=muted)
            save_state(state)
        except Exception as e:  # noqa: BLE001
            print(f"Haftalık özet gönderilemedi: {type(e).__name__}")
        try:
            send_member_mails()
        except Exception as e:  # noqa: BLE001
            print(f"Üye e-postaları gönderilemedi: {str(e)[:200]}")


if __name__ == "__main__":
    main()
    if SUPABASE_URL and not DRY and not (SEED or MIGRATE or TEST_PUSH or DIAG or RESEND or RESEND_KARAR):
        try:
            import metin
            lim = int(os.environ.get("METIN_LIMIT") or 15)
            metin.fill(db, limit=lim, budget=max(150, lim * 5))
        except Exception as e:  # noqa: BLE001
            print(f"Tam metin turu atlandı: {type(e).__name__} {getattr(e, 'code', '')}")
        hour = datetime.now(TR).hour
        if not (hour >= QUIET[0] or hour < QUIET[1]):  # gece eşleşmeler sabah toplu bildirilir
            try:
                print(f"Takip listesi: {db('POST', 'rpc/run_watch', {})} yeni eşleşme")
            except Exception as e:  # noqa: BLE001
                print(f"Takip listesi turu atlandı: {type(e).__name__} {getattr(e, 'code', '')}")
        nt = datetime.now(TR)
        busy = nt.weekday() < 5 and 8 <= nt.hour < 19  # bu saatlerde tarama 5 dakikada bir, dışında saatlik
        if not busy or nt.minute % 15 < 5 or "--news" in sys.argv or (os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch" and not os.environ.get("TMPRO_AUTO")):
            try:
                import haber
                haber.run(db)
            except Exception as e:  # noqa: BLE001
                detail = ""
                try:
                    detail = json.loads(e.read().decode()).get("message", "")[:160]  # PostgREST hata metni (kullanıcı verisi içermez)
                except Exception:  # noqa: BLE001
                    pass
                print(f"Haber turu atlandı: {type(e).__name__} {getattr(e, 'code', '')} {detail}")
        try:
            import yorum
            yorum.fill(db)
        except Exception as e:  # noqa: BLE001
            print(f"Müfettiş notu turu atlandı: {type(e).__name__} {getattr(e, 'code', '')}")
