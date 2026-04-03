#!/bin/bash
# MacBook da local test
# Ishlatish: bash start.sh

set -e
cd "$(dirname "$0")"

# --- Eski jarayonlarni to'xtatish ---
pkill -f "uvicorn server:app" 2>/dev/null || true
pkill -f "python bot.py"      2>/dev/null || true
pkill -f "ngrok http"          2>/dev/null || true
sleep 1

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🚄 Tickets Bot — Local"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# --- Server ishga tushirish ---
echo "▶ Server ishga tushmoqda..."
uvicorn server:app --host 127.0.0.1 --port 8000 > /tmp/server.log 2>&1 &
SERVER_PID=$!
sleep 2

# Server ishlayaptimi?
if ! kill -0 $SERVER_PID 2>/dev/null; then
    echo "❌ Server ishga tushmadi!"
    cat /tmp/server.log
    exit 1
fi
echo "✅ Server: http://localhost:8000"

# --- ngrok tunnel ---
echo "▶ ngrok tunnel ochilmoqda..."
ngrok http 8000 --log=stdout > /tmp/ngrok.log 2>&1 &
NGROK_PID=$!
sleep 3

# ngrok URL ni olish
NGROK_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null \
  | python3 -c "import sys,json; t=json.load(sys.stdin)['tunnels']; print([x['public_url'] for x in t if x['proto']=='https'][0])" 2>/dev/null)

if [ -z "$NGROK_URL" ]; then
    echo "⚠️  ngrok URL olinmadi. Hisobingiz yo'qmi?"
    echo "   Davom etish uchun: https://dashboard.ngrok.com/signup"
    echo "   Login qilgach: ngrok config add-authtoken <TOKEN>"
    NGROK_URL="http://localhost:8000  (ngrok ishlamadi)"
fi

# .env ni yangilash
sed -i '' "s|WEBAPP_URL=.*|WEBAPP_URL=$NGROK_URL|" .env 2>/dev/null || \
  echo "WEBAPP_URL=$NGROK_URL" >> .env

echo "✅ Tunnel: $NGROK_URL"
echo ""

# --- Bot ishga tushirish ---
echo "▶ Telegram bot ishga tushmoqda..."
python bot.py > /tmp/bot.log 2>&1 &
BOT_PID=$!
sleep 2

if ! kill -0 $BOT_PID 2>/dev/null; then
    echo "❌ Bot ishga tushmadi!"
    cat /tmp/bot.log
    exit 1
fi
echo "✅ Bot ishlayapti"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ Hamma narsa tayyor!"
echo ""
echo "  🌐 Mini App URL : $NGROK_URL"
echo "  📱 Botga yozing : Telegram da /start"
echo ""
echo "  Loglarni ko'rish:"
echo "    tail -f /tmp/server.log"
echo "    tail -f /tmp/bot.log"
echo "    tail -f /tmp/ngrok.log"
echo ""
echo "  To'xtatish: bash stop.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# BotFather da Mini App URL ni ko'rsatish
echo ""
echo "⚠️  BotFather da yangilash kerak:"
echo "   /mybots → botingiz → Bot Settings → Menu Button"
echo "   yoki /newapp → URL: $NGROK_URL"
echo ""

# Jarayonlar to'xtaguncha kutish
wait
