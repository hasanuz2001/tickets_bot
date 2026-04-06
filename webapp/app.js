"use strict";

// ───────────────────────────── TELEGRAM INIT ─────────────────────────────────
const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); }

const TG_USER     = tg?.initDataUnsafe?.user;
const TG_USER_ID  = TG_USER?.id ? String(TG_USER.id) : null;

// API base — same origin in prod, localhost in dev
const API_BASE = (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1")
  ? "http://localhost:8000"
  : "";

// ───────────────────────────── CONSTANTS ─────────────────────────────────────
const STATIONS = [
  { code: "2900000", name: "Toshkent" },
  { code: "2900001", name: "Toshkent Shimoliy" },
  { code: "2900002", name: "Toshkent Janubiy" },
  { code: "2900700", name: "Samarqand" },
  { code: "2900800", name: "Buxoro" },
  { code: "2900930", name: "Navoiy" },
  { code: "2900720", name: "Jizzax" },
  { code: "2900680", name: "Andijon" },
  { code: "2900940", name: "Namangan" },
  { code: "2900880", name: "Qo'qon" },
  { code: "2900920", name: "Marg'ilon" },
  { code: "2900750", name: "Qarshi" },
  { code: "2900255", name: "Termiz" },
  { code: "2900790", name: "Urganch" },
  { code: "2900172", name: "Xiva" },
  { code: "2900970", name: "Nukus" },
];

const DAY_NAMES   = ["Yak", "Dush", "Sesh", "Chor", "Pay", "Jum", "Shan"];
const MONTH_NAMES = ["Yan", "Fev", "Mar", "Apr", "May", "Iyun", "Iyul", "Avg", "Sen", "Okt", "Noy", "Dek"];
const CAR_ICONS   = { "Плацкарт": "🛏", "Купе": "🛏", "СВ": "⭐", "Люкс": "⭐", "Сидячий": "💺", "Общий": "🚃" };

// Vaqt oralig'i uchun soatlar (05:00 dan 23:00 gacha)
const TIME_SLOTS = ["05:00","06:00","07:00","08:00","09:00","10:00","11:00","12:00",
                    "13:00","14:00","15:00","16:00","17:00","18:00","19:00","20:00",
                    "21:00","22:00","23:00"];

// Poyezd brend ranglari
const BRAND_CLASS = {
  "Afrosiyob": "brand-afrosiyob",
  "Sharq":     "brand-sharq",
  "Talgo":     "brand-talgo",
  "Скорый":    "brand-express",
  "Cкорый":    "brand-express",
};

/** API dagi vagon nomi → Ekonom / Business / VIP guruhlari */
const COMFORT_OPTIONS = [
  { id: "all", label: "Barcha turlar", icon: "🎫", hint: "Platskart, kupe, SV, lyuks va boshqalar" },
  { id: "economy", label: "Ekonom", icon: "🛤", hint: "Platskart, sidyachiy, obshchiy" },
  { id: "business", label: "Business", icon: "🛏", hint: "Kupe klass" },
  { id: "vip", label: "VIP", icon: "⭐", hint: "SV, lyuks" },
];

function comfortLabel(comfortId) {
  const o = COMFORT_OPTIONS.find(x => x.id === comfortId);
  return o ? o.label : "Barcha turlar";
}

function carMatchesComfort(carTypeName, comfort) {
  if (!comfort || comfort === "all") return true;
  const n = (carTypeName || "").toLowerCase();
  if (comfort === "economy") {
    return ["плацкарт", "сидяч", "общ", "эконом"].some(k => n.includes(k));
  }
  if (comfort === "business") {
    return ["купе", "бизнес", "business"].some(k => n.includes(k));
  }
  if (comfort === "vip") {
    if (["люкс", "lux", "vip", "спальн"].some(k => n.includes(k))) return true;
    const t = n.replace(/[\s.№]/g, "");
    return t === "св";
  }
  return true;
}

// ───────────────────────────── STATE ─────────────────────────────────────────
const state = {
  fromCode: null, fromName: null,
  toCode:   null, toName:   null,
  date:     null, dateLabel: null,
  timeFrom: null, timeTo: null,   // "08:00" formatida, null = filtr yo'q
  comfortClass: "all",             // all | economy | business | vip
  pickerTarget: null,
  screenStack: ["screenMain"],
  activeSubs: {},
};

// ───────────────────────────── NAVIGATION ────────────────────────────────────
function showScreen(id) {
  document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
  document.getElementById(id).classList.add("active");

  const isMain = id === "screenMain";
  document.getElementById("backBtn").classList.toggle("visible", !isMain);
  document.getElementById("bellBtn").style.display    = isMain ? "" : "none";
  document.getElementById("profileBtn").style.display = isMain ? "" : "none";

  const titles = {
    screenMain:          "🚆 Chipta Qidirish",
    screenStation:       "Stansiya tanlang",
    screenDate:          "Sana tanlang",
    screenTime:          "Vaqt oralig'i",
    screenComfort:       "Joy turi",
    screenResults:       "Natijalar",
    screenSubscriptions: "🔔 Kuzatishlarim",
    screenProfile:       "👤 Profil",
  };
  document.getElementById("headerTitle").textContent = titles[id] || "";

  if (state.screenStack[state.screenStack.length - 1] !== id) {
    state.screenStack.push(id);
  }
}

function goBack() {
  state.screenStack.pop();
  const prev = state.screenStack[state.screenStack.length - 1] || "screenMain";
  showScreen(prev);
}

// ───────────────────────────── STATION PICKER ────────────────────────────────
function openStationPicker(target) {
  state.pickerTarget = target;
  document.getElementById("stationSearch").value = "";
  renderStations(STATIONS);
  showScreen("screenStation");
  setTimeout(() => document.getElementById("stationSearch").focus(), 150);
}

function renderStations(list) {
  const exclude = state.pickerTarget === "to" ? state.fromCode : state.toCode;
  const filtered = list.filter(s => s.code !== exclude);
  document.getElementById("stationList").innerHTML = filtered.map(s =>
    `<div class="station-item" onclick="selectStation('${s.code}','${escQ(s.name)}')">
       <div class="station-dot"></div>
       <span class="station-name">${s.name}</span>
     </div>`
  ).join("");
}

function filterStations() {
  const q = document.getElementById("stationSearch").value.toLowerCase();
  renderStations(STATIONS.filter(s => s.name.toLowerCase().includes(q)));
}

function selectStation(code, name) {
  if (state.pickerTarget === "from") {
    state.fromCode = code; state.fromName = name;
    setField("fromValue", name);
  } else {
    state.toCode = code; state.toName = name;
    setField("toValue", name);
  }
  updateSearchBtn();
  state.screenStack = state.screenStack.filter(s => s !== "screenStation");
  showScreen("screenMain");
}

function swapStations() {
  [state.fromCode, state.toCode]   = [state.toCode,   state.fromCode];
  [state.fromName, state.toName]   = [state.toName,   state.fromName];
  state.fromName ? setField("fromValue", state.fromName) : clearField("fromValue");
  state.toName   ? setField("toValue",   state.toName)   : clearField("toValue");
  updateSearchBtn();
}

// ───────────────────────────── DATE PICKER ───────────────────────────────────
function openDatePicker() {
  renderDates();
  showScreen("screenDate");
}

function renderDates() {
  const today = new Date();
  document.getElementById("dateGrid").innerHTML = Array.from({ length: 14 }, (_, i) => {
    const d    = new Date(today); d.setDate(today.getDate() + i);
    const val  = fmtDate(d);
    const sel  = val === state.date;
    return `
      <div class="date-card ${i === 0 ? "today" : ""} ${sel ? "selected" : ""}"
           onclick="selectDate('${val}','${d.getDate()} ${MONTH_NAMES[d.getMonth()]} ${d.getFullYear()}')">
        <div class="day-name">${DAY_NAMES[d.getDay()]}${i === 0 ? " (bugun)" : ""}</div>
        <div class="day-num">${String(d.getDate()).padStart(2,"0")}</div>
        <div class="month-name">${MONTH_NAMES[d.getMonth()]}</div>
      </div>`;
  }).join("");
}

function selectDate(value, label) {
  state.date = value; state.dateLabel = label;
  setField("dateValue", label);
  updateSearchBtn();
  state.screenStack = state.screenStack.filter(s => s !== "screenDate");
  showScreen("screenMain");
}

// ───────────────────────────── TIME PICKER ───────────────────────────────────
// Temporary state while user is picking (confirmed on button click)
let _tmpTimeFrom = null;
let _tmpTimeTo   = null;

function openTimePicker() {
  _tmpTimeFrom = state.timeFrom;
  _tmpTimeTo   = state.timeTo;
  renderTimePicker();
  showScreen("screenTime");
}

function renderTimePicker() {
  const anyBtn = document.getElementById("timeAnyBtn");
  anyBtn.classList.toggle("selected", !_tmpTimeFrom && !_tmpTimeTo);

  const renderSlots = (containerId, selected) => {
    const el = document.getElementById(containerId);
    el.innerHTML = TIME_SLOTS.map(t => {
      const cls = t === selected ? "time-slot selected" : "time-slot";
      const fn  = containerId === "timeSlotsFrom" ? "setTimeFrom" : "setTimeTo";
      return `<div class="${cls}" onclick="${fn}('${t}')">${t}</div>`;
    }).join("");
  };

  renderSlots("timeSlotsFrom", _tmpTimeFrom);
  renderSlots("timeSlotsTo",   _tmpTimeTo);
}

function setTimeFrom(t) {
  _tmpTimeFrom = t;
  renderTimePicker();
}

function setTimeTo(t) {
  _tmpTimeTo = t;
  renderTimePicker();
}

function selectTimeAny() {
  _tmpTimeFrom = null;
  _tmpTimeTo   = null;
  state.timeFrom = null;
  state.timeTo   = null;
  document.getElementById("timeAnyBtn").classList.add("selected");
  setField("timeValue", "Barcha vaqt");
  state.screenStack = state.screenStack.filter(s => s !== "screenTime");
  showScreen("screenMain");
}

function confirmTime() {
  if (_tmpTimeFrom && _tmpTimeTo && _tmpTimeFrom >= _tmpTimeTo) {
    showToast("⚠️ 'Dan' vaqti 'Gacha' dan kichik bo'lishi kerak");
    return;
  }
  state.timeFrom = _tmpTimeFrom;
  state.timeTo   = _tmpTimeTo;
  const label = (state.timeFrom || state.timeTo)
    ? `${state.timeFrom || "00:00"} — ${state.timeTo || "23:59"}`
    : "Barcha vaqt";
  setField("timeValue", label);
  state.screenStack = state.screenStack.filter(s => s !== "screenTime");
  showScreen("screenMain");
}

// ───────────────────────────── JOY TURI (COMFORT) ────────────────────────────
function openComfortPicker() {
  renderComfortPicker();
  showScreen("screenComfort");
}

function renderComfortPicker() {
  document.getElementById("comfortOptions").innerHTML = COMFORT_OPTIONS.map(o => `
    <div class="comfort-option ${state.comfortClass === o.id ? "selected" : ""}"
         onclick="selectComfort('${o.id}')">
      <span class="comfort-option-icon">${o.icon}</span>
      <div class="comfort-option-text">
        <div class="comfort-option-title">${o.label}</div>
        <div class="comfort-option-desc">${o.hint}</div>
      </div>
    </div>`).join("");
}

function selectComfort(id) {
  state.comfortClass = COMFORT_OPTIONS.some(x => x.id === id) ? id : "all";
  setField("comfortValue", comfortLabel(state.comfortClass));
  state.screenStack = state.screenStack.filter(s => s !== "screenComfort");
  showScreen("screenMain");
}

// ───────────────────────────── FIELD HELPERS ─────────────────────────────────
function setField(id, text) {
  const el = document.getElementById(id);
  el.textContent = text; el.classList.add("selected");
}
function clearField(id) {
  const el = document.getElementById(id);
  const defaults = {
    fromValue: "Stansiya tanlang", toValue: "Stansiya tanlang", dateValue: "Sana tanlang",
    comfortValue: "Barcha turlar",
  };
  el.textContent = defaults[id] || ""; el.classList.remove("selected");
}
function updateSearchBtn() {
  document.getElementById("searchBtn").disabled = !(state.fromCode && state.toCode && state.date);
}

// ───────────────────────────── SEARCH ────────────────────────────────────────
async function doSearch() {
  if (!(state.fromCode && state.toCode && state.date)) return;
  showLoading(true, "Poyezdlar qidirilmoqda...");
  try {
    const resp = await apiFetch("/api/trains", {
      method: "POST",
      body: JSON.stringify({ from_code: state.fromCode, to_code: state.toCode, date: state.date }),
    });
    renderResults(resp);
  } catch {
    showError("Serverga ulanishda xatolik. Internet aloqasini tekshiring.");
  } finally {
    showLoading(false);
  }
}

// ───────────────────────────── RENDER RESULTS ────────────────────────────────
function renderResults(data) {
  let trains = [];
  try { trains = data.data.directions.forward.trains || []; } catch { trains = []; }

  const timeInfo = (state.timeFrom || state.timeTo)
    ? `&nbsp;⏰ ${state.timeFrom || "00:00"} — ${state.timeTo || "23:59"}`
    : "";
  const comfortInfo = state.comfortClass && state.comfortClass !== "all"
    ? `&nbsp;🪑 ${comfortLabel(state.comfortClass)}`
    : "";
  document.getElementById("resultsHeader").innerHTML = `
    <div class="route-info">
      <span>${state.fromName}</span>
      <span class="route-arrow">→</span>
      <span>${state.toName}</span>
    </div>
    <div class="date-info">📅 ${state.dateLabel}${timeInfo}${comfortInfo}</div>`;

  const subKey = subKeyOf(state.fromCode, state.toCode, state.date);
  const isWatching = !!state.activeSubs[subKey];

  // Vaqt filtri
  const inTimeRange = (train) => {
    if (!state.timeFrom && !state.timeTo) return true;
    const dep = parseTime(train.departureDate || train.departureTime);
    if (!dep) return true;
    const from = state.timeFrom || "00:00";
    const to   = state.timeTo   || "23:59";
    return dep >= from && dep <= to;
  };

  const timeFilteredTrains = trains.filter(inTimeRange);
  const rawAvailable = timeFilteredTrains.filter(t =>
    (t.cars || []).some(c => c.freeSeats > 0)
  );
  const availableTrains = rawAvailable
    .map(t => ({
      ...t,
      cars: (t.cars || []).filter(c =>
        c.freeSeats > 0 && carMatchesComfort(c.carTypeName, state.comfortClass)
      ),
    }))
    .filter(t => t.cars.length > 0);

  let html = "";

  const noTrainsAtAll   = trains.length === 0;
  const noInTimeRange   = timeFilteredTrains.length === 0 && trains.length > 0;
  const timeFilteredEmpty = timeFilteredTrains.length === 0;
  const noSeatsComfort  = !timeFilteredEmpty && rawAvailable.length > 0 && availableTrains.length === 0
    && state.comfortClass !== "all";
  const noSeatsRaw      = !timeFilteredEmpty && rawAvailable.length === 0;

  if (noTrainsAtAll || noInTimeRange || noSeatsComfort || noSeatsRaw) {
    let icon, title, msg;
    if (noTrainsAtAll) {
      icon = "🚫"; title = "Poyezd topilmadi";
      msg = "Bu sana uchun ushbu yo'nalishda hozircha reys ko'rinmayapti. Bilet chiqishi yoki bo'sh joy paydo bo'lishi bilanoq bildirishnoma olish uchun pastdagi tugmani bosing — bot har 10 daqiqada tekshiradi va Telegramga xabar yuboradi.";
    } else if (noInTimeRange) {
      icon = "⏰"; title = "Bu vaqtda poyezd yo'q";
      msg = `${state.timeFrom || "00:00"}–${state.timeTo || "23:59"} oralig'ida jo'nash topilmadi. Vaqt oralig'ini kengaytirishingiz mumkin yoki shu filtr bilan kuzating — tanlangan vaqtda joy ochilishi bilanoq bildirishnoma yuboramiz (har 10 daqiqada).`;
    } else if (noSeatsComfort) {
      icon = "🪑"; title = "Bu joy turida bo'sh joy yo'q";
      msg = `${comfortLabel(state.comfortClass)} uchun bo'sh joy topilmadi. "Barcha turlar"ni tanlang yoki boshqa tur bilan qidiring. Kuzatuvni yoqsangiz, kerakli turda joy ochilganda xabar beramiz.`;
    } else {
      icon = "😕"; title = "Bo'sh o'rin yo'q";
      msg = "Tanlangan vaqtda barcha vagonlarda joy band. Kuzatuvni yoqsangiz, bo'sh joy chiqishi bilan Telegram orqali bildirishnoma olasiz; \"Avtomatik sotib olish\" bo'lsa, bilet paydo bo'lishi bilan xaridga harakat qilinadi (har 10 daqiqada tekshiriladi).";
    }
    html = `
      <div class="no-seats-banner">
        <div class="banner-icon">${icon}</div>
        <h3>${title}</h3>
        <p>${msg}</p>
        ${buildBigWatchBtn(subKey, isWatching)}
      </div>`;
  } else {
    // Show trains with seats
    html = availableTrains.map(train => buildTrainCard(train, subKey, isWatching)).join("");
  }

  html += `<button class="new-search-btn" onclick="resetToMain()">🔄 Yangi qidiruv</button>`;
  document.getElementById("trainsList").innerHTML = html;
  showScreen("screenResults");
}

function parseTime(val) {
  if (!val) return "";
  const s = String(val).trim();
  // "2026-04-07T07:30:00"
  if (s.includes("T")) return s.split("T")[1].slice(0, 5);
  // "07.04.2026 07:30:00"  or  "07.04.2026 07:30"
  if (s.includes(" ")) return s.split(" ")[1].slice(0, 5);
  // Already "07:30" or "07:30:00"
  if (s.includes(":")) return s.slice(0, 5);
  return s;
}

function getBrandClass(brand) {
  return BRAND_CLASS[brand] || "brand-default";
}

function buildTrainCard(train, subKey, isWatching) {
  const dep   = parseTime(train.departureDate || train.departureTime);
  const arr   = parseTime(train.arrivalDate   || train.arrivalTime);
  const brand = train.brand || train.type || "";
  const avail = (train.cars || []).filter(c => c.freeSeats > 0);

  const seatsHtml = avail.map(car => {
    const icon  = CAR_ICONS[car.carTypeName] || "🪑";
    const price = (car.tariffs || []).map(t => t.tariff).filter(Boolean)[0];
    const trainData = JSON.stringify({
      number:   train.number || "",
      brand:    brand,
      dep:      dep,
      arr:      arr,
      car_type: car.carTypeName || "Vagon",
    }).replace(/'/g, "\\'");
    return `<div class="seat-row">
      <div class="seat-type">
        <span class="seat-icon">${icon}</span>
        <span class="seat-name">${car.carTypeName || "Vagon"}</span>
        <span class="seat-count">(${car.freeSeats} joy)</span>
      </div>
      <div style="display:flex;flex-direction:column;align-items:flex-end;gap:2px">
        <span class="seat-price">${price ? `${Number(price).toLocaleString()} so'm` : "—"}</span>
        <button class="inline-buy-btn" onclick='requestBuyTicket(JSON.parse(decodeURIComponent("${encodeURIComponent(JSON.stringify({number:train.number||"",brand,dep,arr,car_type:car.carTypeName||"Vagon"}))}")))''>🎫 Olish</button>
      </div>
    </div>`;
  }).join("");

  return `
    <div class="train-card">
      <div class="train-header">
        <div class="train-times">
          <span class="train-dep">${dep}</span>
          <div class="train-duration"><span class="arrow-line"></span>→</div>
          <span class="train-arr">${arr}</span>
        </div>
        <div class="train-meta">
          <div class="train-brand ${getBrandClass(brand)}">${brand || "Poyezd"}</div>
          <div class="train-num">№${train.number || ""}</div>
        </div>
      </div>
      <div class="seats-list">${seatsHtml}</div>
      <button class="buy-btn" onclick="openRailway()">🌐 O'zim sotib olish</button>
      ${buildWatchBtn(subKey, isWatching)}
    </div>`;
}

function buildWatchBtn(subKey, isWatching) {
  if (!TG_USER_ID) return "";
  return isWatching
    ? `<button class="watch-btn watching" onclick="unsubscribe('${subKey}')">✅ Kuzatilmoqda — bekor qilish</button>`
    : `<button class="watch-btn auto-buy-btn" onclick="subscribe('${subKey}', true)">🤖 Avtomatik sotib olish</button>`;
}

function buildBigWatchBtn(subKey, isWatching) {
  if (!TG_USER_ID) return `<p style="color:var(--tg-hint);font-size:12px">Telegram orqali oching.</p>`;
  return isWatching
    ? `<button class="big-watch-btn watching" onclick="unsubscribe('${subKey}')">✅ Kuzatilmoqda — bekor qilish</button>`
    : `<button class="big-watch-btn" onclick="subscribe('${subKey}', true)">🤖 Avtomatik sotib olish</button>`;
}

// ───────────────────────────── SUBSCRIBE / UNSUBSCRIBE ───────────────────────
async function subscribe(subKey, autoBuy = false) {
  if (!TG_USER_ID) {
    showToast("Botni Telegram orqali oching!");
    return;
  }
  showLoading(true, "Qo'shilmoqda...");
  try {
    const res = await apiFetch("/api/subscribe", {
      method: "POST",
      body: JSON.stringify({
        user_id:    TG_USER_ID,
        from_code:  state.fromCode,
        to_code:    state.toCode,
        from_name:  state.fromName,
        to_name:    state.toName,
        date:       state.date,
        time_from:  state.timeFrom || null,
        time_to:    state.timeTo   || null,
        auto_buy:   autoBuy,
        comfort_class: state.comfortClass || "all",
      }),
    });
    if (res.status === "ok" || res.status === "already_exists") {
      state.activeSubs[subKey] = res.id;
      const warns = res.auto_buy_warnings || [];
      if (autoBuy && warns.length) {
        showToast(warns[0]);
      } else {
        showToast(autoBuy
          ? "🤖 Kuzatuv yoqildi. Bilet chiqishi bilan jarayon boshlanadi (bir necha soniya ichida tekshiriladi)."
          : "✅ Kuzatuv yoqildi!"
        );
      }
      refreshResultButtons(subKey, true);
      updateBellBadge();
    }
  } catch {
    showToast("Xatolik yuz berdi. Qayta urinib ko'ring.");
  } finally {
    showLoading(false);
  }
}

async function unsubscribe(subKey) {
  const subId = state.activeSubs[subKey];
  if (!subId) return;
  showLoading(true, "Bekor qilinmoqda...");
  try {
    await apiFetch(`/api/subscriptions/${subId}`, { method: "DELETE" });
    delete state.activeSubs[subKey];
    showToast("🔕 Kuzatuv bekor qilindi.");
    refreshResultButtons(subKey, false);
    updateBellBadge();
  } catch {
    showToast("Xatolik. Qayta urinib ko'ring.");
  } finally {
    showLoading(false);
  }
}

function refreshResultButtons(subKey, isWatching) {
  document.querySelectorAll(".watch-btn").forEach(btn => {
    btn.className = isWatching ? "watch-btn watching" : "watch-btn auto-buy-btn";
    btn.textContent = isWatching ? "✅ Kuzatilmoqda — bekor qilish" : "🤖 Avtomatik sotib olish";
    btn.onclick = isWatching ? () => unsubscribe(subKey) : () => subscribe(subKey, true);
  });
  document.querySelectorAll(".big-watch-btn").forEach(btn => {
    btn.className = isWatching ? "big-watch-btn watching" : "big-watch-btn";
    btn.textContent = isWatching ? "✅ Kuzatilmoqda — bekor qilish" : "🤖 Avtomatik sotib olish";
    btn.onclick = isWatching ? () => unsubscribe(subKey) : () => subscribe(subKey, true);
  });
}

// ───────────────────────────── SUBSCRIPTIONS SCREEN ──────────────────────────
async function goToSubscriptions() {
  if (!TG_USER_ID) {
    showToast("Botni Telegram orqali oching!");
    return;
  }
  showLoading(true, "Yuklanmoqda...");
  try {
    const res = await apiFetch(`/api/subscriptions/${TG_USER_ID}`);
    renderSubscriptions(res.subscriptions || []);
    showScreen("screenSubscriptions");
  } catch {
    showToast("Ma'lumot olishda xatolik.");
  } finally {
    showLoading(false);
  }
}

function renderSubscriptions(subs) {
  const container = document.getElementById("subsList");

  if (!subs.length) {
    container.innerHTML = `
      <div class="subs-empty">
        <div class="subs-empty-icon">🔕</div>
        <h3>Kuzatishlar yo'q</h3>
        <p>Poyezd qidirganda natijalar ekranidagi kuzatuv tugmasini bosing — hozir chipta ko'rinmasa ham bot har 10 daqiqada tekshiradi va bilet yoki bo'sh joy paydo bo'lishi bilanoq bildirishnoma yuboradi.</p>
      </div>`;
    return;
  }

  // Refresh local cache
  subs.forEach(s => {
    state.activeSubs[subKeyOf(s.from_code, s.to_code, s.date)] = s.id;
  });

  container.innerHTML = `
    <p class="subs-section-title">${subs.length} ta faol kuzatuv</p>
    ${subs.map(s => `
      <div class="sub-card" id="sub-${s.id}">
        <div class="sub-icon">🚆</div>
        <div class="sub-info">
          <div class="sub-route">${s.from_name} → ${s.to_name}</div>
          <div class="sub-date">📅 ${s.date}${s.time_from || s.time_to ? `&nbsp;⏰ ${s.time_from||"00:00"}–${s.time_to||"23:59"}` : ""}${s.comfort_class && s.comfort_class !== "all" ? `&nbsp;🪑 ${comfortLabel(s.comfort_class)}` : ""}</div>
          <span class="sub-status">${s.auto_buy ? "🤖 Avtomatik xarid" : "⏳ Kuzatilmoqda"} (har 10 daqiqa)</span>
        </div>
        <button class="sub-delete" onclick="deleteSubFromList(${s.id},'${subKeyOf(s.from_code, s.to_code, s.date)}')" title="O'chirish">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
            <path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </button>
      </div>
    `).join("")}`;
}

async function deleteSubFromList(subId, subKey) {
  try {
    await apiFetch(`/api/subscriptions/${subId}`, { method: "DELETE" });
    delete state.activeSubs[subKey];
    document.getElementById(`sub-${subId}`)?.remove();
    updateBellBadge();
    // If list is now empty, show empty state
    if (!document.querySelector(".sub-card")) {
      renderSubscriptions([]);
    }
    showToast("🔕 Bekor qilindi.");
  } catch {
    showToast("Xatolik. Qayta urinib ko'ring.");
  }
}

// ───────────────────────────── PROFILE ───────────────────────────────────────
async function goToProfile() {
  showScreen("screenProfile");
  await loadProfile();
}

async function loadProfile() {
  if (!TG_USER_ID) return;
  try {
    const p = await apiFetch(`/api/passenger/${TG_USER_ID}`);
    document.getElementById("inputFullName").value = p.full_name || "";
    document.getElementById("inputPassport").value = p.passport  || "";
    document.getElementById("inputPhone").value    = p.phone     || "";
    document.getElementById("profileAvatar").textContent = "✅";
    document.getElementById("profileSavedInfo").style.display = "";
    document.getElementById("profileDot").style.display = "";
  } catch {
    // Not saved yet — empty form
    document.getElementById("profileDot").style.display = "none";
  }
}

async function saveProfile() {
  if (!TG_USER_ID) {
    showToast("Telegram orqali oching!");
    return;
  }
  const fullName = document.getElementById("inputFullName").value.trim().toUpperCase();
  const passport = document.getElementById("inputPassport").value.trim().toUpperCase();
  const phone    = document.getElementById("inputPhone").value.trim();

  if (!fullName) { showToast("⚠️ To'liq ismni kiriting"); return; }
  if (passport.length < 6) { showToast("⚠️ Passport raqamini to'g'ri kiriting"); return; }
  if (!phone.startsWith("+")) { showToast("⚠️ Telefon: +998... formatida kiriting"); return; }

  showLoading(true, "Saqlanmoqda...");
  try {
    await apiFetch("/api/passenger", {
      method: "POST",
      body: JSON.stringify({
        user_id:   TG_USER_ID,
        full_name: fullName,
        passport:  passport,
        phone:     phone,
      }),
    });
    document.getElementById("profileAvatar").textContent = "✅";
    document.getElementById("profileSavedInfo").style.display = "";
    document.getElementById("profileDot").style.display = "";
    showToast("✅ Ma'lumotlar saqlandi!");
  } catch {
    showToast("❌ Xatolik yuz berdi.");
  } finally {
    showLoading(false);
  }
}

// ───────────────────────────── BELL BADGE ────────────────────────────────────
async function loadActiveSubs() {
  if (!TG_USER_ID) return;
  try {
    const res = await apiFetch(`/api/subscriptions/${TG_USER_ID}`);
    (res.subscriptions || []).forEach(s => {
      state.activeSubs[subKeyOf(s.from_code, s.to_code, s.date)] = s.id;
    });
    updateBellBadge();
  } catch { /* silent */ }
}

function updateBellBadge() {
  const count = Object.keys(state.activeSubs).length;
  const badge = document.getElementById("bellBadge");
  badge.style.display = count > 0 ? "" : "none";
}

// ───────────────────────────── HELPERS ───────────────────────────────────────
async function apiFetch(path, options = {}) {
  const resp = await fetch(API_BASE + path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

function subKeyOf(fromCode, toCode, date) {
  return `${fromCode}|${toCode}|${date}`;
}

function fmtDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
}

function escQ(s) { return s.replace(/'/g, "\\'"); }

function showLoading(on, text = "Yuklanmoqda...") {
  document.getElementById("loadingText").textContent = text;
  document.getElementById("loadingOverlay").classList.toggle("active", on);
}

let toastTimer;
function showToast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 3000);
}

function showError(msg) {
  document.getElementById("resultsHeader").innerHTML = `<div class="route-info"><span>${state.fromName || ""}</span><span class="route-arrow">→</span><span>${state.toName || ""}</span></div>`;
  document.getElementById("trainsList").innerHTML = `
    <div class="no-results">
      <div class="no-results-icon">⚠️</div>
      <h3>Xatolik</h3>
      <p>${msg}</p>
    </div>
    <button class="new-search-btn" onclick="resetToMain()">🔄 Qayta urinish</button>`;
  showScreen("screenResults");
}

function resetToMain() {
  state.screenStack = ["screenMain"];
  showScreen("screenMain");
}

function openRailway() {
  const url = "https://eticket.railway.uz";
  if (tg) tg.openLink(url);
  else window.open(url, "_blank");
}

function requestBuyTicket(train) {
  if (!TG_USER_ID) {
    showToast("Iltimos, botni Telegram orqali oching.");
    return;
  }
  const payload = JSON.stringify({
    action:    "buy",
    from_code: state.fromCode,
    to_code:   state.toCode,
    from_name: state.fromName,
    to_name:   state.toName,
    date:      state.date,
    train,
  });
  if (tg) {
    tg.sendData(payload);  // Botga yuboradi va Mini App yopiladi
  } else {
    showToast("Faqat Telegram orqali ishlaydi.");
  }
}

// ───────────────────────────── INIT ──────────────────────────────────────────
updateSearchBtn();
loadActiveSubs();
loadProfile();
