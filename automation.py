"""
eticket.railway.uz — RAILWAY_LOGIN: telefon (9 yoki 998...) yoki email (@), RAILWAY_PASSWORD.
Default UI: o'zbekcha (/uz/auth/login, /uz/pages/...). RAILWAY_UI_LANG=ru — ruscha sahifa.
"""

import json
import logging
import os
import random
import re
import time
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


_UZ_MONTH_NAMES: dict[int, tuple[str, ...]] = {
    1: ("Yanvar", "yanvar"),
    2: ("Fevral", "fevral"),
    3: ("Mart", "mart"),
    4: ("Aprel", "aprel"),
    5: ("May", "may"),
    6: ("Iyun", "iyun"),
    7: ("Iyul", "iyul"),
    8: ("Avgust", "avgust"),
    9: ("Sentyabr", "sentyabr"),
    10: ("Oktyabr", "oktyabr"),
    11: ("Noyabr", "noyabr"),
    12: ("Dekabr", "dekabr"),
}

# Natijalar sahifasidagi kun tablari: «Sesh 07 apr», «10 apr»
_TAB_MONTH: dict[int, tuple[str, ...]] = {
    1: ("yan", "jan"),
    2: ("fev", "feb"),
    3: ("mar",),
    4: ("apr", "aprel"),
    5: ("may",),
    6: ("iyun", "jun"),
    7: ("iyul", "jul"),
    8: ("avg", "aug"),
    9: ("sen", "sep"),
    10: ("okt", "oct"),
    11: ("noy", "nov"),
    12: ("dek", "dec"),
}


def _parse_calendar_head_month_year(text: str) -> tuple[int, int] | None:
    """BS datepicker sarlavhasi: «Aprel 2026» / «April 2026»."""
    raw = (text or "").replace("\u00a0", " ")
    m_y = re.search(r"(20\d{2})", raw)
    if not m_y:
        return None
    y = int(m_y.group(1))
    low = raw.lower()
    for mo, names in _UZ_MONTH_NAMES.items():
        for nm in names:
            if nm.lower() in low:
                return (mo, y)
    ru_m = (
        ("январ", 1),
        ("феврал", 2),
        ("март", 3),
        ("апрел", 4),
        ("мая", 5),
        ("июн", 6),
        ("июл", 7),
        ("август", 8),
        ("сентябр", 9),
        ("октябр", 10),
        ("ноябр", 11),
        ("декабр", 12),
    )
    for prefix, mo in ru_m:
        if prefix in low:
            return (mo, y)
    en_m = (
        ("january", 1),
        ("february", 2),
        ("march", 3),
        ("april", 4),
        ("may", 5),
        ("june", 6),
        ("july", 7),
        ("august", 8),
        ("september", 9),
        ("october", 10),
        ("november", 11),
        ("december", 12),
    )
    for name, mo in en_m:
        if name in low:
            return (mo, y)
    return None


async def _select_date_via_calendar_grid(page, bar, date_iso: str) -> bool:
    """
    Matn maydoniga yozmasdan — kalendar ochiladi, oy/yilga o'tiladi, kunning raqamiga bosiladi.
    (vis_sync dagi birinchi topilgan input 10→8 ga buzishni oldini oladi.)
    """
    d_iso = (date_iso or "").strip()[:10]
    try:
        dt = datetime.strptime(d_iso, "%Y-%m-%d")
    except ValueError:
        return False
    months_re = (
        r"Yanvar|Fevral|Mart|Aprel|May|Iyun|Iyul|Avgust|Sentyabr|Oktyabr|Noyabr|Dekabr|"
        r"yanvar|fevral|mart|aprel|may|iyun|iyul|avgust|sentyabr|oktyabr|noyabr|dekabr|"
        r"январ|феврал|март|апрел|мая|июн|июл|август|сентябр|октябр|ноябр|декабр"
    )
    pat = re.compile(rf"\d{{1,2}}[\s\u00a0]+({months_re})", re.I)
    opened = False
    for root in (bar, page.locator("body")):
        trig = root.get_by_text(pat).first
        if not await trig.count():
            continue
        try:
            await trig.scroll_into_view_if_needed()
            await trig.click(timeout=5000, force=True)
            opened = True
            logger.info("[railway][date] grid: sana matni bosildi")
            break
        except Exception as e:
            logger.warning("[railway][date] grid ochish: %s", e)
    if not opened:
        return False

    await page.wait_for_timeout(550)
    cal = page.locator(
        ".bs-datepicker-container, [class*='bs-datepicker'], [class*='date-picker'], [class*='datepicker'], [class*='calendar'], [role='dialog']"
    ).filter(
        has=page.locator(
            "xpath=.//*[contains(., '202') and (contains(., 'Aprel') or contains(., 'May') or contains(., 'Yanvar') or contains(., 'Du Se Ch Pa Ju Sh Ya') or contains(., 'Mo Tu We Th Fr Sa Su'))]"
        )
    ).first
    if not await cal.count():
        cal = page.locator(
            "xpath=(//*[self::div or self::section or self::aside][contains(., '202') and (contains(., 'Aprel') or contains(., 'May') or contains(., 'Yanvar') or contains(., 'Du Se Ch Pa Ju Sh Ya') or contains(., 'Mo Tu We Th Fr Sa Su'))])[last()]"
        ).first
    if not await cal.count():
        logger.warning("[railway][date] grid: konteyner topilmadi (fallback global kun bosish)")
        cal = page.locator("body").first

    prev_b = cal.locator("button.previous, .previous, .bs-datepicker-navigation-previous").first
    next_b = cal.locator("button.next, .next, .bs-datepicker-navigation-next").first
    if not await prev_b.count() or not await next_b.count():
        hb = cal.locator(".bs-datepicker-head button, thead button")
        hc = await hb.count()
        if hc >= 3:
            prev_b = hb.nth(0)
            next_b = hb.nth(hc - 1)

    for _ in range(28):
        head = cal.locator(".bs-datepicker-head, thead").first
        title = ""
        try:
            title = await head.inner_text()
        except Exception:
            pass
        cur = _parse_calendar_head_month_year(title)
        if cur == (dt.month, dt.year):
            break
        cm, cy = cur if cur else (None, None)
        try:
            if cm is None or cy is None:
                await next_b.click(timeout=3500)
            elif cy < dt.year or (cy == dt.year and cm < dt.month):
                await next_b.click(timeout=3500)
            else:
                await prev_b.click(timeout=3500)
        except Exception as e:
            logger.warning("[railway][date] grid nav: %s", e)
            break
        await page.wait_for_timeout(280)
    else:
        logger.warning("[railway][date] grid: oy navigatsiyasi limit")
        await page.keyboard.press("Escape")
        return False

    day_re = re.compile(rf"^\s*{dt.day}\s*$")
    try:
        body = cal.locator(".bs-datepicker-body, tbody, [class*='day'], [class*='calendar']").first
        cell = body.locator(
            "xpath=.//*[self::button or self::span or self::div or self::td]"
            f"[normalize-space(text())='{dt.day}']"
            "[not(contains(translate(@class,'DISABLEDOUTSIDE','disabledoutside'),'disabled'))]"
            "[not(contains(translate(@class,'DISABLEDOUTSIDE','disabledoutside'),'outside'))]"
        ).first
        if not await cell.count():
            cell = body.locator("button, span, div, td").filter(has_text=day_re).first
        if not await cell.count():
            cell = cal.locator("button, span, div, td").filter(has_text=day_re).first
        if await cell.count():
            await cell.click(timeout=5000)
            await page.wait_for_timeout(450)
            await _resync_search_trains_input2(page, d_iso)
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(200)
            logger.info("[railway][date] grid: kun %s tanlandi", dt.day)
            return True
    except Exception as e:
        logger.warning("[railway][date] grid kun: %s", e)
    await page.keyboard.press("Escape")
    return False


def _search_bar_reflects_date_iso(bar_text: str, date_iso: str) -> bool:
    """«10 Aprel» kabi matn maqsad sanaga (YYYY-MM-DD) mos keladimi."""
    raw = (date_iso or "").strip()[:10]
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return True
    t = re.sub(r"\s+", " ", (bar_text or "").replace("\u00a0", " ")).strip()
    if not t:
        return False
    for name in _UZ_MONTH_NAMES.get(dt.month, ()):
        if name.lower() not in t.lower():
            continue
        for day_s in (str(dt.day), f"{dt.day:02d}"):
            if re.search(rf"\b{re.escape(day_s)}\s+{re.escape(name)}\b", t, re.I):
                return True
    return False


async def _bar_inner_text_compact(bar) -> str:
    try:
        txt = await bar.inner_text()
        return re.sub(r"\s+", " ", (txt or "").replace("\u00a0", " ")).strip()
    except Exception:
        return ""


def _results_heading_matches_date(body: str, date_iso: str) -> bool:
    """«07 APREL, 2026» / «10 apr» — ro'yxat qaysi kun uchun yuklangan."""
    raw = (date_iso or "").strip()[:10]
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return True
    t = body or ""
    if re.search(rf"\b{dt.day}\s+APREL\s*,\s*{dt.year}\b", t, re.I):
        return True
    for name in _UZ_MONTH_NAMES.get(dt.month, ()):
        if re.search(rf"\b{dt.day}\s+{re.escape(name)}\b", t, re.I):
            return True
    for suf in _TAB_MONTH.get(dt.month, ()):
        if re.search(rf"\b{dt.day}\s+{re.escape(suf)}\b", t, re.I):
            return True
    return False


async def _click_results_date_tab(page, date_iso: str) -> bool:
    raw = (date_iso or "").strip()[:10]
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return False
    d = dt.day
    for suf in _TAB_MONTH.get(dt.month, ("apr",)):
        pat = re.compile(rf"\b{d}\s+{re.escape(suf)}\b", re.I)
        loc = (
            page.locator(
                "button, a, [role='tab'], [class*='swiper-slide'], div[role='button'], span[role='button']"
            )
            .filter(has_text=pat)
            .first
        )
        try:
            if await loc.count():
                await loc.scroll_into_view_if_needed()
                await loc.click(timeout=6000)
                logger.info("[railway][date] natijalar kun tabi: %s %s", d, suf)
                await page.wait_for_timeout(400)
                return True
        except Exception as e:
            logger.warning("[railway][date] tab %s: %s", suf, e)
    return False


async def _ensure_train_list_shows_target_date(page, date_iso: str) -> None:
    if not (date_iso or "").strip():
        return
    d_iso = date_iso.strip()[:10]
    try:
        body = await page.inner_text("body")
    except Exception:
        return
    if _results_heading_matches_date(body, d_iso):
        logger.info("[railway][date] natija sarlavhasi maqsad sanaga mos")
        return
    logger.info("[railway][date] boshqa kun uchun ro'yxat — tab orqali %s", d_iso)
    if await _click_results_date_tab(page, d_iso):
        await page.wait_for_timeout(2000)
        await _dismiss_railway_overlays(page)


async def _get_train_page_state(page) -> dict:
    try:
        return await page.evaluate(
            """() => {
                const body = (document.body && document.body.innerText) || '';
                const cards = document.querySelectorAll('.result-card').length;
                let purchaseButtons = 0;
                try {
                    document.querySelectorAll('button').forEach((b) => {
                        const t = (b.textContent || '');
                        if (/Poyezdni tanlash|поездни танлаш|Выбрать поезд/i.test(t)) purchaseButtons++;
                    });
                } catch (e) {}
                const noTrain = /mavjud\\s+emas|rsatilgan\\s+sanada|поезд.*нет|нет\\s+поездов/i.test(body);
                const spin = !!document.querySelector(
                    ".mat-progress-spinner, [class*='mat-progress'], [class*='spinner']"
                );
                let trainBlocks = 0;
                try {
                    document.querySelectorAll("[class*='train']").forEach((el) => {
                        const c = String(el.className || '');
                        if (c && !c.includes('search-trains')) trainBlocks++;
                    });
                } catch (e) {}
                return { cards, purchaseButtons, trainBlocks, noTrain, spin };
            }"""
        )
    except Exception:
        return {
            "cards": 0,
            "purchaseButtons": 0,
            "trainBlocks": 0,
            "noTrain": False,
            "spin": False,
        }


async def _wait_train_results_or_banner(page, timeout_ms: int = 34000) -> str:
    """
    .result-card, «Poyezdni tanlash», yoki yetarli poyezd bloklari (barcha joylar band bo'lsa ham).
    Yoki barqaror «mavjud emas».
    Qaytaradi: 'results' | 'no_trains' | 'timeout'
    """
    t0 = time.monotonic()
    stable_no_train = 0
    last_key = None
    while True:
        st = await _get_train_page_state(page)
        cards = int(st.get("cards") or 0)
        pb = int(st.get("purchaseButtons") or 0)
        tb = int(st.get("trainBlocks") or 0)
        no_tr = bool(st.get("noTrain"))
        spin = bool(st.get("spin"))
        key = (cards, pb, tb, no_tr, spin)
        if key != last_key:
            last_key = key
            logger.info(
                "[buy_ticket][wait] cards=%s purchaseButtons=%s trainBlocks=%s noTrain=%s spin=%s",
                cards,
                pb,
                tb,
                no_tr,
                spin,
            )

        if cards > 0 or pb > 0 or tb >= 3:
            return "results"
        if no_tr and cards == 0 and pb == 0 and tb <= 1:
            stable_no_train += 1
            if stable_no_train >= 6:
                return "no_trains"
        elif spin:
            stable_no_train = max(0, stable_no_train - 1)
        else:
            stable_no_train = 0

        if (time.monotonic() - t0) * 1000 >= timeout_ms:
            return "timeout"
        await page.wait_for_timeout(400)


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


async def _resync_search_trains_input2(page, date_iso: str) -> None:
    """Yashirin input[2] — Angular DD-MM-YYYY va DD.MM.YYYY."""
    d_iso = (date_iso or "").strip()[:10]
    if not d_iso:
        return
    dotted = _iso_to_railway_dotted(d_iso)
    dmy = _iso_to_railway_dmy(d_iso)
    bar = page.locator("[class*='search-trains']").first
    if not await bar.count():
        return
    ins = bar.locator("input")
    if await ins.count() < 3:
        return
    el = ins.nth(2)
    for v in (dmy, dotted):
        await _angular_set_input_value(el, v)
        await page.wait_for_timeout(120)


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


async def _log_railway_ui_snapshot(page, step: str) -> None:
    """
    Journal tahlili: URL, sd-value, search-trains qisqa matn, 'poyezd yo'q' belgisi, .result-card soni.
    """
    try:
        data = await page.evaluate(
            """() => {
                const t = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                const body = t(document.body && document.body.innerText || '');
                const href = location.href;
                const sd = sessionStorage.getItem('sd-value');
                const bar = document.querySelector("[class*='search-trains']");
                const barSnippet = bar ? t(bar.innerText).slice(0, 400) : '';
                const noTrainBanner = /mavjud\\s+emas|rsatilgan\\s+sanada|поезд.*нет|нет\\s+поездов|не\\s+найден/i.test(body);
                let trainClassNodes = 0;
                try {
                    document.querySelectorAll("[class*='train']").forEach((el) => {
                        const c = String(el.className || '');
                        if (c && !c.includes('search-trains')) trainClassNodes++;
                    });
                } catch (e) {}
                const resultCards = document.querySelectorAll('.result-card').length;
                const hasSpinner = !!document.querySelector("[class*='spinner'], [class*='loader'], .mat-progress-spinner");
                return {
                    href: href.slice(0, 240),
                    sd,
                    barSnippet,
                    noTrainBanner,
                    trainClassNodes,
                    resultCards,
                    hasSpinnerGuess: hasSpinner,
                    bodyHead: body.slice(0, 360),
                };
            }"""
        )
        logger.info(
            "[railway][ui_snapshot] step=%s | %s",
            step,
            json.dumps(data, ensure_ascii=False),
        )
    except Exception as e:
        logger.warning("[railway][ui_snapshot] step=%s xato=%s", step, e)


async def _fill_date_via_calendar_trigger(page, bar, date_iso: str) -> bool:
    """
    Sana matni ('07 Aprel') — bosiladi; popupda avval DD-MM-YYYY (10-04-2026), keyin DD.MM.YYYY.
    Nuqta bilan yozish ba'zan noto'g'ri parse bo'lib bugungi kunga qaytadi.
    """
    d_iso = (date_iso or "").strip()[:10]
    dotted = _iso_to_railway_dotted(d_iso)
    dmy = _iso_to_railway_dmy(d_iso)
    try_formats = [dmy, dotted]
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
        for value_try in try_formats:
            try:
                vis = await loc.is_visible()
                await loc.click(timeout=3000, force=True)
                await loc.fill(value_try, timeout=5000, force=not vis)
                await _angular_set_input_value(loc, value_try)
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(500)
                await _resync_search_trains_input2(page, d_iso)
                logger.info("[railway] kalendar popup: %s | val=%s", sel, value_try)
                return True
            except Exception:
                continue
    try:
        await page.keyboard.press("Control+a")
        await page.keyboard.type(dmy, delay=85)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(500)
        await _resync_search_trains_input2(page, d_iso)
        logger.info("[railway] kalendar klaviatura: %s", dmy)
        return True
    except Exception:
        return False


async def _type_trains_search_date_and_research(page, date_iso: str) -> None:
    """
    redirectedFromHome + dateSelect ba'zan ishlamaydi — sana bugun qoladi.
    Yashirin input: scroll QO'YMAY fill+Angular setter; bo'lmasa kalendar matni.
    """
    d_iso = (date_iso or "").strip()[:10]
    logger.info("[railway][date] === boshlandi: date_iso=%s dotted=%s", d_iso, _iso_to_railway_dotted(d_iso))
    await _dismiss_railway_overlays(page)
    await _log_railway_ui_snapshot(page, "date_after_dismiss")

    dotted = _iso_to_railway_dotted(d_iso)
    bar = page.locator("[class*='search-trains']").first
    if not await bar.count():
        logger.warning(
            "[railway] search-trains konteyner topilmadi — sana yozilmaydi (BETA boshqa class?). URL=%s",
            (await page.evaluate("() => location.href"))[:200],
        )
        await _log_railway_ui_snapshot(page, "date_no_search_bar")
        return

    all_inp = bar.locator("input")
    n_all = await all_inp.count()
    vis = bar.locator("input:visible")
    cnt_vis = await vis.count()
    logger.info("[railway][date] inputlar: jami=%s visible=%s", n_all, cnt_vis)

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
        logger.info("[railway][date] qadam 1/5: input[2] (nth 2) sinov")
        await try_locator("input[2]", all_inp.nth(2))
        logger.info("[railway][date] qadam 1 natija: date_ok=%s pick=%s", date_ok, pick_reason or "-")

    # 2) Atributlar bo'yicha
    if not date_ok:
        logger.info("[railway][date] qadam 2/5: atributlar (date/forward/sana...)")
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
        logger.info("[railway][date] qadam 2 natija: date_ok=%s pick=%s", date_ok, pick_reason or "-")

    # 3) Ko'rinadigan: faqat sanaga o'xshash yoki 3+ input
    if not date_ok:
        logger.info("[railway][date] qadam 3/5: visible pattern / placeholder")
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
        logger.info("[railway][date] qadam 3 natija: date_ok=%s pick=%s", date_ok, pick_reason or "-")

    # 4) form__field[2]
    if not date_ok:
        logger.info("[railway][date] qadam 4/5: form__field[2]")
        fields = bar.locator("[class*='form__field'], [class*='field']").filter(
            has=page.locator("input")
        )
        fc = await fields.count()
        if fc >= 3:
            inner = fields.nth(2).locator("input").first
            await try_locator("form__field[2]", inner)

    # 5) Kalendar — avval grid (kun bosish), keyin matn/input fallback
    if not date_ok:
        logger.info("[railway][date] qadam 5/5: kalendar (grid, keyin typing)")
        if await _select_date_via_calendar_grid(page, bar, d_iso):
            pick_reason = (pick_reason + "+" if pick_reason else "") + "calendar_grid"
            date_ok = True
            if n_all >= 3:
                v2 = await _read_input_value_safe(all_inp.nth(2))
                logger.info("[railway] grid keyin input[2]: %r", v2[:120])
        elif await _fill_date_via_calendar_trigger(page, bar, d_iso):
            pick_reason = (pick_reason + "+" if pick_reason else "") + "calendar_type"
            date_ok = True
            if n_all >= 3:
                v2 = await _read_input_value_safe(all_inp.nth(2))
                logger.info("[railway] kalendar typing keyin input[2]: %r", v2[:120])
        else:
            logger.warning(
                "[railway] sana o'rnatilmadi — kalendar grid/typing ishlamadi."
            )

    logger.info(
        "[railway] sana strategiya: %s; qiymat=%s; date_ok=%s",
        pick_reason or "(bo'sh)",
        dotted,
        date_ok,
    )

    if target is not None:
        after = await _read_input_value_safe(target)
        logger.info("[railway][date] sana input dan keyin: %r", after[:120])

    bar_txt = await _bar_inner_text_compact(bar)
    reflects = _search_bar_reflects_date_iso(bar_txt, d_iso)
    logger.info(
        "[railway][date] bar matn ↔ sana_iso mosligi: %s | %s",
        reflects,
        bar_txt[:200],
    )
    if not reflects:
        logger.info(
            "[railway][date] bar matn yashirin inputdan farq qiladi — grid (typing emas)"
        )
        if await _select_date_via_calendar_grid(page, bar, d_iso):
            pick_reason = f"{pick_reason}+grid_sync" if pick_reason else "grid_sync"
            if n_all >= 3:
                v2 = await _read_input_value_safe(all_inp.nth(2))
                logger.info("[railway][date] grid_sync keyin input[2]: %r", v2[:120])
        else:
            logger.warning(
                "[railway][date] grid_sync ishlamadi — Izlashdan keyin natijalar tabi ishlatiladi"
            )
        bar_txt = await _bar_inner_text_compact(bar)
        logger.info(
            "[railway][date] grid_sync keyin bar mosligi: %s | %s",
            _search_bar_reflects_date_iso(bar_txt, d_iso),
            bar_txt[:200],
        )

    await _dismiss_railway_overlays(page)
    await _log_railway_ui_snapshot(page, "before_izlash")

    search_btn = bar.locator("button").filter(
        has_text=re.compile(r"Izlash|Qidirish|Найти", re.I)
    ).first
    if await search_btn.count():
        try:
            await search_btn.scroll_into_view_if_needed()
            await search_btn.click(timeout=6000)
            logger.info("[railway][date] Izlash bosildi (search-trains paneli), 2.8s kutish")
            await page.wait_for_timeout(2800)
            await _log_railway_ui_snapshot(page, "after_izlash_wait")
            await _ensure_train_list_shows_target_date(page, d_iso)
            return
        except Exception as ex:
            logger.warning("[railway] Izlash bosishda xato: %s", ex)
    legacy = bar.locator(
        "button:has-text('Izlash'), button:has-text('Найти'), button:has-text('Qidirish')"
    ).first
    if await legacy.count():
        try:
            await legacy.click(timeout=6000)
            logger.info("[railway][date] Izlash bosildi (legacy selector), 2.8s kutish")
            await page.wait_for_timeout(2800)
            await _log_railway_ui_snapshot(page, "after_izlash_wait_legacy")
            await _ensure_train_list_shows_target_date(page, d_iso)
        except Exception as ex:
            logger.warning("[railway] legacy Izlash: %s", ex)
    else:
        logger.warning("[railway] Izlash tugmasi search-trains ichida topilmadi")
        await _log_railway_ui_snapshot(page, "izlash_button_missing")
        await _ensure_train_list_shows_target_date(page, d_iso)


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
    await _log_railway_ui_snapshot(page, "open_trains_after_session_pre_goto")

    logger.info(
        "[railway][open_trains] goto: date_iso=%s %s→%s url_len=%s",
        d_iso,
        from_code,
        to_code,
        len(trains_url),
    )
    logger.info("[railway][open_trains] url_sample=%s", trains_url[:200])
    # To'liq query (sd-value, sf-code, ...) — faqat plain /trains-page ba'zan UI "bugun"da qoladi
    await page.goto(trains_url, wait_until=_WAIT, timeout=45000)
    await _dismiss_railway_overlays(page)
    await _log_railway_ui_snapshot(page, "open_trains_after_goto")
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
        await _log_railway_ui_snapshot(page, "open_trains_sessionstorage_timeout")

    await page.wait_for_timeout(1800)
    await _log_railway_ui_snapshot(page, "open_trains_before_date_research")
    await _type_trains_search_date_and_research(page, d_iso)
    await _log_railway_ui_snapshot(page, "open_trains_after_date_research")
    logger.info("[railway][open_trains] tugadi, trains_url=%s", trains_url[:220])
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


def _train_number_match_variants(raw: str) -> list[str]:
    """765Ф / 765 Ф / 765F / 765 — sayt turlicha ko'rsatadi."""
    t = str(raw).strip()
    if not t:
        return []
    out: list[str] = []
    for v in (
        t,
        t.replace("F", "Ф").replace("f", "ф"),
        t.replace("Ф", "F").replace("ф", "f"),
        re.sub(r"\s+", "", t),
        re.sub(r"\s+", "", t).replace("F", "Ф").replace("f", "ф"),
    ):
        if v and v not in out:
            out.append(v)
    digits = re.sub(r"\D", "", t)
    if len(digits) >= 2 and digits not in out:
        out.append(digits)
    return out


async def _click_buy_for_train(
    page,
    train_number: str,
    dep_time: str = "",
    arr_time: str = "",
) -> bool:
    """Tanlangan poyezd qatoridagi sotib olish tugmasi (RU/UZ)."""
    tnum = str(train_number).strip()
    dep = str(dep_time or "").strip()[:5]
    arr = str(arr_time or "").strip()[:5]
    if not tnum:
        return False

    await _log_railway_ui_snapshot(page, "click_buy_before_scan")
    variants = _train_number_match_variants(tnum)
    buy_like_xpath = (
        "xpath=.//*["
        "self::button or self::a or @role='button' or "
        "contains(translate(@class,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'btn') or "
        "contains(translate(@class,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'button')"
        "][contains(., 'Poyezdni tanlash') or contains(., 'poyezdni tanlash') or "
        "contains(., 'Купить') or contains(., 'Sotib') or contains(., 'Xarid') or contains(., 'Tanlash')]"
    )
    logger.info(
        "[buy][click_train] boshlandi tnum=%r variantlar=%s",
        tnum,
        variants[:10],
    )
    marker = None
    chosen = None
    for cand in variants:
        cands = [
            ("text_eq", page.locator(f"text=№{cand}").first),
            ("regex_loose", page.get_by_text(re.compile(rf"№\s*{re.escape(cand)}", re.I)).first),
            ("regex_word", page.get_by_text(re.compile(rf"№\s*{re.escape(cand)}\b", re.I)).first),
        ]
        digits = re.sub(r"\D", "", cand)
        if len(digits) >= 2 and cand == digits:
            cands.append(
                (
                    "regex_digits_letter",
                    page.get_by_text(re.compile(rf"№\s*{re.escape(digits)}\s*[ФFf]?", re.I)).first,
                )
            )
        for kind, loc in cands:
            try:
                cnt = await loc.count()
                logger.info(
                    "[buy][click_train] sinov cand=%r kind=%s count=%s",
                    cand,
                    kind,
                    cnt,
                )
                if cnt:
                    marker = loc
                    chosen = (cand, kind)
                    break
            except Exception as ex:
                logger.info(
                    "[buy][click_train] sinov cand=%r kind=%s xato=%s",
                    cand,
                    kind,
                    ex,
                )
                continue
        if marker:
            break

    if not marker or not await marker.count():
        # Fallback: sahifada ko'pincha "Sharg 709Ф (СК)" format bo'ladi (№ belgisisiz).
        buy_buttons = page.locator(
            "button:has-text('Poyezdni tanlash'), button:has-text('poyezdni tanlash'), "
            "button:has-text('Купить'), button:has-text('Sotib'), button:has-text('Xarid'), "
            "a:has-text('Poyezdni tanlash'), a:has-text('Купить'), a:has-text('Tanlash'), "
            "[role='button']:has-text('Poyezdni tanlash'), [role='button']:has-text('Tanlash'), "
            "[class*='btn']:has-text('Poyezdni tanlash'), [class*='button']:has-text('Poyezdni tanlash')"
        )
        btn_count = await buy_buttons.count()
        logger.info("[buy][click_train] fallback tugmalar soni=%s", btn_count)
        for i in range(btn_count):
            btn = buy_buttons.nth(i)
            try:
                if not await btn.is_visible():
                    continue
            except Exception:
                continue
            try:
                ctx = btn.locator(
                    "xpath=ancestor::*[self::div or self::li or self::article or self::section][1]"
                ).first
                ctx_txt = await ctx.inner_text()
            except Exception:
                try:
                    ctx_txt = await btn.inner_text()
                except Exception:
                    ctx_txt = ""
            low = (ctx_txt or "").lower()
            if not low:
                continue
            hit = False
            for cand in variants:
                c = (cand or "").strip().lower()
                if not c:
                    continue
                if c in low:
                    hit = True
                    break
                d = re.sub(r"\D", "", c)
                if len(d) >= 2 and re.search(rf"\b{re.escape(d)}\s*[фf]?\b", low, re.I):
                    hit = True
                    break
            if not hit:
                continue
            try:
                await btn.scroll_into_view_if_needed()
                await btn.click(timeout=12000)
                await page.wait_for_timeout(2200)
                await _log_railway_ui_snapshot(page, "click_buy_after_click_fallback")
                logger.info("[buy][click_train] fallback orqali bosildi: idx=%s", i)
                return True
            except Exception as ex:
                logger.warning("[buy][click_train] fallback click xato idx=%s err=%s", i, ex)
                continue

        if dep and arr:
            logger.info("[buy][click_train] vaqt fallback: %s -> %s", dep, arr)
            time_buttons = page.locator(
                "button:has-text('Poyezdni tanlash'), button:has-text('poyezdni tanlash'), "
                "button:has-text('Купить'), button:has-text('Sotib'), button:has-text('Xarid'), "
                "a:has-text('Poyezdni tanlash'), a:has-text('Купить'), a:has-text('Tanlash'), "
                "[role='button']:has-text('Poyezdni tanlash'), [role='button']:has-text('Tanlash'), "
                "[class*='btn']:has-text('Poyezdni tanlash'), [class*='button']:has-text('Poyezdni tanlash')"
            )
            tcnt = await time_buttons.count()
            for i in range(tcnt):
                btn = time_buttons.nth(i)
                try:
                    if not await btn.is_visible():
                        continue
                except Exception:
                    continue
                try:
                    ctx = btn.locator(
                        "xpath=ancestor::*[self::div or self::li or self::article or self::section][1]"
                    ).first
                    ctx_txt = await ctx.inner_text()
                except Exception:
                    ctx_txt = ""
                low = (ctx_txt or "").lower()
                if not low:
                    continue
                if dep in low and arr in low:
                    try:
                        await btn.scroll_into_view_if_needed()
                        await btn.click(timeout=12000)
                        await page.wait_for_timeout(2200)
                        await _log_railway_ui_snapshot(
                            page, "click_buy_after_click_time_fallback"
                        )
                        logger.info("[buy][click_train] vaqt fallback orqali bosildi: idx=%s", i)
                        return True
                    except Exception as ex:
                        logger.warning(
                            "[buy][click_train] vaqt fallback click xato idx=%s err=%s",
                            i,
                            ex,
                        )
                        continue

            # Agar global clickable selectorlar ham bo'sh bo'lsa:
            # vaqt satrini topib, shu qatordagi "buy-like" elementni bosamiz.
            dep_re = re.escape(dep)
            arr_re = re.escape(arr)
            row_marker = page.get_by_text(re.compile(rf"\b{dep_re}\b")).first
            if await row_marker.count():
                try:
                    row = row_marker.locator(
                        f"xpath=ancestor::*[contains(., '{dep}') and contains(., '{arr}')][1]"
                    ).first
                    row_btn = row.locator(buy_like_xpath).first
                    if await row_btn.count():
                        await row_btn.scroll_into_view_if_needed()
                        await row_btn.click(timeout=12000, force=True)
                        await page.wait_for_timeout(2200)
                        await _log_railway_ui_snapshot(
                            page, "click_buy_after_click_time_row_fallback"
                        )
                        logger.info("[buy][click_train] vaqt+qator fallback orqali bosildi")
                        return True
                except Exception as ex:
                    logger.warning("[buy][click_train] vaqt+qator fallback xato: %s", ex)

        logger.warning("[buy] Poyezd №%s topilmadi (qidiruv: %s)", tnum, variants[:6])
        await _log_railway_ui_snapshot(page, "click_buy_train_not_found")
        return False

    logger.info("[buy][click_train] topildi: %s", chosen)

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
        await _log_railway_ui_snapshot(page, "click_buy_button_missing")
        return False

    logger.info("[buy][click_train] sotib olish tugmasi topildi, click")
    await buy_btn.click(timeout=12000)
    await page.wait_for_timeout(2200)
    await _log_railway_ui_snapshot(page, "click_buy_after_click")
    return True


def _seat_selection_success(before: dict, after: dict) -> bool:
    """_seat_selection_probe() natijalari: joy tanlanganini aniqlash."""
    if bool(after.get("seatWarn")):
        return False
    if int(after.get("selected") or 0) > int(before.get("selected") or 0):
        return True
    bf = int(before.get("freeSeats") or -1)
    af = int(after.get("freeSeats") or -1)
    if bf >= 0 and af >= 0 and af < bf:
        return True
    ba = int(before.get("accentShapes") or 0)
    aa = int(after.get("accentShapes") or 0)
    if aa > ba:
        return True
    return False


async def _pick_car_and_seat(page, car_type: str) -> None:
    """Avval eng arzon tarif/vagon, keyin bo'sh joylardan random bittasi."""

    def _parse_price_sum(raw: str) -> int | None:
        txt = (raw or "").replace("\u00a0", " ")
        m = re.findall(r"(\d[\d\s]{2,})\s*(?:so['`ʼ]m|сум)", txt, re.I)
        if not m:
            return None
        digits = re.sub(r"\D", "", m[0] or "")
        return int(digits) if digits else None

    preferred = (car_type or "").strip().lower()
    pick_candidates: list[tuple[int, int, int, object]] = []
    choose_btn = page.locator(
        "button:has-text('Tanlash'), button:has-text('tanlash'), "
        "button:has-text('Выбрать'), button:has-text('Tanla')"
    )
    btn_count = await choose_btn.count()
    for i in range(btn_count):
        btn = choose_btn.nth(i)
        try:
            if not await btn.is_visible():
                continue
        except Exception:
            continue
        try:
            ctx = btn.locator("xpath=ancestor::*[self::div or self::li or self::article][1]").first
            txt = await ctx.inner_text()
        except Exception:
            txt = await btn.inner_text()
        price = _parse_price_sum(txt)
        if price is None:
            continue
        # Foydalanuvchi car_type bergan bo'lsa, o'sha turga prioritet beramiz.
        pref_rank = 0 if (preferred and preferred in txt.lower()) else 1
        pick_candidates.append((pref_rank, price, i, btn))

    if pick_candidates:
        pick_candidates.sort(key=lambda x: (x[0], x[1], x[2]))
        pref_rank, cheapest, idx, best_btn = pick_candidates[0]
        try:
            await best_btn.scroll_into_view_if_needed()
            await best_btn.click(timeout=7000)
            await page.wait_for_timeout(1100)
            logger.info(
                "[buy] Tarif tanlandi: idx=%s narx=%s pref_rank=%s",
                idx,
                cheapest,
                pref_rank,
            )
        except Exception as e:
            logger.warning("[buy] Arzon tarif tugmasini bosib bo'lmadi: %s", e)
    elif preferred:
        # Narxni o'qiy olmasak ham so'ralgan vagon turini bosib ko'ramiz.
        for loc in (
            page.get_by_role("button", name=re.compile(re.escape(preferred), re.I)),
            page.locator(f"button:has-text('{preferred}')").first,
            page.locator(f"text={preferred}").first,
        ):
            try:
                if hasattr(loc, "count") and await loc.count():
                    await loc.click(timeout=5000)
                    await page.wait_for_timeout(900)
                    logger.info("[buy] So'ralgan vagon turi tanlandi: %s", preferred)
                    break
            except Exception:
                continue

    async def _seat_selection_probe() -> dict:
        try:
            return await page.evaluate(
                """() => {
                    const root =
                        document.querySelector('[class*="scheme" i]') ||
                        document.querySelector('[class*="seat-map" i]') ||
                        document.body;
                    const all = Array.from(root.querySelectorAll('*'));
                    const allDoc = Array.from(document.querySelectorAll('*'));
                    const cls = (el) => String(el.className || '').toLowerCase();
                    const visible = (el) => {
                        const st = window.getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        return st.visibility !== 'hidden' && st.display !== 'none' && r.width >= 8 && r.height >= 8;
                    };
                    let selected = 0;
                    all.forEach((el) => {
                        const c = cls(el);
                        const aria = String(el.getAttribute('aria-selected') || el.getAttribute('aria-pressed') || '').toLowerCase();
                        if (
                            c.includes('selected') ||
                            c.includes('active') ||
                            c.includes('chosen') ||
                            c.includes('picked') ||
                            c.includes('current') ||
                            c.includes('highlight') ||
                            c.includes('checked') ||
                            c.includes('pressed') ||
                            aria === 'true'
                        ) {
                            if (visible(el)) selected++;
                        }
                    });
                    const accentPaint = (v) => {
                        const s = String(v || '');
                        if (!s || s === 'none') return false;
                        const i = s.indexOf('rgb');
                        if (i < 0) return false;
                        const o = s.indexOf('(', i);
                        const cl = s.indexOf(')', o);
                        if (o < 0 || cl < 0) return false;
                        const parts = s
                            .slice(o + 1, cl)
                            .split(',')
                            .map((x) => parseInt(String(x).trim(), 10));
                        if (parts.length < 3 || parts.some((n) => Number.isNaN(n))) return false;
                        const r = parts[0];
                        const g = parts[1];
                        const b = parts[2];
                        if (b >= 130 && b > r + 18) return true;
                        if (g >= 110 && b >= 90 && r < 95) return true;
                        return false;
                    };
                    let accentShapes = 0;
                    const scheme =
                        document.querySelector('[class*="scheme" i]') ||
                        document.querySelector('[class*="seat-map" i]') ||
                        root;
                    Array.from(scheme.querySelectorAll('path, rect, circle, polygon, ellipse')).forEach((el) => {
                        if (!visible(el)) return;
                        const r = el.getBoundingClientRect();
                        const area = r.width * r.height;
                        if (area < 35 || area > 3600) return;
                        const st = window.getComputedStyle(el);
                        if (accentPaint(st.fill) || accentPaint(st.stroke)) accentShapes++;
                    });
                    const continueLike = allDoc.find((el) => {
                        const t = String(el.textContent || '').toLowerCase();
                        if (!visible(el)) return false;
                        if (!(t.includes("davom") || t.includes("продолж") || t.includes("далее") || t.includes("to'lov") || t.includes("к оплате"))) return false;
                        if (!(el instanceof HTMLElement)) return false;
                        return !el.hasAttribute('disabled') && el.getAttribute('aria-disabled') !== 'true';
                    });
                    const body = String((document.body && document.body.innerText) || '');
                    const mUz = body.match(/Bosh\\s*o['’]?rindiqlar\\s*:\\s*(\\d{1,3})/i);
                    const mRu = body.match(/Свободн\\S*\\s*мест\\S*\\s*:\\s*(\\d{1,3})/i);
                    const freeSeats = Number((mUz && mUz[1]) || (mRu && mRu[1]) || -1);
                    const low = body.toLowerCase();
                    const seatWarn =
                        low.includes("joy tanlamadingiz") ||
                        low.includes("место не выбра") ||
                        low.includes("select a seat") ||
                        low.includes("bosh vagonida joy tanlamadingiz");
                    return { selected, continueEnabled: !!continueLike, freeSeats, seatWarn, accentShapes };
                }"""
            )
        except Exception:
            return {
                "selected": 0,
                "continueEnabled": False,
                "freeSeats": -1,
                "seatWarn": False,
                "accentShapes": 0,
            }

    async def _seat_dom_diag() -> None:
        """cars-page joy sxemasi bo'yicha qisqa diagnostika (log uchun)."""
        try:
            diag = await page.evaluate(
                """() => {
                    const root =
                        document.querySelector('[class*="scheme" i]') ||
                        document.querySelector('[class*="seat-map" i]') ||
                        document.body;
                    const q = (s) => root.querySelectorAll(s).length;
                    const byPointer = Array.from(root.querySelectorAll('*')).filter((el) => {
                        const st = window.getComputedStyle(el);
                        if (st.cursor !== 'pointer') return false;
                        const r = el.getBoundingClientRect();
                        return r.width >= 8 && r.height >= 8 && r.width <= 90 && r.height <= 90;
                    }).length;
                    return {
                        rootTag: String(root.tagName || '').toLowerCase(),
                        dataSeat: q('[data-seat]'),
                        dataPlace: q('[data-place]'),
                        seatClass: q('[class*="seat" i]'),
                        placeClass: q('[class*="place" i]'),
                        svgNodes: q('svg *'),
                        pointerNodes: byPointer,
                    };
                }"""
            )
            logger.info("[buy] seat_dom_diag: %s", diag)
        except Exception as ex:
            logger.warning("[buy] seat_dom_diag xato: %s", ex)

    await _seat_dom_diag()

    seat_selectors = [
        # Avval seat-map ichidagi aniq tugmalar.
        "[class*='scheme' i] [data-seat]:not([disabled])",
        "[class*='scheme' i] [data-place]:not([disabled])",
        "[class*='scheme' i] [class*='seat' i]",
        "[data-seat]:not([disabled])",
        "[data-place]:not([disabled])",
        "button.seat:not(.disabled):not(.busy):not(.occupied)",
        "[class*='Seat']:not([class*='disabled']):not([class*='occupied']):not([class*='busy'])",
        "[class*='seat-free']",
        "[aria-label*='joy' i], [aria-label*='mesto' i], [aria-label*='место' i]",
    ]
    for sel in seat_selectors:
        seats = page.locator(sel)
        cnt = await seats.count()
        if not cnt:
            continue
        # "Random joy": mavjud joylardan tasodifiy bittasini tanlaymiz.
        start = random.randrange(cnt)
        for shift in range(cnt):
            idx = (start + shift) % cnt
            btn = seats.nth(idx)
            try:
                if not await btn.is_visible():
                    continue
                before = await _seat_selection_probe()
                # Seat elementini atributlar orqali ham tekshiramiz (text ko'pincha bo'sh bo'ladi).
                meta = await btn.evaluate(
                    """(el) => {
                        const txt = (el.textContent || '').trim();
                        const aria = (el.getAttribute('aria-label') || '').trim();
                        const ds = (el.getAttribute('data-seat') || '').trim();
                        const dp = (el.getAttribute('data-place') || '').trim();
                        const cls = (el.className || '').toString();
                        const dis = el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true';
                        return { txt, aria, ds, dp, cls, dis };
                    }"""
                )
                if meta.get("dis"):
                    continue
                blob = " ".join(
                    [
                        str(meta.get("txt") or ""),
                        str(meta.get("aria") or ""),
                        str(meta.get("ds") or ""),
                        str(meta.get("dp") or ""),
                    ]
                ).strip()
                # Joy raqami ko'rinmasa, bu container bo'lish ehtimoli yuqori.
                if not re.search(r"\b\d{1,3}\b", blob):
                    continue
                # Juda uzun konteyner matnlari (narx/tavsif) bo'lsa joy sifatida qabul qilmaymiz.
                if len(blob) > 64:
                    continue
                # "Faqat joy raqami"ga yaqin bo'lishi kerak (masalan: "14" yoki data-seat=14).
                txt_only = str(meta.get("txt") or "").strip()
                ds_only = str(meta.get("ds") or "").strip()
                dp_only = str(meta.get("dp") or "").strip()
                if not (
                    re.fullmatch(r"\d{1,3}", txt_only or "")
                    or re.fullmatch(r"\d{1,3}", ds_only or "")
                    or re.fullmatch(r"\d{1,3}", dp_only or "")
                ):
                    continue
                low_blob = blob.lower()
                if any(x in low_blob for x in ("vagon", "вагон", "narx", "сум", "o'rindiq", "bo'sh o'rin")):
                    continue
                await btn.click(timeout=5000)
                await page.wait_for_timeout(1000)
                after = await _seat_selection_probe()
                if _seat_selection_success(before, after):
                    logger.info("[buy] Random joy tanlandi: %s (idx=%s/%s)", sel, idx, cnt)
                    return
            except Exception:
                continue

    # Yakuniy fallback: DOMdan "free seat"ga o'xshash elementni topib JS orqali bosish.
    try:
        # Avval seat-map ichidagi kichik, raqamli seat chiplarni topamiz.
        js_precise = await page.evaluate(
            """() => {
                const root =
                    document.querySelector('[class*="scheme" i]') ||
                    document.querySelector('[class*="seat-map" i]') ||
                    document.body;
                const visible = (el) => {
                    const st = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return st.visibility !== 'hidden' && st.display !== 'none' && r.width >= 10 && r.height >= 10;
                };
                const isDisabled = (el) => {
                    const c = String(el.className || '').toLowerCase();
                    const dis = el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true';
                    return dis || c.includes('disabled') || c.includes('busy') || c.includes('occupied') || c.includes('sold');
                };
                const all = Array.from(root.querySelectorAll('button, div, span, a'));
                const candidates = all.filter((el) => {
                    if (!visible(el) || isDisabled(el)) return false;
                    const r = el.getBoundingClientRect();
                    // Seat chiplar odatda kichik bo'ladi.
                    if (r.width > 70 || r.height > 70) return false;
                    const txt = String(el.textContent || '').trim();
                    if (!/^\\d{1,3}$/.test(txt)) return false;
                    const c = String(el.className || '').toLowerCase();
                    const aria = String(el.getAttribute('aria-label') || '').toLowerCase();
                    const seatLike =
                        c.includes('seat') ||
                        c.includes('place') ||
                        c.includes('chair') ||
                        aria.includes('joy') ||
                        aria.includes('mesto') ||
                        aria.includes('место');
                    return seatLike;
                });
                if (!candidates.length) return false;
                const pick = candidates[Math.floor(Math.random() * candidates.length)];
                pick.scrollIntoView({ block: 'center', inline: 'center' });
                const before = String(pick.className || '').toLowerCase();
                pick.click();
                try {
                    pick.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                    pick.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                } catch (e) {}
                const after = String(pick.className || '').toLowerCase();
                return after.includes('selected') || after.includes('active') || after.includes('chosen') || before !== after;
            }"""
        )
        if js_precise:
            await page.wait_for_timeout(900)
            logger.info("[buy] Random joy tanlandi: js_precise_numeric")
            return
    except Exception as ex:
        logger.warning("[buy] js precise seat fallback xato: %s", ex)

    try:
        # Qo'shimcha fallback: raqamli matn (masalan "14") turgan tugunni topib,
        # eng yaqin clickable parentni bosamiz.
        js_numeric_parent = await page.evaluate(
            """() => {
                const root =
                    document.querySelector('[class*="scheme" i]') ||
                    document.querySelector('[class*="seat-map" i]') ||
                    document.body;
                const visible = (el) => {
                    const st = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return st.visibility !== 'hidden' && st.display !== 'none' && r.width >= 8 && r.height >= 8;
                };
                const disabledLike = (el) => {
                    const c = String(el.className || '').toLowerCase();
                    return (
                        el.hasAttribute('disabled') ||
                        el.getAttribute('aria-disabled') === 'true' ||
                        c.includes('disabled') ||
                        c.includes('busy') ||
                        c.includes('occupied') ||
                        c.includes('sold')
                    );
                };
                const nums = Array.from(root.querySelectorAll('*')).filter((el) => {
                    const t = String(el.textContent || '').trim();
                    if (!/^\\d{1,3}$/.test(t)) return false;
                    if (!visible(el)) return false;
                    const r = el.getBoundingClientRect();
                    return r.width <= 44 && r.height <= 44;
                });
                if (!nums.length) return false;
                const shuffled = nums.sort(() => Math.random() - 0.5);
                for (const n of shuffled) {
                    let p = n;
                    for (let i = 0; i < 4 && p; i++) {
                        const cls = String(p.className || '').toLowerCase();
                        const clickable =
                            p.tagName === 'BUTTON' ||
                            p.tagName === 'A' ||
                            p.getAttribute('role') === 'button' ||
                            p.hasAttribute('onclick') ||
                            cls.includes('seat') ||
                            cls.includes('place');
                        if (clickable && visible(p) && !disabledLike(p)) {
                            p.scrollIntoView({ block: 'center', inline: 'center' });
                            p.click();
                            return true;
                        }
                        p = p.parentElement;
                    }
                }
                return false;
            }"""
        )
        if js_numeric_parent:
            await page.wait_for_timeout(900)
            logger.info("[buy] Random joy tanlandi: js_numeric_parent")
            return
    except Exception as ex:
        logger.warning("[buy] js numeric-parent fallback xato: %s", ex)

    try:
        js_clicked = await page.evaluate(
            """() => {
                const all = Array.from(document.querySelectorAll('[data-seat], [data-place], [aria-label], [class*="seat"], [class*="place"]'));
                const visible = (el) => {
                    const st = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return st.visibility !== 'hidden' && st.display !== 'none' && r.width >= 10 && r.height >= 10;
                };
                const freeLike = all.filter((el) => {
                    const cls = String(el.className || '').toLowerCase();
                    const aria = String(el.getAttribute('aria-label') || '').toLowerCase();
                    const txt = String(el.textContent || '').toLowerCase();
                    const ds = String(el.getAttribute('data-seat') || el.getAttribute('data-place') || '');
                    const r = el.getBoundingClientRect();
                    const disabled = el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true' || cls.includes('disabled') || cls.includes('busy') || cls.includes('occupied');
                    if (disabled) return false;
                    if (!visible(el)) return false;
                    // Seat tugmalar odatda kichik bo'ladi; katta kartochka/containerlarni chiqarib tashlaymiz.
                    if (r.width > 72 || r.height > 72) return false;
                    const blobText = `${txt} ${aria} ${ds}`.trim();
                    const hasNum = /\\b\\d{1,3}\\b/.test(blobText);
                    if (!hasNum) return false;
                    // Faqat "raqamga yaqin" seat matni.
                    const onlyNumLike = /^\\s*\\d{1,3}\\s*$/.test(txt) || /^\\s*\\d{1,3}\\s*$/.test(ds);
                    if (!onlyNumLike && !/\\b(joy|mesto|место)\\b/i.test(blobText)) return false;
                    const blob = blobText;
                    if (blob.length > 64) return false;
                    if (/(vagon|вагон|narx|сум|o'rindiq|bo'sh o'rin)/i.test(blob)) return false;
                    return cls.includes('seat') || cls.includes('place') || aria.includes('joy') || aria.includes('mesto') || aria.includes('место') || !!ds;
                });
                if (!freeLike.length) return false;
                const pick = freeLike[Math.floor(Math.random() * freeLike.length)];
                pick.scrollIntoView({ block: 'center', inline: 'center' });
                const before = String(pick.className || '').toLowerCase();
                pick.click();
                // Ba'zi UIlarda oddiy click event yetmaydi — mousedown/up ham yuboramiz.
                try {
                    pick.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                    pick.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                } catch (e) {}
                const after = String(pick.className || '').toLowerCase();
                const becameSelected =
                    after.includes('selected') ||
                    after.includes('active') ||
                    after.includes('chosen') ||
                    (before !== after && (after.includes('seat') || after.includes('place')));
                return becameSelected;
            }"""
        )
        if js_clicked:
            await page.wait_for_timeout(900)
            logger.info("[buy] Random joy tanlandi: js_fallback")
            return
    except Exception as ex:
        logger.warning("[buy] js seat fallback xato: %s", ex)

    # SVG/pointer fallback: matnsiz seat chiplar uchun.
    try:
        js_pointer_svg = await page.evaluate(
            """() => {
                const root =
                    document.querySelector('[class*="scheme" i]') ||
                    document.querySelector('[class*="seat-map" i]') ||
                    document.body;
                const visible = (el) => {
                    const st = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return st.visibility !== 'hidden' && st.display !== 'none' && r.width >= 8 && r.height >= 8;
                };
                const disabledLike = (el) => {
                    const c = String(el.className || '').toLowerCase();
                    return (
                        el.hasAttribute('disabled') ||
                        el.getAttribute('aria-disabled') === 'true' ||
                        c.includes('disabled') ||
                        c.includes('busy') ||
                        c.includes('occupied') ||
                        c.includes('sold')
                    );
                };
                const seatLike = (el) => {
                    const c = String(el.className || '').toLowerCase();
                    const a = String(el.getAttribute('aria-label') || '').toLowerCase();
                    const d = String(el.getAttribute('data-seat') || el.getAttribute('data-place') || '').toLowerCase();
                    return (
                        c.includes('seat') ||
                        c.includes('place') ||
                        a.includes('joy') ||
                        a.includes('mesto') ||
                        a.includes('место') ||
                        !!d
                    );
                };
                const pointer = Array.from(root.querySelectorAll('*')).filter((el) => {
                    if (!visible(el) || disabledLike(el)) return false;
                    const st = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    if (r.width > 90 || r.height > 90) return false;
                    if (st.cursor === 'pointer' && seatLike(el)) return true;
                    // SVG elementlar uchun cursor har doim pointer bo'lmasligi mumkin.
                    if (el instanceof SVGElement && seatLike(el)) return true;
                    return false;
                });
                if (!pointer.length) return false;
                const shuffled = pointer.sort(() => Math.random() - 0.5);
                for (const el of shuffled) {
                    const r = el.getBoundingClientRect();
                    const x = Math.floor(r.left + r.width / 2);
                    const y = Math.floor(r.top + r.height / 2);
                    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
                    const top = document.elementFromPoint(x, y);
                    const target = top || el;
                    if (!target || !visible(target) || disabledLike(target)) continue;
                    target.scrollIntoView({ block: 'center', inline: 'center' });
                    try {
                        target.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX: x, clientY: y }));
                        target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, clientX: x, clientY: y }));
                        target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, clientX: x, clientY: y }));
                        target.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: x, clientY: y }));
                    } catch (e) {
                        try { target.click(); } catch (e2) {}
                    }
                    return true;
                }
                return false;
            }"""
        )
        if js_pointer_svg:
            await page.wait_for_timeout(900)
            logger.info("[buy] Random joy tanlandi: js_pointer_svg")
            return
    except Exception as ex:
        logger.warning("[buy] js pointer/svg fallback xato: %s", ex)

    # Pointer-only fallback: seatLike klass/aria bo'lmasa ham kichik pointer elementlarni sinab ko'ramiz.
    try:
        js_pointer_any = await page.evaluate(
            """() => {
                const root =
                    document.querySelector('[class*="scheme" i]') ||
                    document.querySelector('[class*="seat-map" i]') ||
                    document.body;
                const all = Array.from(root.querySelectorAll('*'));
                const visible = (el) => {
                    const st = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return st.visibility !== 'hidden' && st.display !== 'none' && r.width >= 8 && r.height >= 8;
                };
                const disabledLike = (el) => {
                    const c = String(el.className || '').toLowerCase();
                    return (
                        el.hasAttribute('disabled') ||
                        el.getAttribute('aria-disabled') === 'true' ||
                        c.includes('disabled') ||
                        c.includes('busy') ||
                        c.includes('occupied') ||
                        c.includes('sold')
                    );
                };
                const probe = () => {
                    let selected = 0;
                    for (const el of all) {
                        const c = String(el.className || '').toLowerCase();
                        const aria = String(el.getAttribute('aria-selected') || el.getAttribute('aria-pressed') || '').toLowerCase();
                        if ((c.includes('selected') || c.includes('active') || c.includes('chosen') || aria === 'true') && visible(el)) {
                            selected++;
                        }
                    }
                    const continueEnabled = all.some((el) => {
                        if (!visible(el)) return false;
                        const t = String(el.textContent || '').toLowerCase();
                        if (!(t.includes('davom') || t.includes('продолж') || t.includes('далее') || t.includes("to'lov") || t.includes('к оплате'))) return false;
                        const c = String(el.className || '').toLowerCase();
                        return !disabledLike(el) && !c.includes('disabled');
                    });
                    return { selected, continueEnabled };
                };

                const pointer = all.filter((el) => {
                    if (!visible(el) || disabledLike(el)) return false;
                    const st = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    // Yirik konteynerlarni chiqaramiz.
                    if (r.width > 64 || r.height > 64) return false;
                    if (r.width < 10 || r.height < 10) return false;
                    return st.cursor === 'pointer' || el instanceof SVGElement;
                });
                if (!pointer.length) return false;

                const before = probe();
                const shuffled = pointer.sort(() => Math.random() - 0.5).slice(0, 24);
                for (const el of shuffled) {
                    const r = el.getBoundingClientRect();
                    const x = Math.floor(r.left + r.width / 2);
                    const y = Math.floor(r.top + r.height / 2);
                    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;

                    const target = document.elementFromPoint(x, y) || el;
                    if (!target || !visible(target) || disabledLike(target)) continue;
                    target.scrollIntoView({ block: 'center', inline: 'center' });
                    try {
                        target.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX: x, clientY: y }));
                        target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, clientX: x, clientY: y }));
                        target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, clientX: x, clientY: y }));
                        target.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: x, clientY: y }));
                    } catch (e) {
                        try { target.click(); } catch (e2) {}
                    }

                    const after = probe();
                    if (after.selected > before.selected) return true;
                }
                return false;
            }"""
        )
        if js_pointer_any:
            await page.wait_for_timeout(900)
            logger.info("[buy] Random joy tanlandi: js_pointer_any")
            return
    except Exception as ex:
        logger.warning("[buy] js pointer-any fallback xato: %s", ex)

    # Browser-level mouse click fallback: SVG/chizma ichida koordinata bilan bosish.
    # JS click event ba'zi Angular handlerlarni trigger qilmaydi, real mouse click esa trigger qiladi.
    try:
        click_points = await page.evaluate(
            """() => {
                const root =
                    document.querySelector('[class*="scheme" i]') ||
                    document.querySelector('[class*="seat-map" i]') ||
                    document.body;
                const visible = (el) => {
                    const st = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return st.visibility !== 'hidden' && st.display !== 'none' && r.width >= 8 && r.height >= 8;
                };
                const small = (r) => r.width <= 72 && r.height <= 72 && r.width >= 10 && r.height >= 10;
                const points = [];

                // 1) Raqamli tugunlar (masalan "14") markazi.
                const numeric = Array.from(root.querySelectorAll('*')).filter((el) => {
                    const t = String(el.textContent || '').trim();
                    if (!/^\\d{1,3}$/.test(t)) return false;
                    if (!visible(el)) return false;
                    const r = el.getBoundingClientRect();
                    if (!small(r)) return false;
                    return true;
                });
                for (const el of numeric) {
                    const r = el.getBoundingClientRect();
                    points.push({
                        x: Math.round(r.left + r.width / 2),
                        y: Math.round(r.top + r.height / 2),
                        tag: String(el.tagName || '').toLowerCase(),
                    });
                }

                // 2) Agar raqamli tugun bo'lmasa, pointer/SVG kichik tugunlar.
                if (!points.length) {
                    const pointer = Array.from(root.querySelectorAll('*')).filter((el) => {
                        if (!visible(el)) return false;
                        const st = window.getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        if (!small(r)) return false;
                        return st.cursor === 'pointer' || el instanceof SVGElement;
                    });
                    for (const el of pointer) {
                        const r = el.getBoundingClientRect();
                        points.push({
                            x: Math.round(r.left + r.width / 2),
                            y: Math.round(r.top + r.height / 2),
                            tag: String(el.tagName || '').toLowerCase(),
                        });
                    }
                }

                // Dublikatlarni chiqaramiz.
                const uniq = [];
                const seen = new Set();
                for (const p of points) {
                    const k = `${p.x}:${p.y}`;
                    if (seen.has(k)) continue;
                    seen.add(k);
                    uniq.push(p);
                }
                return uniq.slice(0, 120);
            }"""
        )
        if click_points:
            random.shuffle(click_points)
            probe_before = await _seat_selection_probe()
            # Ko'p urinish qilmaymiz: eng ko'pi 24 ta nuqta.
            for p in click_points[:48]:
                x = int(p.get("x") or 0)
                y = int(p.get("y") or 0)
                if x <= 0 or y <= 0:
                    continue
                try:
                    await page.mouse.click(x, y)
                    await page.wait_for_timeout(320)
                    after = await _seat_selection_probe()
                    before_sel = int(probe_before.get("selected") or 0)
                    after_sel = int(after.get("selected") or 0)
                    before_free = int(probe_before.get("freeSeats") or -1)
                    after_free = int(after.get("freeSeats") or -1)
                    before_ac = int(probe_before.get("accentShapes") or 0)
                    after_ac = int(after.get("accentShapes") or 0)
                    if _seat_selection_success(probe_before, after):
                        logger.info(
                            "[buy] Random joy tanlandi: mouse_xy (%s,%s) tag=%s sel=%s->%s free=%s->%s ac=%s->%s",
                            x,
                            y,
                            p.get("tag") or "-",
                            before_sel,
                            after_sel,
                            before_free,
                            after_free,
                            before_ac,
                            after_ac,
                        )
                        return
                except Exception:
                    continue
    except Exception as ex:
        logger.warning("[buy] mouse_xy seat fallback xato: %s", ex)

    # Oxirgi fallback: bitta JS bilan taxminiy bosish o'rniga probe bilan tekshiruvli sikl.
    try:
        for try_idx in range(40):
            before_cp = await _seat_selection_probe()
            clicked = await page.evaluate(
                """() => {
                const root =
                    document.querySelector('[class*="scheme" i]') ||
                    document.querySelector('[class*="seat-map" i]') ||
                    document.body;
                const visible = (el) => {
                    const st = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return st.visibility !== 'hidden' && st.display !== 'none' && r.width >= 8 && r.height >= 8;
                };
                const disabledLike = (el) => {
                    const c = String(el.className || '').toLowerCase();
                    return (
                        el.hasAttribute('disabled') ||
                        el.getAttribute('aria-disabled') === 'true' ||
                        c.includes('disabled') ||
                        c.includes('busy') ||
                        c.includes('occupied') ||
                        c.includes('sold')
                    );
                };
                const clickableLike = (el) => {
                    if (!el) return false;
                    if (disabledLike(el) || !visible(el)) return false;
                    const tag = String(el.tagName || '').toUpperCase();
                    const cls = String(el.className || '').toLowerCase();
                    if (tag === 'BUTTON' || tag === 'A') return true;
                    if (el.getAttribute('role') === 'button') return true;
                    if (el.hasAttribute('onclick')) return true;
                    if (cls.includes('seat') || cls.includes('place')) return true;
                    if (el instanceof SVGElement && ['G', 'RECT', 'CIRCLE', 'PATH', 'TSPAN', 'TEXT'].includes(tag)) {
                        return true;
                    }
                    return false;
                };
                const labels = Array.from(root.querySelectorAll('*')).filter((el) => {
                    const t = String(el.textContent || '').trim();
                    if (!/^\\d{1,3}$/.test(t)) return false;
                    if (!visible(el)) return false;
                    const r = el.getBoundingClientRect();
                    if (r.width > 56 || r.height > 56) return false;
                    return true;
                });
                if (!labels.length) return false;
                const lb = labels[Math.floor(Math.random() * labels.length)];
                const r = lb.getBoundingClientRect();
                const x = Math.floor(r.left + r.width / 2);
                const y = Math.floor(r.top + r.height / 2);
                const stack = Array.from(document.elementsFromPoint(x, y) || []);
                let target = stack.find((el) => clickableLike(el));
                if (!target) {
                    let p = lb;
                    for (let i = 0; i < 8 && p; i++) {
                        if (clickableLike(p)) {
                            target = p;
                            break;
                        }
                        p = p.parentElement;
                    }
                }
                if (!target) return false;
                target.scrollIntoView({ block: 'center', inline: 'center' });
                try {
                    target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, clientX: x, clientY: y }));
                    target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, clientX: x, clientY: y }));
                    target.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: x, clientY: y }));
                } catch (e) {
                    try { target.click(); } catch (e2) { return false; }
                }
                return true;
            }"""
            )
            if not clicked:
                break
            await page.wait_for_timeout(500)
            after_cp = await _seat_selection_probe()
            if _seat_selection_success(before_cp, after_cp):
                logger.info("[buy] Random joy tanlandi: js_click_by_point try=%s", try_idx)
                return
    except Exception as ex:
        logger.warning("[buy] js click-by-point fallback xato: %s", ex)

    # SVG ichidagi raqamli label (text/tspan) — Playwright + mouse.
    try:
        sch = page.locator("[class*='scheme' i]").first
        if await sch.count() > 0:
            tiles = sch.locator("svg text, svg tspan").filter(
                has_text=re.compile(r"^[1-9]\d{0,2}$")
            )
            tc = await tiles.count()
            if tc:
                order = list(range(tc))
                random.shuffle(order)
                for idx in order[: min(tc, 55)]:
                    before_pl = await _seat_selection_probe()
                    el = tiles.nth(idx)
                    try:
                        await el.scroll_into_view_if_needed()
                        box = await el.bounding_box()
                        if box:
                            await page.mouse.click(
                                box["x"] + box["width"] / 2,
                                box["y"] + box["height"] / 2,
                            )
                        else:
                            await el.click(timeout=3500, force=True)
                    except Exception:
                        continue
                    await page.wait_for_timeout(450)
                    after_pl = await _seat_selection_probe()
                    if _seat_selection_success(before_pl, after_pl):
                        logger.info(
                            "[buy] Random joy tanlandi: playwright_svg_label idx=%s/%s",
                            idx,
                            tc,
                        )
                        return
    except Exception as ex:
        logger.warning("[buy] playwright svg label seat xato: %s", ex)

    logger.warning("[buy] Avtomatik random joy tanlash topilmadi (keyingi bosqichga o'tiladi)")


async def _fill_passenger(page, passenger: dict) -> None:
    name = (passenger.get("full_name") or "").strip()
    passport = (passenger.get("passport") or "").strip()
    phone = (passenger.get("phone") or "").strip()
    birth_date = (passenger.get("birth_date") or "").strip()  # kutilgan format: YYYY-MM-DD
    gender = (passenger.get("gender") or "").strip().lower()
    citizenship = (passenger.get("citizenship") or "").strip()
    logger.info(
        "[buy] Passenger profile: name=%s passport=%s phone=%s birth=%s gender=%s citizen=%s",
        bool(name),
        bool(passport),
        bool(phone),
        bool(birth_date),
        bool(gender),
        bool(citizenship),
    )

    async def _open_passenger_block_if_needed() -> None:
        # Ba'zi sahifalarda yo'lovchi forma "kiritish" tugmasi bosilgandan keyin ochiladi.
        targets = (
            "Yo'lovchilar haqida ma'lumot",
            "ma'lumotlaringizni kiriting",
            "ma'lumot kirit",
            "yo'lovchi",
            "kiriting",
            "Пассажир",
            "введите данные",
            "добавить",
            "Add passenger",
        )
        for t in targets:
            for loc in (
                page.get_by_role("button", name=re.compile(re.escape(t), re.I)),
                page.get_by_role("link", name=re.compile(re.escape(t), re.I)),
                page.locator(f"text={t}"),
            ):
                try:
                    c = await loc.count()
                except Exception:
                    c = 0
                if not c:
                    continue
                for i in range(min(c, 3)):
                    el = loc.nth(i)
                    try:
                        await el.scroll_into_view_if_needed()
                        await el.click(timeout=1500)
                        await page.wait_for_timeout(220)
                    except Exception:
                        continue

    async def _diag_passenger_fields() -> None:
        try:
            d = await page.evaluate(
                """() => {
                    const vis = (el) => {
                        const st = window.getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        return st.visibility !== 'hidden' && st.display !== 'none' && r.width > 6 && r.height > 6;
                    };
                    const all = Array.from(document.querySelectorAll('input, select, textarea'));
                    const v = all.filter(vis);
                    const sample = v.slice(0, 12).map((el) => ({
                        tag: String(el.tagName || '').toLowerCase(),
                        type: String(el.getAttribute('type') || '').toLowerCase(),
                        name: String(el.getAttribute('name') || ''),
                        fc: String(el.getAttribute('formcontrolname') || ''),
                        ph: String(el.getAttribute('placeholder') || ''),
                    }));
                    return { all: all.length, visible: v.length, sample };
                }"""
            )
            logger.info("[buy] passenger_fields_diag: %s", d)
        except Exception as ex:
            logger.warning("[buy] passenger_fields_diag xato: %s", ex)

    await _open_passenger_block_if_needed()
    await _diag_passenger_fields()

    async def _fill_by_selectors(value: str, selectors: list[str], label: str) -> bool:
        if not value:
            return False
        for sel in selectors:
            loc = page.locator(sel)
            cnt = await loc.count()
            if not cnt:
                continue
            for i in range(min(cnt, 6)):
                el = loc.nth(i)
                try:
                    try:
                        await el.scroll_into_view_if_needed()
                    except Exception:
                        pass
                    if not await el.is_visible():
                        continue
                    try:
                        await el.click(timeout=1500)
                    except Exception:
                        pass
                    try:
                        await el.fill(value, timeout=3500)
                    except Exception:
                        # Maskali inputlar uchun type fallback
                        try:
                            await el.press("Control+A", timeout=1200)
                        except Exception:
                            pass
                        await el.type(value, delay=20, timeout=3500)
                    try:
                        await el.dispatch_event("input")
                        await el.dispatch_event("change")
                    except Exception:
                        pass
                    logger.info("[buy] Passenger filled: %s via %s[%s]", label, sel, i)
                    return True
                except Exception:
                    continue
        logger.warning("[buy] Passenger field not filled: %s", label)
        return False

    await _fill_by_selectors(
        name,
        [
            "input[placeholder*='ФИО' i]",
            "input[placeholder*='Имя' i]",
            "input[placeholder*='ism' i]",
            "input[autocomplete='name']",
            "input[name*='first' i]",
            "input[name*='last' i]",
            "input[name*='full' i][name*='name' i]",
            "input[name*='fio' i]",
            "input[name*='name' i]",
            "input[formcontrolname*='name' i]",
            "input[formcontrolname*='first' i]",
            "input[formcontrolname*='last' i]",
            "input[type='text']",
        ],
        "full_name",
    )
    await _fill_by_selectors(
        passport,
        [
            "input[placeholder*='Паспорт' i]",
            "input[placeholder*='Серия' i]",
            "input[placeholder*='passport' i]",
            "input[name*='passport' i]",
            "input[name*='doc' i]",
            "input[name*='serial' i]",
            "input[name*='number' i]",
            "input[formcontrolname*='pass' i]",
            "input[formcontrolname*='document' i]",
        ],
        "passport",
    )
    await _fill_by_selectors(
        phone,
        [
            "input[type='tel']",
            "input[placeholder*='Телефон' i]",
            "input[placeholder*='phone' i]",
            "input[name*='phone' i]",
            "input[formcontrolname*='phone' i]",
        ],
        "phone",
    )
    # Tug'ilgan sana: ko'p formalarda date input yoki DOB/Birth nomi bilan bo'ladi.
    if birth_date:
        dob = birth_date
        m = re.match(r"^(\\d{4})-(\\d{2})-(\\d{2})$", birth_date)
        dob_dotted = f"{m.group(3)}.{m.group(2)}.{m.group(1)}" if m else birth_date
        ok_dob = await _fill_by_selectors(
            dob,
            [
                "input[type='date']",
                "input[name*='birth' i]",
                "input[name*='dob' i]",
                "input[placeholder*='туғил' i], input[placeholder*='рожден' i], input[placeholder*='birth' i]",
                "input[formcontrolname*='birth' i]",
            ],
            "birth_date",
        )
        if not ok_dob and dob_dotted != dob:
            await _fill_by_selectors(
                dob_dotted,
                [
                    "input[name*='birth' i]",
                    "input[name*='dob' i]",
                    "input[placeholder*='туғил' i], input[placeholder*='рожден' i], input[placeholder*='birth' i]",
                    "input[formcontrolname*='birth' i]",
                ],
                "birth_date_dotted",
            )

    # Jins: select/radio variantlarini qo'llab-quvvatlash.
    if gender in ("male", "female"):
        try:
            js_gender = await page.evaluate(
                """(g) => {
                    const labels = {
                        male: ["male", "erkak", "муж", "мужской", "m"],
                        female: ["female", "ayol", "жен", "женский", "f"],
                    };
                    const wanted = labels[g] || [];
                    const all = Array.from(document.querySelectorAll('select, input[type="radio"], button, [role="radio"]'));
                    const vis = (el) => {
                        const st = window.getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        return st.visibility !== 'hidden' && st.display !== 'none' && r.width > 6 && r.height > 6;
                    };
                    // 1) select
                    for (const s of all.filter(el => el.tagName === 'SELECT')) {
                        const opts = Array.from(s.options || []);
                        const hit = opts.find(o => wanted.some(w => String(o.value || '').toLowerCase().includes(w) || String(o.textContent || '').toLowerCase().includes(w)));
                        if (hit) {
                            s.value = hit.value;
                            s.dispatchEvent(new Event('change', { bubbles: true }));
                            return true;
                        }
                    }
                    // 2) radio/button
                    for (const el of all) {
                        if (!vis(el)) continue;
                        const t = `${el.getAttribute('value') || ''} ${el.getAttribute('aria-label') || ''} ${el.textContent || ''}`.toLowerCase();
                        if (!wanted.some(w => t.includes(w))) continue;
                        el.click();
                        return true;
                    }
                    return false;
                }""",
                gender,
            )
            if js_gender:
                logger.info("[buy] Passenger filled: gender=%s", gender)
            else:
                logger.warning("[buy] Passenger field not filled: gender")
        except Exception:
            logger.warning("[buy] Passenger gender fill xato")

    await _fill_by_selectors(
        citizenship,
        [
            "input[name*='citizen' i]",
            "input[name*='nation' i]",
            "input[placeholder*='fuqaro' i], input[placeholder*='гражд' i], input[placeholder*='citizen' i]",
            "input[formcontrolname*='citizen' i]",
        ],
        "citizenship",
    )


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
                await btn.scroll_into_view_if_needed()
                await btn.click(timeout=8000)
                await page.wait_for_timeout(2000)
                return True
            except Exception:
                try:
                    await btn.click(timeout=8000, force=True)
                    await page.wait_for_timeout(2000)
                    return True
                except Exception:
                    pass
                continue
    legacy = page.locator(
        "button:has-text('Продолжить'), button:has-text('Далее'), "
        "button:has-text('К оплате'), button:has-text('Davom'), "
        "button:has-text('Davom etish')"
    ).first
    if await legacy.count():
        try:
            await legacy.scroll_into_view_if_needed()
            await legacy.click(timeout=8000)
            await page.wait_for_timeout(2000)
            return True
        except Exception:
            pass
    try:
        js_ok = await page.evaluate(
            """() => {
                const all = Array.from(document.querySelectorAll('button, a, [role="button"], [class*="btn"], [class*="button"]'));
                const visible = (el) => {
                    const st = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return st.visibility !== 'hidden' && st.display !== 'none' && r.width > 10 && r.height > 10;
                };
                const pick = all.find((el) => {
                    const t = String(el.textContent || '').toLowerCase();
                    const c = String(el.className || '').toLowerCase();
                    const disabled = el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true' || c.includes('disabled');
                    if (disabled || !visible(el)) return false;
                    return t.includes('davom') || t.includes('продолж') || t.includes('далее') || t.includes("to'lov") || t.includes('к оплате');
                });
                if (!pick) return false;
                pick.scrollIntoView({ block: 'center', inline: 'center' });
                pick.click();
                return true;
            }"""
        )
        if js_ok:
            await page.wait_for_timeout(2000)
            return True
    except Exception:
        pass
    return False


def _looks_like_payment_step(url: str, content_snippet: str) -> bool:
    u = url.lower()
    if any(x in u for x in ("/cars-page", "/trains-page")):
        return False
    if any(x in u for x in ("pay", "payment", "oplata", "tolov", "checkout", "order")):
        return True
    c = content_snippet.lower()
    return any(
        x in c for x in ("оплат", "to'lov", "тўлов", "payment", "payme", "click.uz")
    )


async def open_ticket_page(
    from_code: str,
    to_code: str,
    date: str,
    train_number: str,
    dep_time: str = "",
    arr_time: str = "",
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

            outcome = await _wait_train_results_or_banner(page, 34000)
            if outcome == "timeout":
                st_rec = await _get_train_page_state(page)
                pb = int(st_rec.get("purchaseButtons") or 0)
                tb = int(st_rec.get("trainBlocks") or 0)
                if pb > 0 or tb >= 3:
                    logger.info(
                        "[open_ticket] vaqt tugadi, lekin ro'yxat izlari: purchaseButtons=%s trainBlocks=%s",
                        pb,
                        tb,
                    )
                    outcome = "results"

            clicked = False
            if outcome == "results":
                await _ensure_train_list_shows_target_date(page, (date or "").strip()[:10])
                clicked = await _click_buy_for_train(
                    page, train_number, dep_time=dep_time, arr_time=arr_time
                )
            elif outcome == "no_trains":
                logger.info("[open_ticket] Tanlangan sanada poyezd yo'q (banner)")
            else:
                logger.warning("[open_ticket] Ro'yxat kutish timeout")

            scr = await page.screenshot(full_page=False)
            if outcome == "no_trains":
                msg = (
                    "ℹ️ Tanlangan sanada ushbu yo'nalishda poyezdlar ko'rinmadi "
                    "(eticket javobi bo'sh / «mavjud emas»)."
                )
            elif outcome == "timeout":
                msg = "ℹ️ Poyezdlar ro'yxati yuklanmadi yoki juda uzoq kutildi."
            else:
                msg = "✅ To'lov bosqichiga yaqin" if clicked else "ℹ️ Poyezdlar sahifasi"
            return {
                "success": True,
                "screenshot": scr,
                "url": page.url if clicked else trains_url,
                "message": msg,
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
    dep_time: str,
    arr_time: str,
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

            logger.info(
                "[buy_ticket][1/6] login OK | yo'nalish %s→%s sana=%s poyezd=%r",
                from_name or from_code,
                to_name or to_code,
                date,
                train_number,
            )

            trains_url = await _open_trains_search(
                page, from_code, to_code, from_name, to_name, date
            )
            logger.info("[buy_ticket][2/6] open_trains tugadi | url=%s", trains_url[:240])

            logger.info(
                "[buy_ticket][3/6] qidiruv natijasi: .result-card yoki barqaror «mavjud emas» (~34s)"
            )
            outcome = await _wait_train_results_or_banner(page, 34000)
            if outcome == "timeout":
                st_rec = await _get_train_page_state(page)
                pb = int(st_rec.get("purchaseButtons") or 0)
                tb = int(st_rec.get("trainBlocks") or 0)
                if pb > 0 or tb >= 3:
                    logger.info(
                        "[buy_ticket] vaqt tugadi, lekin ro'yxat izlari: purchaseButtons=%s trainBlocks=%s",
                        pb,
                        tb,
                    )
                    outcome = "results"
            await _log_railway_ui_snapshot(page, f"buy_ticket_wait_{outcome}")
            logger.info("[buy_ticket][4/6] kutish natijasi: %s", outcome)

            if outcome == "timeout":
                scr = await page.screenshot(full_page=True)
                return {
                    "status": "error",
                    "message": (
                        "Poyezdlar ro'yxati yuklanmadi yoki javob juda uzoq kutildi. "
                        "Internet yoki eticket.railway.uz ni keyinroq urinib ko'ring."
                    ),
                    "screenshot": scr,
                }
            if outcome == "no_trains":
                scr = await page.screenshot(full_page=True)
                return {
                    "status": "error",
                    "message": (
                        "Tanlangan sanada ushbu yo'nalishda poyezdlar ko'rinmadi "
                        "(sayt: shu sanada poyezd yo'q yoki ro'yxat bo'sh). "
                        "Sanani yoki yo'nalishni tekshirib, qayta urinib ko'ring."
                    ),
                    "screenshot": scr,
                }

            await _ensure_train_list_shows_target_date(page, (date or "").strip()[:10])
            await _log_railway_ui_snapshot(page, "buy_ticket_after_date_ensure")

            logger.info(
                "[buy_ticket][5/6] _click_buy_for_train(%r, dep=%s, arr=%s)",
                train_number,
                dep_time,
                arr_time,
            )
            if not await _click_buy_for_train(
                page, train_number, dep_time=dep_time, arr_time=arr_time
            ):
                scr = await page.screenshot(full_page=True)
                st = await _get_train_page_state(page)
                nc = int(st.get("cards") or 0)
                nt = bool(st.get("noTrain"))
                if nc == 0 or nt:
                    msg = (
                        "Ro'yxat bo'sh yoki tanlangan sanada poyezd mavjud emas — "
                        f"№{train_number} ni tanlab bo'lmadi."
                    )
                else:
                    msg = (
                        f"Poyezd №{train_number} yoki «Sotib olish» tugmasi ro'yxatda topilmadi. "
                        "Boshqa poyezd tanlang yoki qo'lda tekshiring."
                    )
                return {"status": "error", "message": msg, "screenshot": scr}

            logger.info("[buy_ticket][6/6] vagon/joy va yo'lovchi bosqichlari")
            await _pick_car_and_seat(page, car_type or "")
            await page.wait_for_timeout(800)
            await _fill_passenger(page, passenger)
            await page.wait_for_timeout(600)

            # Cars-pagedan chiqmaguncha bir necha marta seat+continue qilamiz.
            for attempt in range(3):
                await _click_continue_to_payment(page)
                await page.wait_for_timeout(1200)
                cur_url = (page.url or "").lower()
                if "/cars-page" not in cur_url:
                    break
                try:
                    body_now = (await page.inner_text("body") or "").lower()
                except Exception:
                    body_now = ""
                seat_warn = (
                    "joy tanlamadingiz" in body_now
                    or "место не выбра" in body_now
                    or "select a seat" in body_now
                )
                logger.info(
                    "[buy] cars-page da qoldi (attempt=%s, seat_warn=%s): joyni qayta tanlash retry",
                    attempt + 1,
                    seat_warn,
                )
                await _pick_car_and_seat(page, car_type or "")
                await page.wait_for_timeout(600)

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
        dep_time=train.get("dep") or "",
        arr_time=train.get("arr") or "",
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
