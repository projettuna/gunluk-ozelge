#!/data/data/com.termux/files/usr/bin/bash
# TMPRO · Yargıtay telefonu tek seferlik kurulum (cron yerine kendi döngüsü).
# Kullanım (Termux):  curl -fsSL https://tmpro.tmproapp.workers.dev/turkiye/kur.sh | bash
set -e
P=/data/data/com.termux/files/usr
D=$HOME/tmpro
mkdir -p "$D" "$HOME/.termux/boot"
cd "$D"
[ -f .env ] || { echo "HATA: $D/.env yok (gizli anahtar dosyası). Kurulum rehberindeki 3. adımı yapın."; exit 1; }
curl -fsSLO https://tmpro.tmproapp.workers.dev/turkiye/yargitay.py

# 1) Döngü: saatte bir çalışır, cron'a ihtiyaç yok
cat > "$D/dongu.sh" <<'X'
#!/data/data/com.termux/files/usr/bin/bash
D=/data/data/com.termux/files/home/tmpro
cd "$D" || exit 1
termux-wake-lock 2>/dev/null
echo $$ > "$D/dongu.pid"
while true; do
  ( . ./.env && /data/data/com.termux/files/usr/bin/python yargitay.py ) >> log.txt 2>&1
  tail -n 400 log.txt > log.tmp && mv log.tmp log.txt
  sleep 3600
done
X
chmod +x "$D/dongu.sh"

# 2) Başlatıcı: zaten çalışıyorsa ikinci kopyayı açmaz
cat > "$D/baslat.sh" <<'X'
#!/data/data/com.termux/files/usr/bin/bash
D=/data/data/com.termux/files/home/tmpro
if [ -f "$D/dongu.pid" ] && kill -0 "$(cat "$D/dongu.pid")" 2>/dev/null; then exit 0; fi
nohup "$D/dongu.sh" > /dev/null 2>&1 &
X
chmod +x "$D/baslat.sh"

# 3) Telefon yeniden başlayınca (Termux:Boot uygulaması varsa) ve Termux her açılınca kendiliğinden başlasın
cp "$D/baslat.sh" "$HOME/.termux/boot/tmpro"
touch "$HOME/.bashrc"
grep -q 'tmpro/baslat.sh' "$HOME/.bashrc" || echo '~/tmpro/baslat.sh' >> "$HOME/.bashrc"

# 4) Eski cron kaydını kaldır (çift çalışmasın)
crontab -r 2>/dev/null || true

"$D/baslat.sh"
sleep 2
if [ -f "$D/dongu.pid" ] && kill -0 "$(cat "$D/dongu.pid")" 2>/dev/null; then
  echo "TAMAM: Yargıtay döngüsü çalışıyor. İlk arama şimdi başladı, birkaç dakika sürer."
else
  echo "HATA: döngü başlamadı"
fi
