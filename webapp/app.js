"use strict";

// ───────────────────────────── TELEGRAM INIT ─────────────────────────────────
const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); }

const TG_USER     = tg?.initDataUnsafe?.user;
const TG_USER_ID  = TG_USER?.id ? String(TG_USER.id) : null;
const SEARCH_HISTORY_KEY = "tickets_bot_search_history_v1";
const SEARCH_HISTORY_MAX = 8;

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
  { code: "2900850", name: "Guliston" },
  { code: "2900255", name: "Termiz" },
  { code: "2900790", name: "Urganch" },
  { code: "2900172", name: "Xiva" },
  { code: "2900970", name: "Nukus" },
];

const DAY_NAMES   = ["Yak", "Dush", "Sesh", "Chor", "Pay", "Jum", "Shan"];
const MONTH_NAMES = ["Yan", "Fev", "Mar", "Apr", "May", "Iyun", "Iyul", "Avg", "Sen", "Okt", "Noy", "Dek"];
const CAR_ICONS   = { "Плацкарт": "🛏", "Купе": "🛏", "СВ": "⭐", "Люкс": "⭐", "Сидячий": "💺", "Общий": "🚃" };

// Vaqt oralig'i: 00:00 dan 23:59 gacha (har soat + kun oxirgi daqiqasi)
const TIME_SLOTS = [
  ...Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, "0")}:00`),
  "23:59",
];

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

/** Poyezd brendi / turi (API dagi brand + type bo'yicha filtr) */
const TRAIN_BRAND_OPTIONS = [
  { id: "all", label: "Barcha poyezdlar", icon: "🚆", hint: "Afrosiyob, Sharq, tezkor va boshqalar" },
  { id: "afrosiyob", label: "Afrosiyob", icon: "🚅", hint: "Tezyurar Afrosiyob" },
  { id: "sharq", label: "Sharq", icon: "⚡", hint: "Sharq tezyurar poyezdi" },
  { id: "talgo", label: "Talgo", icon: "🚄", hint: "Talgo" },
  { id: "express", label: "Tezkor / oddiy", icon: "🚃", hint: "Skoriy, yo'lovchi va boshqa tezkor/oddiy reyslar" },
];

function trainBrandLabel(brandId) {
  const o = TRAIN_BRAND_OPTIONS.find(x => x.id === brandId);
  return o ? o.label : "Barcha poyezdlar";
}

function trainMatchesSingleBrand(train, brandId) {
  const blob = `${train.brand || ""} ${train.type || ""}`.toLowerCase();
  if (brandId === "afrosiyob") {
    return blob.includes("afrosiyob") || blob.includes("афроси");
  }
  if (brandId === "sharq") {
    return blob.includes("sharq") || blob.includes("шарқ") || blob.includes("шарк");
  }
  if (brandId === "talgo") {
    return blob.includes("talgo") || blob.includes("тальго");
  }
  if (brandId === "express") {
    return ["скор", "скорый", "tez", "пассажир", "yo'lovchi", "yoʻlovchi", "yolovchi"].some(k => blob.includes(k));
  }
  return false;
}

/** Vergul bilan bir nechta tur: "afrosiyob,sharq" */
function trainMatchesBrandCsv(train, csv) {
  if (!csv || csv === "all") return true;
  return csv.split(",").some(p => trainMatchesSingleBrand(train, p.trim()));
}

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

function carMatchesComfortCsv(carTypeName, csv) {
  if (!csv || csv === "all") return true;
  return csv.split(",").some(p => carMatchesComfort(carTypeName, p.trim()));
}

/** Vagon nomi qaysi qulaylik guruhi — foydalanuvchiga qisqa matn */
function comfortBucketLabel(carTypeName) {
  if (carMatchesComfort(carTypeName, "economy")) return "Ekonom";
  if (carMatchesComfort(carTypeName, "business")) return "Business";
  if (carMatchesComfort(carTypeName, "vip")) return "VIP";
  return carTypeName || "Boshqa";
}

function normalizeComfortCsv(s) {
  const valid = ["economy", "business", "vip"];
  const parts = String(s || "").toLowerCase().split(",").map(x => x.trim()).filter(x => valid.includes(x));
  return parts.length ? [...new Set(parts)].sort().join(",") : "all";
}

function normalizeTrainBrandCsv(s) {
  const valid = ["afrosiyob", "sharq", "talgo", "express"];
  const parts = String(s || "").toLowerCase().split(",").map(x => x.trim()).filter(x => valid.includes(x));
  return parts.length ? [...new Set(parts)].sort().join(",") : "all";
}

const MULTI_LABEL_SEP = " va ";

function comfortCsvLabel() {
  if (!state.comfortCsv || state.comfortCsv === "all") return "Barcha turlar";
  return state.comfortCsv.split(",").map(p => comfortLabel(p.trim())).join(MULTI_LABEL_SEP);
}

function trainBrandCsvLabel() {
  if (!state.trainBrandCsv || state.trainBrandCsv === "all") return "Barcha poyezdlar";
  return state.trainBrandCsv.split(",").map(p => trainBrandLabel(p.trim())).join(MULTI_LABEL_SEP);
}

function comfortCsvLabelFromServer(raw) {
  if (!raw || raw === "all") return "";
  return String(raw).split(",").map(x => comfortLabel(x.trim())).join(MULTI_LABEL_SEP);
}

function trainBrandCsvLabelFromServer(raw) {
  if (!raw || raw === "all") return "";
  return String(raw).split(",").map(x => trainBrandLabel(x.trim())).join(MULTI_LABEL_SEP);
}

function subKeyFromServerRow(s) {
  return subKeyOf(
    s.from_code,
    s.to_code,
    s.date,
    s.train_number,
    s.train_brand ?? "all",
    s.comfort_class ?? "all"
  );
}

function trainHasAnyFreeSeat(train) {
  return (train.cars || []).some(c => (c.freeSeats || 0) > 0);
}

// ───────────────────────────── STATE ─────────────────────────────────────────
const state = {
  fromCode: null, fromName: null,
  toCode:   null, toName:   null,
  date:     null, dateLabel: null,
  timeFrom: null, timeTo: null,   // "08:00" formatida, null = filtr yo'q
  trainBrandCsv: "all",            // vergul: afrosiyob,sharq
  comfortCsv: "all",              // vergul: economy,business
  pickerTarget: null,
  screenStack: ["screenMain"],
  activeSubs: {},
  /** So'nggi yuklangan xarid topshiriqlari (kuzatuvlar ekranida qayta chizish uchun) */
  recentPurchases: [],
  searchHistory: [],
};

function stationNameByCode(code) {
  const s = STATIONS.find(x => String(x.code) === String(code));
  return s ? s.name : String(code || "");
}

function historyEntryFromState() {
  return {
    fromCode: state.fromCode,
    fromName: state.fromName || stationNameByCode(state.fromCode),
    toCode: state.toCode,
    toName: state.toName || stationNameByCode(state.toCode),
    date: state.date,
    dateLabel: state.dateLabel || state.date,
    timeFrom: state.timeFrom || null,
    timeTo: state.timeTo || null,
    trainBrandCsv: state.trainBrandCsv || "all",
    comfortCsv: state.comfortCsv || "all",
    savedAt: Date.now(),
  };
}

function historyKey(e) {
  return [
    e.fromCode || "",
    e.toCode || "",
    e.date || "",
    e.timeFrom || "",
    e.timeTo || "",
    e.trainBrandCsv || "all",
    e.comfortCsv || "all",
  ].join("|");
}

function loadSearchHistory() {
  try {
    const raw = localStorage.getItem(SEARCH_HISTORY_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    state.searchHistory = Array.isArray(arr) ? arr.filter(x => x && x.fromCode && x.toCode && x.date) : [];
  } catch {
    state.searchHistory = [];
  }
}

function saveSearchHistory() {
  try {
    localStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(state.searchHistory.slice(0, SEARCH_HISTORY_MAX)));
  } catch {
    /* ignore */
  }
}

function removeSearchHistoryItem(idx) {
  if (idx < 0 || idx >= state.searchHistory.length) return;
  state.searchHistory.splice(idx, 1);
  saveSearchHistory();
  renderSearchHistory();
}

function clearSearchHistory() {
  if (!state.searchHistory.length) return;
  if (!confirm("Barcha qidiruv tarixini o‘chirasizmi?")) return;
  state.searchHistory = [];
  saveSearchHistory();
  renderSearchHistory();
}

function pushSearchHistoryFromState() {
  if (!(state.fromCode && state.toCode && state.date)) return;
  const e = historyEntryFromState();
  const k = historyKey(e);
  state.searchHistory = [e, ...state.searchHistory.filter(x => historyKey(x) !== k)].slice(0, SEARCH_HISTORY_MAX);
  saveSearchHistory();
  renderSearchHistory();
}

function renderSearchHistory() {
  const box = document.getElementById("historyList");
  const wrap = document.getElementById("historySection");
  if (!box || !wrap) return;
  if (!state.searchHistory.length) {
    wrap.style.display = "none";
    box.innerHTML = "";
    return;
  }
  wrap.style.display = "";
  box.innerHTML = state.searchHistory.map((h, i) => {
    const t = (h.timeFrom || h.timeTo) ? ` · ${h.timeFrom || "00:00"}-${h.timeTo || "23:59"}` : "";
    const trainBrandText = (h.trainBrandCsv && h.trainBrandCsv !== "all")
      ? ` · 🚄 ${trainBrandCsvLabelFromServer(h.trainBrandCsv)}`
      : "";
    const comfortText = (h.comfortCsv && h.comfortCsv !== "all")
      ? ` · 🪑 ${comfortCsvLabelFromServer(h.comfortCsv)}`
      : "";
    return `
      <div class="history-item">
        <div class="history-item-top">
          <div class="history-route">${h.fromName} → ${h.toName}</div>
          <button type="button" class="history-delete-one" title="O‘chirish" aria-label="O‘chirish" onclick="removeSearchHistoryItem(${i})">✕</button>
        </div>
        <div class="history-meta">${h.dateLabel || h.date}${t}${trainBrandText}${comfortText}</div>
        <div class="history-actions">
          <button type="button" class="history-action-btn history-action-secondary" onclick="applyHistoryForEdit(${i})">Tahrirlash</button>
          <button type="button" class="history-action-btn" onclick="applyHistory(${i})">Qayta qidirish</button>
        </div>
      </div>
    `;
  }).join("");
}

async function applyHistory(idx) {
  await applyHistoryCommon(idx, true);
}

async function applyHistoryForEdit(idx) {
  await applyHistoryCommon(idx, false);
}

async function applyHistoryCommon(idx, autoSearch) {
  const h = state.searchHistory[idx];
  if (!h) return;
  state.fromCode = h.fromCode; state.fromName = h.fromName || stationNameByCode(h.fromCode);
  state.toCode = h.toCode; state.toName = h.toName || stationNameByCode(h.toCode);
  state.date = h.date; state.dateLabel = h.dateLabel || h.date;
  state.timeFrom = h.timeFrom || null; state.timeTo = h.timeTo || null;
  state.trainBrandCsv = normalizeTrainBrandCsv(h.trainBrandCsv || "all");
  state.comfortCsv = normalizeComfortCsv(h.comfortCsv || "all");
  setField("fromValue", state.fromName);
  setField("toValue", state.toName);
  setField("dateValue", state.dateLabel);
  setField("timeValue", (state.timeFrom || state.timeTo) ? `${state.timeFrom || "00:00"} — ${state.timeTo || "23:59"}` : "Barcha vaqt");
  setField("trainBrandValue", trainBrandCsvLabel());
  setField("comfortValue", comfortCsvLabel());
  updateSearchBtn();
  state.screenStack = ["screenMain"];
  showScreen("screenMain");
  if (autoSearch) {
    await doSearch();
  } else {
    showToast("Qidiruv parametrlarini o'zgartiring va 'Qidirish'ni bosing.");
  }
}

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
    screenTrainBrand:    "Poyezd turi",
    screenComfort:       "Joy turi",
    screenResults:       "Natijalar",
    screenSubscriptions: "🔔 Kuzatishlar / xaridlar",
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

let _tmpTrainBrandIds = new Set(["all"]);
let _tmpComfortIds = new Set(["all"]);

function trainBrandOptionSelected(id) {
  if (_tmpTrainBrandIds.has("all")) return id === "all";
  return _tmpTrainBrandIds.has(id);
}

function comfortOptionSelected(id) {
  if (_tmpComfortIds.has("all")) return id === "all";
  return _tmpComfortIds.has(id);
}

function trainBrandTmpSummaryLine() {
  if (_tmpTrainBrandIds.has("all")) return "Hozircha: barcha poyezdlar (filtr yo'q)";
  const ids = [..._tmpTrainBrandIds].filter(x => x !== "all").sort();
  if (!ids.length) return "Hozircha: barcha poyezdlar (filtr yo'q)";
  return `Tanlangan: ${ids.map(id => trainBrandLabel(id)).join(MULTI_LABEL_SEP)} (${ids.length} ta tur)`;
}

function comfortTmpSummaryLine() {
  if (_tmpComfortIds.has("all")) return "Hozircha: barcha joy turlari";
  const ids = [..._tmpComfortIds].filter(x => x !== "all").sort();
  if (!ids.length) return "Hozircha: barcha joy turlari";
  return `Tanlangan: ${ids.map(id => comfortLabel(id)).join(MULTI_LABEL_SEP)} (${ids.length} ta tur)`;
}

// ───────────────────────────── POYEZD TURI (bir nechta) ─────────────────────
function openTrainBrandPicker() {
  if (!state.trainBrandCsv || state.trainBrandCsv === "all") {
    _tmpTrainBrandIds = new Set(["all"]);
  } else {
    _tmpTrainBrandIds = new Set(state.trainBrandCsv.split(",").map(x => x.trim()).filter(Boolean));
  }
  renderTrainBrandPicker();
  showScreen("screenTrainBrand");
}

function renderTrainBrandPicker() {
  const sum = document.getElementById("trainBrandPickSummary");
  if (sum) sum.textContent = trainBrandTmpSummaryLine();
  document.getElementById("trainBrandOptions").innerHTML = TRAIN_BRAND_OPTIONS.map(o => {
    const sel = trainBrandOptionSelected(o.id);
    return `
    <button type="button" class="comfort-option ${sel ? "selected" : ""}" data-train-brand="${o.id}">
      <span class="comfort-option-icon" aria-hidden="true">${o.icon}</span>
      <div class="comfort-option-text">
        <div class="comfort-option-title">${o.label}</div>
        <div class="comfort-option-desc">${o.hint}</div>
      </div>
      <span class="comfort-option-tick" aria-hidden="true">${sel ? "✓" : ""}</span>
    </button>`;
  }).join("");
}

function toggleTrainBrandOption(id) {
  if (id === "all") {
    _tmpTrainBrandIds = new Set(["all"]);
  } else {
    _tmpTrainBrandIds.delete("all");
    if (_tmpTrainBrandIds.has(id)) _tmpTrainBrandIds.delete(id);
    else _tmpTrainBrandIds.add(id);
    if (_tmpTrainBrandIds.size === 0) _tmpTrainBrandIds = new Set(["all"]);
  }
  renderTrainBrandPicker();
}

function confirmTrainBrandPicker() {
  if (_tmpTrainBrandIds.has("all") || _tmpTrainBrandIds.size === 0) {
    state.trainBrandCsv = "all";
  } else {
    const ids = [..._tmpTrainBrandIds].filter(x => x !== "all");
    state.trainBrandCsv = normalizeTrainBrandCsv(ids.join(","));
  }
  setField("trainBrandValue", trainBrandCsvLabel());
  state.screenStack = state.screenStack.filter(s => s !== "screenTrainBrand");
  showScreen("screenMain");
}

// ───────────────────────────── JOY TURI (bir nechta) ───────────────────────────
function openComfortPicker() {
  if (!state.comfortCsv || state.comfortCsv === "all") {
    _tmpComfortIds = new Set(["all"]);
  } else {
    _tmpComfortIds = new Set(state.comfortCsv.split(",").map(x => x.trim()).filter(Boolean));
  }
  renderComfortPicker();
  showScreen("screenComfort");
}

function renderComfortPicker() {
  const sum = document.getElementById("comfortPickSummary");
  if (sum) sum.textContent = comfortTmpSummaryLine();
  document.getElementById("comfortOptions").innerHTML = COMFORT_OPTIONS.map(o => {
    const sel = comfortOptionSelected(o.id);
    return `
    <button type="button" class="comfort-option ${sel ? "selected" : ""}" data-comfort-id="${o.id}">
      <span class="comfort-option-icon" aria-hidden="true">${o.icon}</span>
      <div class="comfort-option-text">
        <div class="comfort-option-title">${o.label}</div>
        <div class="comfort-option-desc">${o.hint}</div>
      </div>
      <span class="comfort-option-tick" aria-hidden="true">${sel ? "✓" : ""}</span>
    </button>`;
  }).join("");
}

function toggleComfortOption(id) {
  if (id === "all") {
    _tmpComfortIds = new Set(["all"]);
  } else {
    _tmpComfortIds.delete("all");
    if (_tmpComfortIds.has(id)) _tmpComfortIds.delete(id);
    else _tmpComfortIds.add(id);
    if (_tmpComfortIds.size === 0) _tmpComfortIds = new Set(["all"]);
  }
  renderComfortPicker();
}

function confirmComfortPicker() {
  if (_tmpComfortIds.has("all") || _tmpComfortIds.size === 0) {
    state.comfortCsv = "all";
  } else {
    const ids = [..._tmpComfortIds].filter(x => x !== "all");
    state.comfortCsv = normalizeComfortCsv(ids.join(","));
  }
  setField("comfortValue", comfortCsvLabel());
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
    trainBrandValue: "Barcha poyezdlar",
    comfortValue: "Barcha turlar",
  };
  el.textContent = defaults[id] || ""; el.classList.remove("selected");
}
function updateSearchBtn() {
  document.getElementById("searchBtn").disabled = !(state.fromCode && state.toCode && state.date);
}

async function showAllComfortAndRescan() {
  state.comfortCsv = "all";
  setField("comfortValue", comfortCsvLabel());
  await doSearch();
}

async function showAllTrainBrandsAndRescan() {
  state.trainBrandCsv = "all";
  setField("trainBrandValue", trainBrandCsvLabel());
  await doSearch();
}

// ───────────────────────────── SEARCH ────────────────────────────────────────
async function doSearch() {
  if (!(state.fromCode && state.toCode && state.date)) return;
  pushSearchHistoryFromState();
  showLoading(true, "Poyezdlar qidirilmoqda...");
  try {
    const resp = await apiFetch("/api/trains", {
      method: "POST",
      body: JSON.stringify({ from_code: state.fromCode, to_code: state.toCode, date: state.date }),
    });
    renderResults(resp);
  } catch (err) {
    const m = err && err.message ? String(err.message).trim() : "";
    if (m && m.length > 2) {
      showError(m);
    } else {
      showError("Serverga ulanishda xatolik. Internet aloqasini tekshiring.");
    }
  } finally {
    showLoading(false);
  }
}

// ───────────────────────────── RENDER RESULTS ────────────────────────────────
function renderResults(data) {
  let trainsRaw = [];
  try { trainsRaw = data.data.directions.forward.trains || []; } catch { trainsRaw = []; }

  const trains = trainsRaw.filter(t => trainMatchesBrandCsv(t, state.trainBrandCsv));

  const timeInfo = (state.timeFrom || state.timeTo)
    ? `&nbsp;⏰ ${state.timeFrom || "00:00"} — ${state.timeTo || "23:59"}`
    : "";
  const brandInfo = state.trainBrandCsv && state.trainBrandCsv !== "all"
    ? `&nbsp;🚄 ${trainBrandCsvLabel()}`
    : "";
  const comfortInfo = state.comfortCsv && state.comfortCsv !== "all"
    ? `&nbsp;🪑 ${comfortCsvLabel()}`
    : "";
  document.getElementById("resultsHeader").innerHTML = `
    <div class="route-info">
      <span>${state.fromName}</span>
      <span class="route-arrow">→</span>
      <span>${state.toName}</span>
    </div>
    <div class="date-info">📅 ${state.dateLabel}${timeInfo}${brandInfo}${comfortInfo}</div>`;

  const routeSubKey = subKeyOf(state.fromCode, state.toCode, state.date, "", state.trainBrandCsv, state.comfortCsv);
  const isRouteWatching = !!state.activeSubs[routeSubKey];

  // Vaqt filtri (daqiqalar — "9:30" satr taqqosi xatolari yo'q); vaqt API UTC bo'lsa Toshkentga aylantiriladi
  const inTimeRange = (train) => {
    if (!state.timeFrom && !state.timeTo) return true;
    const dep = parseTime(train.departureDate || train.departureTime);
    const depM = timeHMToMinutes(dep);
    if (depM === null) return true;
    const fromM = state.timeFrom ? timeHMToMinutes(state.timeFrom) : 0;
    const toM = state.timeTo ? timeHMToMinutes(state.timeTo) : (23 * 60 + 59);
    if (fromM === null || toM === null) return true;
    return depM >= fromM && depM <= toM;
  };

  const timeFilteredTrains = trains.filter(inTimeRange);
  const rawAvailable = timeFilteredTrains.filter(t =>
    (t.cars || []).some(c => c.freeSeats > 0)
  );
  const availableTrains = rawAvailable
    .map(t => ({
      ...t,
      cars: (t.cars || []).filter(c =>
        c.freeSeats > 0 && carMatchesComfortCsv(c.carTypeName, state.comfortCsv)
      ),
    }))
    .filter(t => t.cars.length > 0);

  let html = "";

  const noTrainsAtAll = trainsRaw.length === 0;
  const noBrandMatch =
    trainsRaw.length > 0 && trains.length === 0 && state.trainBrandCsv !== "all";
  const noInTimeRange = timeFilteredTrains.length === 0 && trains.length > 0;

  function trainHasComfortSeats(train) {
    return (train.cars || []).some(c =>
      c.freeSeats > 0 && carMatchesComfortCsv(c.carTypeName, state.comfortCsv)
    );
  }

  if (noTrainsAtAll || noBrandMatch || noInTimeRange) {
    let icon, title, msg;
    if (noTrainsAtAll) {
      icon = "🚫"; title = "Poyezd topilmadi";
      msg = "Bu sana uchun ushbu yo'nalishda hozircha reys ko'rinmayapti. Pastdagi tugmalar bilan butun yo'nalish bo'yicha kuzating — bot har 10 daqiqada tekshiradi.";
    } else if (noBrandMatch) {
      icon = "🚄"; title = "Bu turdagi poyezd yo'q";
      msg = `Yo'nalishda reyslar bor, lekin <b>${trainBrandCsvLabel()}</b> tanlovlari uchun mos poyezd yo'q. Filtrni o'zgartiring yoki barcha poyezdlarni ko'ring.`;
    } else {
      icon = "⏰"; title = "Bu vaqtda poyezd yo'q";
      msg = `${state.timeFrom || "00:00"}–${state.timeTo || "23:59"} oralig'ida jo'nash topilmadi. Vaqt oralig'ini kengaytiring yoki kuzatuvni yoqing.`;
    }
    const brandBtn = noBrandMatch
      ? `<button type="button" class="comfort-mismatch-route-btn" style="margin-top:12px" onclick="showAllTrainBrandsAndRescan()">Barcha poyezdlarni ko'rsatish</button>`
      : "";
    html = `
      <div class="no-seats-banner">
        <div class="banner-icon">${icon}</div>
        <h3>${title}</h3>
        <p>${msg}</p>
        ${brandBtn}
        ${mountRouteWatchSection(routeSubKey, isRouteWatching)}
      </div>`;
  } else {
    const comfortBlocked =
      state.comfortCsv !== "all" &&
      rawAvailable.length > 0 &&
      availableTrains.length === 0;
    const routeBanner = comfortBlocked
      ? `<div class="comfort-mismatch-route-banner">
          <span class="comfort-mismatch-route-icon">🪑</span>
          <div class="comfort-mismatch-route-text">
            <strong>${comfortCsvLabel()}</strong> tanlangan — shu turlarda bo'sh joy topilmadi,
            lekin reyslarda <strong>boshqa vagon turlarida</strong> joy bor (masalan, Business / kupe).
          </div>
          <button type="button" class="comfort-mismatch-route-btn" onclick="showAllComfortAndRescan()">Barcha turlarni ko'rsatish</button>
        </div>`
      : "";
    html =
      routeBanner +
      timeFilteredTrains
        .map(train => {
          if (trainHasComfortSeats(train)) return buildTrainCard(train);
          if (trainHasAnyFreeSeat(train)) return buildTrainCardOtherComfort(train);
          return buildSoldOutTrainCard(train);
        })
        .join("");
  }

  html += `<button class="new-search-btn" onclick="resetToMain()">🔄 Yangi qidiruv</button>`;
  document.getElementById("trainsList").innerHTML = html;
  showScreen("screenResults");
}

/** Temiryo'l jadvali O'zbekiston vaqti bilan mos (API UTC (Z) bersa ham) */
const TZ_TASHKENT = "Asia/Tashkent";

function parseTime(val) {
  if (!val) return "";
  const s = String(val).trim();
  if (s.includes("T")) {
    const d = new Date(s);
    if (!Number.isNaN(d.getTime())) {
      try {
        const parts = new Intl.DateTimeFormat("en-GB", {
          timeZone: TZ_TASHKENT,
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        }).formatToParts(d);
        const hour = parts.find(p => p.type === "hour")?.value;
        const minute = parts.find(p => p.type === "minute")?.value;
        if (hour != null && minute != null)
          return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
      } catch {
        /* fallthrough */
      }
    }
    const m = /T(\d{1,2}):(\d{2})/.exec(s);
    if (m) return `${m[1].padStart(2, "0")}:${m[2]}`;
    return "";
  }
  if (s.includes(" ")) {
    const rest = s.split(/\s+/).slice(1).join(" ");
    const m = /(\d{1,2}):(\d{2})/.exec(rest);
    if (m) return `${m[1].padStart(2, "0")}:${m[2]}`;
    return "";
  }
  if (s.includes(":")) {
    const m = /^(\d{1,2}):(\d{2})/.exec(s);
    if (m) return `${m[1].padStart(2, "0")}:${m[2]}`;
  }
  return "";
}

/** "HH:MM" → kun boshidan daqiqalar (filtr uchun) */
function timeHMToMinutes(hm) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(hm).trim());
  if (!m) return null;
  const h = parseInt(m[1], 10);
  const min = parseInt(m[2], 10);
  if (h > 23 || min > 59) return null;
  return h * 60 + min;
}

function getBrandClass(brand) {
  return BRAND_CLASS[brand] || "brand-default";
}

/** Bir vagonda bir nechta tarif bo'lsa, saytdagi asosiy narx odatda eng pasti — birinchisini emas, minimumni olamiz. */
function carMinTariff(car) {
  const nums = (car.tariffs || [])
    .map(t => (t && t.tariff != null ? Number(t.tariff) : NaN))
    .filter(n => !Number.isNaN(n) && n > 0);
  if (!nums.length) return null;
  return Math.min(...nums);
}

function buildTrainCard(train) {
  const dep   = parseTime(train.departureDate || train.departureTime);
  const arr   = parseTime(train.arrivalDate   || train.arrivalTime);
  const brand = train.brand || train.type || "";
  const avail = (train.cars || []).filter(c =>
    c.freeSeats > 0 && carMatchesComfortCsv(c.carTypeName, state.comfortCsv)
  );

  const seatsHtml = avail.map(car => {
    const icon  = CAR_ICONS[car.carTypeName] || "🪑";
    const price = carMinTariff(car);
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
        <button class="inline-buy-btn" onclick='requestBuyTicket(JSON.parse(decodeURIComponent("${encodeURIComponent(JSON.stringify({number:train.number||"",brand,dep,arr,car_type:car.carTypeName||"Vagon"}))}")))' >🎫 Olish</button>
      </div>
    </div>`;
  }).join("");

  const firstCar = avail[0];
  const autoPayload = firstCar
    ? encodeURIComponent(JSON.stringify({
        number:   train.number || "",
        brand,
        dep,
        arr,
        car_type: firstCar.carTypeName || "Vagon",
      }))
    : "";
  const autoExtra =
    avail.length > 1
      ? " Boshqa vagon uchun qatordagi tugmalardan foydalaning."
      : "";

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
      <p class="train-card-hint">🎫 <b>Olish</b> — chatda tasdiqlash. 🤖 <b>Avtomatik</b> — darhol server orqali; <b>Profil</b> to'ldirilgan bo'lishi kerak.${autoExtra}</p>
      <button type="button" class="buy-btn buy-btn-auto" onclick='requestAutoBuyTicket(JSON.parse(decodeURIComponent("${autoPayload}")))'>🤖 Avtomatik sotib olish (${escHtmlText((firstCar && firstCar.carTypeName) || "vagon")})</button>
      <button class="buy-btn" onclick="openRailway()">🌐 O'zim sotib olish (sayt)</button>
    </div>`;
}

/** Tanlangan qulaylikda joy yo'q, lekin API boshqa vagonlarda bo'sh joy qaytarganda */
function buildTrainCardOtherComfort(train) {
  const dep   = parseTime(train.departureDate || train.departureTime);
  const arr   = parseTime(train.arrivalDate   || train.arrivalTime);
  const brand = train.brand || train.type || "";
  const avail = (train.cars || []).filter(c => (c.freeSeats || 0) > 0);
  const bucketLabels = [...new Set(avail.map(c => comfortBucketLabel(c.carTypeName)))];
  const bucketsHint = bucketLabels.join(", ");

  const seatsHtml = avail.map(car => {
    const icon  = CAR_ICONS[car.carTypeName] || "🪑";
    const price = carMinTariff(car);
    return `<div class="seat-row">
      <div class="seat-type">
        <span class="seat-icon">${icon}</span>
        <span class="seat-name">${car.carTypeName || "Vagon"}</span>
        <span class="seat-count">(${car.freeSeats} joy)</span>
      </div>
      <div style="display:flex;flex-direction:column;align-items:flex-end;gap:2px">
        <span class="seat-price">${price ? `${Number(price).toLocaleString()} so'm` : "—"}</span>
        <button class="inline-buy-btn" onclick='requestBuyTicket(JSON.parse(decodeURIComponent("${encodeURIComponent(JSON.stringify({number:train.number||"",brand,dep,arr,car_type:car.carTypeName||"Vagon"}))}")))' >🎫 Olish</button>
      </div>
    </div>`;
  }).join("");

  const firstOther = avail[0];
  const autoPayloadOther = firstOther
    ? encodeURIComponent(JSON.stringify({
        number:   train.number || "",
        brand,
        dep,
        arr,
        car_type: firstOther.carTypeName || "Vagon",
      }))
    : "";

  return `
    <div class="train-card train-card-other-comfort">
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
      <p class="comfort-filter-hint">
        <strong>${comfortCsvLabel()}</strong> filtri yoqilgan — shu turlarda joy yo'q.
        Boshqa turlarda joy bor: <strong>${bucketsHint}</strong>.
      </p>
      <div class="seats-list">${seatsHtml}</div>
      <p class="train-card-hint">Quyidagi vagonlarda bo'sh joy bor. 🤖 Avtomatik — birinchi qatordagi vagon (${escHtmlText((firstOther && firstOther.carTypeName) || "")}).</p>
      <button type="button" class="buy-btn buy-btn-auto" onclick='requestAutoBuyTicket(JSON.parse(decodeURIComponent("${autoPayloadOther}")))'>🤖 Avtomatik sotib olish (${escHtmlText((firstOther && firstOther.carTypeName) || "vagon")})</button>
      <button type="button" class="buy-btn buy-btn-secondary" onclick="showAllComfortAndRescan()">🎫 Barcha turlar bilan qayta qidirish</button>
      <button class="buy-btn" onclick="openRailway()">🌐 O'zim sotib olish (sayt)</button>
    </div>`;
}

function buildSoldOutTrainCard(train) {
  const dep   = parseTime(train.departureDate || train.departureTime);
  const arr   = parseTime(train.arrivalDate   || train.arrivalTime);
  const brand = train.brand || train.type || "";
  const num   = String(train.number ?? "").trim();
  const subKey = subKeyOf(state.fromCode, state.toCode, state.date, num, state.trainBrandCsv, state.comfortCsv);
  const isW = !!state.activeSubs[subKey];

  return `
    <div class="train-card train-card-soldout" data-train-num="${encodeURIComponent(num)}"
         data-dep="${encodeURIComponent(dep || "")}" data-arr="${encodeURIComponent(arr || "")}">
      <div class="train-header">
        <div class="train-times">
          <span class="train-dep">${dep}</span>
          <div class="train-duration"><span class="arrow-line"></span>→</div>
          <span class="train-arr">${arr}</span>
        </div>
        <div class="train-meta">
          <div class="train-brand ${getBrandClass(brand)}">${brand || "Poyezd"}</div>
          <div class="train-num">№${num}</div>
        </div>
      </div>
      <p class="soldout-note">Hozircha bo'sh joy yo'q</p>
      <div class="train-soldout-actions">${soldOutTrainActionsHtml(num, isW, dep, arr)}</div>
    </div>`;
}

function soldOutTrainActionsHtml(trainNum, isWatching, dep, arr) {
  if (!TG_USER_ID) {
    return `<p class="soldout-telegram-hint">Telegram orqali oching</p>`;
  }
  const n = JSON.stringify(String(trainNum ?? ""));
  const d = JSON.stringify(dep != null ? String(dep) : "");
  const a = JSON.stringify(arr != null ? String(arr) : "");
  if (isWatching) {
    return `<button type="button" class="watch-row-btn watching" onclick='unsubscribeTrain(${n})'>✅ Kuzatilmoqda — bekor qilish</button>`;
  }
  return `
    <button type="button" class="watch-row-btn notify" onclick='subscribeTrainWatch(${n}, false, ${d}, ${a})'>🔔 Bilet bo'lganda xabar berish</button>
    <button type="button" class="watch-row-btn auto" onclick='subscribeTrainWatch(${n}, true, ${d}, ${a})'>🤖 Paydo bo'lganda sotib olish</button>`;
}

function buildRouteWatchSection(routeSubKey, isWatching) {
  if (!TG_USER_ID) {
    return `<p style="color:var(--tg-hint);font-size:12px">Telegram orqali oching</p>`;
  }
  const rk = JSON.stringify(routeSubKey);
  if (isWatching) {
    return `<button type="button" class="big-watch-btn watching" onclick='unsubscribe(${rk})'>✅ Kuzatilmoqda — bekor qilish</button>`;
  }
  return `
    <div class="route-watch-btns">
      <button type="button" class="big-watch-btn notify" onclick='subscribe(${rk}, false)'>🔔 Bilet bo'lganda xabar berish</button>
      <button type="button" class="big-watch-btn auto" onclick='subscribe(${rk}, true)'>🤖 Paydo bo'lganda sotib olish</button>
    </div>`;
}

function mountRouteWatchSection(routeSubKey, isWatching) {
  return `<div class="route-watch-section">${buildRouteWatchSection(routeSubKey, isWatching)}</div>`;
}

function subscribeTrainWatch(trainNumber, autoBuy, depTime, arrTime) {
  subscribe(
    subKeyOf(state.fromCode, state.toCode, state.date, trainNumber, state.trainBrandCsv, state.comfortCsv),
    autoBuy,
    trainNumber,
    depTime,
    arrTime
  );
}

function unsubscribeTrain(trainNumber) {
  unsubscribe(subKeyOf(state.fromCode, state.toCode, state.date, trainNumber, state.trainBrandCsv, state.comfortCsv));
}

// ───────────────────────────── SUBSCRIBE / UNSUBSCRIBE ───────────────────────
async function subscribe(subKey, autoBuy = false, trainNumber = null, depTime = null, arrTime = null) {
  if (!TG_USER_ID) {
    showToast("Botni Telegram orqali oching!");
    return;
  }
  const tn = trainNumber != null && String(trainNumber).trim() !== "" ? String(trainNumber).trim() : null;
  const dep = depTime != null && String(depTime).trim() !== "" ? String(depTime).trim() : null;
  const arr = arrTime != null && String(arrTime).trim() !== "" ? String(arrTime).trim() : null;
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
        comfort_class: state.comfortCsv === "all" ? "all" : state.comfortCsv,
        train_number: tn,
        train_brand: state.trainBrandCsv === "all" ? null : state.trainBrandCsv,
        dep_time:   tn ? dep : null,
        arr_time:   tn ? arr : null,
      }),
    });
    if (res.status === "ok" || res.status === "already_exists") {
      state.activeSubs[subKey] = res.id;
      const warns = res.auto_buy_warnings || [];
      if (autoBuy && warns.length) {
        showToast(warns[0]);
      } else {
        showToast(autoBuy
          ? "🤖 Shu reysda joy chiqishi bilan avtomatik sotib olishga harakat qilinadi."
          : "🔔 Shu reys / yo'nalish bo'yicha joy chiqsa xabar beramiz."
        );
      }
      refreshWatchUI(subKey);
      updateBellBadge();
    } else {
      showToast("Javob keldi, holatni Kuzatishlar ekranidan tekshiring.");
    }
  } catch (e) {
    const m = (e && e.message) ? String(e.message).trim() : "";
    showToast(m && m.length < 220 ? m : (m ? m.slice(0, 217) + "…" : "Xatolik yuz berdi. Qayta urinib ko'ring."));
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
    refreshWatchUI(subKey);
    updateBellBadge();
  } catch {
    showToast("Xatolik. Qayta urinib ko'ring.");
  } finally {
    showLoading(false);
  }
}

function refreshWatchUI(changedSubKey) {
  const routeKey = subKeyOf(state.fromCode, state.toCode, state.date, "", state.trainBrandCsv, state.comfortCsv);
  const isRoute = !!state.activeSubs[routeKey];
  const sec = document.querySelector(".route-watch-section");
  if (sec) sec.outerHTML = mountRouteWatchSection(routeKey, isRoute);
  document.querySelectorAll(".train-card-soldout").forEach(card => {
    const enc = card.getAttribute("data-train-num") || "";
    const num = decodeURIComponent(enc);
    const dep = decodeURIComponent(card.getAttribute("data-dep") || "");
    const arr = decodeURIComponent(card.getAttribute("data-arr") || "");
    const sk = subKeyOf(state.fromCode, state.toCode, state.date, num, state.trainBrandCsv, state.comfortCsv);
    const box = card.querySelector(".train-soldout-actions");
    if (box) {
      box.innerHTML = soldOutTrainActionsHtml(num, !!state.activeSubs[sk], dep, arr);
    }
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
    const [res, resPur] = await Promise.all([
      apiFetch(`/api/subscriptions/${TG_USER_ID}`),
      apiFetch(`/api/purchase-requests/${TG_USER_ID}?limit=50`).catch(() => ({ purchases: [] })),
    ]);
    renderSubscriptions(res.subscriptions || [], resPur.purchases || []);
    showScreen("screenSubscriptions");
  } catch {
    showToast("Ma'lumot olishda xatolik.");
  } finally {
    showLoading(false);
  }
}

function purchaseStatusLabel(st) {
  const k = String(st || "").toLowerCase();
  const m = {
    pending: "⏳ Kutilmoqda",
    success: "✅ Bajarildi",
    partial: "⚠️ Qisman",
    error: "❌ Xato",
  };
  return m[k] || (st ? String(st) : "—");
}

function purchaseSourceLabel(src) {
  if (src === "watch") return "🔔 Kuzatuvdan avto";
  return "📱 Mini App";
}

function purchaseCardHtml(p) {
  const src = purchaseSourceLabel(p.source);
  const st = purchaseStatusLabel(p.status);
  const msg = escHtmlText(String(p.result_msg || "").replace(/\s+/g, " ").trim().slice(0, 240));
  const t = escHtmlText(String(p.created_at || "").replace("T", " ").slice(0, 19));
  const stRaw = String(p.status || "pending").toLowerCase().replace(/[^a-z]/g, "") || "pending";
  const stCls = "purchase-status-" + stRaw;
  return `
      <div class="purchase-card" data-purchase-id="${p.id}">
        <div class="purchase-icon">🎫</div>
        <div class="purchase-info">
          <div class="purchase-route">${escHtmlText(p.from_name)} → ${escHtmlText(p.to_name)}</div>
          <div class="purchase-meta">📅 ${escHtmlText(p.date)} · 🚆 ${escHtmlText(p.train_brand || "")} №${escHtmlText(String(p.train_number || ""))}</div>
          <div class="purchase-meta">⏱ ${escHtmlText(p.dep_time || "")} → ${escHtmlText(p.arr_time || "")} · ${escHtmlText(p.car_type || "")}</div>
          <div class="purchase-row">
            <span class="purchase-src">${src}</span>
            <span class="purchase-status ${stCls}">${st}</span>
          </div>
          ${msg ? `<div class="purchase-msg">${msg}</div>` : ""}
          <div class="purchase-time">${t}</div>
        </div>
      </div>`;
}

function renderSubscriptions(subs, purchases) {
  const container = document.getElementById("subsList");
  subs = subs || [];
  purchases = purchases || [];
  state.activeSubs = {};
  state.recentPurchases = purchases;

  const blocks = [];

  if (subs.length) {
    subs.forEach((s) => {
      state.activeSubs[subKeyFromServerRow(s)] = s.id;
    });
    blocks.push(`<p class="subs-section-title">Faol kuzatuvlar (${subs.length})</p>`);
    blocks.push(
      subs
        .map((s) => {
          const tbL = trainBrandCsvLabelFromServer(s.train_brand);
          const ccL = comfortCsvLabelFromServer(s.comfort_class);
          return `
      <div class="sub-card" id="sub-${s.id}">
        <div class="sub-icon">🚆</div>
        <div class="sub-info">
          <div class="sub-route">${s.from_name} → ${s.to_name}</div>
          ${subCardReysLineHtml(s)}
          <div class="sub-date">📅 ${s.date}${s.time_from || s.time_to ? `&nbsp;⏰ Qidiruv: ${s.time_from || "00:00"}–${s.time_to || "23:59"}` : ""}${tbL ? `&nbsp;🚄 ${tbL}` : ""}${ccL ? `&nbsp;🪑 ${ccL}` : ""}</div>
          <span class="sub-status">${s.auto_buy ? "🤖 Avtomatik xarid" : "⏳ Faqat xabar"} (har 10 daqiqa)</span>
          <div class="sub-actions">
            ${Number(s.auto_buy) ? `<button type="button" class="sub-action-btn" onclick="disableSubAutoBuy(${s.id})">🤖 Avtoni o'chirish</button>` : ""}
            <button type="button" class="sub-action-btn sub-action-danger" onclick='deleteSubFromList(${s.id},${JSON.stringify(subKeyFromServerRow(s))})'>🔕 Kuzatuvni to'xtatish</button>
          </div>
        </div>
      </div>`;
        })
        .join(""),
    );
  } else {
    blocks.push(`<p class="subs-section-title">Faol kuzatuvlar</p>`);
    blocks.push(`
      <div class="subs-empty subs-empty-inline">
        <div class="subs-empty-icon">🔕</div>
        <h3>Hozircha kuzatuv yo'q</h3>
        <p>Natijalar ekranidagi kuzatuv tugmasi orqali qo'shasiz. Pastda avtomatik / qo'lda yuborilgan chipta topshiriqlari ko'rinadi.</p>
      </div>`);
  }

  if (purchases.length) {
    blocks.push(`<p class="subs-section-title">Chipta topshiriqlari (${purchases.length})</p>`);
    blocks.push(`<p class="subs-hint">Kuzatuvdan avtomatik xarid yoki «Chipta olish» — holat serverda yangilanadi.</p>`);
    blocks.push(purchases.map((p) => purchaseCardHtml(p)).join(""));
  } else if (!subs.length) {
    blocks.push(`<p class="subs-section-title">Chipta topshiriqlari</p>`);
    blocks.push(`<div class="subs-empty subs-empty-inline"><p>Hozircha topshiriq yo'q.</p></div>`);
  }

  container.innerHTML = blocks.join("");
}

async function disableSubAutoBuy(subId) {
  if (!TG_USER_ID) {
    showToast("Telegram orqali oching.");
    return;
  }
  showLoading(true, "Yangilanmoqda...");
  try {
    await apiFetch(`/api/subscriptions/${subId}`, {
      method: "PATCH",
      body: JSON.stringify({ user_id: TG_USER_ID, auto_buy: false }),
    });
    showToast("✅ Avtomatik sotib olish o'chirildi. Joy chiqsa faqat xabar keladi.");
    const [res, resPur] = await Promise.all([
      apiFetch(`/api/subscriptions/${TG_USER_ID}`),
      apiFetch(`/api/purchase-requests/${TG_USER_ID}?limit=50`).catch(() => ({ purchases: [] })),
    ]);
    renderSubscriptions(res.subscriptions || [], resPur.purchases || []);
    updateBellBadge();
  } catch {
    showToast("Xatolik. Qayta urinib ko'ring.");
  } finally {
    showLoading(false);
  }
}

async function deleteSubFromList(subId, subKey) {
  try {
    await apiFetch(`/api/subscriptions/${subId}`, { method: "DELETE" });
    delete state.activeSubs[subKey];
    document.getElementById(`sub-${subId}`)?.remove();
    updateBellBadge();
    // If list is now empty, show empty state
    if (!document.querySelector(".sub-card")) {
      renderSubscriptions([], state.recentPurchases || []);
    }
    showToast("🔕 Bekor qilindi.");
  } catch {
    showToast("Xatolik. Qayta urinib ko'ring.");
  }
}

// Chipta xaridi uchun server bilan bir xil majburiy maydonlar
const PASSENGER_FIELD_LABELS = {
  full_name: "To'liq ism",
  passport: "Passport",
  phone: "Telefon (+998...)",
  birth_date: "Tug'ilgan sana",
  gender: "Jins",
  citizenship: "Fuqarolik",
};

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
    document.getElementById("inputBirthDate").value = p.birth_date || "";
    document.getElementById("inputGender").value = p.gender || "";
    document.getElementById("inputCitizenship").value = p.citizenship || "";
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
  const birthDate = document.getElementById("inputBirthDate").value || null;
  const gender = document.getElementById("inputGender").value || null;
  const citizenship = document.getElementById("inputCitizenship").value || null;

  if (!fullName) { showToast("⚠️ To'liq ismni kiriting"); return; }
  if (passport.length < 6) { showToast("⚠️ Passport raqamini to'g'ri kiriting"); return; }
  if (!phone.startsWith("+")) { showToast("⚠️ Telefon: +998... formatida kiriting"); return; }
  if (!birthDate) { showToast("⚠️ Tug'ilgan sanani kiriting"); return; }
  if (!gender) { showToast("⚠️ Jinsni tanlang"); return; }
  if (!citizenship) { showToast("⚠️ Fuqarolikni tanlang"); return; }

  showLoading(true, "Saqlanmoqda...");
  try {
    await apiFetch("/api/passenger", {
      method: "POST",
      body: JSON.stringify({
        user_id:   TG_USER_ID,
        full_name: fullName,
        passport:  passport,
        phone:     phone,
        birth_date: birthDate,
        gender: gender,
        citizenship: citizenship,
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
    state.activeSubs = {};
    (res.subscriptions || []).forEach(s => {
      state.activeSubs[subKeyFromServerRow(s)] = s.id;
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
  const text = await resp.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!resp.ok) {
    const d = data && data.detail;
    let msg = "";
    if (typeof d === "string") msg = d;
    else if (Array.isArray(d)) msg = d.map(e => (e && e.msg) || String(e)).join(" ");
    else if (d != null && typeof d === "object") {
      if (Array.isArray(d.missing_labels_uz) && d.missing_labels_uz.length) {
        msg =
          "Profil to'liq emas: " +
          d.missing_labels_uz.join(", ") +
          ". «Profil» bo'limida to'ldiring.";
      } else {
        msg = typeof d.message === "string" ? d.message : JSON.stringify(d);
      }
    }
    throw new Error(msg || `HTTP ${resp.status}`);
  }
  return data;
}

function subKeyOf(fromCode, toCode, date, trainNumber, trainBrandCsv, comfortCsv) {
  const t = trainNumber != null && String(trainNumber).trim() !== ""
    ? String(trainNumber).trim()
    : "";
  let b = "";
  if (trainBrandCsv != null && String(trainBrandCsv).trim() !== "") {
    const nb = normalizeTrainBrandCsv(trainBrandCsv);
    if (nb !== "all") b = nb;
  }
  let c = "";
  if (comfortCsv != null && String(comfortCsv).trim() !== "") {
    const nc = normalizeComfortCsv(comfortCsv);
    if (nc !== "all") c = nc;
  }
  return `${fromCode}|${toCode}|${date}|${t}|${b}|${c}`;
}

function fmtDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
}

function escQ(s) { return s.replace(/'/g, "\\'"); }

/** Kartochka matnida HTML buzilishining oldini olish */
function escHtmlText(s) {
  return String(s ?? "").replace(/[<>]/g, "");
}

/** Kuzatishlarim: qaysi reys va qachon jo'naydi */
function subCardReysLineHtml(s) {
  const tn = s.train_number && String(s.train_number).trim();
  if (!tn) {
    return `<div class="sub-reys sub-reys-route">📋 <b>Butun yo'nalish</b> <span class="sub-reys-hint">(alohida reys tanlanmagan)</span></div>`;
  }
  const dep = s.dep_time && String(s.dep_time).trim();
  const arr = s.arr_time && String(s.arr_time).trim();
  let times = "";
  if (dep) {
    times = arr
      ? ` <span class="sub-reys-time">⏱ ${escHtmlText(dep)} → ${escHtmlText(arr)}</span>`
      : ` <span class="sub-reys-time">⏱ ${escHtmlText(dep)}</span>`;
  }
  return `<div class="sub-reys">🚆 Reys <b>№${escHtmlText(tn)}</b>${times}</div>`;
}

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

/** Server /api/purchase — tasdiqlashsiz, Playwright (RAILWAY_LOGIN + profil) */
async function pollPurchaseStatus(purchaseId) {
  if (!TG_USER_ID) return;
  const uid = encodeURIComponent(TG_USER_ID);
  const maxAttempts = 80;
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise(r => setTimeout(r, 2500));
    try {
      const s = await fetch(
        `${API_BASE}/api/purchase/${purchaseId}/status?user_id=${uid}`
      );
      if (!s.ok) continue;
      const j = await s.json();
      const st = j.status;
      if (st && st !== "pending") {
        const ok = st === "success" || st === "partial";
        const rm = String(j.result_msg || st || "").replace(/\s+/g, " ").trim();
        const short = rm.length > 220 ? rm.slice(0, 217) + "…" : rm;
        showToast((ok ? "✅ " : "❌ ") + (short || st));
        return;
      }
    } catch {
      /* tarmoq — keyingi urinish */
    }
  }
  showToast("⏳ Uzoq kutildi. Natija Telegram chatda yoki server logida tekshiring.");
}

async function requestAutoBuyTicket(train) {
  if (!TG_USER_ID) {
    showToast("Iltimos, botni Telegram orqali oching.");
    return;
  }
  const carType = (train && train.car_type) || "Vagon";
  showLoading(true, "Buyurtma yuborilmoqda...");
  try {
    let prof;
    try {
      prof = await apiFetch(`/api/passenger/${TG_USER_ID}`);
    } catch {
      showToast("Avval «Profil» bo'limida yo'lovchi ma'lumotlarini kiriting.");
      return;
    }
    if (!prof.profile_complete) {
      const keys = prof.missing_fields || [];
      const lab = keys.map((k) => PASSENGER_FIELD_LABELS[k] || k).join(", ");
      showToast("Profil to'liq emas: " + lab + ". «Profil» bo'limiga o'ting.");
      return;
    }
    const resp = await fetch(`${API_BASE}/api/purchase`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id:      TG_USER_ID,
        from_code:    state.fromCode,
        to_code:      state.toCode,
        from_name:    state.fromName,
        to_name:      state.toName,
        date:         state.date,
        train_number: train.number || "",
        train_brand:  train.brand || "",
        dep_time:     train.dep || "",
        arr_time:     train.arr || "",
        car_type:     carType,
      }),
    });
    let data = {};
    try {
      data = await resp.json();
    } catch {
      data = {};
    }
    if (!resp.ok) {
      const d = data.detail;
      let msg;
      if (typeof d === "string") msg = d;
      else if (Array.isArray(d)) msg = d.map((e) => e.msg || e).join(" ");
      else if (d && typeof d === "object" && Array.isArray(d.missing_labels_uz) && d.missing_labels_uz.length) {
        msg =
          "Profil to'liq emas: " +
          d.missing_labels_uz.join(", ") +
          ". «Profil» bo'limida to'ldiring.";
      } else if (d && typeof d === "object" && typeof d.message === "string") {
        msg = d.message;
      } else msg = `Xatolik (${resp.status})`;
      showToast(msg);
      return;
    }
    showToast("✅ Buyurtma qabul qilindi, avtomatik xarid ketmoqda…");
    if (data.purchase_id != null) pollPurchaseStatus(data.purchase_id);
  } catch {
    showToast("Serverga ulanishda xatolik.");
  } finally {
    showLoading(false);
  }
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
/** Sensor: pointerdown + preventDefault — dublikat click oldini oladi. Sichqoncha: faqat click. */
function attachMultiPickerToggle(root, dataAttr, toggleFn) {
  if (!root || root.dataset.delegated) return;
  root.dataset.delegated = "1";
  const hasPE = typeof PointerEvent !== "undefined";
  if (hasPE) {
    root.addEventListener(
      "pointerdown",
      (e) => {
        if (e.pointerType === "mouse" && e.button !== 0) return;
        const btn = e.target.closest(`[${dataAttr}]`);
        if (!btn || !root.contains(btn)) return;
        if (e.pointerType === "touch" || e.pointerType === "pen") {
          e.preventDefault();
          toggleFn(btn.getAttribute(dataAttr));
        }
      },
      { passive: false }
    );
  }
  root.addEventListener("click", (e) => {
    if (hasPE && e.sourceCapabilities && e.sourceCapabilities.firesTouchEvents) return;
    const btn = e.target.closest(`[${dataAttr}]`);
    if (!btn || !root.contains(btn)) return;
    toggleFn(btn.getAttribute(dataAttr));
  });
}

function setupMultiPickerDelegation() {
  attachMultiPickerToggle(
    document.getElementById("trainBrandOptions"),
    "data-train-brand",
    toggleTrainBrandOption
  );
  attachMultiPickerToggle(
    document.getElementById("comfortOptions"),
    "data-comfort-id",
    toggleComfortOption
  );
}

setupMultiPickerDelegation();
loadSearchHistory();
renderSearchHistory();
updateSearchBtn();
loadActiveSubs();
loadProfile();
