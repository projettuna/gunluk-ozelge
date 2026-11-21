#!/data/data/com.termux/files/usr/bin/bash
# TMPRO · Yargıtay telefonu kurulum / onarım. Tekrar tekrar çalıştırılabilir.
# Kullanım (Termux):  curl -fsSL https://tmpro.tmproapp.workers.dev/turkiye/kur.sh | bash
U=/data/data/com.termux/files/usr
D=/data/data/com.termux/files/home/tmpro
SITE=https://tmpro.tmproapp.workers.dev/turkiye
hata() { echo; echo "HATA: $*"; exit 1; }
adim() { echo "• $*"; }

mkdir -p "$D" "$HOME/.termux/boot" && cd "$D" || hata "klasör oluşturulamadı"
[ -f .env ] || hata "$D/.env yok (gizli anahtar dosyası). Önce .env bloğunu yapıştırın."
. ./.env
[ -n "$TMPRO_INGEST_TOKEN" ] && [ -n "$TMPRO_SUPABASE_URL" ] || hata ".env eksik: TMPRO_SUPABASE_URL / TMPRO_INGEST_TOKEN yok"
command -v python >/dev/null || hata "python kurulu değil: pkg install -y python"

adim "Eski döngüler durduruluyor"
pkill -f "$D/dongu.sh" 2>/dev/null; pkill -f "yargitay.py" 2>/dev/null
crontab -r 2>/dev/null; rm -f "$D/dongu.pid"

adim "Telefon uyanık tutuluyor (wake lock)"
termux-wake-lock 2>/dev/null &

adim "İnternet kontrolü"
for i in $(seq 1 12); do
  python - <<'P' && break
import socket, sys
try:
    socket.getaddrinfo("tmpro.tmproapp.workers.dev", 443); socket.getaddrinfo("bedesten.adalet.gov.tr", 443)
except OSError: sys.exit(1)
P
  [ "$i" = 12 ] && hata "internet yok (adresler çözülemiyor). Wi-Fi veya mobil veriyi açıp komutu yeniden çalıştırın."
  echo "  internet bekleniyor ($i/12)…"; sleep 10
done

adim "Betik indiriliyor"
curl -fsSL "$SITE/yargitay.py" -o yargitay.py.yeni && python -m py_compile yargitay.py.yeni && mv yargitay.py.yeni yargitay.py \
  || hata "betik indirilemedi"

adim "Sunucu bağlantısı deneniyor"
KOD=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${TMPRO_SUPABASE_URL%/}/rest/v1/rpc/yargitay_ping" \
  -H "apikey: $TMPRO_ANON_KEY" -H "Content-Type: application/json" \
  -d "{\"token\":\"$TMPRO_INGEST_TOKEN\",\"info\":{\"kurulum\":1}}")
[ "$KOD" = 204 ] || [ "$KOD" = 200 ] || hata "sunucu yanıtı $KOD (anahtar yanlış olabilir: .env içindeki TMPRO_INGEST_TOKEN)"

adim "Döngü kuruluyor"
cat > "$D/dongu.sh" <<'X'
#!/data/data/com.termux/files/usr/bin/bash
# Saatte bir arar; internet/servis hatasında 10 dakika sonra yeniden dener.
D=/data/data/com.termux/files/home/tmpro
cd "$D" || exit 1
echo $$ > "$D/dongu.pid"
termux-wake-lock 2>/dev/null &
while true; do
  echo "=== $(date '+%d.%m %H:%M') ===" >> log.txt
  # -u: satırlar anında log'a yazılsın; timeout: takılan tur 25 dk sonra kesilsin
  ( . ./.env && timeout 1500 /data/data/com.termux/files/usr/bin/python -u yargitay.py ) >> log.txt 2>&1
  kod=$?
  echo "--- tur bitti $(date '+%H:%M'), kod $kod" >> log.txt
  if [ $kod -eq 0 ]; then bekle=3600; else bekle=600; fi
  tail -n 400 log.txt > log.tmp && mv log.tmp log.txt
  sleep $bekle
done
X
cat > "$D/baslat.sh" <<'X'
#!/data/data/com.termux/files/usr/bin/bash
D=/data/data/com.termux/files/home/tmpro
if [ -f "$D/dongu.pid" ] && kill -0 "$(cat "$D/dongu.pid")" 2>/dev/null; then exit 0; fi
nohup "$D/dongu.sh" > /dev/null 2>&1 &
X
chmod +x "$D/dongu.sh" "$D/baslat.sh"
cp "$D/baslat.sh" "$HOME/.termux/boot/tmpro" && chmod +x "$HOME/.termux/boot/tmpro"
touch "$HOME/.bashrc"; grep -q 'tmpro/baslat.sh' "$HOME/.bashrc" || echo '~/tmpro/baslat.sh' >> "$HOME/.bashrc"

"$D/baslat.sh"
for i in 1 2 3 4 5 6 7 8 9 10; do
  sleep 1
  [ -f "$D/dongu.pid" ] && kill -0 "$(cat "$D/dongu.pid")" 2>/dev/null && break
done
[ -f "$D/dongu.pid" ] && kill -0 "$(cat "$D/dongu.pid")" 2>/dev/null || hata "döngü başlamadı"
echo
echo "TAMAM: kurulum bitti, döngü çalışıyor (süreç $(cat "$D/dongu.pid")). İlk arama şimdi başladı."
echo "Termux'u kaydırarak kapatmayın. Durum: tail -20 ~/tmpro/log.txt"
