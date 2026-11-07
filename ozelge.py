#!/usr/bin/env python3
"""GİB'de yeni yayımlanan özelgeleri bulur ve e-postayla gönderir.

Ortam değişkenleri:
  MAIL_TO      alıcı adres(ler), virgülle ayrılmış
  SMTP_HOST    örn. smtp.gmail.com
  SMTP_PORT    örn. 465 (SSL) veya 587 (STARTTLS)
  SMTP_USER    gönderen hesap
  SMTP_PASS    uygulama şifresi
  MAIL_FROM    (isteğe bağlı) gönderen adres, varsayılan SMTP_USER
  KEYWORDS     (isteğe bağlı) virgülle ayrılmış konu filtresi, örn. "KDV,gelir vergisi"
Kullanım:
  python ozelge.py            # yenileri bul, gönder, seen.json'u güncelle
  python ozelge.py --dry-run  # gönderme, sadece yazdır
  python ozelge.py --debug    # ham yanıtları debug/ klasörüne kaydet
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
from urllib.parse import urljoin
from urllib.request import Request, urlopen

BASE = "https://www.gib.gov.tr"
# Denenecek kaynaklar: önce JSON API'ler, sonra HTML sayfaları.
SOURCES = [
    "https://gib.gov.tr/api/gibportal/mevzuat/ozelge/list?page=0&size=50&sortFieldName=id&sortType=DESC",
    "https://www.gib.gov.tr/api/gibportal/mevzuat/ozelge/list?page=0&size=50",
    "https://www.gib.gov.tr/ozelgeler",
    "https://www.gib.gov.tr/mevzuat/tur/ozelgeler",
    "https://www.gib.gov.tr/mevzuat/ozelgeler",
]
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen.json")
TR = timezone(timedelta(hours=3))
UA = "Mozilla/5.0 (X11; Linux x86_64) ozelge-bildirim/1.0"
DEBUG = "--debug" in sys.argv
DRY = "--dry-run" in sys.argv or not os.environ.get("SMTP_PASS")

TITLE_KEYS = ("baslik", "title", "konu", "ozet", "name", "adi", "aciklama")
DATE_KEYS = ("tarih", "date", "yayimTarihi", "yayinTarihi", "ozelgeTarihi", "createdDate", "kayitTarihi")
ID_KEYS = ("id", "sayi", "ozelgeSayisi", "no", "slug", "uuid")
URL_KEYS = ("url", "link", "path", "slug")


def fetch(url):
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json, text/html;q=0.9"})
    with urlopen(req, timeout=60) as r:
        raw = r.read()
        ctype = r.headers.get("Content-Type", "")
    text = raw.decode("utf-8", errors="replace")
    if DEBUG:
        os.makedirs("debug", exist_ok=True)
        name = re.sub(r"[^A-Za-z0-9]+", "_", url)[-80:]
        with open(os.path.join("debug", name + ".txt"), "w", encoding="utf-8") as f:
            f.write(f"URL: {url}\nContent-Type: {ctype}\n\n{text}")
    return text, ctype


def pick(d, keys):
    lower = {k.lower(): v for k, v in d.items()}
    for k in keys:
        v = lower.get(k.lower())
        if v not in (None, "", []):
            return v
    return None


def walk_lists(obj):
    """JSON içindeki sözlük listelerini (özelge kayıtları adayları) bulur."""
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj):
            yield obj
        for x in obj:
            yield from walk_lists(x)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from walk_lists(v)


def items_from_json(data, source_url):
    best = []
    for lst in walk_lists(data):
        items = []
        for d in lst:
            title = pick(d, TITLE_KEYS)
            if not isinstance(title, str):
                continue
            ident = pick(d, ID_KEYS)
            date = pick(d, DATE_KEYS)
            link = pick(d, URL_KEYS)
            if isinstance(link, str) and not link.startswith("http"):
                link = urljoin(BASE + "/", link.lstrip("/")) if "/" in link else f"{BASE}/ozelge/{link}"
            elif not link and ident is not None:
                link = f"{BASE}/ozelgeler"
            items.append({
                "id": str(ident if ident is not None else title),
                "title": strip_tags(title),
                "date": str(date or ""),
                "url": link or f"{BASE}/ozelgeler",
            })
        if len(items) > len(best):
            best = items
    return best


def strip_tags(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def items_from_html(text, source_url):
    # Next.js sayfaları veriyi __NEXT_DATA__ içinde gömer.
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', text, re.S)
    if m:
        try:
            got = items_from_json(json.loads(m.group(1)), source_url)
            if got:
                return got
        except ValueError:
            pass
    items, seen = [], set()
    for href, inner in re.findall(r'<a[^>]+href="([^"]*ozelge[^"]*)"[^>]*>(.*?)</a>', text, re.S | re.I):
        url = urljoin(source_url, html.unescape(href))
        title = strip_tags(inner)
        if len(title) < 15 or url in seen or url.rstrip("/").endswith(("ozelgeler", "ozelge")):
            continue
        seen.add(url)
        items.append({"id": url, "title": title, "date": "", "url": url})
    return items


def get_items():
    errors = []
    for url in SOURCES:
        try:
            text, ctype = fetch(url)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{url}: {e}")
            continue
        try:
            items = items_from_json(json.loads(text), url)
        except ValueError:
            items = items_from_html(text, url)
        print(f"{url}: {len(items)} kayıt")
        if items:
            return items
        errors.append(f"{url}: kayıt bulunamadı")
    raise RuntimeError("Hiçbir kaynaktan özelge alınamadı:\n" + "\n".join(errors))


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def save_state(ids):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(ids)[-5000:], f, ensure_ascii=False, indent=0)


def build_mail(items, first_run):
    today = datetime.now(TR).strftime("%d.%m.%Y")
    if first_run:
        subject = f"Özelge bildirimi kuruldu ({today})"
        intro = "Kurulum tamamlandı. Bundan sonra her gün yeni özelgeler gelecek. GİB'deki son özelgeler:"
    else:
        subject = f"{len(items)} yeni özelge ({today})"
        intro = f"GİB'de yayımlanan {len(items)} yeni özelge:"
    rows_txt, rows_html = [], []
    for it in items:
        date = f" ({it['date'][:10]})" if it["date"] else ""
        rows_txt.append(f"- {it['title']}{date}\n  {it['url']}")
        rows_html.append(
            f'<li style="margin-bottom:10px"><a href="{html.escape(it["url"])}">{html.escape(it["title"])}</a>'
            f'<span style="color:#666">{html.escape(date)}</span></li>'
        )
    text = intro + "\n\n" + "\n".join(rows_txt)
    body = f'<p>{html.escape(intro)}</p><ul>{"".join(rows_html)}</ul>'
    return subject, text, body


def send(subject, text, body):
    to = [a.strip() for a in os.environ["MAIL_TO"].split(",") if a.strip()]
    user = os.environ["SMTP_USER"]
    sender = os.environ.get("MAIL_FROM") or user
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, f"Özelge Bildirimi <{sender}>", ", ".join(to)
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(body, "html", "utf-8"))
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
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
    seen = set(state or [])
    new = [it for it in items if it["id"] not in seen]
    kw = [k.strip().lower() for k in os.environ.get("KEYWORDS", "").split(",") if k.strip()]
    if kw:
        new = [it for it in new if any(k in it["title"].lower() for k in kw)]
    to_send = items[:10] if first_run else new
    print(f"Toplam {len(items)}, yeni {len(new)}, ilk çalışma: {first_run}")
    if to_send:
        subject, text, body = build_mail(to_send, first_run)
        if DRY:
            print(subject + "\n" + text)
        else:
            send(subject, text, body)
    if not DRY:
        save_state(seen | {it["id"] for it in items})


if __name__ == "__main__":
    main()
