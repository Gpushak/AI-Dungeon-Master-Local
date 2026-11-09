const logEl = document.querySelector("#log");
const actionEl = document.querySelector("#action");
const sendEl = document.querySelector("#send");
const statusEl = document.querySelector("#status");
const barEl = document.querySelector("#bar");
const barLabel = document.querySelector("#bar-label");
const noticeEl = document.querySelector("#notice");
const panel = document.querySelector("#panel");
const panelBody = document.querySelector("#panel-body");
const panelTitle = document.querySelector("#panel-title");

let strings = {};
let state = null;
let drafting = false;
let revision = 0;
let eventRev = 0;
let settingsCache = null;
let loadingOlder = false;
let historyExpanded = false;
let tailFrom = null;
let pollTimer = 0;
let pendingPlayer = "";
let pendingIndex = null;
let awaitingSettle = false;
let settleOnce = false;
let turnRev = null;
let sendingTurn = false;
let draftClosed = true;
let applyCardDescription = null;

if ("scrollRestoration" in history) history.scrollRestoration = "manual";

function t(key, vars) {
  let text = strings[key] || key;
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (match, name) => (Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : match));
}

function plainText(value) {
  return String(value ?? "")
    .replace(/\p{Extended_Pictographic}/gu, "")
    .replace(/[\uFE0F\u200D\u2300-\u23FF\u25A0-\u25FF\u2600-\u27BF]/g, "")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/^ +/, "");
}

function setNodeText(node, value) {
  const text = String(value ?? "");
  node.replaceChildren(document.createTextNode(text));
  return node;
}

function keyStatusText(source) {
  const data = source || settingsCache || {};
  if (!data.api_key_set) return "";
  const tail = data.api_key_last4 ? ` ····${data.api_key_last4}` : "";
  const language = String(data.language || (state && state.language) || "ru").toLowerCase();
  return language.startsWith("en")
    ? `A key is already saved${tail}.`
    : `Ключ уже задан${tail}.`;
}

function paintStoredKeyNote(source) {
  const note = document.querySelector("[data-key-note]");
  if (!note) return;
  const text = keyStatusText(source);
  setNodeText(note, text ? ` ${text}` : "");
}

function unixText(value) {
  return String(value ?? "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

function actionErrorText(error) {
  const detail = error && error.body ? error.body.detail : "";
  const code = typeof detail === "string" ? detail : "";
  if (code === "exists" || code === "bad name") return t("dialog.bad_name_msg");
  if (code === "bad archive") return t("dialog.import_failed");
  if (code && !["busy", "busy or no world", "no world", "missing", "unknown file", "cannot undo", "cannot regenerate", "cannot edit", "cannot summarize"].includes(code)) {
    return code;
  }
  if (!(state && state.world) || code === "no world") return t("dialog.no_world");
  if (code === "busy" || code === "busy or no world" || document.body.classList.contains("busy")) return t("dialog.busy");
  return "";
}

function asText(value) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(asText).filter(Boolean).join(", ");
  if (typeof value === "object") {
    return Object.entries(value).map(([key, item]) => {
      const text = asText(item);
      return text ? `${key}: ${text}` : "";
    }).filter(Boolean).join("\n");
  }
  return String(value);
}

function applyStrings() {
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    if (node.id === "send" && node.classList.contains("stop")) return;
    node.textContent = t(node.dataset.i18n);
  });
  actionEl.setAttribute("aria-label", t("btn.make_move"));
  nextText.setAttribute("aria-label", t("dialog.next_title"));
  fitChrome();
}

function failNotice(error) {
  const detail = error && error.body ? error.body.detail : "";
  const code = typeof detail === "string" ? detail : "";
  const known = ["busy", "exists", "missing", "bad name", "bad archive", "cannot undo", "cannot regenerate", "cannot summarize", "cannot edit", "busy or no world", "no world", "unknown file"];
  if (code && !known.includes(code)) {
    paintNotice(code);
    return;
  }
  if (code === "busy" || code === "busy or no world" || document.body.classList.contains("busy")) {
    paintNotice(state && state.world ? t("dialog.busy") : t("dialog.no_world"));
    return;
  }
  if (code === "no world" || !(state && state.world)) paintNotice(t("dialog.no_world"));
}

async function api(path, options) {
  const opts = { cache: "no-store", ...(options || {}) };
  const method = (opts.method || "GET").toUpperCase();
  const url = method === "GET" ? path + (path.includes("?") ? "&" : "?") + "_=" + Date.now() : path;
  const response = await fetch(url, opts);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(response.statusText);
    error.status = response.status;
    error.body = data;
    throw error;
  }
  return data;
}

function paintFill(fill) {
  const ratio = Math.max(0, Math.min(1, fill.ratio || 0));
  barEl.className = fill.color || "ok";
  barEl.querySelector("span").style.width = `${ratio * 100}%`;
  barLabel.textContent = fill.label || "";
}

function paintNotice(text) {
  noticeEl.textContent = text || "";
  noticeEl.hidden = !text;
}

function paintMeters(meters) {
  if (!meters) return;
  const summaryBtn = document.querySelector("#toggle-summary");
  const memoryBtn = document.querySelector("#toggle-memory");
  const summaryCount = document.querySelector("#summary-count");
  const memoryCount = document.querySelector("#memory-count");
  summaryBtn.textContent = meters.summary_toggle || "";
  memoryBtn.textContent = meters.memory_toggle || "";
  summaryBtn.classList.toggle("on", Boolean(meters.summary_enabled));
  memoryBtn.classList.toggle("on", Boolean(meters.memory_enabled));
  summaryCount.textContent = meters.summary_text || "";
  memoryCount.textContent = meters.memory_text || "";
  summaryCount.className = meters.summary_color || "";
  memoryCount.className = meters.memory_color || "";
}

function paintStatus(status) {
  statusEl.textContent = status.text || "";
  const stop = Boolean(status.busy);
  document.body.classList.toggle("busy", stop);
  if (stop) document.body.classList.remove("writing");
  sendEl.classList.toggle("stop", stop);
  sendEl.textContent = stop ? t("btn.stop") : t("btn.send");
  actionEl.disabled = stop;
  for (const id of ["undo", "reroll", "edit", "summarize", "next"]) {
    const node = document.getElementById(id);
    if (node) node.disabled = stop;
  }
  fitChrome();
  syncPolling();
}

let freshIndex = null;
let awaitFresh = false;
let freshAnchor = null;

function noteFreshReply() {
  awaitFresh = true;
  const rows = state && state.history ? state.history : [];
  freshAnchor = rows.length ? rows[rows.length - 1].index : -1;
}

function settleFresh(snap) {
  if (!awaitFresh || !snap || snap.streaming) return;
  const rows = snap.history || [];
  const last = rows[rows.length - 1];
  if (last && last.kind === "dm" && last.index !== freshAnchor) freshIndex = last.index;
  awaitFresh = false;
}

function freshMark() {
  const line = document.createElement("hr");
  line.className = "fresh-mark";
  return line;
}

function jumpToEnd() {
  tailReady = false;
  const go = () => window.scrollTo(0, document.documentElement.scrollHeight);
  go();
  requestAnimationFrame(() => {
    go();
    requestAnimationFrame(() => { tailReady = true; });
  });
}

function nearBottom() {
  return document.documentElement.scrollHeight - window.scrollY - window.innerHeight < 180;
}

function reasoningBlock(text, hidden, live) {
  if (!text && !hidden && !live) return null;
  const details = document.createElement("details");
  details.className = "reasoning";
  if (live) details.open = true;
  const summary = document.createElement("summary");
  summary.textContent = t("log.reasoning");
  const body = document.createElement("div");
  body.className = "reasoning-body";
  body.textContent = text || (hidden ? t("log.reasoning_hidden") : "");
  details.append(summary, body);
  return details;
}

function renderLog(mode = "end", draftOverride) {
  if (!state) return;
  const fromDom = document.querySelector("#draft")?.textContent || "";
  const fromState = state && typeof state.draft === "string" ? state.draft : "";
  const draftText = drafting
    ? (typeof draftOverride === "string" ? draftOverride : (fromState.length >= fromDom.length ? fromState : fromDom))
    : "";
  const draftReasoning = drafting && state && typeof state.draft_reasoning === "string" ? state.draft_reasoning : "";
  const stick = mode === "end" || (mode === "follow" && nearBottom());
  const anchorY = window.scrollY;
  const anchorHeight = document.documentElement.scrollHeight;
  logEl.replaceChildren();
  if (state.history_from > 0) {
    const earlier = document.createElement("button");
    earlier.type = "button";
    earlier.className = "earlier";
    earlier.textContent = t("log.earlier");
    earlier.addEventListener("click", () => loadOlder());
    logEl.appendChild(earlier);
  }
  const lineBeforeDraft = awaitFresh && drafting;
  for (const row of state.history) {
    if (!lineBeforeDraft && freshIndex != null && row.index === freshIndex) {
      logEl.appendChild(freshMark());
    }
    if (row.kind === "dm" && (row.reasoning || row.reasoning_hidden)) {
      const thought = reasoningBlock(row.reasoning || "", Boolean(row.reasoning_hidden), false);
      if (thought) logEl.appendChild(thought);
    }
    const p = document.createElement("p");
    p.className = row.kind;
    p.dataset.index = String(row.index);
    setNodeText(p, plainText(row.text));
    if (row.kind === "player" || row.kind === "dm") {
      p.tabIndex = 0;
      p.setAttribute("role", "button");
      p.title = row.kind === "dm" ? t("dialog.edit_dm") : t("dialog.edit_player");
      const open = () => editRow(row);
      p.addEventListener("dblclick", open);
      p.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        open();
      });
    }
    logEl.appendChild(p);
  }
  if (drafting) {
    if (lineBeforeDraft) logEl.appendChild(freshMark());
    const thought = reasoningBlock(draftReasoning, false, true);
    if (thought) {
      thought.id = "draft-reasoning";
      logEl.appendChild(thought);
    }
    const p = document.createElement("p");
    p.className = "dm draft";
    p.id = "draft";
    setNodeText(p, draftText);
    logEl.appendChild(p);
  }
  if (mode === "keep") {
    const grown = document.documentElement.scrollHeight - anchorHeight;
    window.scrollTo(0, anchorY + grown);
  } else if (stick) {
    jumpToEnd();
  }
}

function ensureDraft() {
  if (draftClosed) return null;
  let draft = document.querySelector("#draft");
  if (draft) return draft;
  drafting = true;
  draft = document.createElement("p");
  draft.className = "dm draft";
  draft.id = "draft";
  logEl.appendChild(draft);
  return draft;
}

function ensureDraftReasoning() {
  const draft = ensureDraft();
  if (!draft) return null;
  let block = document.querySelector("#draft-reasoning");
  if (block) return block;
  block = reasoningBlock("", false, true);
  if (!block) return null;
  block.id = "draft-reasoning";
  draft.before(block);
  return block;
}

async function loadOlder() {
  if (loadingOlder || !state || !state.history_from) return;
  loadingOlder = true;
  try {
    const page = await api(`/api/history?before=${state.history_from}`);
    if (!page.history.length) return;
    const seen = new Set(state.history.map((row) => row.index));
    const older = page.history.filter((row) => !seen.has(row.index));
    if (!older.length) {
      state.history_from = page.history_from;
      renderLog("keep");
      return;
    }
    state.history = older.concat(state.history);
    state.history_from = page.history_from;
    state.history_total = page.history_total;
    historyExpanded = true;
    renderLog("keep");
  } finally {
    loadingOlder = false;
  }
}

function paintModels() {
  const menu = document.querySelector("#models-menu");
  const current = document.querySelector("#models-current");
  const presets = (state && state.presets) || { active: "", items: [] };
  const active = (presets.items || []).find((item) => item.name === presets.active);
  setNodeText(current, active ? active.name : "");
  current.hidden = !active;
  menu.replaceChildren();
  if (!(presets.items || []).length) {
    const empty = document.createElement("p");
    empty.className = "pop-empty";
    empty.textContent = t("models.empty");
    menu.append(empty);
    return;
  }
  for (const item of presets.items) {
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("role", "menuitemradio");
    button.setAttribute("aria-checked", item.name === presets.active ? "true" : "false");
    const name = document.createElement("span");
    setNodeText(name, item.name);
    button.append(name);
    if (item.model) {
      const model = document.createElement("small");
      model.textContent = item.model;
      button.append(model);
    }
    button.addEventListener("click", () => selectPreset(item.name));
    menu.append(button);
  }
}

async function selectPreset(name) {
  setModelsOpen(false);
  if (state && state.presets && state.presets.active === name) return;
  try {
    const presets = await api("/api/presets/activate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (state) state.presets = presets;
    paintModels();
    if (!settingsCache) return;
    const found = (settingsCache.api_presets || []).find((item) => item.name === presets.active);
    if (!found) return;
    settingsCache.active_api_preset = found.name;
    settingsCache.api_url = found.api_url || "";
    settingsCache.api_key = "";
    settingsCache.api_key_set = Boolean(found.api_key_set);
    settingsCache.api_key_last4 = found.api_key_last4 || "";
    settingsCache.model = found.model || "";
    settingsCache.reasoning = Boolean(found.reasoning);
    settingsCache.reasoning_max_tokens = Number(found.reasoning_max_tokens) || 1024;
    const preset = document.querySelector("#settings-preset");
    if (preset) preset.value = found.name;
    for (const key of ["api_url", "model", "reasoning_max_tokens"]) {
      const input = document.querySelector(`[data-setting="${key}"]`);
      if (input) input.value = settingsCache[key];
    }
    const keyInput = document.querySelector('[data-setting="api_key"]');
    if (keyInput) keyInput.value = "";
    const reasoningInput = document.querySelector('[data-setting="reasoning"]');
    if (reasoningInput) reasoningInput.checked = Boolean(settingsCache.reasoning);
    paintStoredKeyNote();
  } catch (error) {
    failNotice(error);
  }
}

function setModelsOpen(open) {
  if (open) {
    setWorldsOpen(false);
    setModesOpen(false);
  }
  const menu = document.querySelector("#models-menu");
  const toggle = document.querySelector("#models-toggle");
  menu.hidden = !open;
  toggle.setAttribute("aria-expanded", open ? "true" : "false");
  toggle.closest(".models").classList.toggle("open", open);
}

function worldItems(list) {
  return (list || []).map((item) => (
    item && typeof item === "object"
      ? { name: item.name || "", language: item.language || "" }
      : { name: String(item || ""), language: "" }
  )).filter((item) => item.name);
}

function appendLangMark(parent, language) {
  if (language !== "ru" && language !== "en") return;
  const mark = document.createElement("small");
  mark.className = "lang-mark";
  mark.textContent = language.toUpperCase();
  parent.append(mark);
}

function paintWorlds() {
  const menu = document.querySelector("#world-menu");
  const current = document.querySelector("#world-current");
  const items = worldItems(state && state.worlds);
  const activeItem = items.find((item) => item.name === (state && state.world)) || null;
  const active = activeItem ? activeItem.name : "";
  current.replaceChildren();
  const name = document.createElement("span");
  name.className = "name";
  setNodeText(name, active || t("no_worlds"));
  current.append(name);
  if (activeItem) appendLangMark(current, activeItem.language);
  menu.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "pop-empty";
    empty.textContent = t("no_worlds");
    menu.append(empty);
    return;
  }
  const groups = new Set(items.map((item) => item.language).filter(Boolean));
  let previous = null;
  for (const item of items) {
    if (groups.size > 1 && item.language && item.language !== previous) {
      const label = document.createElement("p");
      label.className = "pop-label";
      label.textContent = t(`worlds.lang.${item.language}`);
      menu.append(label);
      previous = item.language;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "world-item";
    button.setAttribute("role", "menuitemradio");
    button.setAttribute("aria-checked", item.name === active ? "true" : "false");
    const title = document.createElement("span");
    setNodeText(title, item.name);
    button.append(title);
    appendLangMark(button, item.language);
    button.addEventListener("click", () => openWorld(item.name));
    menu.append(button);
  }
}

async function openWorld(name) {
  setWorldsOpen(false);
  if (state && state.world === name) return;
  try {
    adoptSnapshot(await api("/api/worlds/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }), "end");
  } catch (error) {
    failNotice(error);
  }
}

let heroAskedFor = "";

function paintMode(snap) {
  const mode = snap && snap.play_mode === "adventure" ? "adventure" : "sandbox";
  if (mode === "adventure") document.documentElement.dataset.mode = "adventure";
  else delete document.documentElement.dataset.mode;
  const current = document.querySelector("#modes-current");
  if (current) current.textContent = t(mode === "adventure" ? "mode.adventure" : "mode.sandbox");
  const menu = document.querySelector("#modes-menu");
  if (!menu) return;
  menu.replaceChildren();
  for (const id of ["sandbox", "adventure"]) {
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("role", "menuitemradio");
    button.setAttribute("aria-checked", id === mode ? "true" : "false");
    button.textContent = t(`mode.${id}`);
    button.addEventListener("click", () => selectMode(id));
    menu.append(button);
  }
}

async function selectMode(mode) {
  setModesOpen(false);
  if (state && state.play_mode === mode) return;
  heroAskedFor = "";
  applySnapshot(await api("/api/mode", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ play_mode: mode }),
  }), "end");
}

const HERO_STATS = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"];

function heroField(id) {
  return document.querySelector(`#hero-${id}`);
}

function openHeroDialog() {
  const hero = (state && state.hero) || {};
  heroField("name").value = hero.name || "";
  heroField("appearance").value = hero.appearance || "";
  heroField("equipment").value = hero.equipment || "";
  for (const key of HERO_STATS) {
    const input = heroField(key);
    const value = Number(hero[key]);
    input.value = Number.isFinite(value) && value > 0 ? String(value) : "10";
  }
  const error = document.querySelector("#hero-error");
  if (error) error.textContent = "";
  const dialog = document.querySelector("#hero-dialog");
  if (!dialog.open) dialog.showModal();
  heroField("name").focus();
}

function maybeAskHero(snap) {
  if (!snap || !snap.needs_hero) return;
  const key = snap.world || "";
  if (heroAskedFor === key) return;
  heroAskedFor = key;
  openHeroDialog();
}

function paintPending(snap) {
  const dialog = document.querySelector("#stat-dialog");
  if (!dialog) return;
  const pending = snap && snap.pending_stats && snap.pending_stats.stats;
  const keys = pending ? Object.keys(pending) : [];
  if (!keys.length) {
    if (dialog.open) dialog.close();
    return;
  }
  const list = document.querySelector("#stat-list");
  const current = snap.pending_stats.current || {};
  list.replaceChildren();
  for (const key of keys) {
    const row = document.createElement("p");
    row.textContent = `${t(`hero.${key}`)}: ${current[key] ?? ""} → ${pending[key]}`;
    list.append(row);
  }
  if (!dialog.open) dialog.showModal();
}

async function resolveStats(accept) {
  const dialog = document.querySelector("#stat-dialog");
  if (dialog.open) dialog.close();
  applySnapshot(await api("/api/hero/stats", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ accept }),
  }), "keep");
}

function setModesOpen(open) {
  if (open) {
    setModelsOpen(false);
    setWorldsOpen(false);
  }
  const menu = document.querySelector("#modes-menu");
  const toggle = document.querySelector("#modes-toggle");
  if (!menu || !toggle) return;
  menu.hidden = !open;
  toggle.setAttribute("aria-expanded", open ? "true" : "false");
  toggle.closest(".modes").classList.toggle("open", open);
}

function setWorldsOpen(open) {
  if (open) {
    setModelsOpen(false);
    setModesOpen(false);
  }
  const menu = document.querySelector("#world-menu");
  const toggle = document.querySelector("#world-toggle");
  menu.hidden = !open;
  toggle.setAttribute("aria-expanded", open ? "true" : "false");
  toggle.closest(".worlds-picker").classList.toggle("open", open);
  if (!open) return;
  const checked = menu.querySelector('[aria-checked="true"]');
  if (checked) menu.scrollTop = Math.max(0, checked.offsetTop - 8);
}

function regresses(snap) {
  if (!state || typeof snap.rev !== "number" || typeof state.rev !== "number") return false;
  if (snap.rev !== state.rev) return snap.rev < state.rev;
  if ((snap.history_total || 0) < (state.history_total || 0)) return true;
  if (state.streaming && snap.streaming && (snap.draft || "").length < (state.draft || "").length) return true;
  if (state.streaming && snap.streaming && (snap.draft_reasoning || "").length < (state.draft_reasoning || "").length) return true;
  if (state.streaming && !snap.streaming && (state.draft || "") && (snap.history_total || 0) === (state.history_total || 0)) return true;
  return false;
}

function applySnapshot(snap, mode = "end") {
  if (!snap) return;
  if ((typeof snap.rev === "number" && snap.rev < revision) || regresses(snap)) {
    if (awaitingSettle) scheduleSettle();
    return;
  }
  if (awaitingSettle && turnRev != null && typeof snap.rev === "number" && snap.rev <= turnRev && !snap.streaming) {
    scheduleSettle();
    return;
  }
  if (pendingPlayer && !snapshotHasPlayer(snap, pendingPlayer)) {
    if (awaitingSettle) scheduleSettle();
    return;
  }
  const domDraft = document.querySelector("#draft")?.textContent || "";
  const serverDraft = snap.draft || "";
  const draftDrift = Boolean(snap.streaming) && domDraft !== serverDraft;
  const unchanged = !draftDrift
    && state
    && snap.rev === revision
    && serverDraft === (state.draft || "")
    && (snap.draft_reasoning || "") === (state.draft_reasoning || "")
    && Boolean(snap.streaming) === Boolean(state.streaming)
    && snap.history_total === state.history_total
    && snap.status?.text === state.status?.text
    && (snap.notices || []).at(-1) === (state.notices || []).at(-1);
  if (typeof snap.rev === "number") {
    revision = snap.rev;
    if (snap.rev > eventRev) eventRev = snap.rev;
  }
  if (!historyExpanded && Number.isInteger(snap.history_from)) tailFrom = snap.history_from;
  state = snap;
  drafting = Boolean(snap.streaming);
  draftClosed = !snap.streaming;
  if (!snap.streaming) {
    awaitingSettle = false;
    pendingPlayer = "";
    pendingIndex = null;
    turnRev = null;
    settleOnce = false;
  }
  settleFresh(snap);
  paintWorlds();
  paintModels();
  paintMode(snap);
  paintPending(snap);
  maybeAskHero(snap);
  paintFill(snap.fill);
  paintStatus(snap.status);
  paintNotice((snap.notices || []).at(-1) || "");
  paintMeters(snap.meters);
  if (mode === "end" || !unchanged) renderLog(mode);
}

function snapshotHasPlayer(snap, text) {
  const matches = (row) => Boolean(row && row.kind === "player" && text && (
    row.text === text || row.text.startsWith(`${text}\n`)
  ));
  const rows = snap.history || [];
  if (pendingIndex == null) {
    const last = [...rows].reverse().find((row) => row.kind === "player");
    return matches(last);
  }
  const exact = rows.find((row) => row.index === pendingIndex);
  if (exact) return matches(exact);
  return (snap.history_total || 0) > pendingIndex && rows.some((row) => (
    matches(row) && row.index >= pendingIndex
  ));
}

function scheduleSettle() {
  if (settleOnce || !awaitingSettle) return;
  settleOnce = true;
  window.setTimeout(() => {
    if (awaitingSettle) refresh("end").catch(() => {});
  }, 50);
}

function beginTurn() {
  awaitingSettle = true;
  settleOnce = false;
  turnRev = revision;
  syncPolling();
}

function adoptSnapshot(snap, mode) {
  historyExpanded = false;
  pendingPlayer = "";
  pendingIndex = null;
  awaitingSettle = false;
  turnRev = null;
  settleOnce = false;
  applySnapshot(snap, mode);
}

async function refresh(mode = "end") {
  const expanded = historyExpanded
    && state
    && Number.isInteger(state.history_from)
    && state.history_from !== tailFrom;
  const start = expanded ? `?start=${state.history_from}` : "";
  applySnapshot(await api(`/api/state${start}`), mode);
}

function syncPolling() {
  const keep = document.body.classList.contains("busy") || awaitingSettle;
  if (keep) {
    if (!pollTimer) pollTimer = window.setInterval(() => refresh("follow").catch(() => {}), 2000);
  } else if (pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = 0;
  }
}

function catchUp(mode = "end") {
  if (document.visibilityState === "hidden") return;
  refresh(mode).catch(() => {});
}

let source = null;
let leftPage = false;
let resumeTimers = [];

function connectEvents() {
  if (source) {
    source.onopen = null;
    source.onmessage = null;
    source.onerror = null;
    source.close();
  }
  source = new EventSource("/api/events?_=" + Date.now());
  source.onopen = () => catchUp("follow");
  source.onerror = () => {
    const now = Date.now();
    if (now - (connectEvents.lastError || 0) < 1500) return;
    connectEvents.lastError = now;
    catchUp("follow");
  };
  source.onmessage = (message) => {
    let event;
    try {
      event = JSON.parse(message.data);
    } catch (error) {
      return;
    }
    if (typeof event.rev === "number" && event.rev < eventRev) return;
    if (typeof event.rev === "number") eventRev = event.rev;
    if (event.kind === "dm_start") {
      drafting = true;
      draftClosed = false;
      awaitingSettle = true;
      settleOnce = false;
      noteFreshReply();
      if (state) state.streaming = true;
      syncPolling();
      renderLog("end");
    } else if (event.kind === "dm_delta") {
      if (draftClosed) return;
      const follow = nearBottom();
      const draft = ensureDraft();
      if (!draft) return;
      const next = typeof event.full === "string" ? event.full : `${draft.textContent}${event.text || ""}`;
      if (next.length >= draft.textContent.length) {
        setNodeText(draft, next);
        if (state) {
          state.streaming = true;
          state.draft = next;
        }
      }
      if (follow) jumpToEnd();
    } else if (event.kind === "dm_reasoning") {
      if (draftClosed) return;
      const follow = nearBottom();
      const block = ensureDraftReasoning();
      if (!block) return;
      const body = block.querySelector(".reasoning-body");
      const next = typeof event.full === "string" ? event.full : `${body ? body.textContent : ""}${event.text || ""}`;
      if (body && next.length >= body.textContent.length) {
        setNodeText(body, next);
        if (state) {
          state.streaming = true;
          state.draft_reasoning = next;
        }
      }
      if (follow) jumpToEnd();
    } else if (event.kind === "fill") {
      paintFill(event);
    } else if (event.kind === "meters") {
      paintMeters(event);
    } else if (event.kind === "system") {
      paintNotice(event.text || "");
      if (state) state.notices = [event.text || ""];
    } else if (event.kind === "status") {
      paintStatus(event);
      if (state && state.status) {
        state.status = { ...state.status, ...event };
      }
    } else if (event.kind === "scene") {
      if (!(panel.open && panel.dataset.panel && panel.dataset.panel !== "scene")) openPanel("scene", event);
    } else if (event.kind === "card_desc") {
      if (applyCardDescription) applyCardDescription(event);
    } else if (event.kind === "dm_done" || event.kind === "dm_abort") {
      drafting = false;
      draftClosed = true;
      if (state) {
        state.streaming = false;
        state.draft = "";
        state.draft_reasoning = "";
      }
      refresh("end").catch(() => {});
    } else if (event.kind === "history") {
      refresh("end").catch(() => {});
    }
  };
}

function onResume() {
  resumeTimers.forEach((id) => clearTimeout(id));
  connectEvents();
  resumeTimers = [0, 600, 1800, 4000].map((delay) => window.setTimeout(() => catchUp("end"), delay));
  syncPolling();
}

async function boot() {
  strings = await api("/api/strings");
  applyStrings();
  document.querySelector("#lang").textContent = "…";
  await refresh();
  document.querySelector("#lang").textContent = (state.language || "ru").toUpperCase();
  connectEvents();
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      leftPage = true;
      return;
    }
    if (leftPage) {
      leftPage = false;
      onResume();
    }
  });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) onResume();
  });
  document.addEventListener("resume", () => onResume());
  window.addEventListener("online", () => onResume());
}

const nextDialog = document.querySelector("#next-dialog");
const nextText = document.querySelector("#next-text");
const nextError = document.querySelector("#next-error");

document.querySelector("#next").addEventListener("click", () => {
  nextError.textContent = "";
  nextText.value = "";
  if (!nextDialog.open) nextDialog.showModal();
  nextText.focus();
});
document.querySelector("#next-close").addEventListener("click", () => nextDialog.close());
document.querySelector("#next-cancel").addEventListener("click", () => nextDialog.close());
function showPlayerLine(text) {
  if (!text || !state) return;
  beginTurn();
  pendingPlayer = text;
  const last = state.history.at(-1);
  if (last && last.kind === "player" && last.text === text) {
    pendingIndex = last.index;
    return;
  }
  pendingIndex = Number.isInteger(state.history_total) ? state.history_total : state.history.length;
  state.history.push({ index: pendingIndex, kind: "player", text });
  if (Number.isInteger(state.history_total)) state.history_total += 1;
  renderLog("end");
}

function retractPlayerLine(text) {
  if (!text || !state) {
    releaseTurn();
    return;
  }
  const last = state.history.at(-1);
  const shown = last && last.kind === "player" && last.text === text;
  if (shown) {
    state.history.pop();
    if (Number.isInteger(state.history_total)) state.history_total -= 1;
    renderLog("end");
  }
  releaseTurn();
}

function releaseTurn() {
  pendingPlayer = "";
  pendingIndex = null;
  awaitingSettle = false;
  turnRev = null;
  settleOnce = false;
  syncPolling();
}

document.querySelector("#next-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const direction = nextText.value.trim();
  if (!direction) {
    nextError.textContent = t("dialog.empty_next");
    return;
  }
  if (state && state.needs_hero) {
    openHeroDialog();
    return;
  }
  if (sendingTurn || document.body.classList.contains("busy")) {
    nextError.textContent = t("dialog.busy");
    return;
  }
  nextError.textContent = "";
  showPlayerLine(direction);
  sendingTurn = true;
  try {
    await api("/api/turn", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ direction }),
    });
    nextDialog.close();
  } catch (error) {
    retractPlayerLine(direction);
    nextText.value = direction;
    if (error.body && error.body.detail === "hero") openHeroDialog();
    nextError.textContent = actionErrorText(error) || t("dialog.busy");
  } finally {
    sendingTurn = false;
  }
});

document.querySelector("#composer").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (sendEl.classList.contains("stop")) {
    try {
      await api("/api/stop", { method: "POST" });
    } catch (error) {
      failNotice(error);
    }
    return;
  }
  if (state && state.needs_hero) {
    openHeroDialog();
    return;
  }
  if (sendingTurn) return;
  const text = actionEl.value.trim();
  actionEl.value = "";
  if (text) showPlayerLine(text);
  else beginTurn();
  sendingTurn = true;
  try {
    await api("/api/turn", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
    document.body.classList.remove("writing");
    fitChrome();
  } catch (error) {
    retractPlayerLine(text);
    actionEl.value = text;
    if (error.body && error.body.detail === "hero") openHeroDialog();
    failNotice(error);
  } finally {
    sendingTurn = false;
  }
});

document.querySelector("#menu-toggle").addEventListener("click", () => {
  const bar = document.querySelector(".topbar");
  const open = bar.classList.toggle("open");
  document.querySelector("#menu-toggle").setAttribute("aria-expanded", open ? "true" : "false");
  fitChrome();
});

document.querySelector("#models-toggle").addEventListener("click", (event) => {
  event.stopPropagation();
  const menu = document.querySelector("#models-menu");
  setModelsOpen(menu.hidden);
});
document.querySelector("#modes-toggle").addEventListener("click", (event) => {
  event.stopPropagation();
  const menu = document.querySelector("#modes-menu");
  setModesOpen(menu.hidden);
});
document.querySelector("#world-toggle").addEventListener("click", (event) => {
  event.stopPropagation();
  const menu = document.querySelector("#world-menu");
  setWorldsOpen(menu.hidden);
});
document.addEventListener("click", (event) => {
  if (!event.target.closest(".models")) setModelsOpen(false);
  if (!event.target.closest(".modes")) setModesOpen(false);
  if (!event.target.closest(".worlds-picker")) setWorldsOpen(false);
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (!document.querySelector("#models-menu").hidden) setModelsOpen(false);
  if (!document.querySelector("#modes-menu").hidden) setModesOpen(false);
  if (!document.querySelector("#world-menu").hidden) setWorldsOpen(false);
});
document.querySelector("#hero-close").addEventListener("click", () => document.querySelector("#hero-dialog").close());
document.querySelector("#hero-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = document.querySelector("#hero-error");
  error.textContent = "";
  const payload = {
    name: heroField("name").value.trim(),
    appearance: heroField("appearance").value.trim(),
    equipment: heroField("equipment").value.trim(),
  };
  for (const key of HERO_STATS) payload[key] = Number(heroField(key).value);
  if (!payload.name) {
    error.textContent = t("hero.required");
    return;
  }
  try {
    applySnapshot(await api("/api/hero", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }), "keep");
    document.querySelector("#hero-dialog").close();
  } catch (err) {
    error.textContent = t("hero.required");
  }
});
document.querySelector("#stat-close").addEventListener("click", () => resolveStats(false));
document.querySelector("#stat-reject").addEventListener("click", () => resolveStats(false));
document.querySelector("#stat-accept").addEventListener("click", () => resolveStats(true));

document.querySelector("#act").addEventListener("click", async () => {
  if (document.body.classList.contains("busy")) {
    try {
      await api("/api/stop", { method: "POST" });
    } catch (error) {
      failNotice(error);
    }
    return;
  }
  const writing = document.body.classList.toggle("writing");
  fitChrome();
  if (writing) actionEl.focus();
});

actionEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    document.querySelector("#composer").requestSubmit();
  } else if (event.key === "Escape") {
    api("/api/stop", { method: "POST" });
  }
});

document.querySelector("#undo").addEventListener("click", async () => {
  try {
    adoptSnapshot(await api("/api/undo", { method: "POST" }), "end");
  } catch (error) {
    failNotice(error);
  }
});

document.querySelector("#toggle-summary").addEventListener("click", async () => {
  try {
    paintMeters(await api("/api/toggles/summary", { method: "POST" }));
  } catch (error) {
    failNotice(error);
  }
});
document.querySelector("#toggle-memory").addEventListener("click", async () => {
  try {
    paintMeters(await api("/api/toggles/memory", { method: "POST" }));
  } catch (error) {
    failNotice(error);
  }
});

document.querySelector("#reroll").addEventListener("click", () => api("/api/regenerate", { method: "POST" }).catch(failNotice));
document.querySelector("#edit").addEventListener("click", () => {
  const rows = editableRows();
  if (rows.length) openEditor(rows[rows.length - 1].index);
});
document.querySelector("#summarize").addEventListener("click", () => api("/api/summary", { method: "POST" }).catch(failNotice));

document.querySelector("#lang").addEventListener("click", async () => {
  const next = (state.language === "en") ? "ru" : "en";
  const openTab = panelBody.querySelector(".tabs button[aria-pressed='true']");
  const preferred = openTab ? openTab.dataset.tab : "ai";
  try {
    const updated = await api("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language: next }),
    });
    if (settingsCache) {
      settingsCache.language = updated.language;
      settingsCache.prompts = updated.prompts;
    }
    strings = await api("/api/strings");
    applyStrings();
    await refresh("keep");
    document.querySelector("#lang").textContent = next.toUpperCase();
    if (settingsCache && panel.open && panel.dataset.panel === "settings" && paintSettingsForm) {
      paintSettingsForm(preferred);
    }
  } catch (error) {
    failNotice(error);
  }
});

document.querySelector("#panel-close").addEventListener("click", () => panel.close());

function editableRows() {
  return (state.history || []).filter((row) => row.kind === "player" || row.kind === "dm");
}

function openEditor(index) {
  const rows = editableRows().map((row) => ({ index: row.index, kind: row.kind, text: row.text, draft: row.text }));
  let pos = rows.findIndex((row) => row.index === index);
  if (pos < 0) pos = rows.length - 1;
  if (pos < 0) return;
  panelBody.replaceChildren();
  const heading = document.createElement("p");
  heading.className = "section";
  const label = document.createElement("label");
  const labelText = document.createTextNode("");
  const area = document.createElement("textarea");
  area.rows = 14;
  label.append(labelText, area);
  const nav = document.createElement("div");
  nav.className = "row";
  const prev = document.createElement("button");
  prev.type = "button";
  prev.textContent = t("dialog.edit_prev");
  const next = document.createElement("button");
  next.type = "button";
  next.textContent = t("dialog.edit_next");
  const save = document.createElement("button");
  save.type = "button";
  save.className = "primary";
  save.textContent = t("btn.save_ok");
  function stash() {
    if (rows[pos]) rows[pos].draft = area.value;
  }
  function show() {
    const row = rows[pos];
    const title = row.kind === "dm" ? t("dialog.edit_dm") : t("dialog.edit_player");
    panelTitle.textContent = title;
    heading.textContent = `${title} (${pos + 1}/${rows.length})`;
    labelText.textContent = row.kind === "dm" ? t("dialog.edit_dm_label") : t("dialog.edit_player_label");
    area.value = row.draft;
    prev.disabled = pos === 0;
    next.disabled = pos === rows.length - 1;
  }
  prev.addEventListener("click", () => { if (pos > 0) { stash(); pos -= 1; show(); } });
  next.addEventListener("click", () => { if (pos < rows.length - 1) { stash(); pos += 1; show(); } });
  save.addEventListener("click", async () => {
    stash();
    const dirty = rows.filter((row) => row.draft.trim() && row.draft !== row.text);
    if (!dirty.length) {
      if (!rows[pos].draft.trim()) return;
      panel.close();
      return;
    }
    const start = Math.min(state.history_from || 0, ...dirty.map((row) => row.index));
    try {
      for (const row of dirty) {
        await api(`/api/history/${row.index}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: row.draft.trim() }),
        });
        row.text = row.draft.trim();
      }
      if (Number.isInteger(tailFrom) && start < tailFrom) historyExpanded = true;
      applySnapshot(await api(`/api/state?start=${start}`), "keep");
      if (rows[pos].draft.trim()) panel.close();
    } catch (error) {
      failNotice(error);
    }
  });
  nav.append(prev, next, save);
  panelBody.append(heading, label, nav);
  show();
  if (!panel.open) panel.showModal();
}

async function editRow(row) {
  openEditor(row.index);
}

function openPanel(name, extra) {
  panel.dataset.panel = name;
  applyCardDescription = null;
  panelTitle.textContent = t(`btn.${name === "settings" ? "ai_settings" : name === "files" ? "world_files" : name === "scene" ? "scene_prompt" : name}`);
  panelBody.replaceChildren();
  const loaders = { worlds: renderWorlds, files: renderFiles, cards: renderCards, memory: renderMemory, settings: renderSettings, prompt: renderPrompt, scene: renderScene, gallery: renderGallery };
  loaders[name](extra);
  if (!panel.open) panel.showModal();
}

document.querySelectorAll("[data-panel]").forEach((button) => {
  button.addEventListener("click", () => openPanel(button.dataset.panel));
});

function mountCardEditor(host, cardsData, options) {
  const saveEnabled = !options || options.save !== false;
  const cards = cardsData.cards || (cardsData.cards = []);
  let current = 0;
  let query = "";
  const layout = document.createElement("div");
  layout.className = "cards-layout";
  const left = document.createElement("div");
  const listLabel = document.createElement("p");
  listLabel.className = "section";
  listLabel.textContent = t("cards.list");
  const search = document.createElement("input");
  search.type = "search";
  search.placeholder = t("cards.search");
  const list = document.createElement("div");
  list.className = "card-list";
  const right = document.createElement("div");
  const title = document.createElement("input");
  title.type = "text";
  const desc = document.createElement("textarea");
  desc.id = "card-desc";
  desc.rows = 10;
  const triggers = document.createElement("input");
  triggers.type = "text";
  triggers.placeholder = t("cards.triggers_ph");
  const note = document.createElement("p");
  note.className = "error";

  function labeled(text, field, hint) {
    const wrap = document.createElement("div");
    const label = document.createElement("label");
    label.textContent = text;
    label.append(field);
    wrap.append(label);
    if (hint) {
      const help = document.createElement("p");
      help.className = "hint";
      help.textContent = hint;
      wrap.append(help);
    }
    return wrap;
  }

  function nextId() {
    let max = 0;
    for (const card of cards) {
      const match = String(card.id || "").match(/card_(\d+)/);
      if (match) max = Math.max(max, Number(match[1]));
    }
    return `card_${String(max + 1).padStart(3, "0")}`;
  }

  function read() {
    if (!cards[current]) return;
    const card = cards[current];
    card.title = title.value.trim();
    if (desc.value !== asText(card.description)) card.description = desc.value;
    card.triggers = triggers.value.split(/[,;\n]+/).map((item) => item.trim()).filter(Boolean);
  }

  function write() {
    const card = cards[current] || { title: "", description: "", triggers: [] };
    title.value = card.title || "";
    desc.value = asText(card.description);
    triggers.value = (card.triggers || []).map(asText).join(", ");
  }

  function visible() {
    const needle = query.trim().toLowerCase();
    return cards.map((card, index) => ({ card, index })).filter(({ card }) => {
      if (!needle) return true;
      const blob = `${asText(card.title)} ${asText(card.description)} ${(card.triggers || []).map(asText).join(" ")}`.toLowerCase();
      return blob.includes(needle);
    });
  }

  function draw() {
    list.replaceChildren();
    for (const item of visible()) {
      const button = document.createElement("button");
      button.type = "button";
      setNodeText(button, item.card.title || t("cards.untitled"));
      button.setAttribute("aria-pressed", item.index === current ? "true" : "false");
      button.addEventListener("click", () => {
        read();
        current = item.index;
        write();
        draw();
      });
      list.append(button);
    }
  }

  search.addEventListener("input", () => {
    read();
    query = search.value;
    draw();
  });
  const row = document.createElement("div");
  row.className = "row";
  const add = document.createElement("button");
  add.type = "button";
  add.textContent = t("btn.add");
  add.addEventListener("click", () => {
    read();
    cards.push({ id: nextId(), title: t("cards.new"), description: "", triggers: [] });
    current = cards.length - 1;
    write();
    draw();
  });
  const del = document.createElement("button");
  del.type = "button";
  del.className = "danger";
  del.textContent = t("btn.delete");
  del.addEventListener("click", () => {
    if (!cards[current]) return;
    if (!window.confirm(t("cards.delete_q"))) return;
    cards.splice(current, 1);
    current = Math.max(0, current - 1);
    write();
    draw();
  });
  let pendingTitle = "";
  let pendingIndex = -1;
  const gen = document.createElement("button");
  gen.type = "button";
  gen.textContent = t("cards.generate_desc");
  gen.addEventListener("click", () => {
    note.textContent = "";
    if (!title.value.trim()) {
      note.textContent = t("cards.enter_title_first");
      return;
    }
    pendingTitle = title.value.trim();
    pendingIndex = current;
    api("/api/cards/describe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: title.value, description: desc.value }),
    }).catch((error) => {
      const detail = error && error.body && error.body.detail;
      note.textContent = detail === "no world" || !(state && state.world) ? t("dialog.no_world") : t("dialog.busy");
    });
  });
  const save = document.createElement("button");
  save.type = "button";
  save.className = "primary";
  save.textContent = t("btn.save");
  save.addEventListener("click", async () => {
    read();
    for (const card of cards) {
      if (!String(card.title || "").trim()) card.title = t("cards.untitled");
    }
    try {
      await api("/api/cards", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cards }),
      });
      await refresh("keep");
      write();
      draw();
    } catch (error) {
      const detail = error && error.body && error.body.detail;
      note.textContent = detail === "no world" || !(state && state.world) ? t("dialog.no_world") : t("dialog.busy");
    }
  });
  row.append(add, del, gen);
  if (saveEnabled) row.append(save);
  right.append(
    labeled(t("cards.title"), title),
    labeled(t("cards.desc"), desc),
    labeled(t("cards.triggers"), triggers, t("cards.empty_triggers")),
    note,
    row,
  );
  left.append(listLabel, search, list);
  layout.append(left, right);
  host.append(layout);
  write();
  draw();
  applyCardDescription = (event) => {
    if (String(event.title || "").trim() !== pendingTitle) return;
    const card = cards[pendingIndex];
    if (!card) return;
    card.description = event.text || "";
    if (pendingIndex === current) desc.value = card.description;
  };
  return { read };
}

async function renderWorlds() {
  panelTitle.textContent = t("btn.worlds");
  panelBody.replaceChildren();
  const data = await api("/api/worlds");
  const items = worldItems(data.worlds);
  let selected = data.current || (items[0] && items[0].name) || "";
  const heading = document.createElement("p");
  heading.className = "section";
  heading.textContent = t("dialog.your_worlds");
  const list = document.createElement("div");
  list.className = "world-list";
  function draw() {
    list.replaceChildren();
    const groups = new Set(items.map((item) => item.language).filter(Boolean));
    let previous = null;
    for (const item of items) {
      if (groups.size > 1 && item.language && item.language !== previous) {
        const label = document.createElement("p");
        label.className = "section";
        label.textContent = t(`worlds.lang.${item.language}`);
        list.append(label);
        previous = item.language;
      }
      const button = document.createElement("button");
      button.type = "button";
      const title = document.createElement("span");
      setNodeText(title, item.name);
      button.append(title);
      appendLangMark(button, item.language);
      button.setAttribute("aria-pressed", item.name === selected ? "true" : "false");
      button.addEventListener("click", () => {
        selected = item.name;
        draw();
      });
      list.append(button);
    }
  }
  draw();
  const note = document.createElement("p");
  note.className = "error";
  const actions = document.createElement("div");
  actions.className = "row";
  const load = document.createElement("button");
  load.type = "button";
  load.className = "primary";
  load.textContent = t("btn.load");
  load.addEventListener("click", async () => {
    if (!selected) return;
    note.textContent = "";
    try {
      adoptSnapshot(await api("/api/worlds/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: selected }),
      }), "end");
      panel.close();
    } catch (error) {
      const detail = error.body && error.body.detail;
      note.textContent = error.status === 400 ? t("dialog.bad_name_msg") : (typeof detail === "string" && detail !== "busy" ? detail : t("dialog.busy"));
    }
  });
  const del = document.createElement("button");
  del.type = "button";
  del.className = "danger";
  del.textContent = t("btn.delete");
  del.addEventListener("click", async () => {
    if (!selected) return;
    const question = t("dialog.delete_world_q").replace("{name}", selected);
    if (!window.confirm(question)) return;
    try {
      adoptSnapshot(await api(`/api/worlds/${encodeURIComponent(selected)}`, { method: "DELETE" }), "end");
    } catch (error) {
      note.textContent = actionErrorText(error) || t("dialog.busy");
      return;
    }
    renderWorlds();
  });
  const create = document.createElement("button");
  create.type = "button";
  create.textContent = t("btn.create");
  create.addEventListener("click", () => renderCreateWorld());
  const exp = document.createElement("button");
  exp.type = "button";
  exp.textContent = t("btn.export");
  exp.addEventListener("click", () => {
    if (!selected) return;
    const link = document.createElement("a");
    link.href = `/api/worlds/${encodeURIComponent(selected)}/export`;
    link.download = `${selected}.zip`;
    document.body.append(link);
    link.click();
    link.remove();
  });
  const file = document.createElement("input");
  file.type = "file";
  file.accept = ".zip,application/zip";
  file.hidden = true;
  const imp = document.createElement("button");
  imp.type = "button";
  imp.textContent = t("btn.import");
  imp.addEventListener("click", () => {
    note.textContent = "";
    file.click();
  });
  file.addEventListener("change", async () => {
    const chosen = file.files && file.files[0];
    file.value = "";
    if (!chosen) return;
    const stem = chosen.name.replace(/\.zip$/i, "").trim();
    note.textContent = "";
    try {
      const imported = await api(`/api/worlds/import?name=${encodeURIComponent(stem)}`, {
        method: "POST",
        headers: { "Content-Type": "application/zip" },
        body: chosen,
      });
      adoptSnapshot(imported.state, "end");
      panel.close();
    } catch (err) {
      const detail = err.body && err.body.detail;
      if (detail === "busy") note.textContent = t("dialog.busy");
      else if (detail === "exists" || detail === "bad name") note.textContent = t("dialog.bad_name_msg");
      else if (detail === "bad archive" || err.status === 400) note.textContent = t("dialog.import_failed");
      else note.textContent = actionErrorText(err) || t("dialog.import_failed");
    }
  });
  actions.append(load, exp, imp, create, del);
  panelBody.append(heading, list, note, file, actions);
}

async function renderCreateWorld() {
  let draft;
  try {
    draft = await api("/api/worlds/template");
  } catch (error) {
    failNotice(error);
    return;
  }
  panelTitle.textContent = t("dialog.create_world");
  panelBody.replaceChildren();
  const error = document.createElement("p");
  error.className = "error";
  const nameLabel = document.createElement("label");
  nameLabel.textContent = t("dialog.world_name");
  const name = document.createElement("input");
  name.type = "text";
  name.value = draft.name || "";
  nameLabel.append(name);
  const files = draft.files || {};
  for (const name of Object.keys(files)) files[name] = unixText(files[name]);
  const names = Object.keys(files);
  let currentFile = names[0] || "";
  const buttons = document.createElement("div");
  buttons.className = "file-buttons";
  const area = document.createElement("textarea");
  area.rows = 12;
  function show(file) {
    if (currentFile && currentFile !== file) files[currentFile] = area.value;
    currentFile = file;
    area.value = files[file] || "";
    buttons.querySelectorAll("button").forEach((button) => {
      button.setAttribute("aria-pressed", button.dataset.file === file ? "true" : "false");
    });
  }
  for (const file of names) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.file = file;
    setNodeText(button, t(`world_file.${file}`));
    button.addEventListener("click", () => show(file));
    buttons.append(button);
  }
  area.addEventListener("input", () => { files[currentFile] = area.value; });
  if (currentFile) show(currentFile);
  const cardsTitle = document.createElement("p");
  cardsTitle.className = "section";
  cardsTitle.textContent = t("world_file.story_cards");
  const cardsHost = document.createElement("div");
  const editor = mountCardEditor(cardsHost, draft.cards || { cards: [] }, { save: false });
  const actions = document.createElement("div");
  actions.className = "row";
  const ok = document.createElement("button");
  ok.type = "button";
  ok.className = "primary";
  ok.textContent = t("btn.create_ok");
  ok.addEventListener("click", async () => {
    error.textContent = "";
    files[currentFile] = area.value;
    editor.read();
    try {
      const created = await api("/api/worlds", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.value, files, cards: draft.cards }),
      });
      adoptSnapshot(created.state, "end");
      panel.close();
    } catch (err) {
      const detail = err.body && err.body.detail;
      error.textContent = detail === "busy" ? t("dialog.busy") : t("dialog.bad_name_msg");
    }
  });
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.textContent = t("btn.cancel");
  cancel.addEventListener("click", () => renderWorlds());
  actions.append(ok, cancel);
  panelBody.append(error, nameLabel, buttons, area, cardsTitle, cardsHost, actions);
}

async function renderFiles() {
  let files;
  try {
    files = await api("/api/files");
  } catch (error) {
    const note = document.createElement("p");
    note.className = "error";
    note.textContent = t("dialog.no_world");
    panelBody.append(note);
    return;
  }
  for (const name of Object.keys(files)) files[name] = unixText(files[name]);
  const original = { ...files };
  const names = Object.keys(files);
  let current = names[0] || "";
  const buttons = document.createElement("div");
  buttons.className = "file-buttons";
  const area = document.createElement("textarea");
  area.rows = 16;
  function show(name) {
    if (current && current !== name) files[current] = area.value;
    current = name;
    area.value = files[name] || "";
    buttons.querySelectorAll("button").forEach((button) => {
      button.setAttribute("aria-pressed", button.dataset.file === name ? "true" : "false");
    });
  }
  for (const name of names) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.file = name;
    setNodeText(button, t(`world_file.${name}`));
    button.addEventListener("click", () => show(name));
    buttons.append(button);
  }
  area.addEventListener("input", () => { files[current] = area.value; });
  if (current) show(current);
  const save = document.createElement("button");
  save.type = "button";
  save.textContent = t("btn.save");
  const note = document.createElement("p");
  note.className = "error";
  save.addEventListener("click", async () => {
    if (current) files[current] = area.value;
    const dirty = names.filter((name) => files[name] !== original[name]);
    if (!dirty.length) return;
    note.textContent = "";
    try {
      let fill = null;
      for (const name of dirty) {
        const result = await api(`/api/files/${encodeURIComponent(name)}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: files[name] }),
        });
        fill = result.fill;
        original[name] = files[name];
      }
      if (fill) paintFill(fill);
      await refresh("keep");
    } catch (error) {
      const detail = error && error.body && error.body.detail;
      note.textContent = detail === "no world" || !(state && state.world) ? t("dialog.no_world") : t("dialog.busy");
    }
  });
  panelBody.append(buttons, area, note, save);
}

async function renderCards() {
  const data = await api("/api/cards");
  mountCardEditor(panelBody, data);
}

async function renderMemory() {
  const memory = await api("/api/memory");
  const box = document.createElement("div");
  const entries = memory.entries || [];
  if (!state || !state.world) {
    const p = document.createElement("p");
    p.textContent = t("dialog.no_world");
    box.append(p);
    panelBody.append(box);
    return;
  }
  const stats = document.createElement("p");
  stats.className = "section";
  stats.textContent = entries.length
    ? t("dialog.memory_stats", { n: entries.length, turns: memory.last_indexed_turn || 0 })
    : t("dialog.memory_empty");
  box.append(stats);
  for (const entry of entries) {
    const keys = (entry.keys || []).map(asText).filter(Boolean).join(", ") || "—";
    const npcs = (entry.npcs || []).map(asText).filter(Boolean).join(", ") || "—";
    const p = document.createElement("p");
    p.className = "memory-entry";
    p.textContent = t("dialog.memory_entry", {
      id: entry.id || "",
      start: entry.turn_start ?? "?",
      end: entry.turn_end ?? "?",
      keys,
      npcs,
      location: asText(entry.location) || "—",
      summary: asText(entry.summary),
    });
    box.append(p);
  }
  panelBody.append(box);
}

async function copyText(text) {
  const value = String(text || "");
  if (!value) return false;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch (error) {
    /* LAN pages are not a secure context; the fallback below still copies. */
  }
  const area = document.createElement("textarea");
  area.value = value;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.left = "-9999px";
  document.body.append(area);
  area.select();
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } catch (error) {
    copied = false;
  }
  area.remove();
  return copied;
}

async function renderPrompt() {
  const data = await api("/api/prompt");
  const prompt = data.prompt;
  const area = document.createElement("textarea");
  area.rows = 18;
  area.readOnly = true;
  const full = prompt
    ? t("dialog.prompt_time", { time: prompt.time || "", tokens: prompt.tokens ?? "" })
      + t("dialog.prompt_body", { system: prompt.system || "", user: prompt.user || "" })
    : t("dialog.no_prompt");
  area.value = full;
  const copy = document.createElement("button");
  copy.type = "button";
  copy.textContent = t("btn.copy");
  copy.disabled = !prompt;
  copy.addEventListener("click", async () => {
    if (await copyText(full)) paintNotice(t("msg.prompt_copied"));
  });
  panelBody.append(area, copy);
}

async function renderScene(extra) {
  const data = await api("/api/scene");
  const scene = extra && extra.prompt != null ? extra : data.scene;
  let style = data.image_prompt_style || "sd";
  let look = data.image_look || "none";

  function choiceRow(title, values, selected, labelPrefix, onPick) {
    const headingNode = document.createElement("p");
    headingNode.className = "section";
    headingNode.textContent = t(title);
    const row = document.createElement("div");
    row.className = "choice-row";
    row.setAttribute("role", "group");
    row.setAttribute("aria-label", t(title));
    for (const value of values) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = t(`${labelPrefix}.${value}`);
      button.setAttribute("aria-pressed", value === selected ? "true" : "false");
      button.addEventListener("click", () => {
        for (const item of row.querySelectorAll("button")) item.setAttribute("aria-pressed", "false");
        button.setAttribute("aria-pressed", "true");
        onPick(value);
      });
      row.append(button);
    }
    return [headingNode, row];
  }

  function saveSceneOptions() {
    api("/api/scene/options", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_prompt_style: style, image_look: look }),
    }).catch(() => {});
  }

  function labeledBox(title, rows, value, onEdit) {
    const label = document.createElement("label");
    label.textContent = title;
    const area = document.createElement("textarea");
    area.rows = rows;
    area.value = value || "";
    area.addEventListener("input", () => onEdit(area.value));
    label.append(area);
    return label;
  }

  const note = document.createElement("p");
  note.className = "error";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "primary";
  button.textContent = t("btn.scene_prompt");
  button.addEventListener("click", async () => {
    note.textContent = "";
    try {
      const result = await api("/api/scene", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image_prompt_style: style, image_look: look }),
      });
      if (result && result.ok === false) {
        note.className = "error";
        note.textContent = result.notice || t("scene.needs_history");
      } else {
        note.className = "hint";
        note.textContent = t("status.scene_prompt");
      }
    } catch (error) {
      note.textContent = state && state.world ? t("dialog.busy") : t("dialog.no_world");
    }
  });
  let promptText = scene ? scene.prompt : "";
  let negativeText = scene ? scene.negative : "";
  let saveTimer = 0;
  const imageButton = document.createElement("button");
  imageButton.type = "button";
  imageButton.textContent = t("btn.scene_image");
  function syncImageButton() {
    imageButton.disabled = !String(promptText || "").trim() || (data.image_backend || "off") === "off" || Boolean(scene && scene.image_pending);
    copyPrompt.disabled = !promptText;
    copyNegative.disabled = !negativeText;
  }
  function rememberText() {
    syncImageButton();
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      api("/api/scene/text", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: promptText, negative: negativeText }),
      }).catch(() => {});
    }, 300);
  }
  imageButton.addEventListener("click", async () => {
    note.textContent = "";
    clearTimeout(saveTimer);
    try {
      const result = await api("/api/scene/image", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: promptText, negative: negativeText }),
      });
      if (result && result.ok === false) {
        note.className = "error";
        note.textContent = result.notice || t("scene.image_off");
      } else {
        note.className = "hint";
        note.textContent = t("status.scene_image");
      }
    } catch (error) {
      note.className = "error";
      note.textContent = state && state.world ? t("dialog.busy") : t("dialog.no_world");
    }
  });
  let picture = null;
  if (scene && scene.image) {
    picture = document.createElement("img");
    picture.className = "scene-image";
    picture.alt = t("scene.image_alt");
    picture.src = scene.image;
  }
  const copies = document.createElement("div");
  copies.className = "row";
  const copyPrompt = document.createElement("button");
  copyPrompt.type = "button";
  copyPrompt.textContent = t("scene.copy_prompt");
  copyPrompt.addEventListener("click", async () => {
    if (await copyText(promptText)) paintNotice(t("scene.copied_prompt"));
  });
  const copyNegative = document.createElement("button");
  copyNegative.type = "button";
  copyNegative.textContent = t("scene.copy_negative");
  copyNegative.addEventListener("click", async () => {
    if (await copyText(negativeText)) paintNotice(t("scene.copied_negative"));
  });
    copies.append(copyPrompt, copyNegative);
  syncImageButton();
  if (scene && scene.image_pending) {
    note.className = "hint";
    note.textContent = t("status.scene_image");
  }
  const actions = document.createElement("div");
  actions.className = "row";
  actions.append(button, imageButton);
  panelBody.append(
    ...choiceRow("scene.format", data.image_styles || [], style, "image_style", (value) => {
      style = value;
      saveSceneOptions();
    }),
    ...choiceRow("scene.look", data.image_looks || [], look, "image_look", (value) => {
      look = value;
      saveSceneOptions();
    }),
    labeledBox(t("scene.prompt_label"), 8, promptText, (value) => {
      promptText = value;
      rememberText();
    }),
    labeledBox(t("scene.negative_label"), 4, negativeText, (value) => {
      negativeText = value;
      rememberText();
    }),
    ...(picture ? [picture] : []),
    note,
    actions,
    copies,
  );
}

async function renderGallery() {
  let data;
  try {
    data = await api("/api/images");
  } catch (error) {
    const note = document.createElement("p");
    note.className = "error";
    note.textContent = state && state.world ? t("dialog.busy") : t("dialog.no_world");
    panelBody.append(note);
    return;
  }
  const images = data.images || [];
  if (!images.length) {
    const empty = document.createElement("p");
    empty.textContent = t("gallery.empty");
    panelBody.append(empty);
    return;
  }
  const view = document.createElement("div");
  const big = document.createElement("img");
  big.className = "scene-image";
  big.hidden = true;
  big.alt = t("scene.image_alt");
  const del = document.createElement("button");
  del.type = "button";
  del.className = "danger";
  del.textContent = t("gallery.delete");
  del.hidden = true;
  let selected = "";
  del.addEventListener("click", async () => {
    if (!selected || !window.confirm(t("gallery.delete_q"))) return;
    try {
      await api(`/api/images/${encodeURIComponent(selected)}`, { method: "DELETE" });
      openPanel("gallery");
    } catch (error) {
      const note = document.createElement("p");
      note.className = "error";
      note.textContent = t("dialog.busy");
      panelBody.append(note);
    }
  });
  const grid = document.createElement("div");
  grid.className = "gallery";
  for (const item of images) {
    const button = document.createElement("button");
    button.type = "button";
    const img = document.createElement("img");
    img.src = item.url;
    img.alt = item.name;
    button.append(img);
    button.addEventListener("click", () => {
      selected = item.name;
      big.src = item.url;
      big.hidden = false;
      del.hidden = false;
      for (const other of grid.querySelectorAll("button")) other.setAttribute("aria-pressed", other === button ? "true" : "false");
    });
    grid.append(button);
  }
  view.append(big, del);
  panelBody.append(view, grid);
}

async function renderSettings() {
  try {
    settingsCache = await api("/api/settings");
  } catch (error) {
    failNotice(error);
    const note = document.createElement("p");
    note.className = "error";
    note.textContent = actionErrorText(error) || t("dialog.busy");
    panelBody.append(note);
    return;
  }
  paintSettingsForm("ai");
}

function paintSettingsForm(preferredTab) {
  if (!settingsCache) return;
  panelBody.replaceChildren();
  const initial = preferredTab || "ai";
  const tabs = document.createElement("div");
  tabs.className = "tabs";
  const body = document.createElement("div");
  const names = [
    ["ai", "dialog.tab_ai"],
    ["game", "dialog.tab_game"],
    ["prompts", "dialog.tab_prompts"],
  ];
  function show(which) {
    body.replaceChildren();
    tabs.querySelectorAll("button").forEach((button) => button.setAttribute("aria-pressed", button.dataset.tab === which ? "true" : "false"));
    if (which === "ai") body.append(aiFields());
    else if (which === "game") body.append(gameFields());
    else body.append(promptFields());
  }
  for (const [id, key] of names) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.tab = id;
    button.textContent = t(key);
    button.addEventListener("click", () => show(id));
    tabs.append(button);
  }
  const error = document.createElement("p");
  error.className = "error";
  const save = document.createElement("button");
  save.type = "button";
  save.textContent = t("btn.save");
  save.addEventListener("click", async () => {
    error.textContent = "";
    try {
      settingsCache = await api("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settingsCache),
      });
      await refresh("keep");
    } catch (err) {
      const detail = err.body && err.body.detail;
      error.textContent = detail === "busy" ? t("dialog.busy") : JSON.stringify(err.body || err.message);
    }
  });
  panelBody.append(lanBlock(), tabs, body, error, save);
  show(initial);

  function lanBlock() {
    const box = document.createElement("div");
    box.className = "lan-box";
    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = t("dialog.lan_hint");
    const urls = document.createElement("div");
    urls.className = "lan-urls";
    const restart = document.createElement("p");
    restart.className = "hint";
    let info = null;
    function address(label, value) {
      const wrap = document.createElement("label");
      wrap.textContent = label;
      const input = document.createElement("input");
      input.type = "text";
      input.readOnly = true;
      input.value = value;
      input.addEventListener("focus", () => input.select());
      wrap.append(input);
      return wrap;
    }
    function paint() {
      urls.replaceChildren();
      restart.textContent = "";
      if (!info) return;
      urls.append(address(t("dialog.lan_this_computer"), info.local_url));
      if (info.lan_urls && info.lan_urls.length) {
        for (const url of info.lan_urls) urls.append(address(t("dialog.lan_phone"), url));
      } else if (!(info.tailscale_urls && info.tailscale_urls.length)) {
        const empty = document.createElement("p");
        empty.className = "hint";
        empty.textContent = t("dialog.lan_none");
        urls.append(empty);
      }
      for (const url of info.tailscale_urls || []) urls.append(address(t("dialog.lan_tailscale"), url));
      const open = Boolean(settingsCache.lan_access);
      const listening = info.listening === "0.0.0.0";
      restart.textContent = open === listening ? "" : t("dialog.lan_restart");
    }
    const toggle = check(t("dialog.lan_access"), "lan_access");
    toggle.querySelector("input").addEventListener("change", paint);
    api("/api/network").then((payload) => {
      info = payload;
      paint();
    }).catch(() => {});
    box.append(heading(t("dialog.lan_title")), toggle, hint, urls, restart);
    return box;
  }

  function field(label, key, options) {
    const spec = options || {};
    const wrap = document.createElement("label");
    wrap.textContent = label;
    const input = document.createElement("input");
    input.type = spec.type || "text";
    if (spec.min != null) input.min = String(spec.min);
    if (spec.max != null) input.max = String(spec.max);
    if (spec.step != null) input.step = String(spec.step);
    input.value = settingsCache[key] ?? "";
    input.dataset.setting = key;
    input.addEventListener("input", () => {
      if (spec.type === "number") {
        if (input.value.trim() === "") return;
        const number = Number(input.value);
        if (Number.isFinite(number)) settingsCache[key] = number;
        return;
      }
      settingsCache[key] = input.value;
    });
    wrap.append(input);
    return wrap;
  }
  function check(label, key) {
    const wrap = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = Boolean(settingsCache[key]);
    input.dataset.setting = key;
    input.addEventListener("change", () => { settingsCache[key] = input.checked; });
    wrap.append(input, document.createTextNode(" " + label));
    return wrap;
  }
  function heading(text) {
    const node = document.createElement("p");
    node.className = "section";
    node.textContent = text;
    return node;
  }
  function choice(label, key, values) {
    const wrap = document.createElement("label");
    wrap.textContent = label;
    const select = document.createElement("select");
    const current = String(settingsCache[key] ?? "");
    const options = values.includes(current) ? values : [current, ...values];
    for (const value of options) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      select.append(option);
    }
    select.value = current;
    select.addEventListener("change", () => { settingsCache[key] = Number(select.value); });
    wrap.append(select);
    return wrap;
  }
  function aiFields() {
    const box = document.createElement("div");
    box.append(heading(t("dialog.api_config")));
    const preset = document.createElement("select");
    preset.id = "settings-preset";
    const manual = document.createElement("option");
    manual.value = "";
    manual.textContent = t("dialog.manual_preset");
    preset.append(manual);
    for (const item of settingsCache.api_presets || []) {
      const option = document.createElement("option");
      option.value = item.name;
      option.textContent = item.name;
      preset.append(option);
    }
    const known = [...preset.options].some((option) => option.value === (settingsCache.active_api_preset || ""));
    preset.value = known ? (settingsCache.active_api_preset || "") : "";
    const url = field(t("dialog.api_url"), "api_url");
    const key = document.createElement("label");
    const keyCaption = document.createElement("span");
    keyCaption.append(document.createTextNode(t("dialog.api_key")));
    const keyNote = document.createElement("span");
    keyNote.dataset.keyNote = "1";
    keyCaption.append(keyNote);
    const keyInput = document.createElement("input");
    keyInput.type = "password";
    keyInput.value = "";
    keyInput.autocomplete = "new-password";
    keyInput.dataset.setting = "api_key";
    settingsCache.api_key = "";
    keyInput.addEventListener("input", () => { settingsCache.api_key = keyInput.value; });
    key.append(keyCaption, keyInput);
    setNodeText(keyNote, keyStatusText() ? ` ${keyStatusText()}` : "");
    const model = field(t("dialog.model"), "model");
    const reasoningBox = check(t("dialog.reasoning"), "reasoning");
    const reasoningLimit = field(t("dialog.reasoning_max_tokens"), "reasoning_max_tokens", {
      type: "number",
      min: 64,
      max: 32768,
      step: 64,
    });
    preset.addEventListener("change", () => {
      settingsCache.active_api_preset = preset.value;
      settingsCache.api_key = "";
      keyInput.value = "";
      const found = (settingsCache.api_presets || []).find((item) => item.name === preset.value);
      if (!found) {
        settingsCache.api_key_set = false;
        settingsCache.api_key_last4 = "";
        paintStoredKeyNote();
        return;
      }
      settingsCache.api_url = found.api_url || "";
      settingsCache.api_key_set = Boolean(found.api_key_set);
      settingsCache.api_key_last4 = found.api_key_last4 || "";
      settingsCache.model = found.model || "";
      settingsCache.reasoning = Boolean(found.reasoning);
      settingsCache.reasoning_max_tokens = Number(found.reasoning_max_tokens) || 1024;
      url.querySelector("input").value = settingsCache.api_url;
      model.querySelector("input").value = settingsCache.model;
      reasoningBox.querySelector("input").checked = settingsCache.reasoning;
      reasoningLimit.querySelector("input").value = String(settingsCache.reasoning_max_tokens);
      paintStoredKeyNote();
    });
    const showKey = check(t("dialog.show_key"), "show_api_key");
    showKey.querySelector("input").checked = false;
    showKey.querySelector("input").addEventListener("change", (event) => {
      keyInput.type = event.target.checked ? "text" : "password";
    });
    const actions = document.createElement("div");
    actions.className = "row";
    const saveAs = document.createElement("button");
    saveAs.type = "button";
    saveAs.textContent = t("btn.save_as");
    saveAs.addEventListener("click", () => {
      const name = window.prompt(t("dialog.preset_name"));
      if (!name || !name.trim()) return;
      const data = {
        name: name.trim(),
        api_url: settingsCache.api_url || "",
        api_key: settingsCache.api_key || "",
        model: settingsCache.model || "",
        reasoning: Boolean(settingsCache.reasoning),
        reasoning_max_tokens: Number(settingsCache.reasoning_max_tokens) || 1024,
      };
      const list = settingsCache.api_presets || [];
      const index = list.findIndex((item) => item.name === data.name);
      if (index >= 0) list[index] = data;
      else list.push(data);
      settingsCache.api_presets = list;
      settingsCache.active_api_preset = data.name;
      show("ai");
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = t("btn.delete_icon");
    remove.addEventListener("click", () => {
      const name = settingsCache.active_api_preset;
      if (!name) {
        error.textContent = t("dialog.delete_preset_pick");
        return;
      }
      const question = t("dialog.delete_preset_q").replace("{name}", name);
      if (!window.confirm(question)) return;
      settingsCache.api_presets = (settingsCache.api_presets || []).filter((item) => item.name !== name);
      settingsCache.active_api_preset = "";
      error.textContent = "";
      show("ai");
    });
    actions.append(saveAs, remove);
    const presetWrap = document.createElement("label");
    presetWrap.append(document.createTextNode(t("dialog.preset_name")), preset);
    box.append(
      presetWrap,
      actions,
      url,
      key,
      showKey,
      model,
      reasoningBox,
      reasoningLimit,
      field(t("dialog.temperature"), "temperature", { type: "number", min: 0, max: 2, step: 0.1 }),
      field(t("dialog.context_size"), "context_size", { type: "number", min: 4096, max: 131072, step: 4096 }),
    );
    return box;
  }
  function gameFields() {
    const box = document.createElement("div");
    const styleLabel = document.createElement("label");
    styleLabel.textContent = t("dialog.image_style");
    const style = document.createElement("select");
    for (const name of settingsCache.image_styles || []) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = t(`image_style.${name}`);
      style.append(option);
    }
    style.value = settingsCache.image_prompt_style || "";
    style.addEventListener("change", () => { settingsCache.image_prompt_style = style.value; });
    styleLabel.append(style);
    const lookLabel = document.createElement("label");
    lookLabel.textContent = t("dialog.image_look");
    const look = document.createElement("select");
    for (const name of settingsCache.image_looks || []) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = t(`image_look.${name}`);
      look.append(option);
    }
    look.value = settingsCache.image_look || "none";
    look.addEventListener("change", () => { settingsCache.image_look = look.value; });
    lookLabel.append(look);
    function workflowField() {
      const wrap = document.createElement("label");
      wrap.textContent = t("dialog.comfy_workflow");
      const select = document.createElement("select");
      const files = settingsCache.workflows || [];
      const current = settingsCache.comfy_workflow || "";
      const options = !current || files.includes(current) ? files.slice() : [current, ...files];
      if (!options.length) {
        const empty = document.createElement("option");
        empty.value = "";
        empty.textContent = t("dialog.workflow_empty");
        select.append(empty);
      }
      for (const name of options) {
        const option = document.createElement("option");
        option.value = name;
        option.textContent = name;
        select.append(option);
      }
      if ([...select.options].some((option) => option.value === current)) select.value = current;
      select.addEventListener("change", () => { settingsCache.comfy_workflow = select.value; });
      wrap.append(select);
      const hint = document.createElement("p");
      hint.className = "hint";
      hint.textContent = t("dialog.workflow_hint");
      return [wrap, hint];
    }
    function imageGeneratorFields() {
      const backendLabel = document.createElement("label");
      backendLabel.textContent = t("dialog.image_backend");
      const backend = document.createElement("select");
      const names = settingsCache.image_backends || ["off", "comfy", "a1111"];
      for (const name of names) {
        const option = document.createElement("option");
        option.value = name;
        option.textContent = t(`image_backend.${name}`);
        backend.append(option);
      }
      backend.value = names.includes(settingsCache.image_backend) ? settingsCache.image_backend : "off";
      backendLabel.append(backend);
      const comfyBlock = document.createElement("div");
      comfyBlock.append(field(t("dialog.comfy_url"), "comfy_url"), ...workflowField());
      const a1111Block = document.createElement("div");
      a1111Block.append(
        field(t("dialog.a1111_url"), "a1111_url"),
        field(t("dialog.image_width"), "image_width", { type: "number", min: 64, max: 4096, step: 8 }),
        field(t("dialog.image_height"), "image_height", { type: "number", min: 64, max: 4096, step: 8 }),
        field(t("dialog.image_steps"), "image_steps", { type: "number", min: 1, max: 150, step: 1 }),
      );
      const auto = check(t("dialog.image_auto"), "image_auto");
      const sendNegative = check(t("dialog.image_send_negative"), "image_send_negative");
      const test = document.createElement("button");
      test.type = "button";
      test.textContent = t("dialog.image_test");
      const note = document.createElement("p");
      note.className = "hint";
      test.addEventListener("click", async () => {
        note.textContent = "";
        try {
          const result = await api("/api/image/test", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              image_backend: settingsCache.image_backend,
              comfy_url: settingsCache.comfy_url,
              a1111_url: settingsCache.a1111_url,
            }),
          });
          note.className = result && result.ok ? "hint" : "error";
          note.textContent = (result && result.notice) || "";
        } catch (error) {
          note.className = "error";
          note.textContent = actionErrorText(error) || t("scene.image_offline");
        }
      });
      function sync() {
        const selected = settingsCache.image_backend || "off";
        comfyBlock.hidden = selected !== "comfy";
        a1111Block.hidden = selected !== "a1111";
        auto.hidden = selected === "off";
        sendNegative.hidden = selected === "off";
        test.hidden = selected === "off";
        if (selected === "off") note.textContent = "";
      }
      backend.addEventListener("change", () => {
        settingsCache.image_backend = backend.value;
        sync();
      });
      sync();
      return [heading(t("dialog.section_image")), backendLabel, comfyBlock, a1111Block, auto, sendNegative, test, note];
    }
    const imageNodes = imageGeneratorFields();
    const nodes = [
      heading(t("dialog.gen_params")),
      check(t("dialog.stream"), "stream_mode"),
      field(t("dialog.max_tokens"), "max_tokens", { type: "number", min: 1, step: 1 }),
      heading(t("dialog.section_summary")),
      check(t("dialog.auto_summary"), "summary_enabled"),
      field(t("dialog.summary_fill"), "summary_fill_percent", { type: "number", min: 50, max: 95, step: 1 }),
      heading(t("dialog.section_memory")),
      check(t("dialog.memory_bank"), "memory_enabled"),
      choice(t("dialog.memory_every"), "memory_interval", ["3", "5", "10", "15"]),
      choice(t("dialog.memory_top_k"), "memory_top_k", ["3", "5", "7", "10"]),
      styleLabel,
      lookLabel,
      ...imageNodes,
    ];
    if ((settingsCache.play_mode || "sandbox") !== "adventure") {
      nodes.push(
        heading(t("dialog.section_sandbox_mechanics")),
        check(t("dialog.sandbox_d20"), "sandbox_d20"),
        check(t("dialog.sandbox_hero"), "sandbox_hero"),
        check(t("dialog.sandbox_npc"), "sandbox_npc"),
      );
    }
    box.append(...nodes);
    return box;
  }
  function promptFields() {
    const box = document.createElement("div");
    const list = document.createElement("div");
    list.className = "prompt-list";
    const area = document.createElement("textarea");
    area.rows = 12;
    const limitWrap = document.createElement("label");
    limitWrap.textContent = t("dialog.response_limit");
    limitWrap.hidden = true;
    limitWrap.style.display = "none";
    const limitInput = document.createElement("input");
    limitInput.type = "number";
    limitInput.min = "1";
    limitInput.max = "16384";
    limitInput.step = "1";
    limitWrap.append(limitInput);
    const lang = settingsCache.language || "ru";
    settingsCache.prompt_overrides = settingsCache.prompt_overrides || { ru: {}, en: {} };
    settingsCache.response_limits = settingsCache.response_limits || {};
    let selected = null;
    function choose(prompt) {
      selected = prompt;
      area.value = prompt.text;
      list.querySelectorAll("button").forEach((button) => {
        button.setAttribute("aria-pressed", button === prompt.button ? "true" : "false");
      });
      const hasLimit = Number.isFinite(prompt.limit);
      limitWrap.hidden = !hasLimit;
      limitWrap.style.display = hasLimit ? "block" : "none";
      if (!hasLimit) return;
      const stored = settingsCache.response_limits[prompt.key];
      limitInput.value = String(stored != null ? stored : prompt.limit);
    }
    limitInput.addEventListener("input", () => {
      if (!selected || limitWrap.hidden) return;
      const value = Number(limitInput.value);
      if (Number.isFinite(value)) settingsCache.response_limits[selected.key] = value;
    });
    for (const group of settingsCache.prompts || []) {
      const title = document.createElement("p");
      title.textContent = group.title;
      list.append(title);
      for (const prompt of group.prompts) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = prompt.name || prompt.key;
        prompt.button = button;
        button.addEventListener("click", () => choose(prompt));
        list.append(button);
      }
    }
    const first = (settingsCache.prompts || []).flatMap((group) => group.prompts || [])[0];
    if (first) choose(first);
    area.addEventListener("input", () => {
      if (!selected) return;
      selected.text = area.value;
      settingsCache.prompt_overrides[lang] = settingsCache.prompt_overrides[lang] || {};
      settingsCache.prompt_overrides[lang][selected.key] = area.value;
    });
    const reset = document.createElement("button");
    reset.type = "button";
    reset.textContent = t("btn.reset_prompt");
    reset.addEventListener("click", () => {
      if (!selected) return;
      area.value = selected.builtin;
      selected.text = selected.builtin;
      settingsCache.prompt_overrides[lang][selected.key] = "";
    });
    box.append(list, area, limitWrap, reset);
    return box;
  }
}

window.addEventListener("scroll", () => {
  if (!tailReady || loadingOlder || !state || !state.history_from) return;
  if (window.scrollY > 80) return;
  if (document.documentElement.scrollHeight <= window.innerHeight + 80) return;
  loadOlder();
}, { passive: true });

function fitChrome() {
  const viewport = window.visualViewport;
  const keyboard = viewport
    ? Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop)
    : 0;
  document.documentElement.style.setProperty("--keyboard", `${Math.round(keyboard)}px`);
  const topbar = document.querySelector(".topbar");
  if (topbar) document.documentElement.style.setProperty("--topbar-height", `${topbar.offsetHeight}px`);
  const composer = document.querySelector("#composer");
  if (composer) {
    document.documentElement.style.setProperty("--composer-height", `${composer.offsetHeight}px`);
  }
}

fitChrome();
window.addEventListener("resize", fitChrome);
if (window.visualViewport) {
  window.visualViewport.addEventListener("resize", fitChrome);
  window.visualViewport.addEventListener("scroll", fitChrome);
}
actionEl.addEventListener("focus", () => {
  const follow = nearBottom();
  setTimeout(() => {
    fitChrome();
    if (follow) jumpToEnd();
  }, 280);
});

boot();
