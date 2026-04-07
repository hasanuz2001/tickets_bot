#!/bin/bash
# Playwright Chromium — Ubuntu 22.04 va 24.04 (Noble, jumladan ARM / ubuntu-ports).
#
# Tartib (git pull dan keyin):
#   cd /opt/app && bash deploy/configure.sh          # pip + playwright yangilanishi
#   sudo bash deploy/install-playwright-deps.sh
#
set -e
APP_DIR="${1:-${TICKETS_BOT_HOME:-/opt/app}}"
PW="$APP_DIR/venv/bin/playwright"

if [ "$(id -u)" -ne 0 ]; then
  echo "Root kerak: sudo bash $0"
  exit 1
fi

if [ ! -x "$PW" ]; then
  echo "Topilmadi: $PW — avval: cd $APP_DIR && bash deploy/configure.sh"
  exit 1
fi

# /etc/os-release — Noble = 24.04 (libasound2 virtual, t64 paketlar)
NOBLE=0
if [ -r /etc/os-release ]; then
  # shellcheck source=/dev/null
  . /etc/os-release
  case "${VERSION_ID:-}" in
    24.*) NOBLE=1 ;;
  esac
fi

echo ">>> apt yangilanmoqda..."
apt-get update -qq

if [ "$NOBLE" = 1 ]; then
  echo ">>> Ubuntu 24.04 (Noble) — t64 va libasound2t64..."
  apt-get install -y \
    libnss3 libnspr4 libasound2t64 \
    libatk-bridge2.0-0t64 libatk1.0-0t64 libatspi2.0-0t64 \
    libcups2t64 libdbus-1-3 libdrm2 libgbm1 libglib2.0-0t64 libgtk-3-0t64 \
    libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 libxkbcommon0 \
    libpango-1.0-0 libcairo2 fonts-liberation libxi6 libxss1
else
  echo ">>> Ubuntu 22.04 yoki boshqa — klassik paketlar..."
  apt-get install -y \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libatspi2.0-0 \
    libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libdrm2 libxkbcommon0 libgtk-3-0 \
    libglib2.0-0 fonts-liberation libasound2 \
    || apt-get install -y \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libatspi2.0-0 \
    libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libdrm2 libxkbcommon0 libgtk-3-0 libglib2.0-0 \
    fonts-liberation libasound2t64
fi

echo ">>> Playwright: chromium..."
"$PW" install chromium || true

echo ">>> Playwright: install-deps chromium..."
if ! "$PW" install-deps chromium; then
  echo ""
  echo "⚠️  install-deps xato berdi. Pip paketini yangilang (Noble uchun 1.49+):"
  echo "    cd $APP_DIR && source venv/bin/activate && pip install -U 'playwright>=1.49,<1.57'"
  echo "    $PW install chromium && $PW install-deps chromium"
  exit 1
fi

echo ""
echo "✅ Tayyor: systemctl restart tickets-server"
