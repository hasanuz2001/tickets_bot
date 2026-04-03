#!/bin/bash
# Lokal kompyuterda ishlatiladi — fayllarni serverga yuklaydi
# Ishlatish: bash deploy/upload.sh SERVER_IP

set -e

SERVER_IP=${1:?"Server IP ni bering: bash upload.sh 1.2.3.4"}

echo "📤 Fayllar $SERVER_IP ga yuklanmoqda..."

rsync -avz --exclude='.env' \
           --exclude='venv/' \
           --exclude='__pycache__/' \
           --exclude='*.pyc' \
           --exclude='subscriptions.db' \
           --exclude='.DS_Store' \
  "$(dirname "$0")/../" \
  "root@$SERVER_IP:/opt/tickets_bot/"

echo ""
echo "✅ Yuklandi!"
echo ""
echo "Endi serverda bajaring:"
echo ""
echo "  ssh root@$SERVER_IP"
echo "  bash /opt/tickets_bot/deploy/setup.sh"
echo "  bash /opt/tickets_bot/deploy/configure.sh"
echo "  bash /opt/tickets_bot/deploy/nginx.sh"
echo "  bash /opt/tickets_bot/deploy/services.sh"
