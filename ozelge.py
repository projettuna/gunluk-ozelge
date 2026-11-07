#!/usr/bin/env python3
"""GİB'de yeni yayımlanan özelgeleri bulur ve e-postayla gönderir.

Ortam değişkenleri:
  MAIL_TO      alıcı adres(ler), virgülle ayrılmış
  SMTP_HOST    örn. smtp.gmail.com
  SMTP_PORT    örn. 465 (SSL) veya 587 (STARTTLS)
  SMTP_USER    gönderen hesap
  SMTP_PASS    uygulama şifresi (yoksa e-posta gönderilmez, sadece ekrana yazılır)
  MAIL_FROM    (isteğe bağlı) gönderen adres, varsayılan SMTP_USER
  KEYWORDS     (isteğe bağlı) virgülle ayrılmış konu filtresi, örn. "KDV,gelir vergisi"
Kullanım:
  python ozelge.py            # yenileri bul, gönder, seen.json'u güncelle
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
from urllib.request import Request, urlopen

API = "https://gib.gov.tr/api/gibportal/mevzuat/ozelge/list?page=0&size={size}&sortFieldName=id&sortType=DESC"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen.json")
TR = timezone(timedelta(hours=3))
UA = "Mozilla/5.0 (X11; Linux x86_64) ozelge-bildirim/1.0"
DRY = "--dry-run" in sys.argv or not os.environ.get("SMTP_PASS")


def strip_tags(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def get_items(size=50):
    req = Request(
        API.format(size=size),
        data=b"{}",
        headers={"User-Agent": UA, "Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode("utf-8"))
    items = []
    for rec in data["resultContainer"]["content"]:
        if rec.get("deleted"):
            continue
        text = strip_tags(rec.get("description"))
        sayi = re.search(r"Sayı\s*:\s*(\S+)", text)
        tarih = re.search(r"Sayı\s*:\s*\S+\s+(\d{2}\.\d{2}\.\d{4})", text)
        konu = re.search(r"Konu\s*:\s*(.+?)(?:\s*\*{3,}|\s+İlgi\s*:|$)", text)
        ilgi = text.find("İlgi")
        ozet = text[ilgi:] if ilgi >= 0 else text
        ozet = re.sub(r"^İlgi\s*:\s*", "", ozet)
        items.append({
            "id": int(rec["id"]),
            "title": strip_tags(rec.get("title")) or (konu.group(1) if konu else "Başlıksız özelge"),
            "sayi": sayi.group(1) if sayi else "",
            "tarih": tarih.group(1) if tarih else "",
            "url": rec.get("siteLink") or f"https://gib.gov.tr/mevzuat/ozelge/{rec['id']}",
            "ozet": (ozet[:280] + "…") if len(ozet) > 280 else ozet,
        })
    return items


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def save_state(last_id):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_id": last_id, "updated": datetime.now(TR).isoformat(timespec="seconds")}, f)
        f.write("\n")


def build_mail(items, first_run):
    today = datetime.now(TR).strftime("%d.%m.%Y")
    if first_run:
        subject = f"Özelge bildirimi kuruldu ({today})"
        intro = "Kurulum tamamlandı. Bundan sonra her sabah yeni yayımlanan özelgeler bu adrese gelecek. GİB'deki son özelgeler:"
    else:
        subject = f"{len(items)} yeni özelge ({today})"
        intro = f"GİB'de dünden bu yana yayımlanan {len(items)} yeni özelge:"
    rows_txt, rows_html = [], []
    for it in items:
        meta = " · ".join(x for x in (it["tarih"], it["sayi"]) if x)
        rows_txt.append(f"- {it['title']}\n  {meta}\n  {it['url']}")
        rows_html.append(
            '<li style="margin-bottom:16px">'
            f'<a href="{html.escape(it["url"])}" style="font-weight:bold">{html.escape(it["title"])}</a><br>'
            f'<span style="color:#666;font-size:13px">{html.escape(meta)}</span><br>'
            f'<span style="font-size:13px">{html.escape(it["ozet"])}</span></li>'
        )
    text = intro + "\n\n" + "\n\n".join(rows_txt)
    body = (f'<div style="font-family:Arial,sans-serif;max-width:680px"><p>{html.escape(intro)}</p>'
            f'<ul style="padding-left:18px">{"".join(rows_html)}</ul>'
            '<p style="color:#999;font-size:12px">Kaynak: gib.gov.tr özelgeler</p></div>')
    return subject, text, body


def send(subject, text, body):
    to = [a.strip() for a in os.environ["MAIL_TO"].split(",") if a.strip()]
    user = os.environ["SMTP_USER"]
    sender = os.environ.get("MAIL_FROM") or user
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, f"Özelge Bildirimi <{sender}>", ", ".join(to)
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
    print(f"E-posta gönderildi: {subject} -> {to}")


def main():
    items = get_items()
    state = load_state()
    first_run = state is None
    last_id = (state or {}).get("last_id", 0)
    new = [it for it in items if it["id"] > last_id]
    kw = [k.strip().lower() for k in os.environ.get("KEYWORDS", "").split(",") if k.strip()]
    if kw:
        new = [it for it in new if any(k in (it["title"] + " " + it["ozet"]).lower() for k in kw)]
    to_send = items[:10] if first_run else new
    print(f"Listelenen {len(items)}, son görülen id {last_id}, yeni {len(new)}, ilk çalışma: {first_run}")
    if to_send:
        subject, text, body = build_mail(to_send, first_run)
        if DRY:
            print("(e-posta gönderilmedi, deneme modu)\n" + subject + "\n\n" + text)
        else:
            send(subject, text, body)
    if not DRY and items:
        save_state(max(last_id, max(it["id"] for it in items)))


if __name__ == "__main__":
    main()
