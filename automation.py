"""
eticket.railway.uz avtomatik bron jarayoni
Playwright bilan: login → poyezd topish → joy tanlash → to'lov sahifasiga o'tish
"""

import asyncio
import logging
import os
import sqlite3
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

RAILWAY = "https://eticket.railway.uz"
DB_PATH = os.getenv("DB_PATH", "subscriptions.db")


def get_user_credentials(user_id: str) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT login, password FROM user_credentials WHERE user_id=?", (user_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


async def open_ticket_page(
    user_id: str,
    from_code: str,
    to_code: str,
    date: str,
    train_number: str,
    time_from: str = None,
    time_to: str = None,
) -> dict:
    """
    Returns:
        {
          "success": True/False,
          "screenshot": bytes | None,   # PNG screenshot
          "url": str,                   # URL foydalanuvchiga yuboriladigan
          "message": str,               # Holat xabari
        }
    """
    creds = get_user_credentials(user_id)
    if not creds:
        return {
            "success": False,
            "screenshot": None,
            "url": f"{RAILWAY}/ru/train/{from_code}/{to_code}/{date}",
            "message": "Login ma'lumotlari topilmadi. /login buyrug'ini yuboring.",
        }

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        context = await browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
            locale="ru-RU",
        )
        page = await context.new_page()

        try:
            # ── 1. Login ──────────────────────────────────────────
            logger.info(f"[automation] Logging in for user {user_id}...")
            await page.goto(f"{RAILWAY}/ru/home", wait_until="networkidle", timeout=20000)

            # Login tugmasini bosish
            await page.click("a[href*='login'], a:has-text('Вход'), button:has-text('Войти')", timeout=5000)
            await page.wait_for_timeout(1000)

            # Email/telefon va parol
            await page.fill("input[type='email'], input[type='text'][placeholder*='mail'], input[name='email']",
                            creds["login"], timeout=5000)
            await page.fill("input[type='password']", creds["password"], timeout=5000)
            await page.click("button[type='submit'], button:has-text('Войти'), button:has-text('Кириш')",
                             timeout=5000)

            await page.wait_for_timeout(2000)
            logger.info(f"[automation] Login done, current URL: {page.url}")

            # ── 2. Qidiruv sahifasiga o'tish ──────────────────────
            search_url = f"{RAILWAY}/ru/home"
            await page.goto(search_url, wait_until="networkidle", timeout=20000)
            await page.wait_for_timeout(1000)

            # ── 3. Poyezdlar ro'yxatiga to'g'ridan o'tish ─────────
            # Trains page URL with query params
            trains_url = (
                f"{RAILWAY}/uz/pages/trains-page?"
                f"depCode={from_code}&arvCode={to_code}&date={date}"
            )
            logger.info(f"[automation] Navigating to trains: {trains_url}")
            await page.goto(trains_url, wait_until="networkidle", timeout=25000)
            await page.wait_for_timeout(2000)

            # ── 4. Kerakli poyezdni topish va bosish ──────────────
            screenshot_bytes = None
            clicked = False

            # Poyezd kartochkalarini kutish
            try:
                await page.wait_for_selector(".train-card, [class*='train'], [class*='Train']",
                                             timeout=10000)
                # Train number bo'yicha qidirish
                locator = page.locator(f"text={train_number}").first
                if await locator.count() > 0:
                    # Scroll to it
                    await locator.scroll_into_view_if_needed()
                    await page.wait_for_timeout(500)

                    # Screenshot train kartochkasini
                    screenshot_bytes = await page.screenshot(full_page=False)

                    # "Купить" tugmasini topish va bosish
                    buy_btn = page.locator(
                        f"text={train_number} >> .. >> .. >> button:has-text('Купить'), "
                        f"text={train_number} >> .. >> button:has-text('Buy')"
                    ).first
                    if await buy_btn.count() > 0:
                        await buy_btn.click()
                        await page.wait_for_timeout(2000)
                        screenshot_bytes = await page.screenshot(full_page=False)
                        clicked = True
                        logger.info(f"[automation] Clicked Buy for train {train_number}")
                    else:
                        logger.warning(f"[automation] Buy button not found for {train_number}")
                else:
                    logger.warning(f"[automation] Train {train_number} not found on page")

            except PWTimeout:
                logger.warning("[automation] Train list timeout")

            if screenshot_bytes is None:
                screenshot_bytes = await page.screenshot(full_page=False)

            final_url = page.url
            logger.info(f"[automation] Final URL: {final_url}")

            return {
                "success": True,
                "screenshot": screenshot_bytes,
                "url": final_url if clicked else trains_url,
                "message": (
                    f"✅ {train_number} poyezdiga joy tanlash sahifasi ochildi"
                    if clicked else
                    f"ℹ️ Poyezdlar sahifasi tayyorlandi ({train_number} topilmadi)"
                ),
            }

        except Exception as e:
            logger.error(f"[automation] Error: {e}")
            screenshot_bytes = None
            try:
                screenshot_bytes = await page.screenshot(full_page=False)
            except Exception:
                pass
            return {
                "success": False,
                "screenshot": screenshot_bytes,
                "url": f"{RAILWAY}/uz/pages/trains-page?depCode={from_code}&arvCode={to_code}&date={date}",
                "message": f"Avtomatik ochishda xatolik: {type(e).__name__}",
            }
        finally:
            await browser.close()


async def send_booking_notification(
    user_id: str,
    sub: dict,
    train: dict,
    bot_token: str,
):
    """Bilet topilganda notification + screenshot yuborish."""
    import httpx

    result = await open_ticket_page(
        user_id    = user_id,
        from_code  = sub["from_code"],
        to_code    = sub["to_code"],
        date       = sub["date"],
        train_number = train["number"],
        time_from  = sub.get("time_from"),
        time_to    = sub.get("time_to"),
    )

    tg_api = f"https://api.telegram.org/bot{bot_token}"

    # ── Screenshot yuborish ───────────────────────────────────────────────────
    if result["screenshot"]:
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(
                f"{tg_api}/sendPhoto",
                data={"chat_id": user_id, "caption": "📸 To'lov sahifasi"},
                files={"photo": ("screen.png", result["screenshot"], "image/png")},
            )

    # ── Asosiy xabar + havola tugmasi ────────────────────────────────────────
    time_info = ""
    if sub.get("time_from") or sub.get("time_to"):
        time_info = f"\n⏰ {sub.get('time_from','00:00')} — {sub.get('time_to','23:59')}"

    seats_text = "\n".join(
        f"  🪑 {s['type']}: <b>{s['free']} joy</b> | "
        f"{int(s['price']):,} so'm" if s.get("price") else f"  🪑 {s['type']}: {s['free']} joy"
        for s in train["seats"][:3]
    )

    text = (
        f"🎫 <b>Bilet mavjud!</b>\n\n"
        f"🚆 <b>{sub['from_name']} → {sub['to_name']}</b>\n"
        f"📅 {sub['date']}{time_info}\n\n"
        f"🕐 <b>{train['dep']} → {train['arr']}</b>  |  {train['brand']} №{train['number']}\n"
        f"{seats_text}\n\n"
        f"{result['message']}"
    )

    keyboard = {
        "inline_keyboard": [[
            {"text": "💳 To'lovni yakunlash", "url": result["url"]}
        ]]
    }

    import json
    async with httpx.AsyncClient(timeout=15) as client:
        await client.post(
            f"{tg_api}/sendMessage",
            json={
                "chat_id":    user_id,
                "text":       text,
                "parse_mode": "HTML",
                "reply_markup": keyboard,
            },
        )
