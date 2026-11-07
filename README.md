# Günlük özelge bildirimi

Her sabah 08:00'de (Türkiye) GİB'de yeni yayımlanan özelgeleri kontrol eder ve e-postayla gönderir.

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

Elle çalıştırmak için: **Actions → Günlük özelge bildirimi → Run workflow**.
İlk çalışmada kurulum e-postası ve son 10 özelge gelir; sonrasında sadece yeniler.
