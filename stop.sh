#!/bin/bash
pkill -f "uvicorn server:app" 2>/dev/null && echo "✅ Server to'xtatildi" || echo "Server ishlamayotgan edi"
pkill -f "python bot.py"      2>/dev/null && echo "✅ Bot to'xtatildi"    || echo "Bot ishlamayotgan edi"
pkill -f "ngrok http"          2>/dev/null && echo "✅ Tunnel yopildi"     || echo "Tunnel ishlamayotgan edi"
