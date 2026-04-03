"""
Telegram Mini App backend
- FastAPI: API proxy + static files
- SQLite: subscriptions storage
- APScheduler: every 10 min ticket check
- Telegram Bot API: push notifications
"""

import asyncio
import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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
        for col in ["time_from TEXT", "time_to TEXT", "auto_buy INTEGER DEFAULT 0"]:
            try:
                conn.execute(f"ALTER TABLE subscriptions ADD COLUMN {col}")
            except Exception:
                pass
        conn.commit()
    logger.info("Database initialized.")


# ── RAILWAY API ───────────────────────────────────────────────────────────────
async def fetch_trains(from_code: str, to_code: str, date: str) -> dict:
    import uuid
    payload = {
        "directions": {
            "forward": {
                "date": date,
                "depStationCode": from_code,
                "arvStationCode": to_code,
            }
        }
    }
    # Double-submit cookie pattern: generate UUID, send as both Cookie and header
    xsrf = str(uuid.uuid4())
    headers = {
        "User-Agent": RAILWAY_UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ru-RU,ru;q=0.9,uz;q=0.8",
        "Content-Type": "application/json",
        "Origin":  RAILWAY_BASE,
        "Referer": RAILWAY_BASE + "/ru/home",
        "Cookie": f"XSRF-TOKEN={xsrf}",
        "X-XSRF-TOKEN": xsrf,
    }
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        resp = await client.post(RAILWAY_API, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


def _parse_time(val) -> str:
    """Extract HH:MM from various formats:
       '2026-04-07T07:30:00', '07.04.2026 07:30:00', '07:30'
    """
    if not val:
        return ""
    s = str(val).strip()
    if "T" in s:
        return s.split("T")[1][:5]
    if " " in s:
        return s.split(" ")[1][:5]
    if ":" in s:
        return s[:5]
    return s


def extract_available(data: dict, time_from: str = None, time_to: str = None) -> list[dict]:
    """Return trains with free seats, optionally filtered by departure time range."""
    available = []
    try:
        trains = data["data"]["directions"]["forward"]["trains"]
    except (KeyError, TypeError):
        return available

    for train in trains:
        dep = _parse_time(train.get("departureDate") or train.get("departureTime"))

        # Vaqt filtri
        if time_from and dep and dep < time_from:
            continue
        if time_to and dep and dep > time_to:
            continue

        seats = []
        for car in train.get("cars", []):
            free = car.get("freeSeats", 0)
            if free > 0:
                price = next(
                    (t.get("tariff") for t in car.get("tariffs", []) if t.get("tariff")),
                    None,
                )
                seats.append({
                    "type":  car.get("carTypeName", "Vagon"),
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

    lines = [
        "🎫 <b>Bilet mavjud!</b>",
        "",
        f"🚆 <b>{sub['from_name']} → {sub['to_name']}</b>",
        f"📅 {sub['date']}{time_filter}",
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
        try:
            data     = await fetch_trains(sub["from_code"], sub["to_code"], sub["date"])
            trains   = extract_available(data, sub["time_from"], sub["time_to"])

            if trains:
                train = trains[0]

                if sub["auto_buy"] and os.getenv("RAILWAY_LOGIN") and os.getenv("RAILWAY_PASSWORD"):
                    # ── Avtomatik xarid ──────────────────────────────
                    logger.info(f"[auto_buy] Starting purchase for sub {sub['id']}")

                    # Yo'lovchi ma'lumotini olish
                    with get_db() as c:
                        passenger = c.execute(
                            "SELECT * FROM passenger_info WHERE user_id=?",
                            (sub["user_id"],)
                        ).fetchone()

                    if passenger:
                        try:
                            from automation import buy_ticket
                            result = await buy_ticket(
                                from_name    = sub["from_name"],
                                to_name      = sub["to_name"],
                                date         = sub["date"],
                                train_number = train["number"],
                                car_type     = train["seats"][0]["type"] if train["seats"] else "",
                                passenger    = dict(passenger),
                            )
                            # Natijani yuborish
                            tg_url = f"https://api.telegram.org/bot{BOT_TOKEN}"
                            seats_txt = "\n".join(
                                f"  🪑 {s['type']}: {s['free']} joy | {int(s['price']):,} so'm"
                                for s in train["seats"][:2] if s.get("price")
                            )
                            emoji = "✅" if result["status"] == "success" else "⚠️"
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
                        # Yo'lovchi ma'lumoti yo'q — oddiy notification
                        msg = (
                            build_notification(sub, trains) +
                            "\n\n⚠️ Avtomatik xarid uchun /myinfo buyrug'ini yuboring!"
                        )
                        await send_telegram_message(sub["user_id"], msg)
                else:
                    # ── Oddiy notification ───────────────────────────
                    msg = build_notification(sub, trains)
                    await send_telegram_message(sub["user_id"], msg)

                logger.info(f"Processed sub {sub['id']} for user {sub['user_id']}")

                # Deactivate after notifying — user can re-subscribe if needed
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

        await asyncio.sleep(0.5)   # rate-limit between subscriptions


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


# ── ROUTES ────────────────────────────────────────────────────────────────────
@app.post("/api/trains")
async def search_trains(req: TrainSearchRequest):
    try:
        data = await fetch_trains(req.from_code, req.to_code, req.date)
        return data
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="Railway API xatosi")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/subscribe")
async def subscribe(req: SubscribeRequest):
    today = datetime.now().strftime("%Y-%m-%d")
    if req.date < today:
        raise HTTPException(status_code=400, detail="O'tgan sanaga obuna bo'lib bo'lmaydi")

    with get_db() as conn:
        # Prevent duplicate active subscriptions
        existing = conn.execute(
            """SELECT id FROM subscriptions
               WHERE user_id=? AND from_code=? AND to_code=? AND date=? AND is_active=1""",
            (req.user_id, req.from_code, req.to_code, req.date),
        ).fetchone()

        if existing:
            return {"status": "already_exists", "id": existing["id"]}

        cur = conn.execute(
            """INSERT INTO subscriptions
               (user_id, from_code, to_code, from_name, to_name, date, time_from, time_to, auto_buy)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (req.user_id, req.from_code, req.to_code, req.from_name, req.to_name,
             req.date, req.time_from, req.time_to, 1 if req.auto_buy else 0),
        )
        conn.commit()
        sub_id = cur.lastrowid

    logger.info(f"New subscription #{sub_id}: {req.from_name}→{req.to_name} {req.date} (user {req.user_id})")
    return {"status": "ok", "id": sub_id}


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


@app.post("/api/passenger")
async def save_passenger(req: PassengerRequest):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO passenger_info (user_id, full_name, passport, phone)
               VALUES (?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 full_name=excluded.full_name,
                 passport=excluded.passport,
                 phone=excluded.phone,
                 updated_at=datetime('now')""",
            (req.user_id, req.full_name, req.passport, req.phone),
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
    return dict(row)


# ── PURCHASE ──────────────────────────────────────────────────────────────────
class PurchaseRequest(BaseModel):
    user_id:      str
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


async def process_purchase(purchase_id: int, passenger: dict, req: PurchaseRequest):
    """Playwright orqali chipta xarid qilish."""
    from automation import buy_ticket
    logger.info(f"Processing purchase #{purchase_id} for user {req.user_id}")

    result = await buy_ticket(
        from_name    = req.from_name,
        to_name      = req.to_name,
        date         = req.date,
        train_number = req.train_number,
        car_type     = req.car_type,
        passenger    = passenger,
    )

    # Natijani saqlash
    with get_db() as conn:
        conn.execute(
            "UPDATE purchase_requests SET status=?, result_msg=? WHERE id=?",
            (result["status"], result["message"], purchase_id),
        )
        conn.commit()

    # Telegram xabar yuborish
    tg = f"https://api.telegram.org/bot{BOT_TOKEN}"
    status_emoji = "✅" if result["status"] == "success" else "❌"
    text = (
        f"{status_emoji} <b>Chipta xaridi</b>\n\n"
        f"🚆 {req.from_name} → {req.to_name}\n"
        f"📅 {req.date}\n"
        f"🕐 {req.dep_time} → {req.arr_time} | {req.train_brand} №{req.train_number}\n\n"
        f"{result['message']}"
    )

    async with httpx.AsyncClient(timeout=15) as client:
        if result.get("screenshot"):
            await client.post(
                f"{tg}/sendPhoto",
                data={"chat_id": req.user_id, "caption": text, "parse_mode": "HTML"},
                files={"photo": ("ticket.png", result["screenshot"], "image/png")},
            )
        else:
            await client.post(f"{tg}/sendMessage", json={
                "chat_id": req.user_id, "text": text, "parse_mode": "HTML",
            })


# ── Manually trigger a check (for testing) ───────────────────────────────────
@app.post("/api/check-now")
async def trigger_check():
    asyncio.create_task(check_subscriptions())
    return {"status": "started"}


# ── STATIC FILES (must be last) ───────────────────────────────────────────────
app.mount("/", StaticFiles(directory="webapp", html=True), name="webapp")
