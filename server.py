"""
Telegram Mini App backend
- FastAPI: API proxy + static files
- SQLite: subscriptions storage
- APScheduler: every 10 min ticket check
- Telegram Bot API: push notifications
"""

import asyncio
import html
import logging
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from passenger_profile import (
    FIELD_LABELS_UZ,
    missing_fields_message_uz,
    passenger_missing_fields,
)

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── CONFIG ────────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set!")
DB_PATH   = "subscriptions.db"
CHECK_INTERVAL_MINUTES = 10

RAILWAY_BASE = "https://eticket.railway.uz"
RAILWAY_API  = f"{RAILWAY_BASE}/api/v3/handbook/trains/list"
RAILWAY_UA   = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

# API vaqtlari ba'zan UTC (Z); filtrlash va xabarlar O'zbekiston vaqti bilan mos bo'lishi kerak
_TASHKENT_TZ = ZoneInfo("Asia/Tashkent")


# ── DATABASE ──────────────────────────────────────────────────────────────────
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT    NOT NULL,
                from_code   TEXT    NOT NULL,
                to_code     TEXT    NOT NULL,
                from_name   TEXT    NOT NULL,
                to_name     TEXT    NOT NULL,
                date        TEXT    NOT NULL,
                time_from   TEXT,
                time_to     TEXT,
                is_active   INTEGER NOT NULL DEFAULT 1,
                notified_at TEXT,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # Yo'lovchi ma'lumotlari (bir marta saqlanadi)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS passenger_info (
                user_id     TEXT PRIMARY KEY,
                full_name   TEXT NOT NULL,
                passport    TEXT NOT NULL,
                phone       TEXT NOT NULL,
                birth_date  TEXT,
                gender      TEXT,
                citizenship TEXT,
                updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # Chipta xarid so'rovlari
        conn.execute("""
            CREATE TABLE IF NOT EXISTS purchase_requests (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT NOT NULL,
                from_name    TEXT NOT NULL,
                to_name      TEXT NOT NULL,
                date         TEXT NOT NULL,
                train_number TEXT NOT NULL,
                train_brand  TEXT NOT NULL,
                dep_time     TEXT NOT NULL,
                arr_time     TEXT NOT NULL,
                car_type     TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'pending',
                result_msg   TEXT,
                screenshot   BLOB,
                created_at   TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # Migrations for existing DBs
        for col in [
            "time_from TEXT",
            "time_to TEXT",
            "auto_buy INTEGER DEFAULT 0",
            "comfort_class TEXT DEFAULT 'all'",
            "train_number TEXT",
            "train_brand TEXT",
            "dep_time TEXT",
            "arr_time TEXT",
        ]:
            try:
                conn.execute(f"ALTER TABLE subscriptions ADD COLUMN {col}")
            except Exception:
                pass
        for col in [
            "birth_date TEXT",
            "gender TEXT",
            "citizenship TEXT",
        ]:
            try:
                conn.execute(f"ALTER TABLE passenger_info ADD COLUMN {col}")
            except Exception:
                pass
        conn.commit()
    logger.info("Database initialized.")


# ── RAILWAY API ───────────────────────────────────────────────────────────────
def _railway_error_detail(resp: httpx.Response) -> str:
    """eticket.railway.uz javobidan foydalanuvchiga tushunarli qisqa matn."""
    text = (resp.text or "").strip()
    try:
        data = resp.json()
    except Exception:
        data = None
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, list) and err:
            msg = err[0].get("message") if isinstance(err[0], dict) else None
            if msg:
                return str(msg)
        if isinstance(data.get("message"), str):
            return data["message"]
    if text and len(text) < 400:
        return text
    return f"HTTP {resp.status_code}"


async def fetch_trains(from_code: str, to_code: str, date: str) -> dict:
    import uuid

    payload = {
        "directions": {
            "forward": {
                "date": date,
                "depStationCode": str(from_code).strip(),
                "arvStationCode": str(to_code).strip(),
            }
        }
    }
    last_resp: httpx.Response | None = None
    # Angular SPA: X-Custom-Language + uz sahifa refereri (v3 handbook shuni kutadi).
    langs = ("uz", "ru")
    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
        for attempt in range(3):
            xsrf = str(uuid.uuid4())
            for lang in langs:
                headers = {
                    "User-Agent": RAILWAY_UA,
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "uz-UZ,uz;q=0.9,ru-RU,ru;q=0.8",
                    "Content-Type": "application/json",
                    "Origin": RAILWAY_BASE,
                    "Referer": f"{RAILWAY_BASE}/{lang}/home",
                    "Cookie": f"XSRF-TOKEN={xsrf}",
                    "X-XSRF-TOKEN": xsrf,
                    "X-Custom-Language": lang,
                }
                resp = await client.post(RAILWAY_API, json=payload, headers=headers)
                last_resp = resp
                if resp.status_code == 200:
                    return resp.json()
                # Keyingi til / qayta urinishdan oldin log
                if attempt == 0 and lang == langs[0]:
                    logger.warning(
                        "Railway trains/list %s (%s): %s",
                        resp.status_code,
                        lang,
                        (resp.text or "")[:300],
                    )
            await asyncio.sleep(0.6 * (attempt + 1))

    assert last_resp is not None
    last_resp.raise_for_status()
    return last_resp.json()


def subscription_train_number(sub: sqlite3.Row) -> str | None:
    """Faol kuzatuv ma'lum poyezd uchun — NULL bo'lsa butun yo'nalish."""
    try:
        t = sub["train_number"]
    except (KeyError, IndexError):
        return None
    if t is None or str(t).strip() == "":
        return None
    return str(t).strip()


def normalize_comfort_spec(raw) -> str:
    """Bitta yoki vergul bilan: economy,business — tartiblangan."""
    if raw is None or str(raw).strip() == "":
        return "all"
    s = str(raw).strip().lower()
    if s == "all":
        return "all"
    valid = {"economy", "business", "vip"}
    parts = sorted({p.strip() for p in s.split(",") if p.strip() and p.strip() in valid})
    return "all" if not parts else ",".join(parts)


def normalize_train_brand_spec(raw) -> str:
    if raw is None or str(raw).strip() == "":
        return "all"
    s = str(raw).strip().lower()
    if s == "all":
        return "all"
    valid = {"afrosiyob", "sharq", "talgo", "express"}
    parts = sorted({p.strip() for p in s.split(",") if p.strip() and p.strip() in valid})
    return "all" if not parts else ",".join(parts)


def subscription_comfort_spec(sub: sqlite3.Row) -> str:
    try:
        c = sub["comfort_class"]
    except (KeyError, IndexError):
        return "all"
    return normalize_comfort_spec(c)


def subscription_train_brand_spec(sub: sqlite3.Row) -> str:
    try:
        b = sub["train_brand"]
    except (KeyError, IndexError):
        return "all"
    return normalize_train_brand_spec(b)


def _train_matches_single_brand(train: dict, brand: str) -> bool:
    blob = f"{train.get('brand') or ''} {train.get('type') or ''}".lower()
    if brand == "afrosiyob":
        return "afrosiyob" in blob or "афроси" in blob
    if brand == "sharq":
        return "sharq" in blob or "шарқ" in blob or "шарк" in blob
    if brand == "talgo":
        return "talgo" in blob or "тальго" in blob
    if brand == "express":
        return any(
            x in blob
            for x in ("скор", "скорый", "tez", "пассажир", "yo'lovchi", "yoʻlovchi", "yolovchi")
        )
    return False


def train_matches_brand_multi(train: dict, spec: str | None) -> bool:
    sp = normalize_train_brand_spec(spec) if spec else "all"
    if sp == "all":
        return True
    return any(_train_matches_single_brand(train, p.strip()) for p in sp.split(",") if p.strip())


def car_matches_comfort_multi(car_type_name: str | None, spec: str | None) -> bool:
    sp = normalize_comfort_spec(spec) if spec else "all"
    if sp == "all":
        return True
    return any(
        car_matches_comfort(car_type_name, p.strip()) for p in sp.split(",") if p.strip()
    )


def car_matches_comfort(car_type_name: str | None, comfort: str | None) -> bool:
    """
    O'zbekiston temir yo'llari vagon turini foydalanuvchi 'ekonom / business / vip' bilan moslashtirish.
    API odatda ruscha: Плацкарт, Купе, СВ, Люкс, Сидячий, Общий.
    """
    if not comfort or comfort == "all":
        return True
    n = (car_type_name or "").casefold().replace("ё", "е").strip()
    if comfort == "economy":
        return any(k in n for k in ("плацкарт", "сидяч", "общ", "эконом", "platz"))
    if comfort == "business":
        return any(k in n for k in ("купе", "бизнес", "business", "compartment"))
    if comfort == "vip":
        return any(k in n for k in ("люкс", "lux", "vip", "спальн")) or (
            n.strip(" .№") == "св"
        )
    return True


def _parse_time(val) -> str:
    """Jo'nash/kelish vaqtini Asia/Tashkent bo'yicha HH:MM qaytaradi (UTC Z bo'lsa aylantiradi)."""
    if not val:
        return ""
    s = str(val).strip()
    if "T" in s:
        try:
            iso = s.replace("Z", "+00:00") if s.endswith("Z") else s
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_TASHKENT_TZ)
            else:
                dt = dt.astimezone(_TASHKENT_TZ)
            return dt.strftime("%H:%M")
        except Exception:
            m = re.search(r"T(\d{1,2}):(\d{2})", s)
            if m:
                return f"{int(m.group(1)):02d}:{m.group(2)}"
            return ""
    if " " in s:
        tail = s.split(" ", 1)[1].strip()
        if ":" in tail:
            a, b, *_ = tail.split(":")
            return f"{int(a):02d}:{b[:2]}"
    if ":" in s:
        a, b, *_ = s.split(":")
        return f"{int(a):02d}:{b[:2]}"
    return ""


def _hm_to_minutes(hm: str) -> int | None:
    if not hm:
        return None
    parts = str(hm).strip().split(":")
    if len(parts) < 2:
        return None
    try:
        h, m = int(parts[0]), int(parts[1][:2])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h * 60 + m
    except ValueError:
        pass
    return None


def _dep_within_window(dep: str, time_from: str | None, time_to: str | None) -> bool:
    """Satr taqqosi o'rniga daqiqalar — '9:30' va '17:56' noto'g'ri chiqmasin."""
    d = _hm_to_minutes(dep)
    if d is None:
        return True
    if time_from:
        tf = _hm_to_minutes(time_from)
        if tf is not None and d < tf:
            return False
    if time_to:
        tt = _hm_to_minutes(time_to)
        if tt is not None and d > tt:
            return False
    return True


def extract_available(
    data: dict,
    time_from: str = None,
    time_to: str = None,
    comfort_class: str = "all",
    train_number: str | None = None,
    train_brand: str | None = None,
) -> list[dict]:
    """Return trains with free seats; vaqt, joy, poyezd turi va ixtiyoriy poyezd raqami bo'yicha filtr."""
    available = []
    try:
        trains = data["data"]["directions"]["forward"]["trains"]
    except (KeyError, TypeError):
        return available

    tn_filter = str(train_number).strip() if train_number else None
    cc_spec = normalize_comfort_spec(comfort_class)
    tb_spec = normalize_train_brand_spec(train_brand)

    for train in trains:
        if tn_filter and str(train.get("number", "")).strip() != tn_filter:
            continue
        if not train_matches_brand_multi(train, tb_spec):
            continue

        dep = _parse_time(train.get("departureDate") or train.get("departureTime"))

        if not _dep_within_window(dep, time_from, time_to):
            continue

        seats = []
        for car in train.get("cars", []):
            free = car.get("freeSeats", 0)
            if free <= 0:
                continue
            cname = car.get("carTypeName", "")
            if not car_matches_comfort_multi(cname, cc_spec):
                continue
            prices = []
            for t in car.get("tariffs", []) or []:
                v = t.get("tariff")
                if v is None or v == "":
                    continue
                try:
                    prices.append(float(v))
                except (TypeError, ValueError):
                    continue
            price = min(prices) if prices else None
            seats.append({
                "type":  cname or "Vagon",
                "free":  free,
                "price": price,
            })
        if seats:
            available.append({
                "dep":    dep,
                "arr":    _parse_time(train.get("arrivalDate") or train.get("arrivalTime")),
                "brand":  train.get("brand") or train.get("type", ""),
                "number": train.get("number", ""),
                "seats":  seats,
            })
    return available


# ── TELEGRAM NOTIFICATION ─────────────────────────────────────────────────────
async def send_telegram_message(user_id: str, text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id":    user_id,
        "text":       text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code != 200:
            logger.warning(f"Telegram send failed for {user_id}: {resp.text}")


def build_notification(sub: sqlite3.Row, trains: list[dict]) -> str:
    time_filter = ""
    if sub["time_from"] or sub["time_to"]:
        time_filter = f"  ⏰ {sub['time_from'] or '00:00'} — {sub['time_to'] or '23:59'}"
    cc_spec = subscription_comfort_spec(sub)
    comfort_filter = ""
    if cc_spec != "all":
        labels = {"economy": "Ekonom", "business": "Business", "vip": "VIP"}
        parts = [labels.get(p.strip(), p.strip()) for p in cc_spec.split(",") if p.strip()]
        comfort_filter = f"  🪑 {', '.join(parts)}"

    tb_spec = subscription_train_brand_spec(sub)
    brand_filter = ""
    if tb_spec != "all":
        bl = {
            "afrosiyob": "Afrosiyob",
            "sharq": "Sharq",
            "talgo": "Talgo",
            "express": "Tezkor",
        }
        parts = [bl.get(p.strip(), p.strip()) for p in tb_spec.split(",") if p.strip()]
        brand_filter = f"  🚄 {', '.join(parts)}"

    stn = subscription_train_number(sub)
    lines = [
        "🎫 <b>Bilet mavjud!</b>",
        "",
        f"🚆 <b>{sub['from_name']} → {sub['to_name']}</b>",
    ]
    if stn:
        try:
            dep_s = str(sub["dep_time"] or "").strip()
            arr_s = str(sub["arr_time"] or "").strip()
        except (KeyError, IndexError):
            dep_s, arr_s = "", ""
        tpart = ""
        if dep_s:
            tpart = f"  ⏱ {dep_s}" + (f" → {arr_s}" if arr_s else "")
        lines.append(f"🚂 <b>Poyezd №{stn}</b>{tpart}")
    lines += [
        f"📅 {sub['date']}{time_filter}{comfort_filter}{brand_filter}",
        "",
    ]
    for t in trains[:3]:
        lines.append(f"🕐 <b>{t['dep']} → {t['arr']}</b>  |  {t['brand']} №{t['number']}")
        for s in t["seats"][:2]:
            price_str = f"{int(s['price']):,} so'm" if s["price"] else "—"
            lines.append(f"  🪑 {s['type']}: <b>{s['free']} joy</b> | {price_str}")
        lines.append("")

    lines.append("👆 <a href='https://eticket.railway.uz'>Chipta sotib olish</a>")
    return "\n".join(lines)


# ── SCHEDULER TASK ────────────────────────────────────────────────────────────
async def process_subscription(sub: sqlite3.Row) -> None:
    """Bitta kuzatuvni tekshirish: joy bo'lsa Telegram + kerak bo'lsa avtomatik xarid."""
    try:
        data = await fetch_trains(sub["from_code"], sub["to_code"], sub["date"])
        trains = extract_available(
            data,
            sub["time_from"],
            sub["time_to"],
            sub["comfort_class"],
            subscription_train_number(sub),
            sub["train_brand"],
        )

        if trains:
            train = trains[0]
            wants_auto = int(sub["auto_buy"] or 0) == 1
            has_rail_creds = bool(
                os.getenv("RAILWAY_LOGIN", "").strip() and os.getenv("RAILWAY_PASSWORD", "").strip()
            )

            if wants_auto and has_rail_creds:
                logger.info(f"[auto_buy] Starting purchase for sub {sub['id']}")

                with get_db() as c:
                    passenger = c.execute(
                        "SELECT * FROM passenger_info WHERE user_id=?",
                        (sub["user_id"],)
                    ).fetchone()

                if passenger:
                    try:
                        from automation import buy_ticket
                        result = await buy_ticket(
                            from_code    = sub["from_code"],
                            to_code      = sub["to_code"],
                            from_name    = sub["from_name"],
                            to_name      = sub["to_name"],
                            date         = sub["date"],
                            train_number = train["number"],
                            car_type     = train["seats"][0]["type"] if train["seats"] else "",
                            passenger    = dict(passenger),
                        )
                        tg_url = f"https://api.telegram.org/bot{BOT_TOKEN}"
                        seats_txt = "\n".join(
                            f"  🪑 {s['type']}: {s['free']} joy | "
                            f"{int(float(s['price'])):,} so'm"
                            for s in train["seats"][:2] if s.get("price") is not None
                        )
                        emoji = "✅" if result["status"] in ("success", "partial") else "⚠️"
                        text = (
                            f"🤖 <b>Avtomatik xarid natijasi</b>\n\n"
                            f"🚆 {sub['from_name']} → {sub['to_name']}\n"
                            f"📅 {sub['date']}\n"
                            f"🕐 {train['dep']} → {train['arr']} | {train['brand']} №{train['number']}\n"
                            f"{seats_txt}\n\n"
                            f"{emoji} {result['message']}"
                        )
                        async with httpx.AsyncClient(timeout=15) as client:
                            if result.get("screenshot"):
                                await client.post(
                                    f"{tg_url}/sendPhoto",
                                    data={"chat_id": sub["user_id"], "caption": text, "parse_mode": "HTML"},
                                    files={"photo": ("result.png", result["screenshot"], "image/png")},
                                )
                            else:
                                await client.post(f"{tg_url}/sendMessage", json={
                                    "chat_id": sub["user_id"], "text": text, "parse_mode": "HTML",
                                })
                    except Exception as ae:
                        logger.error(f"Auto-buy failed: {ae}")
                        msg = build_notification(sub, trains)
                        await send_telegram_message(sub["user_id"], msg)
                else:
                    msg = (
                        build_notification(sub, trains) +
                        "\n\n⚠️ Avtomatik xarid uchun Mini App → Profil yoki /myinfo"
                    )
                    await send_telegram_message(sub["user_id"], msg)
            elif wants_auto and not has_rail_creds:
                msg = (
                    build_notification(sub, trains)
                    + "\n\n⚠️ Serverda <code>RAILWAY_LOGIN</code> / <code>RAILWAY_PASSWORD</code> "
                      "yo'q — avtomatik sotib olish ishlamayapti."
                )
                await send_telegram_message(sub["user_id"], msg)
            else:
                msg = build_notification(sub, trains)
                await send_telegram_message(sub["user_id"], msg)

            logger.info(f"Processed sub {sub['id']} for user {sub['user_id']}")

            with get_db() as conn:
                conn.execute(
                    "UPDATE subscriptions SET is_active=0, notified_at=datetime('now') WHERE id=?",
                    (sub["id"],)
                )
                conn.commit()
        else:
            logger.info(f"Sub {sub['id']}: no seats yet ({sub['from_name']}→{sub['to_name']} {sub['date']})")

    except Exception as e:
        logger.error(f"Error checking sub {sub['id']}: {e}")


async def check_subscription_by_id(sub_id: int) -> None:
    """Mini App obunadan keyin faqat shu kuzatuvni tekshirish (boshqa foydalanuvchilarga xabar ketmasin)."""
    today = datetime.now().strftime("%Y-%m-%d")
    with get_db() as conn:
        sub = conn.execute(
            "SELECT * FROM subscriptions WHERE id=? AND is_active=1 AND date>=?",
            (sub_id, today),
        ).fetchone()
    if not sub:
        logger.info(f"check_subscription_by_id: #{sub_id} faol emas yoki sana o'tgan")
        return
    await process_subscription(sub)


async def check_subscriptions():
    logger.info("Checking subscriptions...")
    today = datetime.now().strftime("%Y-%m-%d")

    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM subscriptions WHERE is_active = 1 AND date >= ?",
            (today,)
        ).fetchall()

    logger.info(f"Active subscriptions: {len(rows)}")

    for sub in rows:
        await process_subscription(sub)
        await asyncio.sleep(0.5)


# ── APP LIFESPAN ──────────────────────────────────────────────────────────────
scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.add_job(
        check_subscriptions,
        "interval",
        minutes=CHECK_INTERVAL_MINUTES,
        id="ticket_checker",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started — checking every {CHECK_INTERVAL_MINUTES} min.")
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Chipta Qidiruv API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── PYDANTIC MODELS ───────────────────────────────────────────────────────────
class TrainSearchRequest(BaseModel):
    from_code: str
    to_code:   str
    date:      str




def _norm_sub_train_number(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


class SubscribeRequest(BaseModel):
    user_id:   str
    from_code: str
    to_code:   str
    from_name: str
    to_name:   str
    date:      str
    time_from: str | None = None
    time_to:   str | None = None
    auto_buy:  bool = False
    comfort_class: str = "all"  # all yoki vergul: economy,business
    train_number: str | None = None  # NULL = butun yo'nalish; raqam = faqat shu reys
    train_brand: str | None = None  # vergul: afrosiyob,sharq
    dep_time: str | None = None  # jo'nash vaqti (HH:MM) — kuzatishlar ro'yxati uchun
    arr_time: str | None = None  # kelish vaqti

    @field_validator("dep_time", "arr_time", mode="before")
    @classmethod
    def _strip_dep_arr(cls, v):
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    @field_validator("train_brand", mode="before")
    @classmethod
    def _tbrand(cls, v):
        if v is None:
            return None
        if isinstance(v, list):
            s = ",".join(str(x).strip() for x in v if str(x).strip())
        else:
            s = str(v).strip()
        if not s or s.lower() == "all":
            return None
        norm = normalize_train_brand_spec(s)
        return None if norm == "all" else norm

    @field_validator("comfort_class", mode="before")
    @classmethod
    def _comfort(cls, v):
        if v is None:
            return "all"
        if isinstance(v, list):
            s = ",".join(str(x).strip() for x in v if str(x).strip())
        else:
            s = str(v).strip()
        return normalize_comfort_spec(s if s else "all")

    @field_validator("train_number", mode="before")
    @classmethod
    def _tn(cls, v):
        return _norm_sub_train_number(v)


# ── ROUTES ────────────────────────────────────────────────────────────────────
@app.post("/api/trains")
async def search_trains(req: TrainSearchRequest):
    try:
        data = await fetch_trains(req.from_code, req.to_code, req.date)
        return data
    except httpx.HTTPStatusError as e:
        upstream = _railway_error_detail(e.response)
        detail = (
            "Temir yo‘llar sayti javob bermadi yoki vaqtincha ishlamayapti. "
            "Birozdan keyin «Qayta urinish» bosing. "
            f"({upstream})"
        )
        raise HTTPException(status_code=502, detail=detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _auto_buy_env_warnings(user_id: str) -> list[str]:
    w = []
    if not os.getenv("RAILWAY_LOGIN", "").strip() or not os.getenv("RAILWAY_PASSWORD", "").strip():
        w.append("Serverda RAILWAY_LOGIN/PASSWORD yo'q — avtomatik xarid ishlamaydi.")
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM passenger_info WHERE user_id=?", (user_id,)
        ).fetchone()
    if not row:
        w.append("Profilda ism/passport/telefon yo'q — avtomatik xarid uchun Profilni to'ldiring.")
    return w


@app.post("/api/subscribe")
async def subscribe(req: SubscribeRequest):
    today = datetime.now().strftime("%Y-%m-%d")
    if req.date < today:
        raise HTTPException(status_code=400, detail="O'tgan sanaga obuna bo'lib bo'lmaydi")

    tn = req.train_number
    tbrand = req.train_brand if req.train_brand and req.train_brand != "all" else None

    with get_db() as conn:
        # Bir xil yo'nalish + sana + poyezd + poyezd turi — takrorlanmasin
        existing = conn.execute(
            """SELECT id FROM subscriptions
               WHERE user_id=? AND from_code=? AND to_code=? AND date=? AND is_active=1
               AND IFNULL(train_number, '') = IFNULL(?, '')
               AND IFNULL(train_brand, '') = IFNULL(?, '')
               AND IFNULL(comfort_class, 'all') = ?""",
            (req.user_id, req.from_code, req.to_code, req.date, tn, tbrand, req.comfort_class),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE subscriptions
                   SET auto_buy=?, time_from=?, time_to=?, comfort_class=?, train_number=?, train_brand=?,
                       dep_time=?, arr_time=?
                   WHERE id=? AND is_active=1""",
                (1 if req.auto_buy else 0, req.time_from, req.time_to,
                 req.comfort_class, tn, tbrand, req.dep_time, req.arr_time, existing["id"]),
            )
            conn.commit()
            sub_id = existing["id"]
            logger.info(f"Subscription #{sub_id} updated (auto_buy={req.auto_buy}, train={tn})")
            asyncio.create_task(check_subscription_by_id(sub_id))
            out = {"status": "already_exists", "id": sub_id}
            if req.auto_buy:
                out["auto_buy_warnings"] = _auto_buy_env_warnings(req.user_id)
            return out

        cur = conn.execute(
            """INSERT INTO subscriptions
               (user_id, from_code, to_code, from_name, to_name, date, time_from, time_to, auto_buy, comfort_class, train_number, train_brand, dep_time, arr_time)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (req.user_id, req.from_code, req.to_code, req.from_name, req.to_name,
             req.date, req.time_from, req.time_to, 1 if req.auto_buy else 0,
             req.comfort_class, tn, tbrand, req.dep_time, req.arr_time),
        )
        conn.commit()
        sub_id = cur.lastrowid

    logger.info(f"New subscription #{sub_id}: {req.from_name}→{req.to_name} {req.date} (user {req.user_id})")
    # Faqat shu obuna (barcha userlarning kuzatuvlarini emas — ortiqcha Telegram xabarlarsiz)
    asyncio.create_task(check_subscription_by_id(sub_id))
    out = {"status": "ok", "id": sub_id}
    if req.auto_buy:
        out["auto_buy_warnings"] = _auto_buy_env_warnings(req.user_id)
    return out


@app.get("/api/subscriptions/{user_id}")
async def get_subscriptions(user_id: str):
    today = datetime.now().strftime("%Y-%m-%d")
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM subscriptions
               WHERE user_id=? AND is_active=1 AND date >= ?
               ORDER BY date ASC""",
            (user_id, today),
        ).fetchall()
    return {"subscriptions": [dict(r) for r in rows]}


class SubscriptionPatchRequest(BaseModel):
    user_id: str
    auto_buy: bool


@app.patch("/api/subscriptions/{sub_id}")
async def patch_subscription(sub_id: int, body: SubscriptionPatchRequest):
    """Faqat o'z obunasi: auto_buy yoqish/o'chirish (kuzatuv faol qoladi)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM subscriptions WHERE id=? AND user_id=? AND is_active=1",
            (sub_id, body.user_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Topilmadi")
        conn.execute(
            "UPDATE subscriptions SET auto_buy=? WHERE id=?",
            (1 if body.auto_buy else 0, sub_id),
        )
        conn.commit()
    return {"status": "ok"}


@app.delete("/api/subscriptions/{sub_id}")
async def delete_subscription(sub_id: int):
    with get_db() as conn:
        conn.execute(
            "UPDATE subscriptions SET is_active=0 WHERE id=?",
            (sub_id,),
        )
        conn.commit()
    return {"status": "ok"}


# ── PASSENGER INFO ───────────────────────────────────────────────────────────
class PassengerRequest(BaseModel):
    user_id:   str
    full_name: str
    passport:  str
    phone:     str
    birth_date: str | None = None
    gender: str | None = None
    citizenship: str | None = None


@app.post("/api/passenger")
async def save_passenger(req: PassengerRequest):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO passenger_info (user_id, full_name, passport, phone, birth_date, gender, citizenship)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 full_name=excluded.full_name,
                 passport=excluded.passport,
                 phone=excluded.phone,
                 birth_date=excluded.birth_date,
                 gender=excluded.gender,
                 citizenship=excluded.citizenship,
                 updated_at=datetime('now')""",
            (
                req.user_id,
                req.full_name,
                req.passport,
                req.phone,
                req.birth_date,
                req.gender,
                req.citizenship,
            ),
        )
        conn.commit()
    return {"status": "ok"}


@app.get("/api/passenger/{user_id}")
async def get_passenger(user_id: str):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM passenger_info WHERE user_id=?", (user_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    d = dict(row)
    missing = passenger_missing_fields(d)
    d["profile_complete"] = len(missing) == 0
    d["missing_fields"] = missing
    return d


# ── PURCHASE ──────────────────────────────────────────────────────────────────
class PurchaseRequest(BaseModel):
    user_id:      str
    from_code:    str
    to_code:      str
    from_name:    str
    to_name:      str
    date:         str
    train_number: str
    train_brand:  str
    dep_time:     str
    arr_time:     str
    car_type:     str


@app.post("/api/purchase")
async def purchase_ticket(req: PurchaseRequest):
    """Chipta xarid buyurtmasini qabul qiladi va background da bajaradi."""
    # Yo'lovchi ma'lumotini olish
    with get_db() as conn:
        passenger = conn.execute(
            "SELECT * FROM passenger_info WHERE user_id=?", (req.user_id,)
        ).fetchone()
        if not passenger:
            raise HTTPException(status_code=400, detail="Avval yo'lovchi ma'lumotini kiriting")

        pdict = dict(passenger)
        missing = passenger_missing_fields(pdict)
        if missing:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": missing_fields_message_uz(missing)
                    + " Mini App → Profil yoki /myinfo",
                    "missing": missing,
                    "missing_labels_uz": [FIELD_LABELS_UZ.get(m, m) for m in missing],
                },
            )

        # Xarid so'rovini saqlash
        cur = conn.execute(
            """INSERT INTO purchase_requests
               (user_id, from_name, to_name, date, train_number, train_brand, dep_time, arr_time, car_type)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (req.user_id, req.from_name, req.to_name, req.date,
             req.train_number, req.train_brand, req.dep_time, req.arr_time, req.car_type),
        )
        purchase_id = cur.lastrowid
        conn.commit()

    # Background da xarid jarayonini boshlash
    asyncio.create_task(process_purchase(purchase_id, dict(passenger), req))
    return {"status": "started", "purchase_id": purchase_id}


async def _notify_purchase_telegram(req: PurchaseRequest, result: dict) -> None:
    """Natijani foydalanuvchiga yuboradi; HTML xatolar va katta caption uchun fallback."""
    chat_id = str(req.user_id).strip()
    if not chat_id:
        return

    def e(s) -> str:
        return html.escape(str(s) if s is not None else "", quote=False)

    status_emoji = "✅" if result.get("status") in ("success", "partial") else "❌"
    msg = e(result.get("message") or "")
    text_html = (
        f"{status_emoji} <b>Chipta xaridi</b>\n\n"
        f"🚆 {e(req.from_name)} → {e(req.to_name)}\n"
        f"📅 {e(req.date)}\n"
        f"🕐 {e(req.dep_time)} → {e(req.arr_time)} | {e(req.train_brand)} №{e(req.train_number)}\n\n"
        f"{msg}"
    )
    text_plain = (
        f"{status_emoji} Chipta xaridi\n\n"
        f"{req.from_name} → {req.to_name}\n"
        f"{req.date}\n"
        f"{req.dep_time} → {req.arr_time} | {req.train_brand} №{req.train_number}\n\n"
        f"{result.get('message') or ''}"
    )[:4090]

    tg = f"https://api.telegram.org/bot{BOT_TOKEN}"
    scr = result.get("screenshot")
    cap = text_html[:1020] if len(text_html) > 1020 else text_html

    async with httpx.AsyncClient(timeout=90) as client:
        if scr and isinstance(scr, (bytes, bytearray)) and len(scr) > 50:
            try:
                r = await client.post(
                    f"{tg}/sendPhoto",
                    data={"chat_id": chat_id, "caption": cap, "parse_mode": "HTML"},
                    files={"photo": ("ticket.png", scr, "image/png")},
                )
                if r.status_code == 200:
                    logger.info("purchase Telegram: sendPhoto ok user=%s", chat_id)
                    return
                logger.warning(
                    "purchase sendPhoto failed %s: %s",
                    r.status_code,
                    (r.text or "")[:800],
                )
            except Exception:
                logger.exception("purchase sendPhoto exception user=%s", chat_id)

        try:
            r = await client.post(
                f"{tg}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text_html[:4090],
                    "parse_mode": "HTML",
                },
            )
            if r.status_code == 200:
                logger.info("purchase Telegram: sendMessage HTML ok user=%s", chat_id)
                return
            logger.warning(
                "purchase sendMessage HTML failed %s: %s",
                r.status_code,
                (r.text or "")[:800],
            )
        except Exception:
            logger.exception("purchase sendMessage HTML user=%s", chat_id)

        try:
            r2 = await client.post(
                f"{tg}/sendMessage",
                json={"chat_id": chat_id, "text": text_plain},
            )
            if r2.status_code != 200:
                logger.error(
                    "purchase sendMessage plain failed %s: %s",
                    r2.status_code,
                    (r2.text or "")[:800],
                )
        except Exception:
            logger.exception("purchase sendMessage plain user=%s", chat_id)


async def process_purchase(purchase_id: int, passenger: dict, req: PurchaseRequest):
    """Playwright orqali chipta xarid qilish; xato yoki Telegram muammosi ham log + DB."""
    result: dict = {"status": "error", "message": "Jarayon boshlanmadi.", "screenshot": None}
    try:
        from automation import buy_ticket

        logger.info("Processing purchase #%s for user %s", purchase_id, req.user_id)
        result = await buy_ticket(
            from_code    = req.from_code,
            to_code      = req.to_code,
            from_name    = req.from_name,
            to_name      = req.to_name,
            date         = req.date,
            train_number = req.train_number,
            dep_time     = req.dep_time,
            arr_time     = req.arr_time,
            car_type     = req.car_type,
            passenger    = passenger,
        )
    except Exception as ex:
        logger.exception("purchase #%s buy_ticket crashed", purchase_id)
        result = {
            "status": "error",
            "message": f"Server: {type(ex).__name__}: {ex}",
            "screenshot": None,
        }

    try:
        with get_db() as conn:
            conn.execute(
                "UPDATE purchase_requests SET status=?, result_msg=? WHERE id=?",
                (result.get("status", "error"), result.get("message"), purchase_id),
            )
            conn.commit()
    except Exception:
        logger.exception("purchase #%s DB update failed", purchase_id)

    try:
        await _notify_purchase_telegram(req, result)
    except Exception:
        logger.exception("purchase #%s Telegram notify failed", purchase_id)


@app.get("/api/purchase/{purchase_id}/status")
async def purchase_status(purchase_id: int, user_id: str):
    """Mini App: xarid natijasini kuzatish (faqat o'z buyurtmasi)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT user_id, status, result_msg FROM purchase_requests WHERE id=?",
            (purchase_id,),
        ).fetchone()
    if not row or str(row["user_id"]) != str(user_id):
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": row["status"], "result_msg": row["result_msg"]}


# ── Manually trigger a check (for testing) ───────────────────────────────────
@app.post("/api/check-now")
async def trigger_check():
    asyncio.create_task(check_subscriptions())
    return {"status": "started"}


# ── STATIC FILES (must be last) ───────────────────────────────────────────────
app.mount("/", StaticFiles(directory="webapp", html=True), name="webapp")
