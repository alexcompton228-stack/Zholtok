#!/usr/bin/env bash
# Забирает новую версию с GitHub, если она есть, и перезапускает бота.
# Запускается таймером zholtok-update.timer каждые 5 минут. Настройки (.env) и база не трогаются.
set -euo pipefail
DIR=/opt/zholtok
cd "$DIR"
git fetch -q --depth 1 origin main
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] && exit 0
old_req="$(sha1sum < requirements.txt)"
git reset -q --hard origin/main
if [ "$old_req" != "$(sha1sum < requirements.txt)" ]; then
  "$DIR/venv/bin/pip" install -q -r requirements.txt
fi
systemctl restart zholtok
logger -t zholtok-update "обновлено до $(git rev-parse --short HEAD)"
