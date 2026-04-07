"""
eticket.railway.uz — RAILWAY_LOGIN: telefon (9 yoki 998...) yoki email (@), RAILWAY_PASSWORD.
Default UI: o'zbekcha (/uz/auth/login, /uz/pages/...). RAILWAY_UI_LANG=ru — ruscha sahifa.
"""

import json
import logging
import os
import re
from datetime import datetime
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

load_dotenv()

logger = logging.getLogger(__name__)

RAILWAY = "https://eticket.railway.uz"
# Barcha avtomatika o'zbek interfeysi: /uz/auth/login, /uz/pages/trains-page
RAILWAY_UI_LANG = os.getenv("RAILWAY_UI_LANG", "uz").strip().lower() or "uz"
RAILWAY_LOGIN = os.getenv("RAILWAY_LOGIN", "").strip()
RAILWAY_PASS = os.getenv("RAILWAY_PASSWORD", "").strip()
_BROWSER_LOCALE = "uz-UZ" if RAILWAY_UI_LANG.startswith("uz") else "ru-RU"


def _trains_page_url(
    from_code: str,
    to_code: str,
    from_name: str,
    to_name: str,
    date_iso: str,
    lang: str | None = None,
) -> str:
    """
    SPA depCode/arvCode ni URL dan o'qimaydi. Query: sd-value (YYYY-MM-DD), sf-code/st-code,
    sf-name/st-name; sd-value2 bo'sh — faqat yo'nalish.
    """
    if lang is None:
        lang = RAILWAY_UI_LANG
    pairs = [
        ("sd-value", date_iso),
        ("sd-value2", ""),
        ("sf-code", str(from_code)),
        ("st-code", str(to_code)),
        ("sf-name", (from_name or "").strip() or str(from_code)),
        ("st-name", (to_name or "").strip() or str(to_code)),
    ]
    return f"{RAILWAY}/{lang}/pages/trains-page?{urlencode(pairs)}"


def _iso_to_railway_dmy(date_iso: str) -> str:
    """
    Angular dateSelect: forwardDate = DD-MM-YYYY (chiziqlar).
    savedData / sessionStorage uchun.
    """
    raw = (date_iso or "").strip()[:10]
    dt = datetime.strptime(raw, "%Y-%m-%d")
    return dt.strftime("%d-%m-%Y")


def _iso_to_railway_dotted(date_iso: str) -> str:
    """Maskali maydon: DD.MM.YYYY (sayt dateMask nuqta bilan)."""
    raw = (date_iso or "").strip()[:10]
    dt = datetime.strptime(raw, "%Y-%m-%d")
    return dt.strftime("%d.%m.%Y")


async def _angular_set_input_value(locator, value: str) -> bool:
    """
    fill() ba'zan Angular FormControl ni yangilamaydi (yashirin input, mask).
    Native value setter + input/change — model sinxron bo'ladi.
    """
    try:
        h = await locator.element_handle(timeout=4000)
        if not h:
            return False
        await h.evaluate(
            """(el, v) => {
                const proto = window.HTMLInputElement.prototype;
                const desc = Object.getOwnPropertyDescriptor(proto, 'value');
                if (desc && desc.set) desc.set.call(el, v);
                else el.value = v;
                try {
                  el.dispatchEvent(new InputEvent('input', {
                    bubbles: true, cancelable: true, inputType: 'insertFromPaste', data: v
                  }));
                } catch (e) {
                  el.dispatchEvent(new Event('input', { bubbles: true }));
                }
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('blur', { bubbles: true }));
            }""",
            value,
        )
        await h.dispose()
        return True
    except Exception:
        return False


async def _read_input_value_safe(locator) -> str:
    try:
        return (await locator.input_value()) or ""
    except Exception:
        return ""


def _date_field_value_ok(visible: str, dotted: str, date_iso: str) -> bool:
    v = (visible or "").strip()
    if not v:
        return False
    if v == dotted or dotted in v:
        return True
    raw = (date_iso or "").strip()[:10]
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return False
    for fmt in (
        f"{dt.day:02d}.{dt.month:02d}.{dt.year}",
        f"{dt.day}.{dt.month}.{dt.year}",
        f"{dt.day:02d}.{dt.month:02d}.{dt.year % 100:02d}",
    ):
        if fmt in v:
            return True
    return False


async def _dismiss_railway_overlays(page) -> None:
    """
    'Chiptaning haqiqiyligini tekshiring' va boshqa overlaylar sana/Izlash ustiga chiqadi.
    """
    for _ in range(2):
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(350)
    for sel in (
        ".cdk-overlay-backdrop",
        ".modal-backdrop",
        "[class*='backdrop']",
    ):
        bd = page.locator(sel).first
        try:
            if await bd.count() and await bd.is_visible():
                await bd.click(timeout=1500, force=True)
                await page.wait_for_timeout(300)
        except Exception:
            pass
    for txt in (
        "Yopish",
        "Orqaga",
        "Bekor",
        "Bekor qilish",
        "Закрыть",
        "×",
    ):
        btn = page.get_by_role("button", name=re.compile(re.escape(txt), re.I)).first
        try:
            if await btn.count() and await btn.is_visible():
                await btn.click(timeout=2000)
                await page.wait_for_timeout(300)
        except Exception:
            pass
    for sel in (
        "button.mat-mdc-dialog-close",
        "[mat-dialog-close]",
        "[class*='dialog'] button[class*='close' i]",
        "button[aria-label='Close']",
    ):
        el = page.locator(sel).first
        try:
            if await el.count() and await el.is_visible():
                await el.click(timeout=2000)
                await page.wait_for_timeout(300)
        except Exception:
            pass


async def _fill_date_via_calendar_trigger(page, bar, dotted: str) -> bool:
    """
    Sana matni ('07 Aprel' / NBSP) — bosiladi, keyin popup yoki klaviatura bilan DD.MM.YYYY.
    """
    months_re = (
        r"Yanvar|Fevral|Mart|Aprel|May|Iyun|Iyul|Avgust|Sentyabr|Oktyabr|Noyabr|Dekabr|"
        r"yanvar|fevral|mart|aprel|may|iyun|iyul|avgust|sentyabr|oktyabr|noyabr|dekabr|"
        r"январ|феврал|март|апрел|мая|июн|июл|август|сентябр|октябр|ноябр|декабр"
    )
    pat = re.compile(rf"\d{{1,2}}[\s\u00a0]+({months_re})", re.I)
    clicked = False
    for scope, root in (("search-trains", bar), ("body", page.locator("body"))):
        trig = root.get_by_text(pat).first
        if not await trig.count():
            continue
        try:
            await trig.scroll_into_view_if_needed()
            await trig.click(timeout=5000, force=True)
            clicked = True
            logger.info("[railway] sana matni bosildi (%s)", scope)
            break
        except Exception as e:
            logger.warning("[railway] sana matn %s: %s", scope, e)
    if not clicked:
        return False

    await page.wait_for_timeout(650)
    for sel in (
        "bs-datepicker-container input",
        ".bs-datepicker-container input",
        "[class*='datepicker'] input",
        ".dropdown-menu.show input",
        ".mat-datepicker-input",
        "mat-datepicker-popup input",
        ".cdk-overlay-container input",
        ".cdk-overlay-pane input",
    ):
        loc = page.locator(sel).first
        if not await loc.count():
            continue
        try:
            vis = await loc.is_visible()
            await loc.fill(dotted, timeout=5000, force=not vis)
            await _angular_set_input_value(loc, dotted)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(450)
            logger.info("[railway] kalendar popup: %s", sel)
            return True
        except Exception:
            continue
    try:
        await page.keyboard.press("Control+a")
        await page.keyboard.type(dotted, delay=85)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(450)
        logger.info("[railway] kalendar ochilgach klaviatura bilan sana")
        return True
    except Exception:
        return False


async def _type_trains_search_date_and_research(page, date_iso: str) -> None:
    """
    redirectedFromHome + dateSelect ba'zan ishlamaydi — sana bugun qoladi.
    Yashirin input: scroll QO'YMAY fill+Angular setter; bo'lmasa kalendar matni.
    """
    d_iso = (date_iso or "").strip()[:10]
    logger.info("[railway] sana qadam: date_iso=%s", d_iso)
    await _dismiss_railway_overlays(page)

    dotted = _iso_to_railway_dotted(d_iso)
    bar = page.locator("[class*='search-trains']").first
    if not await bar.count():
        logger.warning(
            "[railway] search-trains konteyner topilmadi — sana yozilmaydi (BETA boshqa class?). URL=%s",
            (await page.evaluate("() => location.href"))[:200],
        )
        return

    all_inp = bar.locator("input")
    n_all = await all_inp.count()
    vis = bar.locator("input:visible")
    cnt_vis = await vis.count()
    logger.info("[railway] input jami=%s, :visible=%s", n_all, cnt_vis)

    target = None
    pick_reason = ""
    date_ok = False

    async def try_locator(label: str, loc) -> bool:
        nonlocal target, pick_reason, date_ok
        try:
            await loc.fill(dotted, timeout=8000, force=True)
        except Exception as e:
            logger.warning("[railway] %s fill: %s", label, e)
            return False
        await _angular_set_input_value(loc, dotted)
        await page.wait_for_timeout(220)
        await _angular_set_input_value(loc, dotted)
        await page.wait_for_timeout(180)
        val = await _read_input_value_safe(loc)
        if _date_field_value_ok(val, dotted, d_iso):
            target = loc
            pick_reason = label
            date_ok = True
            return True
        logger.info("[railway] %s tekshiruv: input_value=%r", label, val[:100])
        return False

    # 1) Uchunchi input — yashirin: scroll_into_view TALAB QILINMAYDI (30s hang oldini)
    if n_all >= 3:
        await try_locator("input[2]", all_inp.nth(2))

    # 2) Atributlar bo'yicha
    if not date_ok:
        for i in range(n_all):
            el = all_inp.nth(i)
            try:
                blob = " ".join(
                    filter(
                        None,
                        [
                            await el.get_attribute("type"),
                            await el.get_attribute("name"),
                            await el.get_attribute("id"),
                            await el.get_attribute("placeholder"),
                            await el.get_attribute("formcontrolname"),
                        ],
                    )
                ).lower()
            except Exception:
                continue
            if not blob:
                continue
            if any(
                x in blob.replace(" ", "")
                for x in ("date", "forward", "sana", "departure", "calendar")
            ):
                if await try_locator(f"attr[{i}]", el):
                    break

    # 3) Ko'rinadigan: faqat sanaga o'xshash yoki 3+ input
    if not date_ok:
        for i in range(cnt_vis):
            el = vis.nth(i)
            try:
                val = await el.input_value()
                ph = (await el.get_attribute("placeholder")) or ""
            except Exception:
                continue
            if re.search(r"\d{1,2}\.\d{1,2}\.\d{2,4}", val) or re.search(
                r"\d{1,2}\s+[A-Za-zА-Яа-яЁё]", val
            ):
                if await try_locator(f"visible-pattern[{i}]", el):
                    break
            if any(x in ph.lower() for x in ("dd", "kun", "sana", "date", "гггг", "yyyy")):
                if await try_locator(f"visible-ph[{i}]", el):
                    break
        if not date_ok and cnt_vis >= 3:
            try:
                cand = vis.nth(2)
                await cand.click(timeout=5000)
                await cand.press("Control+a")
                await page.keyboard.type(dotted, delay=95)
                await _angular_set_input_value(cand, dotted)
                val = await _read_input_value_safe(cand)
                if _date_field_value_ok(val, dotted, d_iso):
                    target = cand
                    pick_reason = "visible nth(2) type"
                    date_ok = True
            except Exception as e:
                logger.warning("[railway] visible nth(2): %s", e)

    # 4) form__field[2]
    if not date_ok:
        fields = bar.locator("[class*='form__field'], [class*='field']").filter(
            has=page.locator("input")
        )
        fc = await fields.count()
        if fc >= 3:
            inner = fields.nth(2).locator("input").first
            await try_locator("form__field[2]", inner)

    # 5) Kalendar matni — input bo'sh qolganda yoki hali OK emas
    if not date_ok:
        if await _fill_date_via_calendar_trigger(page, bar, dotted):
            pick_reason = (pick_reason + "+" if pick_reason else "") + "calendar"
            date_ok = True
            if n_all >= 3:
                v2 = await _read_input_value_safe(all_inp.nth(2))
                logger.info("[railway] kalendar keyin input[2]: %r", v2[:120])
        else:
            logger.warning(
                "[railway] sana o'rnatilmadi — kalendar trigger yoki popup ishlamadi."
            )

    logger.info(
        "[railway] sana strategiya: %s; qiymat=%s; date_ok=%s",
        pick_reason or "(bo'sh)",
        dotted,
        date_ok,
    )

    if target is not None:
        after = await _read_input_value_safe(target)
        logger.info("[railway] sana input dan keyin: %r", after[:120])

    await _dismiss_railway_overlays(page)

    search_btn = bar.locator("button").filter(
        has_text=re.compile(r"Izlash|Qidirish|Найти", re.I)
    ).first
    if await search_btn.count():
        try:
            await search_btn.scroll_into_view_if_needed()
            await search_btn.click(timeout=6000)
            logger.info("[railway] Izlash bosildi (search-trains paneli)")
            await page.wait_for_timeout(2800)
            return
        except Exception as ex:
            logger.warning("[railway] Izlash bosishda xato: %s", ex)
    legacy = bar.locator(
        "button:has-text('Izlash'), button:has-text('Найти'), button:has-text('Qidirish')"
    ).first
    if await legacy.count():
        try:
            await legacy.click(timeout=6000)
            logger.info("[railway] Izlash bosildi (legacy selector)")
            await page.wait_for_timeout(2800)
        except Exception as ex:
            logger.warning("[railway] legacy Izlash: %s", ex)
    else:
        logger.warning("[railway] Izlash tugmasi search-trains ichida topilmadi")


async def _open_trains_search(
    page,
    from_code: str,
    to_code: str,
    from_name: str,
    to_name: str,
    date_iso: str,
) -> str:
    """
    sessionStorage + savedData.forwardDate (DD-MM-YYYY) + redirectedFromHome — Angular ngOnInit
    ichida update(), dateSelect(forwardDate), searchTrains() (faqat URL query yetarli emas edi: sana "bugun").
    """
    fn = (from_name or "").strip() or str(from_code)
    tn = (to_name or "").strip() or str(to_code)
    d_iso = (date_iso or "").strip()[:10]
    dmy = _iso_to_railway_dmy(d_iso)
    saved_payload = json.dumps(
        {
            "stations": {
                "from": {"code": str(from_code), "nameRu": fn},
                "to": {"code": str(to_code), "nameRu": tn},
            },
            "forwardDate": dmy,
        },
        ensure_ascii=False,
    )
    lang = RAILWAY_UI_LANG
    trains_url = _trains_page_url(from_code, to_code, from_name, to_name, d_iso, lang=lang)
    plain_trains = f"{RAILWAY}/{lang}/pages/trains-page"
    arg = [d_iso, str(from_code), str(to_code)]

    await page.evaluate(
        """([d_iso, saved, fc, tc, fn, tn]) => {
            sessionStorage.setItem('sd-value', d_iso);
            sessionStorage.setItem('sd-value2', '');
            sessionStorage.setItem('sf-code', String(fc));
            sessionStorage.setItem('st-code', String(tc));
            sessionStorage.setItem('sf-name', fn);
            sessionStorage.setItem('st-name', tn);
            sessionStorage.setItem('redirectedFromHome', 'true');
            sessionStorage.setItem('savedData', saved);
        }""",
        [d_iso, saved_payload, str(from_code), str(to_code), fn, tn],
    )

    logger.info(
        "[railway] trains ochish: date_iso=%s %s→%s plain=%s",
        d_iso,
        from_code,
        to_code,
        plain_trains,
    )
    await page.goto(plain_trains, wait_until=_WAIT, timeout=45000)
    await _dismiss_railway_overlays(page)
    try:
        href = await page.evaluate("() => location.href")
        snap = await page.evaluate(
            """() => ({
                sd: sessionStorage.getItem('sd-value'),
                sf: sessionStorage.getItem('sf-code'),
                st: sessionStorage.getItem('st-code'),
                redir: sessionStorage.getItem('redirectedFromHome'),
                saved: (sessionStorage.getItem('savedData') || '').slice(0, 120),
            })"""
        )
        logger.info("[railway] keyin URL=%s sessionStorage=%s", href[:180], snap)
    except Exception as e:
        logger.warning("[railway] URL/sessionStorage log: %s", e)

    try:
        await page.wait_for_function(
            """([d_iso, fc, tc]) => {
                const g = (k) => sessionStorage.getItem(k) || '';
                return g('sd-value') === d_iso && g('sf-code') === String(fc) && g('st-code') === String(tc);
            }""",
            arg=arg,
            timeout=14000,
        )
    except PWTimeout:
        logger.warning("[railway] trains: sessionStorage (sd/sf/st) kutilmadi")

    await page.wait_for_timeout(1800)
    await _type_trains_search_date_and_research(page, d_iso)
    return trains_url

# networkidle SPA da tez-tez osilib qoladi — asosan domcontentloaded
_WAIT = "domcontentloaded"
_HEADLESS = os.getenv("RAILWAY_AUTOMATION_HEADLESS", "true").lower() in ("1", "true", "yes")


def _login_is_email(login: str) -> bool:
    return "@" in (login or "")


def _normalize_uz_phone(login: str) -> str:
    """
    Validatsiya: faqat raqamlar, 998 bilan 12 ta (masalan 998901234567).
    """
    digits = re.sub(r"\D", "", login or "")
    if not digits:
        return ""
    if digits.startswith("998") and len(digits) >= 12:
        return digits[:12]
    if len(digits) == 9:
        return "998" + digits
    if len(digits) == 12 and digits.startswith("998"):
        return digits
    return digits


def _phone_local_digits_for_masked_input(full998: str) -> str:
    """
    eticket.railway.uz maydonida +998 (__) allaqachon turadi — 12 raqam yozilsa
    mask 998 ni qayta "yutib", raqam siljiydi (masalan 93 o'rniga 98 chiqadi).
    Shuning uchun faqat mahalliy 9 ta raqam beramiz.
    """
    if len(full998) >= 12 and full998.startswith("998"):
        return full998[3:12]
    if len(full998) == 9:
        return full998
    return full998[-9:] if len(full998) >= 9 else full998


async def _type_phone_imask(page, login_el, nine_digits: str) -> None:
    """
    IMask maydonida .fill() yoki juda tez sequential ba'zan bitta raqamni yutadi
    (masalan 939578080 → 93 dan keyingi 9 chiqmaydi). Tanlash + sekin type yaxshiroq.
    """
    await login_el.click(timeout=5000)
    await page.wait_for_timeout(200)
    # Playwright Mac da Control+a → Meta+a ga map qilinadi
    await login_el.press("Control+a")
    await page.wait_for_timeout(100)
    await page.keyboard.type(nine_digits, delay=120)
    await page.wait_for_timeout(200)


def _browser_args() -> list[str]:
    return [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
    ]


async def _login_railway(page) -> tuple[bool, str]:
    """
    /uz/auth/login (default) — telefon yoki pochta. RU yozuvlari zaxira sifatida qoldirilgan.
    """
    try:
        await page.goto(
            f"{RAILWAY}/{RAILWAY_UI_LANG}/auth/login",
            wait_until=_WAIT,
            timeout=35000,
        )
    except Exception as e:
        return False, f"Login sahifasini ochib bo'lmadi: {e}"

    await page.wait_for_timeout(900)

    use_email = _login_is_email(RAILWAY_LOGIN)

    if use_email:
        for sel in (
            "button:has-text('POCHTA')",
            "span:has-text('POCHTA')",
            "div[role='tab']:has-text('POCHTA')",
            "a:has-text('POCHTA')",
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
                    logger.info("[railway] pochta tab")
                except Exception:
                    pass
                break
    else:
        for sel in (
            "button:has-text('TELEFON')",
            "span:has-text('TELEFON')",
            "div[role='tab']:has-text('TELEFON')",
            "a:has-text('TELEFON')",
            "button:has-text('ТЕЛЕФОН')",
            "span:has-text('ТЕЛЕФОН')",
            "div[role='tab']:has-text('ТЕЛЕФОН')",
            "a:has-text('ТЕЛЕФОН')",
        ):
            tab = page.locator(sel).first
            if await tab.count():
                try:
                    await tab.click(timeout=3000)
                    await page.wait_for_timeout(600)
                    logger.info("[railway] telefon tab")
                except Exception:
                    pass
                break

    try:
        if use_email:
            login_el = page.locator("input[type='email']").first
            if not await login_el.count():
                login_el = page.locator("input[name*='mail' i], input[name*='email' i]").first
            if not await login_el.count():
                login_el = page.locator("form input[type='text']").first
            await login_el.fill(RAILWAY_LOGIN.strip(), timeout=12000)
        else:
            phone_full = _normalize_uz_phone(RAILWAY_LOGIN)
            if not phone_full or len(phone_full) < 12:
                return (
                    False,
                    "Telefon noto'g'ri: RAILWAY_LOGIN da 9 yoki 12 raqam (998...) kiriting.",
                )
            # Maydonda +998 prefiks bo'lgani uchun 9 ta mahalliy raqam (masalan 939578080)
            phone_to_type = _phone_local_digits_for_masked_input(phone_full)
            login_el = page.locator("input[type='tel']").first
            if not await login_el.count():
                login_el = page.locator(
                    "input[placeholder*='998' i], input[name*='phone' i], "
                    "input[autocomplete='tel'], input[inputmode='numeric']"
                ).first
            if not await login_el.count():
                login_el = page.locator("form input[type='text']").first
            await _type_phone_imask(page, login_el, phone_to_type)

        await page.locator("input[type='password']").first.fill(RAILWAY_PASS, timeout=8000)

        submit = page.locator(
            "button:has-text('ВОЙТИ'), button:has-text('Войти'), "
            "button:has-text('VOITI'), button:has-text('Voiti'), "
            "button:has-text('Kirish'), button[type='submit']"
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

    # UZ sahifada ko'pincha "Poyezdni tanlash"; RU "Купить" va hokazo
    buy_xpath = (
        "xpath=ancestor::*[.//button["
        "contains(., 'Купить') or contains(., 'Sotib') or contains(., 'Xarid') or "
        "contains(., 'Poyezdni tanlash') or contains(., 'poyezdni tanlash')"
        "]][1]//button["
        "contains(., 'Купить') or contains(., 'Sotib') or contains(., 'Xarid') or "
        "contains(., 'Poyezdni tanlash') or contains(., 'poyezdni tanlash')"
        "][1]"
    )
    buy_btn = marker.locator(buy_xpath).first
    if not await buy_btn.count():
        buy_btn = marker.locator(
            "xpath=following::button["
            "contains(., 'Купить') or contains(., 'Sotib') or contains(., 'Xarid') or "
            "contains(., 'Poyezdni tanlash') or contains(., 'poyezdni tanlash')"
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

    for loc in (
        page.locator("input[placeholder*='Имя' i], input[placeholder*='ФИО' i], input[name*='name' i]"),
        page.locator("input[type='text']").filter(has_not=page.locator("[type='password']")),
    ):
        if await loc.count() and name:
            try:
                await loc.first.fill(name, timeout=5000)
                break
            except Exception:
                pass

    for sel in (
        "input[placeholder*='Серия' i], input[placeholder*='Паспорт' i], input[name*='passport' i]",
        "input[placeholder*='passport' i]",
    ):
        el = page.locator(sel).first
        if await el.count() and passport:
            try:
                await el.fill(passport, timeout=5000)
                break
            except Exception:
                pass

    for sel in (
        "input[type='tel']",
        "input[placeholder*='Телефон' i], input[placeholder*='phone' i]",
    ):
        el = page.locator(sel).first
        if await el.count() and phone:
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
        "Davom etish",
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
        "button:has-text('К оплате'), button:has-text('Davom'), "
        "button:has-text('Davom etish')"
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
    from_name: str = "",
    to_name: str = "",
) -> dict:
    trains_url = _trains_page_url(from_code, to_code, from_name, to_name, date)

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
            locale=_BROWSER_LOCALE,
        )
        page = await context.new_page()

        try:
            ok, msg = await _login_railway(page)
            if not ok:
                scr = await page.screenshot(full_page=True)
                await browser.close()
                return {"success": False, "screenshot": scr, "url": page.url, "message": msg}

            await _open_trains_search(page, from_code, to_code, from_name, to_name, date)

            clicked = False
            try:
                # [class*='train'] — search-trains bilan chalkashadi (darhol "topiladi")
                await page.wait_for_selector(
                    "[class*='train']:not([class*='search-trains']), "
                    "[class*='Train']:not([class*='search-trains']), "
                    ".result-card",
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

    trains_url = _trains_page_url(from_code, to_code, from_name, to_name, date)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=_HEADLESS, args=_browser_args())
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            locale=_BROWSER_LOCALE,
        )
        page = await context.new_page()

        try:
            ok, msg = await _login_railway(page)
            if not ok:
                scr = await page.screenshot(full_page=True)
                return {"status": "error", "message": msg, "screenshot": scr}

            trains_url = await _open_trains_search(
                page, from_code, to_code, from_name, to_name, date
            )
            logger.info("[buy_ticket] Trains: %s", trains_url)

            await page.wait_for_selector(
                "[class*='train']:not([class*='search-trains']), "
                "[class*='Train']:not([class*='search-trains']), "
                ".result-card",
                timeout=25000,
            )
            logger.info("[buy_ticket] poyezdlar ro'yxati DOMda paydo bo'ldi (yoki shunga o'xshash element)")

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
        from_name=sub.get("from_name") or "",
        to_name=sub.get("to_name") or "",
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
