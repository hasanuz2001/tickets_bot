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
            # "Вход" havolasini JS orqali bosish (SPA router link)
            logger.info("[automation] Clicking login link...")
            await page.evaluate(
                "() => { const a = Array.from(document.querySelectorAll('a'))"
                ".find(el => el.textContent.trim() === 'Вход'); if(a) a.click(); }"
            )
            await page.wait_for_url("**/auth/login", timeout=8000)
            await page.wait_for_timeout(1000)
            logger.info(f"[automation] Login page: {page.url}")

            # Email bilan kirish uchun "ПОЧТА" tabini bosish
            is_email = "@" in RAILWAY_LOGIN
            if is_email:
                pochta_tab = page.locator(
                    "button:has-text('ПОЧТА'), span:has-text('ПОЧТА'), div:has-text('ПОЧТА')"
                ).first
                if await pochta_tab.count():
                    await pochta_tab.click()
                    await page.wait_for_timeout(800)
                    logger.info("[automation] Switched to email tab")

            # Login field (email yoki telefon)
            login_input = page.locator("input[type='email'], input[type='text']").first
            await login_input.fill(RAILWAY_LOGIN, timeout=8000)

            # Parol
            await page.locator("input[type='password']").first.fill(RAILWAY_PASS, timeout=5000)

            # ВОЙТИ tugmasi
            await page.locator(
                "button:has-text('ВОЙТИ'), button:has-text('Войти'), button[type='submit']"
            ).first.click(timeout=5000)

            await page.wait_for_timeout(3000)
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


async def buy_ticket(
    from_name: str,
    to_name: str,
    date: str,
    train_number: str,
    car_type: str,
    passenger: dict,
) -> dict:
    """
    Chipta xarid qilish:
    login → poyezd → joy tanlash → yo'lovchi ma'lumot → to'lov sahifasi
    """
    if not RAILWAY_LOGIN or not RAILWAY_PASS:
        return {"status": "error", "message": "RAILWAY_LOGIN/PASSWORD o'rnatilmagan.", "screenshot": None}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="ru-RU",
        )
        page = await context.new_page()

        try:
            # ── 1. Login ──────────────────────────────────────────
            logger.info(f"[buy_ticket] Opening home page...")
            await page.goto(f"{RAILWAY}/ru/home", wait_until="networkidle", timeout=25000)

            await page.evaluate(
                "() => { const a = Array.from(document.querySelectorAll('a'))"
                ".find(el => el.textContent.trim() === 'Вход'); if(a) a.click(); }"
            )
            await page.wait_for_url("**/auth/login", timeout=8000)
            await page.wait_for_timeout(1000)

            # Email tab
            if "@" in RAILWAY_LOGIN:
                pochta = page.locator("button:has-text('ПОЧТА'), span:has-text('ПОЧТА')").first
                if await pochta.count():
                    await pochta.click()
                    await page.wait_for_timeout(600)

            await page.locator("input[type='email'], input[type='text']").first.fill(RAILWAY_LOGIN, timeout=8000)
            await page.locator("input[type='password']").first.fill(RAILWAY_PASS, timeout=5000)
            await page.locator("button:has-text('ВОЙТИ'), button[type='submit']").first.click(timeout=5000)
            await page.wait_for_timeout(3000)
            logger.info(f"[buy_ticket] After login: {page.url}")

            # ── 2. Poyezdlar sahifasi ──────────────────────────────
            # Avval qidiruv orqali boramiz
            await page.goto(f"{RAILWAY}/ru/home", wait_until="networkidle", timeout=20000)
            await page.wait_for_timeout(1500)

            # ── 3. Poyezdni topish va "Купить" bosish ─────────────
            trains_url = f"{RAILWAY}/uz/pages/trains-page?date={date}"
            await page.goto(trains_url, wait_until="networkidle", timeout=25000)
            await page.wait_for_timeout(2500)

            # Poyezdni qidirish
            await page.wait_for_selector("[class*='train'], [class*='Train']", timeout=12000)

            train_el = page.locator(f"text=№{train_number}, text={train_number}").first
            if await train_el.count():
                await train_el.scroll_into_view_if_needed()
                await page.wait_for_timeout(500)

            # "Купить" tugmasi
            buy_btn = page.locator(
                "button:has-text('Купить'), button:has-text('Sotib olish')"
            ).first
            if await buy_btn.count():
                await buy_btn.click()
                await page.wait_for_timeout(2000)
                logger.info("[buy_ticket] Clicked Buy button")
            else:
                scr = await page.screenshot(full_page=False)
                return {"status": "error", "message": "Купить tugmasi topilmadi.", "screenshot": scr}

            # ── 4. Joy turi tanlash ────────────────────────────────
            if car_type:
                car_btn = page.locator(f"text={car_type}").first
                if await car_btn.count():
                    await car_btn.click()
                    await page.wait_for_timeout(1000)

            # Birinchi mavjud joy
            seat_btn = page.locator(
                "button.seat:not(.disabled), [class*='seat']:not([class*='occupied']), [class*='free']"
            ).first
            if await seat_btn.count():
                await seat_btn.click()
                await page.wait_for_timeout(1000)

            # ── 5. Yo'lovchi ma'lumotini to'ldirish ───────────────
            await page.wait_for_timeout(1500)

            # Ism-familiya
            name_inputs = page.locator("input[placeholder*='Имя'], input[placeholder*='ФИО'], input[name*='name']")
            if await name_inputs.count():
                await name_inputs.first.fill(passenger["full_name"], timeout=5000)

            # Passport
            passport_input = page.locator(
                "input[placeholder*='Серия'], input[placeholder*='Паспорт'], input[name*='passport']"
            ).first
            if await passport_input.count():
                await passport_input.fill(passenger["passport"], timeout=5000)

            # Telefon
            phone_input = page.locator(
                "input[type='tel'], input[placeholder*='Телефон'], input[placeholder*='phone']"
            ).first
            if await phone_input.count():
                await phone_input.fill(passenger["phone"], timeout=5000)

            await page.wait_for_timeout(1000)

            # ── 6. To'lov sahifasiga o'tish ───────────────────────
            next_btn = page.locator(
                "button:has-text('Продолжить'), button:has-text('Далее'), "
                "button:has-text('Davom'), button:has-text('К оплате')"
            ).first
            if await next_btn.count():
                await next_btn.click()
                await page.wait_for_timeout(2000)

            screenshot = await page.screenshot(full_page=False)
            final_url = page.url

            logger.info(f"[buy_ticket] Final URL: {final_url}")
            return {
                "status":     "success",
                "message":    f"✅ To'lov sahifasi tayyor!\n🔗 {final_url}",
                "screenshot": screenshot,
            }

        except Exception as e:
            logger.error(f"[buy_ticket] Error: {e}")
            scr = None
            try:
                scr = await page.screenshot(full_page=False)
            except Exception:
                pass
            return {
                "status":     "error",
                "message":    f"Xarid jarayonida xatolik: {type(e).__name__}: {e}",
                "screenshot": scr,
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
