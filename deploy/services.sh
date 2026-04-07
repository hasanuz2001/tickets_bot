#!/bin/bash
# systemd servislarni yaratish va ishga tushirish
# Ishlatish: cd /opt/app && bash deploy/services.sh
# Boshqa papka: export TICKETS_BOT_HOME=/opt/boshqa
# Ayrim monorepolarda server.py pastki papkada bo'lsa: TICKETS_BOT_HOME=/opt/app/ostidagi_papka

set -e
APP_DIR="${TICKETS_BOT_HOME:-/opt/app}"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  systemd services"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# --- 1. Server servisi (uvicorn + scheduler) ---
cat > /etc/systemd/system/tickets-server.service << EOF
[Unit]
Description=Tickets Bot Server (FastAPI + Scheduler)
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/uvicorn server:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# --- 2. Bot servisi (telegram polling) ---
cat > /etc/systemd/system/tickets-bot.service << EOF
[Unit]
Description=Tickets Telegram Bot
After=network.target tickets-server.service
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/python bot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Servislarni yoqish va ishga tushirish
systemctl daemon-reload

systemctl enable tickets-server tickets-bot
systemctl restart tickets-server tickets-bot

sleep 3

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Holat tekshiruvi"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
systemctl status tickets-server --no-pager -l
echo ""
systemctl status tickets-bot --no-pager -l
echo ""
echo "✅ Bot va server ishga tushdi!"
echo ""
echo "Foydali buyruqlar:"
echo "  journalctl -fu tickets-server   # server loglari"
echo "  journalctl -fu tickets-bot      # bot loglari"
echo "  systemctl restart tickets-server tickets-bot"
