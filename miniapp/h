#!/usr/bin/env bash
# Желток — защищённый адрес (HTTPS) для приложения: «Мои дела», отправка из любого места Telegram, ссылки на документ.
# Запуск на сервере под root, после того как бот уже установлен:
#   curl -sL alexcompton228-stack.github.io/Zholtok/h | bash
# Что делает: обновляет бота, ставит Caddy (веб-сервер, сам получает бесплатный сертификат Let's Encrypt),
# публикует приложение и API на https://<ip-сервера>.sslip.io (или вашем домене) и включает API в боте.
# Повторный запуск безопасен.
set -euo pipefail

DIR=/opt/zholtok
SERVICE=zholtok
PORT=8081

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
set_env() {   # set_env KEY VALUE — заменить или добавить строку в .env
  if grep -q "^$1=" "$DIR/.env"; then sed -i "s|^$1=.*|$1=$2|" "$DIR/.env"; else printf '%s=%s\n' "$1" "$2" >> "$DIR/.env"; fi
}

if [ "$(id -u)" -ne 0 ]; then echo "Запустите под root."; exit 1; fi
if [ ! -d "$DIR/.git" ] || [ ! -f "$DIR/.env" ]; then
  echo "Бот ещё не установлен. Сначала: curl -sL alexcompton228-stack.github.io/Zholtok/i | bash"; exit 1
fi

say "1/6 Обновляю бота с GitHub"
cd "$DIR"
git fetch -q --depth 1 origin main
git reset -q --hard origin/main
"$DIR/venv/bin/pip" install -q -r requirements.txt

say "2/6 Определяю адрес сервера"
IP="$(curl -4 -fsS --max-time 10 https://api.ipify.org 2>/dev/null || curl -4 -fsS --max-time 10 https://ifconfig.me 2>/dev/null || true)"
if ! [[ "$IP" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; then echo "Не удалось узнать внешний IP сервера."; exit 1; fi
DEFAULT="${IP//./-}.sslip.io"
DOMAIN=""
read -r -p "Свой домен, если есть (например zholtok.duckdns.org). Нет — просто Enter [$DEFAULT]: " DOMAIN </dev/tty || true
DOMAIN="$(printf '%s' "${DOMAIN:-$DEFAULT}" | tr 'A-Z' 'a-z' | tr -d ' /')"
DOMAIN="${DOMAIN#https:}"; DOMAIN="${DOMAIN#http:}"
if ! [[ "$DOMAIN" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]]; then echo "Странный домен: $DOMAIN"; exit 1; fi
echo "Адрес: https://$DOMAIN/"

say "3/6 Ставлю Caddy"
if ! command -v caddy >/dev/null 2>&1; then
  apt-get update -qq
  if ! DEBIAN_FRONTEND=noninteractive apt-get install -y -qq caddy >/dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl gpg apt-transport-https >/dev/null
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq caddy >/dev/null
  fi
fi
caddy version | head -1

say "4/6 Настраиваю HTTPS"
chmod 755 /opt "$DIR" "$DIR/miniapp"
cat > /etc/caddy/Caddyfile <<EOF
# Желток: приложение (статичные файлы из репозитория) + API бота. Сертификат Caddy получает и продлевает сам.
$DOMAIN {
	encode gzip
	header {
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options "nosniff"
		Referrer-Policy "no-referrer"
		-Server
	}
	handle /api/* {
		reverse_proxy 127.0.0.1:$PORT
	}
	handle {
		root * $DIR/miniapp
		header Cache-Control "no-cache"
		file_server
	}
}
EOF
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; echo "Порты 80 и 443 открыты в ufw."
fi
systemctl enable -q caddy
systemctl restart caddy

say "5/6 Включаю API в боте"
set_env MINIAPP_URL "https://$DOMAIN/"
set_env API_PORT "$PORT"
chmod 600 "$DIR/.env"
# автообновление с GitHub (если его ещё нет)
if [ ! -f /etc/systemd/system/$SERVICE-update.timer ]; then
  cat > /etc/systemd/system/$SERVICE-update.service <<EOF
[Unit]
Description=Zholtok update from GitHub

[Service]
Type=oneshot
ExecStart=/bin/bash $DIR/deploy/update.sh
EOF
  cat > /etc/systemd/system/$SERVICE-update.timer <<EOF
[Unit]
Description=Zholtok update check every 5 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable -q --now $SERVICE-update.timer
fi
systemctl restart $SERVICE

say "6/6 Жду сертификат и проверяю адрес (до 2 минут)"
ok=""
for i in $(seq 1 40); do
  if curl -fsS --max-time 5 "https://$DOMAIN/api/health" 2>/dev/null | grep -q '"ok": true'; then ok=1; break; fi
  sleep 3
done
if [ -n "$ok" ] && curl -fsS --max-time 5 "https://$DOMAIN/catalog.json" >/dev/null 2>&1; then
  say "Готово: https://$DOMAIN/ работает."
  echo "Дальше в Telegram: откройте бота и отправьте /start — кнопка «Открыть Желток» обновится,"
  echo "а слева от поля ввода появится кнопка «Желток». В приложении появится раздел «Мои дела»."
else
  say "Адрес пока не отвечает."
  systemctl is-active --quiet $SERVICE || { echo "Бот не запущен:"; journalctl -u $SERVICE -n 20 --no-pager; }
  echo "Последние строки Caddy:"; journalctl -u caddy -n 15 --no-pager | cut -c1-220
  echo
  echo "Частые причины: у хостинга закрыты порты 80/443 (откройте в панели) или не выдан сертификат для sslip.io."
  echo "Во втором случае запустите скрипт ещё раз и введите свой домен DuckDNS (бесплатно, duckdns.org)."
  exit 1
fi
