#!/bin/bash
# Lokal kompyuterda ishlatiladi — fayllarni serverga yuklaydi
# Ishlatish: bash deploy/upload.sh SERVER_IP

set -e

SERVER_IP=${1:?"Server IP ni bering: bash upload.sh 1.2.3.4"}
# Serverdagi loyiha papkasi (masalan /opt/app)
REMOTE="${TICKETS_BOT_REMOTE:-/opt/app}"

echo "📤 Fayllar $SERVER_IP:$REMOTE ga yuklanmoqda..."

rsync -avz --exclude='.env' \
           --exclude='venv/' \
           --exclude='__pycache__/' \
           --exclude='*.pyc' \
           --exclude='subscriptions.db' \
           --exclude='.DS_Store' \
  "$(dirname "$0")/../" \
  "root@$SERVER_IP:$REMOTE/"

echo ""
echo "✅ Yuklandi!"
echo ""
echo "Endi serverda bajaring:"
echo ""
echo "  ssh root@$SERVER_IP"
echo "  cd $REMOTE && bash deploy/configure.sh"
echo "  cd $REMOTE && bash deploy/nginx.sh"
echo "  cd $REMOTE && bash deploy/services.sh"
