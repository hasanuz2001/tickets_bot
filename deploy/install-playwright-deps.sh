#!/bin/bash
# Playwright Chromium uchun tizim kutubxonalari (Ubuntu 22.04 / 24.04).
# MUHIM: faqat root / sudo bilan.
#
#   cd /opt/app && sudo bash deploy/install-playwright-deps.sh
#   sudo bash deploy/install-playwright-deps.sh /opt/boshqa
#
set -e
APP_DIR="${1:-${TICKETS_BOT_HOME:-/opt/app}}"
PW="$APP_DIR/venv/bin/playwright"

if [ "$(id -u)" -ne 0 ]; then
  echo "Xato: root kerak:"
  echo "  cd $APP_DIR && sudo bash deploy/install-playwright-deps.sh"
  exit 1
fi

if [ ! -x "$PW" ]; then
  echo "Topilmadi: $PW"
  echo "Avval: cd $APP_DIR && bash deploy/configure.sh"
  exit 1
fi

echo ">>> apt yangilanmoqda..."
apt-get update -qq

# Playwright xatosidagi ro'yxat + ko'p serverlarda yetishmaydiganlar
CORE_PKGS=(
  libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libatspi2.0-0
  libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 libgbm1
  libpango-1.0-0 libcairo2 libdrm2 libxkbcommon0 libgtk-3-0
  libglib2.0-0 fonts-liberation
)

echo ">>> Asosiy deb paketlar..."
if ! apt-get install -y "${CORE_PKGS[@]}" libasound2; then
  echo ">>> libasound2 bo'lmasa (Ubuntu 24+): libasound2t64..."
  apt-get install -y "${CORE_PKGS[@]}" libasound2t64 || apt-get install -y "${CORE_PKGS[@]}"
fi

echo ">>> Playwright: chromium brauzer..."
"$PW" install chromium || true

echo ">>> Playwright: install-deps chromium..."
"$PW" install-deps chromium

echo ""
echo "✅ Tayyor. Servisni qayta ishga tushiring:"
echo "   systemctl restart tickets-server"
