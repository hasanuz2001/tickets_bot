#!/bin/bash
# Hetzner Ubuntu 22.04 — to'liq deploy skripti
# Ishlatish: sudo bash setup.sh

set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Tickets Bot — Server Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# --- 1. Tizimni yangilash ---
apt update && apt upgrade -y

# --- 2. Kerakli paketlar ---
apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx git curl

# Playwright Chromium uchun (avtomatik chipta); to'liq ro'yxat: install-playwright-deps.sh
apt install -y \
  libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libatspi2.0-0 \
  libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 libgbm1 \
  libpango-1.0-0 libcairo2 libasound2 libdrm2 libxkbcommon0 || true

# --- 3. Papka yaratish ---
APP_ROOT="${TICKETS_BOT_HOME:-/opt/app}"
mkdir -p "$APP_ROOT"
cd "$APP_ROOT"

echo ""
echo "✅ Tizim paketlari o'rnatildi"
echo ""
echo "Endi loyihani ko'chiring (masalan monorepo bo'lsa /opt/app ichiga):"
echo "  rsync ... root@SERVER_IP:$APP_ROOT/"
echo ""
echo "Keyin davom eting:"
echo "  cd $APP_ROOT && bash deploy/configure.sh"
