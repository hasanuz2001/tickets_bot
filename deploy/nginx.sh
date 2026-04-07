#!/bin/bash
# Nginx + SSL sozlash
# Ishlatish: cd /opt/app && bash deploy/nginx.sh

set -e
APP_ROOT="${TICKETS_BOT_HOME:-/opt/app}"

DOMAIN=$(cat /tmp/bot_domain.txt)
EMAIL="admin@$DOMAIN"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Nginx + SSL: $DOMAIN"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Nginx konfiguratsiya
cat > /etc/nginx/sites-available/tickets_bot << EOF
server {
    listen 80;
    server_name $DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 60s;
    }
}
EOF

# Aktivlashtirish
ln -sf /etc/nginx/sites-available/tickets_bot /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo ""
echo "✅ Nginx sozlandi (HTTP)"
echo ""

# SSL sertifikat
echo "SSL sertifikat olinmoqda..."
certbot --nginx -d $DOMAIN --non-interactive --agree-tos -m $EMAIL

echo ""
echo "✅ SSL sertifikat o'rnatildi"
echo "Davom eting: bash $APP_ROOT/deploy/services.sh"
