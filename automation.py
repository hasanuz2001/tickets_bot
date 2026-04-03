"""
eticket.railway.uz avtomatik bron jarayoni
Umumiy login bilan: login → poyezd → to'lov sahifasi → screenshot
"""

import asyncio
import logging
import os

import httpx
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

RAILWAY       = "https://eticket.railway.uz"
RAILWAY_LOGIN = os.getenv("RAILWAY_LOGIN", "")
RAILWAY_PASS  = os.getenv("RAILWAY_PASSWORD", "")


async def open_ticket_page(
    from_code: str,
    to_code: str,
    date: str,
    train_number: str,
) -> dict:
    """
    Returns:
        success    : bool
        screenshot : bytes | None
        url        : str   — to'lov sahifasi yoki qidiruv sahifasi
        message    : str
    """
    trains_url = (
        f"{RAILWAY}/uz/pages/trains-page"
        f"?depCode={from_code}&arvCode={to_code}&date={date}"
    )

    if not RAILWAY_LOGIN or not RAILWAY_PASS:
        return {
            "success": False, "screenshot": None,
            "url": trains_url,
            "message": "⚠️ Server da RAILWAY_LOGIN va RAILWAY_PASSWORD o'rnatilmagan.",
        }

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
            ),
            locale="ru-RU",
        )
        page = await context.new_page()

        try:
            # ── 1. Asosiy sahifani ochish ──────────────────────────
            logger.info("[automation] Opening home page...")
            await page.goto(f"{RAILWAY}/ru/home", wait_until="networkidle", timeout=25000)
            await page.wait_for_timeout(1500)

            # ── 2. Login sahifasiga o'tish ─────────────────────────
            logger.info("[automation] Navigating to login...")
            await page.goto(f"{RAILWAY}/ru/login", wait_until="networkidle", timeout=15000)
            await page.wait_for_timeout(1000)

            # Email / telefon
            email_input = page.locator(
                "input[type='email'], input[name='email'], "
                "input[placeholder*='mail'], input[placeholder*='Телефон']"
            ).first
            await email_input.fill(RAILWAY_LOGIN, timeout=8000)

            # Parol
            pass_input = page.locator("input[type='password']").first
            await pass_input.fill(RAILWAY_PASS, timeout=5000)

            # Login tugmasi
            await page.locator(
                "button[type='submit'], button:has-text('Войти'), button:has-text('Kirish')"
            ).first.click(timeout=5000)

            await page.wait_for_timeout(2500)
            logger.info(f"[automation] After login: {page.url}")

            # ── 3. Poyezdlar sahifasiga o'tish ────────────────────
            logger.info(f"[automation] Going to trains page: {trains_url}")
            await page.goto(trains_url, wait_until="networkidle", timeout=25000)
            await page.wait_for_timeout(2000)

            # ── 4. Kerakli poyezdni topish ────────────────────────
            screenshot = None
            clicked    = False

            try:
                # Poyezd kartochkalarini kut
                await page.wait_for_selector(
                    "[class*='train'], [class*='Train'], .result-card",
                    timeout=12000,
                )

                # Train number matni bor elementni topish
                train_locator = page.locator(f"text=№{train_number}").first
                if not await train_locator.count():
                    train_locator = page.locator(f"text={train_number}").first

                if await train_locator.count():
                    await train_locator.scroll_into_view_if_needed()
                    await page.wait_for_timeout(500)
                    screenshot = await page.screenshot(full_page=False)

                    # "Купить" / "Sotib olish" tugmasini topish
                    buy_btn = page.locator(
                        "button:has-text('Купить'), button:has-text('Sotib olish'), "
                        "button:has-text('Buy'), a:has-text('Купить')"
                    ).first
                    if await buy_btn.count():
                        await buy_btn.click()
                        await page.wait_for_timeout(2500)
                        screenshot = await page.screenshot(full_page=False)
                        clicked = True
                        logger.info(f"[automation] Clicked Buy for {train_number}")
                    else:
                        logger.info(f"[automation] Buy button not found near {train_number}")
                else:
                    logger.info(f"[automation] Train {train_number} not found, taking page screenshot")

            except PWTimeout:
                logger.warning("[automation] Train list timeout")

            if screenshot is None:
                screenshot = await page.screenshot(full_page=False)

            final_url = page.url
            return {
                "success":    True,
                "screenshot": screenshot,
                "url":        final_url if clicked else trains_url,
                "message":    (
                    f"✅ To'lov sahifasi tayyor!"
                    if clicked else
                    f"ℹ️ Poyezdlar sahifasi ochildi"
                ),
            }

        except Exception as e:
            logger.error(f"[automation] Error: {e}")
            scr = None
            try:
                scr = await page.screenshot(full_page=False)
            except Exception:
                pass
            return {
                "success": False, "screenshot": scr,
                "url": trains_url,
                "message": f"Avtomatik ochishda xatolik ({type(e).__name__})",
            }
        finally:
            await browser.close()


async def send_booking_notification(
    user_id: str,
    sub: dict,
    train: dict,
    bot_token: str,
):
    """Bilet topilganda screenshot + to'lov havolasi yuborish."""
    result = await open_ticket_page(
        from_code    = sub["from_code"],
        to_code      = sub["to_code"],
        date         = sub["date"],
        train_number = train["number"],
    )

    tg = f"https://api.telegram.org/bot{bot_token}"

    # Screenshot
    if result["screenshot"]:
        async with httpx.AsyncClient(timeout=20) as client:
            await client.post(
                f"{tg}/sendPhoto",
                data={"chat_id": user_id, "caption": "📸 To'lov sahifasi"},
                files={"photo": ("screen.png", result["screenshot"], "image/png")},
            )

    # Asosiy xabar
    time_info = ""
    if sub.get("time_from") or sub.get("time_to"):
        time_info = f"\n⏰ {sub.get('time_from','00:00')} — {sub.get('time_to','23:59')}"

    seats_lines = []
    for s in train["seats"][:3]:
        price = f"{int(s['price']):,} so'm" if s.get("price") else "—"
        seats_lines.append(f"  🪑 {s['type']}: <b>{s['free']} joy</b> | {price}")

    text = (
        f"🎫 <b>Bilet mavjud!</b>\n\n"
        f"🚆 <b>{sub['from_name']} → {sub['to_name']}</b>\n"
        f"📅 {sub['date']}{time_info}\n\n"
        f"🕐 <b>{train['dep']} → {train['arr']}</b>  |  {train['brand']} №{train['number']}\n"
        + "\n".join(seats_lines)
        + f"\n\n{result['message']}"
    )

    keyboard = {"inline_keyboard": [[
        {"text": "💳 To'lovni yakunlash", "url": result["url"]}
    ]]}

    async with httpx.AsyncClient(timeout=15) as client:
        await client.post(f"{tg}/sendMessage", json={
            "chat_id":      user_id,
            "text":         text,
            "parse_mode":   "HTML",
            "reply_markup": keyboard,
        })
