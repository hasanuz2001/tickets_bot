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

// ───────────────────────────── STATE ─────────────────────────────────────────
const state = {
  fromCode: null, fromName: null,
  toCode:   null, toName:   null,
  date:     null, dateLabel: null,
  pickerTarget: null,
  screenStack: ["screenMain"],
  // sub id keyed by "fromCode|toCode|date"
  activeSubs: {},
};

// ───────────────────────────── NAVIGATION ────────────────────────────────────
function showScreen(id) {
  document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
  document.getElementById(id).classList.add("active");

  const isMain = id === "screenMain";
  document.getElementById("backBtn").classList.toggle("visible", !isMain);
  document.getElementById("bellBtn").style.display = isMain ? "" : "none";

  const titles = {
    screenMain:          "🚆 Chipta Qidirish",
    screenStation:       "Stansiya tanlang",
    screenDate:          "Sana tanlang",
    screenResults:       "Natijalar",
    screenSubscriptions: "🔔 Kuzatishlarim",
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

// ───────────────────────────── FIELD HELPERS ─────────────────────────────────
function setField(id, text) {
  const el = document.getElementById(id);
  el.textContent = text; el.classList.add("selected");
}
function clearField(id) {
  const el = document.getElementById(id);
  const defaults = { fromValue: "Stansiya tanlang", toValue: "Stansiya tanlang", dateValue: "Sana tanlang" };
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

  document.getElementById("resultsHeader").innerHTML = `
    <div class="route-info">
      <span>${state.fromName}</span>
      <span class="route-arrow">→</span>
      <span>${state.toName}</span>
    </div>
    <div class="date-info">📅 ${state.dateLabel}</div>`;

  const subKey = subKeyOf(state.fromCode, state.toCode, state.date);
  const isWatching = !!state.activeSubs[subKey];

  const availableTrains = trains.filter(t => (t.cars || []).some(c => c.freeSeats > 0));

  let html = "";

  if (!trains.length || !availableTrains.length) {
    // No seats / no trains — show subscribe banner
    html = `
      <div class="no-seats-banner">
        <div class="banner-icon">${trains.length ? "😕" : "🚫"}</div>
        <h3>${trains.length ? "Bo'sh o'rin yo'q" : "Poyezd topilmadi"}</h3>
        <p>${trains.length
          ? "Hozircha barcha vagonlarda joy band. Bot bilet chiqishi bilanoq sizga xabar beradi."
          : "Bu sana uchun ushbu yo'nalishda poyezd mavjud emas."
        }</p>
        ${trains.length ? buildBigWatchBtn(subKey, isWatching) : ""}
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
  const s = String(val);
  if (s.includes("T")) return s.split("T")[1].slice(0, 5);
  return s.slice(0, 5);
}

function buildTrainCard(train, subKey, isWatching) {
  const dep = parseTime(train.departureDate || train.departureTime);
  const arr = parseTime(train.arrivalDate   || train.arrivalTime);
  const avail  = (train.cars || []).filter(c => c.freeSeats > 0);

  const seatsHtml = avail.map(car => {
    const icon  = CAR_ICONS[car.carTypeName] || "🪑";
    const price = (car.tariffs || []).map(t => t.tariff).filter(Boolean)[0];
    return `<div class="seat-row">
      <div class="seat-type">
        <span class="seat-icon">${icon}</span>
        <span class="seat-name">${car.carTypeName || "Vagon"}</span>
        <span class="seat-count">(${car.freeSeats} joy)</span>
      </div>
      <span class="seat-price">${price ? `${Number(price).toLocaleString()} so'm` : "—"}</span>
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
          <div class="train-type">${train.brand || train.type || ""}</div>
          <div class="train-num">№${train.number || ""}</div>
        </div>
      </div>
      <div class="seats-list">${seatsHtml}</div>
      <a href="https://eticket.railway.uz" target="_blank" class="buy-btn">🎫 Chipta sotib olish</a>
      ${buildWatchBtn(subKey, isWatching)}
    </div>`;
}

function buildWatchBtn(subKey, isWatching) {
  if (!TG_USER_ID) return "";
  return isWatching
    ? `<button class="watch-btn watching" onclick="unsubscribe('${subKey}')">✅ Kuzatilmoqda — bekor qilish</button>`
    : `<button class="watch-btn" onclick="subscribe('${subKey}')">🔔 Bilet chiqsa xabar ber</button>`;
}

function buildBigWatchBtn(subKey, isWatching) {
  if (!TG_USER_ID) return `<p style="color:var(--tg-hint);font-size:12px">Bildirishnoma olish uchun Telegramdan oching.</p>`;
  return isWatching
    ? `<button class="big-watch-btn watching" onclick="unsubscribe('${subKey}')">✅ Kuzatilmoqda — bekor qilish</button>`
    : `<button class="big-watch-btn" onclick="subscribe('${subKey}')">🔔 Bilet chiqsa xabar ber</button>`;
}

// ───────────────────────────── SUBSCRIBE / UNSUBSCRIBE ───────────────────────
async function subscribe(subKey) {
  if (!TG_USER_ID) {
    showToast("Botni Telegram orqali oching!");
    return;
  }
  showLoading(true, "Kuzatuv qo'shilmoqda...");
  try {
    const res = await apiFetch("/api/subscribe", {
      method: "POST",
      body: JSON.stringify({
        user_id:   TG_USER_ID,
        from_code: state.fromCode,
        to_code:   state.toCode,
        from_name: state.fromName,
        to_name:   state.toName,
        date:      state.date,
      }),
    });
    if (res.status === "ok" || res.status === "already_exists") {
      state.activeSubs[subKey] = res.id;
      showToast("✅ Kuzatuv yoqildi! Bilet chiqsa xabar beraman.");
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
  // Update all watch buttons on results screen
  document.querySelectorAll(".watch-btn").forEach(btn => {
    btn.className = isWatching ? "watch-btn watching" : "watch-btn";
    btn.textContent = isWatching ? "✅ Kuzatilmoqda — bekor qilish" : "🔔 Bilet chiqsa xabar ber";
    btn.onclick = isWatching ? () => unsubscribe(subKey) : () => subscribe(subKey);
  });
  document.querySelectorAll(".big-watch-btn").forEach(btn => {
    btn.className = isWatching ? "big-watch-btn watching" : "big-watch-btn";
    btn.textContent = isWatching ? "✅ Kuzatilmoqda — bekor qilish" : "🔔 Bilet chiqsa xabar ber";
    btn.onclick = isWatching ? () => unsubscribe(subKey) : () => subscribe(subKey);
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
        <p>Poyezd qidirganda "Bilet chiqsa xabar ber" tugmasini bosing — bot bilet paydo bo'lishi bilanoq sizga Telegram xabar yuboradi.</p>
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
          <div class="sub-date">📅 ${s.date}</div>
          <span class="sub-status">⏳ Kuzatilmoqda (har 10 daqiqa)</span>
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

// ───────────────────────────── INIT ──────────────────────────────────────────
updateSearchBtn();
loadActiveSubs();
