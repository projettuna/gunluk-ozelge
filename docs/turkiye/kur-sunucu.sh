#!/bin/bash
# TMPRO · Yargıtay toplayıcı, Linux sunucu (VDS/VPS) kurulumu. Tekrar çalıştırılabilir.
# Kullanım (root veya sudo ile):
#   curl -fsSL https://tmpro.tmproapp.workers.dev/turkiye/kur-sunucu.sh | sudo bash -s GIZLI_ANAHTAR
# Kendi kullanıcısında (tmpro) ve klasöründe çalışır; web sunucusuna, portlara ve diğer
# projelere dokunmaz. Saatte bir birkaç dakika, en düşük öncelikle (nice 19) çalışır.
SITE=https://tmpro.tmproapp.workers.dev/turkiye
TOKEN="$1"
U=tmpro
D=/home/$U/tmpro
hata() { echo; echo "HATA: $*"; exit 1; }
adim() { echo "• $*"; }

[ "$(id -u)" = 0 ] || hata "root olarak (sudo ile) çalıştırın"

adim "Gerekli programlar (yalnız eksik olan kurulur, mevcutlara dokunulmaz)"
eksik=""
command -v python3 >/dev/null || eksik="$eksik python3"
command -v curl >/dev/null || eksik="$eksik curl"
command -v flock >/dev/null || eksik="$eksik util-linux"
command -v crontab >/dev/null || eksik="$eksik cron"
if [ -n "$eksik" ]; then
  echo "  kurulacak:$eksik"
  if command -v apt-get >/dev/null; then apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-upgrade $eksik >/dev/null
  elif command -v dnf >/dev/null; then dnf install -y -q ${eksik/cron/cronie}
  elif command -v yum >/dev/null; then yum install -y -q ${eksik/cron/cronie}
  fi
fi
for c in python3 curl flock crontab; do command -v $c >/dev/null || hata "$c kurulamadı"; done
systemctl enable --now cron 2>/dev/null || systemctl enable --now crond 2>/dev/null || true

adim "Karar servisine erişim (Türkiye IP'si gerekir)"
KOD=$(curl -s -m 30 -o /dev/null -w "%{http_code}" -X POST https://bedesten.adalet.gov.tr/emsal-karar/searchDocuments \
  -H "Content-Type: application/json" -H "AdaletApplicationName: UyapMevzuat" -d '{"data":{}}')
case "$KOD" in 000|403) hata "bu sunucu bedesten.adalet.gov.tr'ye ulaşamıyor (kod $KOD). Sunucu yurt dışında olabilir; Türkiye lokasyonlu sunucu gerekir.";; esac
echo "  erişim var (kod $KOD)"

adim "Ayrı kullanıcı: $U"
id $U >/dev/null 2>&1 || useradd -m -s /bin/bash $U
mkdir -p "$D"

if [ -n "$TOKEN" ]; then
  cat > "$D/.env" <<X
export TMPRO_SUPABASE_URL="https://hnolhapzcisavhkwyzhs.supabase.co"
export TMPRO_ANON_KEY="sb_publishable_tlfwqtscxxv2vdSHe3PstQ_XO1db8p9"
export TMPRO_INGEST_TOKEN="$TOKEN"
X
fi
[ -f "$D/.env" ] || hata "gizli anahtar verilmedi (komutun sonuna ekleyin)"
. "$D/.env"

adim "Betik indiriliyor"
curl -fsSL "$SITE/yargitay.py" -o "$D/yargitay.py" && python3 -m py_compile "$D/yargitay.py" || hata "betik indirilemedi"

adim "Sunucu bağlantısı deneniyor"
KOD=$(curl -s -m 30 -o /dev/null -w "%{http_code}" -X POST "${TMPRO_SUPABASE_URL%/}/rest/v1/rpc/yargitay_ping" \
  -H "apikey: $TMPRO_ANON_KEY" -H "Content-Type: application/json" \
  -d "{\"token\":\"$TMPRO_INGEST_TOKEN\",\"info\":{\"kurulum\":\"sunucu\"}}")
[ "$KOD" = 204 ] || [ "$KOD" = 200 ] || hata "TMPRO yanıtı $KOD (gizli anahtar yanlış olabilir)"

cat > "$D/calistir.sh" <<'X'
#!/bin/bash
# Saatte bir (cron). Önceki tur sürüyorsa yenisi başlamaz; takılan tur 25 dk'da kesilir.
cd "$(dirname "$0")" || exit 1
. ./.env
{
  echo "=== $(date '+%d.%m %H:%M') ==="
  flock -n .kilit timeout 1500 nice -n 19 python3 -u yargitay.py
  echo "--- tur bitti $(date '+%H:%M'), kod $?"
} >> log.txt 2>&1
tail -n 2000 log.txt > log.tmp && mv log.tmp log.txt
X
chmod 700 "$D/calistir.sh"; chmod 600 "$D/.env"; chown -R $U:$U "$D"
echo "17 * * * * $D/calistir.sh" | crontab -u $U -

adim "İlk arama başlatılıyor (arka planda, birkaç dakika sürer)"
su - $U -c "nohup $D/calistir.sh >/dev/null 2>&1 &"

echo
echo "TAMAM: sunucu kurulumu bitti. Saatte bir (:17) çalışacak. Log: $D/log.txt"
