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
DRY = "--dry-run" in sys.argv or not os.environ.get("SMTP_PASS")
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


def karar_snippet(karar_id):
    """Kararın 359. maddeye değinen kısmını döndürür; değinmiyorsa None."""
    raw = http(f"{DANISTAY}/getDokuman?id={karar_id}&arananKelime={quote(','.join(DANISTAY_WORDS))}", timeout=90)
    try:
        raw = json.loads(raw).get("data") or raw
    except ValueError:
        pass
    text = strip_tags(html.unescape(raw))
    m = MADDE_359.search(text)
    if not m:
        return None
    start = max(0, text.rfind(".", 0, max(0, m.start() - 200)) + 1)
    snippet = text[start:m.end() + 250].strip()
    return snippet[:450] + ("…" if len(snippet) > 450 else "")


def enrich_kararlar(kararlar):
    out = []
    for k in kararlar:
        try:
            snip = karar_snippet(k["id"])
        except Exception as e:  # noqa: BLE001
            print(f"Karar {k['id']} okunamadı: {e}")
            snip = ""
        if snip is None:
            print(f"Karar {k['id']} 359. maddeye değinmiyor, atlandı")
            continue
        k["ozet"] = snip
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
        f'<span style="font-size:13px">{html.escape(k.get("ozet", ""))}</span></li>' for k in items)


def ozelge_txt(items):
    return "\n\n".join(f"- {it['title']}\n  {it['meta']}\n  {it['url']}" for it in items)


def karar_txt(items):
    return "\n\n".join(
        f"- Danıştay {k['daire']} · E. {k['esas']}, K. {k['karar']} · {k['tarih']}\n  {k.get('ozet', '')}" for k in items)


def build_mail(ozelgeler, kararlar, today, ozelge_intro=None, karar_intro=None):
    parts_subject, html_parts, txt_parts = [], [], []
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
    subject = "COSKUNS NEWS - OZELGE | " + subject[:1].upper() + subject[1:] + f" ({today})"
    body = ('<div style="font-family:Arial,sans-serif;max-width:680px">' + "".join(html_parts)
            + '<p style="color:#999;font-size:12px">Kaynak: gib.gov.tr özelgeler, karararama.danistay.gov.tr</p></div>')
    return subject, "\n\n".join(txt_parts), body


def send(subject, text, body):
    if DRY:
        print("(e-posta gönderilmedi, deneme modu)\n" + subject + "\n\n" + text)
        return
    to = [a.strip() for a in os.environ["MAIL_TO"].split(",") if a.strip()]
    user = os.environ["SMTP_USER"]
    sender = os.environ.get("MAIL_FROM") or user
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr(("Özelge Bildirimi", sender))
    msg["To"] = ", ".join(to)
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1])
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(body, "html", "utf-8"))
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


# ---------------------------------------------------------------- ana akış

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_state(state):
    if DRY:
        return
    state["updated"] = datetime.now(TR).isoformat(timespec="seconds")
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
        f.write("\n")


def main():
    now = datetime.now(TR)
    today = now.strftime("%d.%m.%Y")
    state = load_state()

    # Özelgeler
    ozelgeler = get_ozelgeler()
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

    # "Bugün özelge yok" bildirimi
    no_oz_intro = None
    if (not new_oz and now.hour >= NO_OZELGE_HOUR
            and state.get("last_ozelge_mail") != today and state.get("no_ozelge_notice") != today):
        no_oz_intro = f"Bugün ({today}) GİB'de yeni yayımlanan özelge yok."

    if new_oz or new_k or no_oz_intro:
        oz_intro = ("Kurulum tamamlandı. GİB'deki son özelgeler:" if first_ozelge else None) if new_oz else no_oz_intro
        subject, text, body = build_mail(new_oz, new_k, today, oz_intro, karar_intro)
        send(subject, text, body)
        if new_oz:
            state["last_ozelge_mail"] = today
        if no_oz_intro:
            state["no_ozelge_notice"] = today

    if ozelgeler:
        state["last_id"] = max(last_id, max(it["id"] for it in ozelgeler))
    if karar_ids is not None:
        state["karar_seen"] = sorted(set(state.get("karar_seen", [])) | set(karar_ids))[-2000:]
    save_state(state)


if __name__ == "__main__":
    main()
