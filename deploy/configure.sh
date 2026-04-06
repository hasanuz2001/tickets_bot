#!/bin/bash
# Loyiha sozlamalarini qilish
# Ishlatish: bash /opt/tickets_bot/deploy/configure.sh

set -e
APP_DIR="/opt/tickets_bot"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Configure: Python env + .env"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

cd $APP_DIR

# Python virtual environment
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo ""
echo "Playwright Chromium (bitta login orqali avtomatik chipta)..."
"$APP_DIR/venv/bin/playwright" install chromium || true
"$APP_DIR/venv/bin/playwright" install-deps chromium 2>/dev/null || true

echo ""
echo "✅ Python paketlari o'rnatildi"
echo ""

# .env faylini tekshirish
if [ ! -f "$APP_DIR/.env" ]; then
    echo "⚠️  .env fayli topilmadi!"
    echo "Quyidagi ma'lumotlarni kiriting:"
    echo ""

    read -p "BOT_TOKEN: " BOT_TOKEN
    read -p "DUCKDNS domeningiz (masalan: tickets-bot.duckdns.org): " DOMAIN

    cat > $APP_DIR/.env << EOF
BOT_TOKEN=$BOT_TOKEN
WEBAPP_URL=https://$DOMAIN
EOF
    echo ""
    echo "✅ .env fayli yaratildi"
fi

# Domenni .env dan olib nginx uchun saqlash
DOMAIN=$(grep WEBAPP_URL $APP_DIR/.env | cut -d'/' -f3)
echo $DOMAIN > /tmp/bot_domain.txt

echo ""
echo "✅ Konfiguratsiya tayyor"
echo "📱 Telegram Mini App (iPhone): @BotFather → bot → Mini App / URL sozlamalari —"
echo "   WEBAPP_URL hostname (${DOMAIN:-domen}) ro'yxatdan o'tgan bo'lishi kerak."
echo "Davom eting: bash /opt/tickets_bot/deploy/nginx.sh"
