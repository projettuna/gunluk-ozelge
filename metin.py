"""Kayıtların tam metnini kaynağından çekip veritabanına (items.metin) yazar.

Metin düz yazı olarak saklanır (paragraflar satır sonuyla ayrılır). Metni alınamayan
kayıtlara boş metin yazılır, böylece her turda yeniden denenmez; kaynak linki kalır.
"""
import html
import io
import json
import re
import time
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
GIB_FIND = "https://gib.gov.tr/api/gibportal/mevzuat/{path}/findById?id={id}"
GIB_PATHS = {"ozelge": "ozelge", "teblig": "teblig", "sirkuler": "sirkuler", "icgenelge": "icGenelge", "cbk": "cbk"}
MAX_LEN = 400_000


def fetch(url, timeout=60):
    req = Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urlopen(req, timeout=timeout) as r:
        raw = r.read(60_000_000)
        ctype = r.headers.get("Content-Type", "")
    return raw, ctype


def decode(raw, ctype=""):
    m = re.search(r"charset=([\w-]+)", ctype, re.I) or re.search(rb'charset=["\']?([\w-]+)', raw[:3000], re.I)
    cs = (m.group(1).decode() if isinstance(m.group(1), bytes) else m.group(1)) if m else "utf-8"
    try:
        return raw.decode(cs, "replace")
    except LookupError:
        return raw.decode("utf-8", "replace")


def html_to_text(s):
    s = re.sub(r"<(script|style|head)[^>]*>.*?</\1>", " ", s or "", flags=re.S | re.I)
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    s = re.sub(r"\s+", " ", s)  # kaynaktaki satır sonları anlam taşımaz
    # Tablo satırını tek satıra indir: "Sayı : E-123" gibi alanlar bölünmesin
    # (Resmî Gazete gibi tüm sayfayı tabloya koyan kaynaklarda uzun satırlara dokunulmaz)
    s = re.sub(r"<tr[^>]*>(?:(?!<tr|<table).)*?</tr>", lambda m: m.group(0) if len(m.group(0)) > 1500 else re.sub(r"</?(p|div|br|span)[^>]*>", " ", m.group(0), flags=re.I), s, flags=re.S | re.I)
    s = re.sub(r"</t[dh]>", "  ", s, flags=re.I)
    s = re.sub(r"</tr>", "\n", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</(p|div|li|h\d|table|blockquote|ul|ol)>|<(p|div|li|h\d|table)[\s>]", lambda m: "\n\n" + (m.group(0) if m.group(0).startswith("<") and not m.group(0).startswith("</") else ""), s, flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in s.split("\n")]
    out, blank = [], False
    for ln in lines:
        if ln:
            out.append(ln)
            blank = False
        elif not blank and out:
            out.append("")
            blank = True
    return "\n".join(out).strip()


def pdf_to_text(raw):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(raw))
    pages = [(p.extract_text() or "") for p in reader.pages[:120]]
    txt = "\n\n".join(pages)
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


def gib_text(path, id_):
    d = json.loads(decode(*fetch(GIB_FIND.format(path=path, id=id_))))["resultContainer"]
    desc = d.get("description") or ""
    txt = html_to_text(desc)
    if len(txt) >= 120:
        return txt
    # Metin yerine dosya bağlantısı varsa (ör. CB kararları) PDF'i oku
    files = d.get("fileNames") or []
    m = re.search(r'href="([^"]+\.pdf)"', desc)
    url = m.group(1) if m else (f"https://cdn.gib.gov.tr/api/gibportal-file/file/getFile?objectKey={files[0]}" if files else "")
    txt = pdf_to_text(fetch(url)[0]) if url else ""
    return txt if len(txt) >= 300 else ""  # taranmış (resim) PDF


def kanun_text(meta):
    """Kanunun Resmî Gazete'de yayımlandığı sayfayı bulur (ilk birkaç .htm)."""
    no = re.search(r"Kanun No:\s*(\d+)", meta or "")
    d = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", meta or "")
    if not (no and d):
        return ""
    day = f"{d.group(3)}{d.group(2)}{d.group(1)}"
    for n in range(1, 6):
        try:
            raw, ctype = fetch(f"https://www.resmigazete.gov.tr/eskiler/{d.group(3)}/{d.group(2)}/{day}-{n}.htm")
        except Exception:  # noqa: BLE001
            continue
        txt = html_to_text(decode(raw, ctype))
        if re.search(rf"Kanun\s*No\.?\s*:?\s*{no.group(1)}\b", txt, re.I):
            return txt
    return ""


def danistay_text(url):
    raw = decode(*fetch(url, timeout=90))
    try:
        raw = json.loads(raw).get("data") or raw
    except ValueError:
        pass
    inner = re.search(r"&lt;html.*?&lt;/html&gt;", raw, re.S | re.I)
    return html_to_text(html.unescape(inner.group(0)) if inner else raw)


def text_for(item):
    url, tur = item.get("url") or "", item.get("tur") or ""
    u = urlparse(url)
    if "danistay.gov.tr" in u.netloc and "getDokuman" in u.path:
        return danistay_text(url)
    if u.netloc.endswith("gib.gov.tr"):
        parts = [p for p in u.path.split("/") if p]
        if tur == "Kanun" or (len(parts) >= 3 and parts[-2] == "kanun"):
            return kanun_text(item.get("meta"))
        for i in range(len(parts) - 1, 0, -1):
            if parts[i - 1].lower() in GIB_PATHS and parts[i].isdigit():
                return gib_text(GIB_PATHS[parts[i - 1].lower()], parts[i])
        return ""
    if "resmigazete.gov.tr" in u.netloc:
        raw, ctype = fetch(url)
        if raw[:4] == b"%PDF":
            return pdf_to_text(raw) if len(raw) < 8_000_000 else ""
        return html_to_text(decode(raw, ctype))
    return ""  # Anayasa Mahkemesi vb.: sayfa betikle yükleniyor, metin alınamıyor


def fill(db, limit=15, budget=150):
    """Metni olmayan kayıtları doldurur. Depo herkese açık: içerik yazdırılmaz."""
    rows = db("GET", f"items?select=id,tur,url,meta&metin=is.null&order=id.desc&limit={limit}") or []
    start, ok, empty = time.time(), 0, 0
    for r in rows:
        if time.time() - start > budget:
            break
        try:
            txt = text_for(r)[:MAX_LEN]
        except Exception as e:  # noqa: BLE001
            print(f"Metin alınamadı ({r['tur']} #{r['id']}): {type(e).__name__}")
            txt = None if "HTTP Error 429" in str(e) or "timed out" in str(e) else ""
        if txt is None:
            continue
        db("PATCH", f"items?id=eq.{r['id']}", {"metin": txt}, prefer="return=minimal")
        ok += bool(txt)
        empty += not txt
        if "danistay" in (r.get("url") or ""):
            time.sleep(2)
    print(f"Tam metin: {ok} kayıt dolduruldu, {empty} kayıtta metin yok, bekleyen sorgusu {len(rows)}")


if __name__ == "__main__":
    # Deneme: python metin.py <url> [tür] [meta]  → yalnızca uzunluk ve ilk satırlar
    import sys
    t = text_for({"url": sys.argv[1], "tur": sys.argv[2] if len(sys.argv) > 2 else "", "meta": sys.argv[3] if len(sys.argv) > 3 else ""})
    print(len(t))
    print(t[:600])
