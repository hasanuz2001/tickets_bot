"""
eticket.railway.uz — bitta umumiy login (RAILWAY_LOGIN / RAILWAY_PASSWORD) orqali avtomatik bron.
Playwright: login → poyezdlar → Купить → vagon/joy → yo'lovchi → to'lov sahifasi.
"""

import logging
import os
import re

import httpx
from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

load_dotenv()

logger = logging.getLogger(__name__)

RAILWAY = "https://eticket.railway.uz"
RAILWAY_LOGIN = os.getenv("RAILWAY_LOGIN", "").strip()
RAILWAY_PASS = os.getenv("RAILWAY_PASSWORD", "").strip()

# networkidle SPA da tez-tez osilib qoladi — asosan domcontentloaded
_WAIT = "domcontentloaded"
_HEADLESS = os.getenv("RAILWAY_AUTOMATION_HEADLESS", "true").lower() in ("1", "true", "yes")


def _browser_args() -> list[str]:
    return [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
    ]


async def _login_railway(page) -> tuple[bool, str]:
    """
    To'g'ridan-to'g'ri /ru/auth/login — SPA 'Вход' bosishdan ishonchliroq.
    """
    try:
        await page.goto(f"{RAILWAY}/ru/auth/login", wait_until=_WAIT, timeout=35000)
    except Exception as e:
        return False, f"Login sahifasini ochib bo'lmadi: {e}"

    await page.wait_for_timeout(900)

    if "@" in RAILWAY_LOGIN:
        for sel in (
            "button:has-text('ПОЧТА')",
            "span:has-text('ПОЧТА')",
            "div[role='tab']:has-text('ПОЧТА')",
            "a:has-text('ПОЧТА')",
        ):
            tab = page.locator(sel).first
            if await tab.count():
                try:
                    await tab.click(timeout=3000)
                    await page.wait_for_timeout(600)
                    logger.info("[railway] ПОЧТА tab")
                except Exception:
                    pass
                break

    try:
        login_el = page.locator("input[type='email']").first
        if not await login_el.count():
            login_el = page.locator("input[name*='mail' i], input[name*='email' i]").first
        if not await login_el.count():
            login_el = page.locator("form input[type='text']").first
        await login_el.fill(RAILWAY_LOGIN, timeout=12000)
        await page.locator("input[type='password']").first.fill(RAILWAY_PASS, timeout=8000)

        submit = page.locator(
            "button:has-text('ВОЙТИ'), button:has-text('Войти'), "
            "button[type='submit']"
        ).first
        await submit.click(timeout=8000)
    except Exception as e:
        return False, f"Login formani to'ldirishda xato: {e}"

    await page.wait_for_timeout(2800)

    url = page.url
    if "/auth/login" in url:
        return False, (
            "Kirish amalga oshmadi (login sahifasida qoldi). "
            "Login/parol yoki sayt captcha/blokirovka bo'lishi mumkin."
        )

    logger.info("[railway] Login muvaffaq: %s", url[:80])
    return True, "ok"


async def _click_buy_for_train(page, train_number: str) -> bool:
    """Tanlangan poyezd qatoridagi sotib olish tugmasi (RU/UZ)."""
    tnum = str(train_number).strip()
    if not tnum:
        return False

    marker = page.locator(f"text=№{tnum}").first
    if not await marker.count():
        marker = page.get_by_text(re.compile(rf"№\s*{re.escape(tnum)}\b")).first
    if not await marker.count():
        marker = page.locator(f"text={tnum}").first

    if not await marker.count():
        logger.warning("[buy] Poyezd №%s topilmadi", tnum)
        return False

    await marker.scroll_into_view_if_needed()
    await page.wait_for_timeout(400)

    buy_xpath = (
        "xpath=ancestor::*[.//button["
        "contains(., 'Купить') or contains(., 'Sotib') or contains(., 'Xarid')"
        "]][1]//button["
        "contains(., 'Купить') or contains(., 'Sotib') or contains(., 'Xarid')"
        "][1]"
    )
    buy_btn = marker.locator(buy_xpath).first
    if not await buy_btn.count():
        buy_btn = marker.locator(
            "xpath=following::button["
            "contains(., 'Купить') or contains(., 'Sotib') or contains(., 'Xarid')"
            "][1]"
        ).first
    if not await buy_btn.count():
        logger.warning("[buy] Sotib olish tugmasi topilmadi (№%s)", tnum)
        return False

    await buy_btn.click(timeout=12000)
    await page.wait_for_timeout(2200)
    return True


async def _pick_car_and_seat(page, car_type: str) -> None:
    """Vagon turi va birinchi bo'sh joy."""
    if car_type and str(car_type).strip():
        ct = str(car_type).strip()
        for loc in (
            page.get_by_role("button", name=re.compile(re.escape(ct), re.I)),
            page.locator(f"button:has-text('{ct}')").first,
            page.locator(f"text={ct}").first,
        ):
            try:
                if hasattr(loc, "count") and await loc.count():
                    await loc.click(timeout=5000)
                    await page.wait_for_timeout(900)
                    break
            except Exception:
                continue

    seat_selectors = [
        "button.seat:not(.disabled)",
        "[class*='Seat']:not([class*='disabled']):not([class*='occupied'])",
        "[class*='seat-free']",
        "button[data-seat]",
        "[class*='place']:not([class*='busy'])",
    ]
    for sel in seat_selectors:
        btn = page.locator(sel).first
        if await btn.count():
            try:
                await btn.click(timeout=5000)
                await page.wait_for_timeout(1000)
                logger.info("[buy] Joy tanlandi: %s", sel)
                return
            except Exception:
                continue
    logger.warning("[buy] Avtomatik joy tanlash topilmadi (keyingi bosqichga o'tiladi)")


async def _fill_passenger(page, passenger: dict) -> None:
    name = (passenger.get("full_name") or "").strip()
    passport = (passenger.get("passport") or "").strip()
    phone = (passenger.get("phone") or "").strip()

    if name:
        for sel in (
            "input[type='email']",
            "input[placeholder*='Имя']",
            "input[placeholder*='ФИО']",
            "input[placeholder*='Ism']",
            "input[name*='name']",
        ):
            el = page.locator(sel).first
            if await el.count():
                try:
                    await el.fill(name, timeout=5000)
                    break
                except Exception:
                    pass

    if passport:
        for sel in (
            "input[placeholder*='Серия']",
            "input[placeholder*='Паспорт']",
            "input[placeholder*='Passport']",
            "input[name*='passport']",
        ):
            el = page.locator(sel).first
            if await el.count():
                try:
                    await el.fill(passport, timeout=5000)
                    break
                except Exception:
                    pass

    if phone:
        for sel in (
            "input[type='tel']",
            "input[placeholder*='Телефон']",
            "input[placeholder*='Telefon']",
            "input[placeholder*='phone']",
        ):
            el = page.locator(sel).first
            if await el.count():
                try:
                    await el.fill(phone, timeout=5000)
                    break
                except Exception:
                    pass


async def _click_continue_to_payment(page) -> bool:
    names = (
        "Продолжить",
        "Далее",
        "Davom",
        "К оплате",
        "To'lov",
        "Тўлов",
        "Оплатить",
    )
    for n in names:
        btn = page.get_by_role("button", name=re.compile(re.escape(n), re.I)).first
        if await btn.count():
            try:
                await btn.click(timeout=8000)
                await page.wait_for_timeout(2000)
                return True
            except Exception:
                continue
    legacy = page.locator(
        "button:has-text('Продолжить'), button:has-text('Далее'), "
        "button:has-text('К оплате'), button:has-text('Davom')"
    ).first
    if await legacy.count():
        try:
            await legacy.click(timeout=8000)
            await page.wait_for_timeout(2000)
            return True
        except Exception:
            pass
    return False


def _looks_like_payment_step(url: str, content_snippet: str) -> bool:
    u = url.lower()
    if any(x in u for x in ("pay", "payment", "oplata", "tolov", "checkout", "order")):
        return True
    c = content_snippet.lower()
    return any(x in c for x in ("оплат", "to'lov", "тўлов", "payment", "payme", "click"))


async def open_ticket_page(
    from_code: str,
    to_code: str,
    date: str,
    train_number: str,
) -> dict:
    trains_url = (
        f"{RAILWAY}/uz/pages/trains-page"
        f"?depCode={from_code}&arvCode={to_code}&date={date}"
    )

    if not RAILWAY_LOGIN or not RAILWAY_PASS:
        return {
            "success": False,
            "screenshot": None,
            "url": trains_url,
            "message": "⚠️ Serverda RAILWAY_LOGIN / RAILWAY_PASSWORD yo'q.",
        }

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=_HEADLESS, args=_browser_args())
        context = await browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="ru-RU",
        )
        page = await context.new_page()

        try:
            ok, msg = await _login_railway(page)
            if not ok:
                scr = await page.screenshot(full_page=True)
                await browser.close()
                return {"success": False, "screenshot": scr, "url": page.url, "message": msg}

            await page.goto(trains_url, wait_until=_WAIT, timeout=35000)
            await page.wait_for_timeout(2000)

            clicked = False
            try:
                await page.wait_for_selector(
                    "[class*='train'], [class*='Train'], .result-card, article",
                    timeout=20000,
                )
                clicked = await _click_buy_for_train(page, train_number)
            except PWTimeout:
                logger.warning("[open_ticket] Ro'yxat kutilmadi")

            scr = await page.screenshot(full_page=False)
            return {
                "success": True,
                "screenshot": scr,
                "url": page.url if clicked else trains_url,
                "message": "✅ To'lov bosqichiga yaqin" if clicked else "ℹ️ Poyezdlar sahifasi",
            }
        except Exception as e:
            logger.exception("[open_ticket] %s", e)
            scr = None
            try:
                scr = await page.screenshot(full_page=False)
            except Exception:
                pass
            return {
                "success": False,
                "screenshot": scr,
                "url": trains_url,
                "message": f"Xato: {type(e).__name__}: {e}",
            }
        finally:
            await browser.close()


async def buy_ticket(
    from_code: str,
    to_code: str,
    from_name: str,
    to_name: str,
    date: str,
    train_number: str,
    car_type: str,
    passenger: dict,
) -> dict:
    if not RAILWAY_LOGIN or not RAILWAY_PASS:
        return {"status": "error", "message": "RAILWAY_LOGIN/PASSWORD .env da yo'q.", "screenshot": None}
    if not from_code or not to_code:
        return {
            "status": "error",
            "message": "from_code / to_code kerak.",
            "screenshot": None,
        }

    trains_url = (
        f"{RAILWAY}/uz/pages/trains-page"
        f"?depCode={from_code}&arvCode={to_code}&date={date}"
    )

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=_HEADLESS, args=_browser_args())
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="ru-RU",
        )
        page = await context.new_page()

        try:
            ok, msg = await _login_railway(page)
            if not ok:
                scr = await page.screenshot(full_page=True)
                return {"status": "error", "message": msg, "screenshot": scr}

            logger.info("[buy_ticket] Trains: %s", trains_url)
            await page.goto(trains_url, wait_until=_WAIT, timeout=35000)
            await page.wait_for_timeout(2200)

            await page.wait_for_selector(
                "[class*='train'], [class*='Train'], .result-card, article",
                timeout=25000,
            )

            if not await _click_buy_for_train(page, train_number):
                scr = await page.screenshot(full_page=True)
                return {
                    "status": "error",
                    "message": f"Poyezd №{train_number} yoki sotib olish tugmasi topilmadi.",
                    "screenshot": scr,
                }

            await _pick_car_and_seat(page, car_type or "")
            await page.wait_for_timeout(800)
            await _fill_passenger(page, passenger)
            await page.wait_for_timeout(600)

            await _click_continue_to_payment(page)

            screenshot = await page.screenshot(full_page=False)
            final_url = page.url
            try:
                snippet = await page.inner_text("body")
                snippet = snippet[:4000]
            except Exception:
                snippet = ""

            paid = _looks_like_payment_step(final_url, snippet)
            logger.info("[buy_ticket] Yakun URL: %s | to'lovga o'xshaydi: %s", final_url[:100], paid)

            if paid:
                return {
                    "status": "success",
                    "message": f"✅ To'lov sahifasiga yetildi.\n🔗 {final_url}",
                    "screenshot": screenshot,
                }
            return {
                "status": "partial",
                "message": (
                    "⚠️ Avtomatik bosqich yakunlandi; to'lov sahifasi aniq emas. "
                    f"Sahifani tekshiring:\n🔗 {final_url}"
                ),
                "screenshot": screenshot,
            }

        except Exception as e:
            logger.exception("[buy_ticket] %s", e)
            scr = None
            try:
                scr = await page.screenshot(full_page=True)
            except Exception:
                pass
            return {
                "status": "error",
                "message": f"Xarid: {type(e).__name__}: {e}",
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
    """Bilet topilganda screenshot + havola."""
    result = await open_ticket_page(
        from_code=sub["from_code"],
        to_code=sub["to_code"],
        date=sub["date"],
        train_number=train["number"],
    )

    tg = f"https://api.telegram.org/bot{bot_token}"

    if result["screenshot"]:
        async with httpx.AsyncClient(timeout=25) as client:
            await client.post(
                f"{tg}/sendPhoto",
                data={"chat_id": user_id, "caption": "📸 Avtomatik ochilgan sahifa"},
                files={"photo": ("screen.png", result["screenshot"], "image/png")},
            )

    time_info = ""
    if sub.get("time_from") or sub.get("time_to"):
        time_info = f"\n⏰ {sub.get('time_from','00:00')} — {sub.get('time_to','23:59')}"

    seats_lines = []
    for s in train["seats"][:3]:
        price = f"{int(float(s['price'])):,} so'm" if s.get("price") is not None else "—"
        seats_lines.append(f"  🪑 {s['type']}: <b>{s['free']} joy</b> | {price}")

    text = (
        f"🎫 <b>Bilet mavjud!</b>\n\n"
        f"🚆 <b>{sub['from_name']} → {sub['to_name']}</b>\n"
        f"📅 {sub['date']}{time_info}\n\n"
        f"🕐 <b>{train['dep']} → {train['arr']}</b>  |  {train['brand']} №{train['number']}\n"
        + "\n".join(seats_lines)
        + f"\n\n{result['message']}"
    )

    keyboard = {"inline_keyboard": [[{"text": "💳 Saytga o'tish", "url": result["url"]}]]}

    async with httpx.AsyncClient(timeout=15) as client:
        await client.post(
            f"{tg}/sendMessage",
            json={
                "chat_id": user_id,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": keyboard,
            },
        )
