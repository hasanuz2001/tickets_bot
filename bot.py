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
import json

import httpx as _httpx
from urllib.parse import urlparse

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    MenuButtonWebApp,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, ConversationHandler, filters
)

load_dotenv()


def _normalize_webapp_url(raw: str) -> str:
    u = (raw or "").strip().rstrip("/")
    if not u:
        return "http://localhost:8000"
    if "localhost" in u or "127.0.0.1" in u:
        return u
    if u.startswith("http://"):
        u = "https://" + u[len("http://") :]
    return u


# --- SOZLAMALAR ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = _normalize_webapp_url(os.getenv("WEBAPP_URL", ""))
# Bot ichidan server API ga (xarid va h.k.)
SERVER_URL = WEBAPP_URL


def _webapp_domain_hint() -> str:
    return urlparse(WEBAPP_URL).netloc or WEBAPP_URL

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
    "2900850": "Guliston",
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
    inline = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔍 Inline qidiruv", callback_data="new_search")]]
    )
    # iOS Telegram: KeyboardButton+web_app ko'pincha InlineKeyboard dan ishonchliroq ichki WebView ochadi
    reply_kb = ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(
                    text="🎫 Chipta qidirish (Mini App)",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            ]
        ],
        resize_keyboard=True,
    )
    domain_hint = _webapp_domain_hint()
    welcome = (
        "👋 Salom! Men <b>O'zbekiston temir yo'llari</b> chipta qidiruv botiman.\n\n"
        "<b>Telegramda ochish (iPhone):</b> avvalo <b>pastdagi 🎫 tugmani</b> bosing — "
        "odatda ilova ichida ochiladi. Chap-pastki <b>☰ menyuda</b> ham 🎫 bo'lishi mumkin.\n\n"
        "Agar brauzer ochilsa: Telegram <b>Mini App domenini</b> talab qiladi. @BotFather → botingiz → "
        "<b>Bot Settings</b> → <b>Configure Mini App</b> / <b>Edit Mini App URL</b> "
        "(yoki <i>Domain</i>) — quyidagi hostname ni qo'shing: "
        f"<code>{domain_hint}</code>\n\n"
        "Pastki klaviaturani yashirish: /yop"
    )
    await update.message.reply_text(welcome, reply_markup=reply_kb, parse_mode="HTML")
    await update.message.reply_text(
        "Matnli qidiruv (chat ichida):",
        reply_markup=inline,
        parse_mode="HTML",
    )


async def yop_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Pastki tugmalar yashirildi.",
        reply_markup=ReplyKeyboardRemove(),
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


# ── YO'LOVCHI MA'LUMOTI ────────────────────────────────────────────────────────
PASS_NAME, PASS_PASSPORT, PASS_PHONE = range(20, 23)


async def passenger_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    # Avvalgi ma'lumot bormi?
    try:
        async with _httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"{SERVER_URL}/api/passenger/{user_id}")
            if r.status_code == 200:
                p = r.json()
                await update.message.reply_text(
                    f"📋 <b>Saqlangan ma'lumotlar:</b>\n\n"
                    f"👤 {p['full_name']}\n"
                    f"📄 {p['passport']}\n"
                    f"📱 {p['phone']}\n\n"
                    "O'zgartirish uchun <b>to'liq ismingizni</b> yuboring:\n"
                    "<i>(Bekor qilish: /cancel)</i>",
                    parse_mode="HTML",
                )
            else:
                raise Exception("not found")
    except Exception:
        await update.message.reply_text(
            "👤 <b>Yo'lovchi ma'lumotlarini kiriting</b>\n\n"
            "Bu ma'lumotlar chipta xarid qilish uchun ishlatiladi.\n\n"
            "📝 <b>To'liq ismingizni</b> yuboring (pasportdagi kabi):\n"
            "<i>(Bekor qilish: /cancel)</i>",
            parse_mode="HTML",
        )
    return PASS_NAME


async def passenger_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["pass_name"] = update.message.text.strip()
    await update.message.reply_text(
        "📄 <b>Passport raqamingizni</b> yuboring:\n"
        "<i>Masalan: AA1234567</i>",
        parse_mode="HTML",
    )
    return PASS_PASSPORT


async def passenger_passport(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["pass_passport"] = update.message.text.strip().upper()
    await update.message.reply_text(
        "📱 <b>Telefon raqamingizni</b> yuboring:\n"
        "<i>Masalan: +998901234567</i>",
        parse_mode="HTML",
    )
    return PASS_PHONE


async def passenger_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    phone = update.message.text.strip()
    name = context.user_data.get("pass_name", "")
    passport = context.user_data.get("pass_passport", "")

    try:
        async with _httpx.AsyncClient(timeout=8) as client:
            r = await client.post(f"{SERVER_URL}/api/passenger", json={
                "user_id": user_id,
                "full_name": name,
                "passport": passport,
                "phone": phone,
            })
            r.raise_for_status()
        await update.message.reply_text(
            f"✅ <b>Ma'lumotlar saqlandi!</b>\n\n"
            f"👤 {name}\n"
            f"📄 {passport}\n"
            f"📱 {phone}\n\n"
            "Endi Mini App da chipta topib, <b>«🎫 Chipta olish»</b> tugmasini bosing.",
            parse_mode="HTML",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Xatolik: {e}")

    return ConversationHandler.END


# ── MINI APP DAN CHIPTA XARID SO'ROVI ────────────────────────────────────────
async def handle_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mini App dan yuborilgan chipta xarid so'rovini qabul qilish."""
    data_str = update.effective_message.web_app_data.data
    try:
        data = json.loads(data_str)
    except Exception:
        await update.message.reply_text("❌ Noto'g'ri ma'lumot.")
        return

    action = data.get("action")
    user_id = str(update.effective_user.id)

    if action == "buy":
        # Yo'lovchi ma'lumoti bormi?
        try:
            async with _httpx.AsyncClient(timeout=8) as client:
                r = await client.get(f"{SERVER_URL}/api/passenger/{user_id}")
                r.raise_for_status()
                passenger = r.json()
        except Exception:
            await update.message.reply_text(
                "⚠️ Avval yo'lovchi ma'lumotlarini kiriting!\n\n"
                "/myinfo buyrug'ini yuboring.",
                parse_mode="HTML",
            )
            return

        train = data.get("train", {})

        # Tasdiqlash so'rash
        keyboard = [[
            InlineKeyboardButton("✅ Ha, olish", callback_data=f"confirm_buy:{json.dumps(data)}"),
            InlineKeyboardButton("❌ Bekor", callback_data="cancel_buy"),
        ]]
        await update.message.reply_text(
            f"🎫 <b>Chipta xaridi</b>\n\n"
            f"🚆 {data.get('from_name')} → {data.get('to_name')}\n"
            f"📅 {data.get('date')}\n"
            f"🕐 {train.get('dep')} → {train.get('arr')} | {train.get('brand')} №{train.get('number')}\n"
            f"🪑 {train.get('car_type')}\n\n"
            f"👤 {passenger['full_name']}\n"
            f"📄 {passenger['passport']}\n\n"
            f"⚡ Chipta olishni tasdiqlaysizmi?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )


async def confirm_buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel_buy":
        await query.edit_message_text("❌ Bekor qilindi.")
        return

    user_id = str(update.effective_user.id)
    data_str = query.data.replace("confirm_buy:", "", 1)
    try:
        data = json.loads(data_str)
    except Exception:
        await query.edit_message_text("❌ Xatolik.")
        return

    await query.edit_message_text("⏳ Chipta olinmoqda... Bir daqiqa kuting.")

    train = data.get("train", {})
    try:
        async with _httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{SERVER_URL}/api/purchase", json={
                "user_id":      user_id,
                "from_code":    data.get("from_code"),
                "to_code":      data.get("to_code"),
                "from_name":    data.get("from_name"),
                "to_name":      data.get("to_name"),
                "date":         data.get("date"),
                "train_number": train.get("number"),
                "train_brand":  train.get("brand"),
                "dep_time":     train.get("dep"),
                "arr_time":     train.get("arr"),
                "car_type":     train.get("car_type"),
            })
            r.raise_for_status()
        await query.edit_message_text(
            "⏳ Chipta xaridi boshlandi!\n\n"
            "Natija 1-2 daqiqada Telegram xabar sifatida keladi.",
        )
    except Exception as e:
        await query.edit_message_text(f"❌ Xatolik: {e}")


# --- ASOSIY ---
async def post_init(application):
    """Bot ishga tushganda menu tugmasini o'rnatish."""
    if "localhost" in WEBAPP_URL or "127.0.0.1" in WEBAPP_URL:
        print(f"⚠️  WEBAPP_URL={WEBAPP_URL} — telefonda Mini App ishlamaydi; .env da HTTPS manzil qo'ying.")
        return
    await application.bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="🎫 Chipta qidirish",
            web_app=WebAppInfo(url=WEBAPP_URL),
        )
    )
    print(f"✅ Menu button: {WEBAPP_URL}")
    print(f"   BotFather'da Mini App hostname: {_webapp_domain_hint()}")


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

    # Yo'lovchi ma'lumoti
    passenger_conv = ConversationHandler(
        entry_points=[CommandHandler("myinfo", passenger_start)],
        states={
            PASS_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, passenger_name)],
            PASS_PASSPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, passenger_passport)],
            PASS_PHONE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, passenger_phone)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("yop", yop_keyboard))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_webapp_data))
    app.add_handler(CallbackQueryHandler(confirm_buy_callback, pattern="^confirm_buy:|^cancel_buy$"))
    app.add_handler(conv)
    app.add_handler(passenger_conv)

    print("✅ Bot ishga tushdi!")
    app.run_polling()


if __name__ == "__main__":
    main()
