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

# --- 3. Papka yaratish ---
mkdir -p /opt/tickets_bot
cd /opt/tickets_bot

echo ""
echo "✅ Tizim paketlari o'rnatildi"
echo ""
echo "Endi loyihani ko'chiring:"
echo "  scp -r tickets_bot/ root@SERVER_IP:/opt/"
echo ""
echo "Keyin davom eting:"
echo "  bash /opt/tickets_bot/deploy/configure.sh"
