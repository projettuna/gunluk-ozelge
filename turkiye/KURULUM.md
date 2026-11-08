# Türkiye sunucusu: Yargıtay ceza kararları

Yargıtay karar arama sitesi yurt dışından gelen bağlantıları kabul etmiyor. Bu yüzden
`yargitay.py` Türkiye'de duran bir makinede çalışır ve bulduğu kararları TMPRO'ya gönderir.
Bildirimler mevcut düzenle (5 dakikalık tarama) otomatik gider.

## 1. Makine seçimi
- **Önerilen:** Türkiye lokasyonlu en küçük Linux VPS/VDS (1 çekirdek, 1 GB RAM yeterli,
  Ubuntu 22.04 veya 24.04). Türk hosting firmalarının İstanbul lokasyonlu paketleri uygundur.
- **Alternatif:** Evde sürekli açık duran bir bilgisayar veya Raspberry Pi (elektrik/internet
  kesilince tarama durur).
- Hizmeti Merve'nin adına almayın (657 DMK md. 28).

## 2. Kurulum (Ubuntu, sunucuya SSH ile bağlandıktan sonra)
```bash
sudo apt update && sudo apt install -y python3 curl
sudo useradd -m tmpro && sudo -iu tmpro
mkdir -p ~/tmpro && cd ~/tmpro
curl -fsSLO https://tmpro.tmproapp.workers.dev/turkiye/yargitay.py   # ya da dosyayı elle kopyalayın
```
`~/tmpro/.env` dosyasını oluşturun (değerleri aşağıda anlatıldığı gibi doldurun):
```bash
cat > ~/tmpro/.env <<'X'
export TMPRO_SUPABASE_URL="https://hnolhapzcisavhkwyzhs.supabase.co"
export TMPRO_ANON_KEY="docs/config.js içindeki supabaseAnonKey"
export TMPRO_INGEST_TOKEN="Supabase'ten alınan gizli anahtar"
X
chmod 600 ~/tmpro/.env
```
Gizli anahtarı Supabase → SQL Editor'de şu sorguyla görün ve yalnızca bu dosyaya yazın:
```sql
select value from private_settings where key = 'ingest_token';
```

## 3. Deneme ve ilk yükleme
```bash
cd ~/tmpro && . ./.env
python3 yargitay.py --test   # "… sonuç, … ceza dairesi" satırları görünmeli
python3 yargitay.py --seed   # eski kararları bildirimsiz yükler
```

## 4. Otomatik çalıştırma
`crontab -e` ile ekleyin (hafta içi 08–20 arası 30 dakikada bir, diğer zamanlar 3 saatte bir):
```
*/30 8-20 * * 1-5 cd ~/tmpro && . ./.env && python3 yargitay.py >> log.txt 2>&1
0 */3 * * 0,6 cd ~/tmpro && . ./.env && python3 yargitay.py >> log.txt 2>&1
```

## Güvenlik
- Sunucuda yalnızca herkese açık anahtar ve tek işi Yargıtay kaydı eklemek olan gizli anahtar
  bulunur; veritabanının yönetici anahtarı sunucuya konmaz.
- Anahtar ele geçerse Supabase'te yenileyin:
  `update private_settings set value = encode(extensions.gen_random_bytes(24),'hex') where key = 'ingest_token';`
- Betik siteyi yormamak için istekler arasında bekler; sıklığı artırmayın.
