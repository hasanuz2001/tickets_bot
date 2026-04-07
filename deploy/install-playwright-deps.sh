#!/bin/bash
# Playwright Chromium uchun tizim kutubxonalari (Ubuntu/Debian).
# MUHIM: root bilan ishga tushiring.
#   cd /opt/app && sudo bash deploy/install-playwright-deps.sh
# Boshqa papka: sudo bash deploy/install-playwright-deps.sh /opt/boshqa
#
set -e
APP_DIR="${1:-${TICKETS_BOT_HOME:-/opt/app}}"
PW="$APP_DIR/venv/bin/playwright"

if [ "$(id -u)" -ne 0 ]; then
  echo "Xato: root kerak. Masalan:"
  echo "  sudo bash $0"
  exit 1
fi

if [ ! -x "$PW" ]; then
  echo "Topilmadi: $PW"
  echo "Avval: bash $APP_DIR/deploy/configure.sh"
  exit 1
fi

echo "Playwright tizim paketlari o'rnatilmoqda (chromium)..."
"$PW" install-deps chromium
echo "OK. Keyin: systemctl restart tickets-server"
