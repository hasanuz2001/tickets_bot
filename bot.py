"""
O'zbekiston Temir Yo'llari - Telegram Bilet Qidiruv Boti
Ishlatish: python bot.py
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, MenuButtonWebApp
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, ConversationHandler, filters
)

load_dotenv()

# --- SOZLAMALAR ---
BOT_TOKEN  = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://YOUR_DOMAIN_HERE")

RAILWAY_API = "https://eticket.railway.uz/api/v3/handbook/trains/list"
RAILWAY_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "uz",
    "Content-Type": "application/json",
    "Origin": "https://eticket.railway.uz",
}

# Asosiy stansiyalar (kod: nomi)
STATIONS = {
    "2900000": "Toshkent",
    "2900001": "Toshkent Shimoliy",
    "2900002": "Toshkent Janubiy",
    "2900700": "Samarqand",
    "2900800": "Buxoro",
    "2900930": "Navoiy",
    "2900720": "Jizzax",
    "2900680": "Andijon",
    "2900940": "Namangan",
    "2900880": "Qo'qon",
    "2900920": "Marg'ilon",
    "2900750": "Qarshi",
    "2900255": "Termiz",
    "2900790": "Urganch",
    "2900172": "Xiva",
    "2900970": "Nukus",
}

# Conversation holatlari
FROM_STATION, TO_STATION, DATE = range(3)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# --- RAILWAY API ---
async def search_trains(from_code: str, to_code: str, date: str) -> dict:
    """eticket.railway.uz API orqali poyezdlarni qidiradi"""
    payload = {
        "directions": {
            "forward": {
                "date": date,
                "depStationCode": from_code,
                "arvStationCode": to_code
            }
        }
    }
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.post(RAILWAY_API, json=payload, headers=RAILWAY_HEADERS)
            return resp.json()
        except Exception as e:
            logger.error(f"API xatosi: {e}")
            return {}


def format_trains(data: dict, from_name: str, to_name: str, date: str) -> str:
    """API javobini chiroyli matn ko'rinishiga o'tkazadi"""
    try:
        trains = data["data"]["directions"]["forward"]["trains"]
    except (KeyError, TypeError):
        return "❌ Ma'lumot olishda xatolik yuz berdi. Keyinroq urinib ko'ring."

    if not trains:
        return f"😕 {from_name} → {to_name} ({date})\n\nBu sana uchun poyezdlar topilmadi."

    lines = [f"🚆 <b>{from_name} → {to_name}</b>", f"📅 <b>{date}</b>\n"]

    for train in trains:
        dep = train.get("departureTime", "")[:5]
        arr = train.get("arrivalTime", "")[:5]
        t_type = train.get("type", "")
        t_num = train.get("number", "")
        lines.append(f"━━━━━━━━━━━━━━━━━")
        lines.append(f"🕐 {dep} → {arr}  |  {t_type} #{t_num}")

        for car in train.get("cars", []):
            car_type = car.get("carTypeName", "")
            free_seats = car.get("freeSeats", 0)
            if free_seats > 0:
                prices = []
                for tariff in car.get("tariffs", []):
                    cost = tariff.get("tariff", 0)
                    if cost:
                        prices.append(f"{cost:,} so'm")
                price_str = " / ".join(prices) if prices else "—"
                lines.append(f"  🪑 {car_type}: {free_seats} joy | {price_str}")

    lines.append(f"\n🔗 <a href='https://eticket.railway.uz'>Chipta sotib olish</a>")
    return "\n".join(lines)


# --- BOT HANDLERLAR ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(
            "🎫 Chipta qidirish (Mini App)",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )],
        [InlineKeyboardButton("🔍 Inline qidiruv", callback_data="new_search")],
    ]
    await update.message.reply_text(
        "👋 Salom! Men <b>O'zbekiston temir yo'llari</b> chipta qidiruv botiman.\n\n"
        "Quyidagi usullardan birini tanlang:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Qidiruv boshlanadi - jo'nash stansiyasi tanlanadi"""
    keyboard = []
    row = []
    for code, name in STATIONS.items():
        row.append(InlineKeyboardButton(name, callback_data=f"from_{code}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await update.message.reply_text(
        "🚉 <b>Qayerdan</b> jo'naysiz?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return FROM_STATION


async def from_station_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Jo'nash stansiyasi tanlandi"""
    query = update.callback_query
    await query.answer()

    code = query.data.replace("from_", "")
    context.user_data["from_code"] = code
    context.user_data["from_name"] = STATIONS.get(code, code)

    keyboard = []
    row = []
    for c, name in STATIONS.items():
        if c != code:  # Jo'nash stansiyasini chiqarmaymiz
            row.append(InlineKeyboardButton(name, callback_data=f"to_{c}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
    if row:
        keyboard.append(row)

    await query.edit_message_text(
        f"✅ Jo'nash: <b>{STATIONS[code]}</b>\n\n🏁 <b>Qayerga</b> borasiz?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return TO_STATION


async def to_station_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Borish stansiyasi tanlandi"""
    query = update.callback_query
    await query.answer()

    code = query.data.replace("to_", "")
    context.user_data["to_code"] = code
    context.user_data["to_name"] = STATIONS.get(code, code)

    # Sanalar uchun tugmalar (bugundan 10 kun)
    keyboard = []
    row = []
    for i in range(10):
        d = datetime.now() + timedelta(days=i)
        label = d.strftime("%d-%b") if i > 0 else f"Bugun ({d.strftime('%d-%b')})"
        value = d.strftime("%Y-%m-%d")
        row.append(InlineKeyboardButton(label, callback_data=f"date_{value}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await query.edit_message_text(
        f"✅ Jo'nash: <b>{context.user_data['from_name']}</b>\n"
        f"✅ Borish: <b>{context.user_data['to_name']}</b>\n\n"
        f"📅 <b>Qaysi sana</b>?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return DATE


async def date_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sana tanlandi, API ga so'rov yuboriladi"""
    query = update.callback_query
    await query.answer()

    date = query.data.replace("date_", "")
    from_code = context.user_data["from_code"]
    to_code = context.user_data["to_code"]
    from_name = context.user_data["from_name"]
    to_name = context.user_data["to_name"]

    await query.edit_message_text("⏳ Poyezdlar qidirilmoqda...")

    data = await search_trains(from_code, to_code, date)
    result = format_trains(data, from_name, to_name, date)

    keyboard = [[InlineKeyboardButton("🔄 Yangi qidiruv", callback_data="new_search")]]
    await query.edit_message_text(
        result,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )
    return ConversationHandler.END


async def new_search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yangi qidiruv tugmasi bosilganda"""
    query = update.callback_query
    await query.answer()

    keyboard = []
    row = []
    for code, name in STATIONS.items():
        row.append(InlineKeyboardButton(name, callback_data=f"from_{code}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await query.edit_message_text(
        "🚉 <b>Qayerdan</b> jo'naysiz?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return FROM_STATION


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Bekor qilindi.")
    return ConversationHandler.END


# --- ASOSIY ---
async def post_init(application):
    """Bot ishga tushganda menu tugmasini o'rnatish."""
    await application.bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="🎫 Chipta qidirish",
            web_app=WebAppInfo(url=WEBAPP_URL),
        )
    )
    print(f"✅ Menu button o'rnatildi: {WEBAPP_URL}")


def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("search", search_start),
            CallbackQueryHandler(new_search_callback, pattern="^new_search$"),
        ],
        states={
            FROM_STATION: [CallbackQueryHandler(from_station_selected, pattern="^from_")],
            TO_STATION: [CallbackQueryHandler(to_station_selected, pattern="^to_")],
            DATE: [CallbackQueryHandler(date_selected, pattern="^date_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)

    print("✅ Bot ishga tushdi!")
    app.run_polling()


if __name__ == "__main__":
    main()
