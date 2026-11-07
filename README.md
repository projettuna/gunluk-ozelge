# Günlük özelge bildirimi

Her saat GİB'de yeni yayımlanan özelge ve tebliğleri ve VUK 359. maddeye değinen yeni Danıştay kararlarını kontrol eder; yeni bir şey varsa hemen e-postayla gönderir. Gün içinde özelge çıkmazsa 18:00'den sonra "bugün yeni özelge yok" maili atar.

## Kurulum
Depoda **Settings → Secrets and variables → Actions → New repository secret** ile şunları ekleyin:

| Ad | Değer |
|---|---|
| `MAIL_TO` | alıcı adres |
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `465` |
| `SMTP_USER` | gönderen Gmail adresi |
| `SMTP_PASS` | Gmail uygulama şifresi (myaccount.google.com/apppasswords) |

Konu filtresi için (isteğe bağlı) **Variables** sekmesine `KEYWORDS` ekleyin, örn. `KDV,gelir vergisi`.

Elle çalıştırmak için: **Actions → Özelge bildirimi → Run workflow**.
Durum `seen.json` dosyasında tutulur.
