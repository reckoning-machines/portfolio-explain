/* app/static/app.js */
/* eslint-disable no-console */

const eventSummaryCache = new Map();        // event_id -> { headline, bullets, tags }
const eventSummaryInflight = new Map();     // event_id -> Promise


const state = {
  ticker: null,
  book: "default",
  caseId: null,

  draft: null, // { id, event_type, status, payload, missing_fields }
  pendingField: null, // string
  missingPrompts: {}, // field -> prompt

  pendingClarify: null, // { question, choices: [{label, action}] }
};

function $(id) {
  const el = document.getElementById(id);
  if (!el) throw new Error(`Missing DOM element id="${id}"`);
  return el;
}

function showError(id, msg) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!msg) {
    el.style.display = "none";
    el.textContent = "";
    return;
  }
  el.style.display = "";
  el.textContent = msg;
}

async function getEventSummaryCached(event) {
  const id = event.id;
  if (!id) return null;

  if (eventSummaryCache.has(id)) return eventSummaryCache.get(id);

  if (eventSummaryInflight.has(id)) return await eventSummaryInflight.get(id);

  const p = (async () => {
    try {
      const out = await llmEventSummary(id);
      eventSummaryCache.set(id, out);
      return out;
    } catch {
      return null;
    } finally {
      eventSummaryInflight.delete(id);
    }
  })();

  eventSummaryInflight.set(id, p);
  return await p;
}

async function apiJson(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(txt || `HTTP ${res.status}`);
  }
  return await res.json();
}

/* -----------------------------
 * API
 * ----------------------------- */


async function ensureCase(ticker, book = "default") {
  // Response shape: { case, created }
  return await apiJson("/api/cases/ensure", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticker, book }),
  });
}

async function fetchEvents(caseId) {
  return await apiJson(`/api/cases/${caseId}/events`);
}

async function createOrReuseDraft(caseId, eventType, seedPayload = {}) {
  return await apiJson(`/api/cases/${caseId}/drafts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      event_type: eventType,
      seed_payload: seedPayload,
      event_ts: new Date().toISOString(),
    }),
  });
}

async function patchDraft(caseId, eventId, payloadPatch) {
  return await apiJson(`/api/cases/${caseId}/events/${eventId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ payload_patch: payloadPatch }),
  });
}

async function finalizeDraft(caseId, eventId) {
  return await apiJson(`/api/cases/${caseId}/events/${eventId}/finalize`, {
    method: "POST",
  });
}

async function llmMissingFieldPrompts(eventType, missingFields) {
  return await apiJson("/api/llm/missing_field_prompts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event_type: eventType, missing_fields: missingFields }),
  });
}

async function llmCoach(eventType, payload) {
  return await apiJson("/api/llm/coach", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event_type: eventType, payload }),
  });
}

async function llmInterpret(payload) {
  return await apiJson("/api/llm/interpret", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/* -----------------------------
 * Rendering
 * ----------------------------- */

function appendMessage(role, text, meta = "") {
  const log = $("chatLog");
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;

  const metaEl = document.createElement("div");
  metaEl.className = "meta";
  const left = document.createElement("div");
  left.textContent = role === "user" ? "You" : role === "coach" ? "Coach" : "System";
  const right = document.createElement("div");
  right.textContent = meta || "";
  metaEl.appendChild(left);
  metaEl.appendChild(right);

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;

  wrap.appendChild(metaEl);
  wrap.appendChild(bubble);
  log.appendChild(wrap);

  log.scrollTop = log.scrollHeight;
  return wrap;
}

function appendClarifyChoices(choices) {
  // Render clickable buttons under the last message.
  const log = $("chatLog");
  const box = document.createElement("div");
  box.className = "msg sys";

  const metaEl = document.createElement("div");
  metaEl.className = "meta";
  const left = document.createElement("div");
  left.textContent = "System";
  const right = document.createElement("div");
  right.textContent = "clarify";
  metaEl.appendChild(left);
  metaEl.appendChild(right);

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  const row = document.createElement("div");
  row.style.display = "flex";
  row.style.gap = "8px";
  row.style.flexWrap = "wrap";

  for (const ch of choices) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn-secondary";
    btn.textContent = ch.label;
    btn.onclick = async () => {
      try {
        await executeAction(ch.action);
        state.pendingClarify = null;
      } catch (err) {
        appendMessage("sys", `Error: ${String(err.message || err)}`);
      }
    };
    row.appendChild(btn);
  }

  bubble.appendChild(row);
  box.appendChild(metaEl);
  box.appendChild(bubble);
  log.appendChild(box);
  log.scrollTop = log.scrollHeight;
}

function summarizeEvent(e) {
  const t = e.event_type;
  const p = e.payload || {};

  if (t === "INITIATE") return (p.entry_thesis || "").slice(0, 160);
  if (t === "THESIS_UPDATE") return (p.update_summary || "").slice(0, 160);
  if (t === "RISK_NOTE") return `${p.severity || ""} ${p.risk_type || ""} ${(p.note || "").slice(0, 120)}`.trim();
  if (t === "RESIZE") return `${p.from_pct ?? ""} → ${p.to_pct ?? ""} ${p.reason || ""} ${(p.rationale || "").slice(0, 120)}`.trim();
  if (t === "TICKER_RULE") return `rule: ${(p.rule_text || "").slice(0, 160)}`.trim();
  if (t === "POST_MORTEM") return `post-mortem: ${(p.primary_reason || "").slice(0, 120)}`.trim();
  return "";
}

function renderCases(cases) {
  const list = $("caseList");
  list.innerHTML = "";

  const sorted = [...cases].sort((a, b) => String(b.opened_at || "").localeCompare(String(a.opened_at || "")));

  for (const c of sorted) {
    const li = document.createElement("li");

    const title = document.createElement("div");
    title.className = "case-title";
    title.textContent = c.ticker || "—";

    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = c.status || "—";
    title.appendChild(badge);

    const sub = document.createElement("div");
    sub.className = "muted small";
    const opened = c.opened_at ? String(c.opened_at).slice(0, 19).replace("T", " ") : "";
    sub.textContent = `${c.book || "default"}${opened ? " • " + opened : ""}`;

    li.appendChild(title);
    li.appendChild(sub);

    li.onclick = async () => {
      await setContextByCase(c);
    };

    list.appendChild(li);
  }
}

function setContextLine() {
  const line = $("contextLine");
  if (!state.ticker || !state.caseId) {
    line.textContent = "No ticker selected.";
    return;
  }
  line.textContent = `Context: ${state.ticker} • case ${state.caseId}`;
}

function updateRightState() {
  $("stateTicker").textContent = state.ticker || "—";
  $("stateCase").textContent = state.caseId ? String(state.caseId).slice(0, 8) : "—";

  if (!state.draft) {
    $("stateDraft").textContent = "—";
    $("stateNext").textContent = "—";
    return;
  }

  $("stateDraft").textContent = `${state.draft.event_type} (${state.draft.status})`;
  const next = (state.draft.missing_fields || [])[0] || "—";
  $("stateNext").textContent = state.pendingField || next || "—";
}

async function renderMiniTimeline() {
  const ul = $("miniTimeline");
  ul.innerHTML = "";
  if (!state.caseId) return;

  const events = await fetchEvents(state.caseId);
  const last = events.slice(-10).reverse();

  for (const e of last) {
    const li = document.createElement("li");

    const ts = String(e.event_ts || "").slice(0, 19).replace("T", " ");
    const top = document.createElement("div");
    top.innerHTML = `<span class="muted">${ts}</span> • <b>${e.event_type}</b>`;

    const body = document.createElement("div");
    body.className = "muted";

    const sum = await getEventSummaryCached(e);
    if (sum && sum.headline) {
      body.textContent = sum.headline;
    } else {
      body.textContent = summarizeEvent(e);
    }

    li.appendChild(top);
    li.appendChild(body);
    ul.appendChild(li);
  }
}


/* -----------------------------
 * Deterministic parsing helpers
 * ----------------------------- */

const TICKER_RE = /^[A-Z][A-Z0-9]{0,5}(\.[A-Z])?$/;

function isUpperTicker(t) {
  return TICKER_RE.test(String(t || "").trim());
}

function normalizeUpperTickerStrict(t) {
  const s = String(t || "").trim();
  if (!isUpperTicker(s)) return null;
  return s;
}

function parseCommand(lineRaw) {
  const line = String(lineRaw || "").trim();
  const low = line.toLowerCase();

  // deterministic utility commands
  if (low === "events") return { kind: "events" };
  if (low === "draft") return { kind: "draft" };
  if (low === "finalize") return { kind: "finalize" };
  if (low === "close") return { kind: "close" };

  // ticker ABC (strict: ABC must already be uppercase)
  const mTicker = line.match(/^ticker\s+(\S+)\s*$/);
  if (mTicker) {
    const t = normalizeUpperTickerStrict(mTicker[1]);
    if (!t) return { kind: "unknown", text: line };
    return { kind: "ticker", ticker: t };
  }

  // long ABC / short ABC (strict uppercase)
  const mDir = line.match(/^(long|short)\s+(\S+)\s*$/i);
  if (mDir) {
    const t = normalizeUpperTickerStrict(mDir[2]);
    if (!t) return { kind: "unknown", text: line };
    return { kind: "initiate", direction: mDir[1].toUpperCase(), ticker: t };
  }

  // event starters
  const starters = [
    ["update:", "THESIS_UPDATE"],
    ["risk:", "RISK_NOTE"],
    ["size:", "RESIZE"],
    ["rule:", "TICKER_RULE"],
    ["post:", "POST_MORTEM"],
  ];
  for (const [prefix, eventType] of starters) {
    if (low.startsWith(prefix)) {
      const rest = line.slice(prefix.length).trim();
      return { kind: "start_event", eventType, text: rest };
    }
  }

  return { kind: "unknown", text: line };
}

function extractAllowedTickersFromText(text) {
  const re = /\b[A-Z][A-Z0-9]{0,5}(?:\.[A-Z])?\b/g;
  const found = String(text || "").match(re) || [];
  const out = [];
  const seen = new Set();
  for (const t of found) {
    if (!seen.has(t)) {
      seen.add(t);
      out.push(t);
    }
  }
  return out;
}

/* -----------------------------
 * Draft flow
 * ----------------------------- */

function fieldHint(field) {
  const map = {
    direction: "Direction (LONG/SHORT)?",
    horizon_days: "Horizon in days?",
    entry_thesis: "Entry thesis (1–3 sentences)?",
    key_drivers: "Key drivers (comma-separated)?",
    key_risks: "Key risks (comma-separated)?",
    invalidation_triggers: "Invalidation triggers (comma-separated)?",
    conviction: "Conviction (0–100)?",
    position_intent_pct: "Position intent % (number or blank)?",
  };
  return map[field] || `Provide ${field}`;
}

function splitCsv(s) {
  return String(s || "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

function parseScalarMaybeNumber(s) {
  const v = String(s ?? "").trim();
  if (v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : v;
}

async function fetchCasesOpenRecent(limit = 100) {
  return await apiJson(`/api/cases?status=OPEN&limit=${encodeURIComponent(limit)}`);
}

async function closeCase(caseId) {
  return await apiJson(`/api/cases/${caseId}/close`, { method: "POST" });
}

async function llmEventSummary(eventId) {
  return await apiJson("/api/llm/event_summary", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event_id: eventId }),
  });
}


async function setContextTicker(ticker) {
  eventSummaryCache.clear();
  eventSummaryInflight.clear();

  const resp = await ensureCase(ticker, state.book);
  const c = resp.case;

  state.ticker = c.ticker;
  state.caseId = c.id;
  state.draft = null;
  state.pendingField = null;
  state.missingPrompts = {};
  state.pendingClarify = null;

  setContextLine();
  updateRightState();
  $("showEventsBtn").disabled = false;
  $("resetDraftBtn").disabled = false;

  if (resp.created) {
    appendMessage("sys", `Created new case for ${state.ticker} (first time seen in this database).`);
  } else {
    appendMessage("sys", `Context set to ${state.ticker}.`);
  }

  await renderMiniTimeline();
}

async function setContextByCase(c) {
  eventSummaryCache.clear();
  eventSummaryInflight.clear();

  state.ticker = c.ticker;
  state.caseId = c.id;
  state.draft = null;
  state.pendingField = null;
  state.missingPrompts = {};
  state.pendingClarify = null;

  setContextLine();
  updateRightState();
  $("showEventsBtn").disabled = false;
  $("resetDraftBtn").disabled = false;
  appendMessage("sys", `Context set to ${state.ticker}.`);
  await renderMiniTimeline();
}

async function startEventDraft(eventType, seedPayload = {}) {
  if (!state.caseId) throw new Error("No case selected. Use: ticker AAPL");
  const resp = await createOrReuseDraft(state.caseId, eventType, seedPayload);
  state.draft = resp.event;
  state.draft.missing_fields = resp.missing_fields || [];
  state.pendingField = null;
  state.pendingClarify = null;
  updateRightState();

  // prompts best-effort
  if (state.draft.missing_fields.length > 0) {
    try {
      const out = await llmMissingFieldPrompts(state.draft.event_type, state.draft.missing_fields);
      const prompts = out.prompts || [];
      state.missingPrompts = {};
      for (const p of prompts) state.missingPrompts[p.field] = p.prompt;
    } catch {
      state.missingPrompts = {};
    }
  }

  askNextQuestionIfNeeded();
}

function askNextQuestionIfNeeded() {
  if (!state.draft) return;

  const missing = state.draft.missing_fields || [];
  if (missing.length === 0) {
    state.pendingField = null;
    updateRightState();
    appendMessage("sys", `Draft ${state.draft.event_type} is complete. Type "finalize" to save.`);
    return;
  }

  const next = missing[0];
  state.pendingField = next;
  updateRightState();

  const prompt = state.missingPrompts[next] || fieldHint(next);
  appendMessage("sys", prompt);
}

async function applyAnswerToPendingField(answerText) {
  if (!state.caseId || !state.draft || !state.pendingField) {
    appendMessage("sys", "No active question. Start with: ticker AAPL, then update:/risk:/size:/rule:/post:");
    return;
  }

  const f = state.pendingField;
  const patch = {};

  if (["key_drivers", "key_risks", "invalidation_triggers", "tags", "rule_violations"].includes(f)) {
    patch[f] = splitCsv(answerText);
  } else if (["horizon_days", "conviction", "conviction_delta"].includes(f)) {
    patch[f] = Number(String(answerText).trim());
  } else if (["position_intent_pct", "from_pct", "to_pct", "confidence"].includes(f)) {
    patch[f] = parseScalarMaybeNumber(answerText);
  } else if (f === "due_by") {
    const v = String(answerText || "").trim();
    patch[f] = v === "" ? null : v;
  } else if (f === "lesson") {
    const v = String(answerText || "").trim();
    patch[f] = v === "" ? null : v;
  } else {
    patch[f] = answerText;
  }

  const resp = await patchDraft(state.caseId, state.draft.id, patch);
  state.draft = resp.event;
  state.draft.missing_fields = resp.missing_fields || [];
  state.pendingField = null;
  updateRightState();

  // coach best-effort
  try {
    const coach = await llmCoach(state.draft.event_type, state.draft.payload || {});
    const qs = (coach.questions || []).slice(0, 2);
    const checks = (coach.checks || []).slice(0, 2);
    const warns = (coach.warnings || []).slice(0, 1);
    const lines = [];
    for (const q of qs) lines.push(`Q: ${q}`);
    for (const c of checks) lines.push(`Check: ${c}`);
    for (const w of warns) lines.push(`Note: ${w}`);
    if (lines.length > 0) appendMessage("coach", lines.join("\n"));
  } catch {
    // ignore
  }

  if ((state.draft.missing_fields || []).length === 0) {
    appendMessage("sys", `Draft ${state.draft.event_type} complete. Type "finalize" to save.`);
  } else {
    // refresh prompts best-effort
    try {
      const out = await llmMissingFieldPrompts(state.draft.event_type, state.draft.missing_fields);
      const prompts = out.prompts || [];
      state.missingPrompts = {};
      for (const p of prompts) state.missingPrompts[p.field] = p.prompt;
    } catch {
      state.missingPrompts = {};
    }
    askNextQuestionIfNeeded();
  }
}

async function doFinalize() {
  if (!state.caseId || !state.draft) {
    appendMessage("sys", "No draft to finalize.");
    return;
  }
  const missing = state.draft.missing_fields || [];
  if (missing.length > 0) {
    appendMessage("sys", `Cannot finalize. Missing: ${missing.join(", ")}`);
    askNextQuestionIfNeeded();
    return;
  }

  await finalizeDraft(state.caseId, state.draft.id);
  appendMessage("sys", `Finalized ${state.draft.event_type}.`);
  state.draft = null;
  state.pendingField = null;
  state.missingPrompts = {};
  updateRightState();
  await renderMiniTimeline();
}

async function showEventsInChat() {
  if (!state.caseId) {
    appendMessage("sys", "No ticker selected.");
    return;
  }
  const events = await fetchEvents(state.caseId);
  if (!events || events.length === 0) {
    appendMessage("sys", "No FINAL events yet.");
    return;
  }
  const lines = [];
  for (const e of events.slice(-15)) {
    const ts = String(e.event_ts || "").slice(0, 19).replace("T", " ");
    const sum = await getEventSummaryCached(e);
    const text = sum && sum.headline ? sum.headline : summarizeEvent(e);
    lines.push(`${ts} • ${e.event_type} • ${text}`);
  }
  appendMessage("sys", lines.join("\n"));
}

function clearDraft() {
  state.draft = null;
  state.pendingField = null;
  state.missingPrompts = {};
  state.pendingClarify = null;
  updateRightState();
  appendMessage("sys", "Draft cleared.");
}

/* -----------------------------
 * Interpret execution
 * ----------------------------- */

async function executeAction(action) {
  const t = action.type;

  if (t === "CANCEL") {
    state.pendingClarify = null;
    appendMessage("sys", "Canceled.");
    return;
  }

  if (t === "SHOW_EVENTS") {
    return await showEventsInChat();
  }

  if (t === "SHOW_DRAFT") {
    if (!state.draft) return appendMessage("sys", "No active draft.");
    return appendMessage("sys", JSON.stringify({ event_type: state.draft.event_type, payload: state.draft.payload, missing_fields: state.draft.missing_fields }, null, 2));
  }

  if (t === "FINALIZE_DRAFT") {
    return await doFinalize();
  }

  if (t === "SET_CONTEXT") {
    if (!action.ticker || !isUpperTicker(action.ticker)) {
      appendMessage("sys", "Ticker must be uppercase (e.g., AAPL).");
      return;
    }
    return await setContextTicker(action.ticker);
  }

  if (t === "START_EVENT") {
    if (!action.event_type) {
      appendMessage("sys", "Missing event_type.");
      return;
    }
    if (!state.caseId) {
      appendMessage("sys", "No ticker selected. Use: ticker AAPL");
      return;
    }
    const seed = action.seed_payload || {};
    return await startEventDraft(action.event_type, seed);
  }

  if (t === "ANSWER_FIELD") {
    // We only allow answers to pendingField (gated server-side). Execute as normal.
    if (!action.field || !action.answer_text) {
      appendMessage("sys", "Missing answer.");
      return;
    }
    // If it matches pendingField, route through normal patch path.
    if (state.pendingField && action.field === state.pendingField) {
      return await applyAnswerToPendingField(action.answer_text);
    }
    appendMessage("sys", "No matching question is pending.");
    return;
  }

  appendMessage("sys", `Unsupported action: ${t}`);
}

async function interpretAndHandleFreeText(text) {
  const allowed_tickers = extractAllowedTickersFromText(text);

  const payload = {
    text,
    allowed_tickers,
    context: { ticker: state.ticker, case_id: state.caseId },
    draft: {
      event_type: state.draft ? state.draft.event_type : null,
      pending_field: state.pendingField,
      missing_fields: state.draft ? (state.draft.missing_fields || []) : null,
    },
  };

  const out = await llmInterpret(payload);

  if (out.mode === "NOOP") {
    appendMessage("sys", out.message || "I couldn't interpret that. Use uppercase tickers and commands like: ticker AAPL, update:, risk:.");
    return;
  }

  if (out.mode === "CLARIFY") {
    state.pendingClarify = out.clarify;
    appendMessage("sys", out.clarify.question);
    appendClarifyChoices(out.clarify.choices);
    return;
  }

  if (out.mode === "EXECUTE") {
    return await executeAction(out.action);
  }

  appendMessage("sys", "I couldn't interpret that. Use the commands in the right panel.");
}

/* -----------------------------
 * Boot + wiring
 * ----------------------------- */

async function loadRail() {
  showError("railError", null);
  const cases = await fetchCasesOpenRecent(150);
  renderCases(cases);
}

function wireUI() {
  $("quickSwitchForm").onsubmit = async (e) => {
    e.preventDefault();
    showError("railError", null);

    const raw = $("quickSwitchInput").value.trim();
    if (!isUpperTicker(raw)) {
      showError("railError", "Ticker must be uppercase (e.g., AAPL). Company names are not supported.");
      return;
    }

    try {
      await setContextTicker(raw);
      $("quickSwitchInput").value = "";
    } catch (err) {
      showError("railError", String(err.message || err));
    }
  };

  $("refreshCasesBtn").onclick = async () => {
    try {
      await loadRail();
    } catch (err) {
      showError("railError", String(err.message || err));
    }
  };

  $("showEventsBtn").onclick = async () => {
    try {
      await showEventsInChat();
    } catch (err) {
      showError("chatError", String(err.message || err));
    }
  };

  $("resetDraftBtn").onclick = () => clearDraft();

  $("chatForm").onsubmit = async (e) => {
    e.preventDefault();
    showError("chatError", null);

    const input = $("chatInput");
    const text = String(input.value || "").trim();
    if (!text) return;

    appendMessage("user", text);
    input.value = "";

    try {
      // If we are awaiting clarification, user should click buttons; still allow typing "1/2" later if desired.
      if (state.pendingClarify) {
        appendMessage("sys", "Please click one of the clarification options.");
        return;
      }

      // If a draft field is pending, treat input as the answer (deterministic).
      if (state.draft && state.pendingField) {
        return await applyAnswerToPendingField(text);
      }

      // deterministic command parsing
      const cmd = parseCommand(text);

      if (cmd.kind === "events") return await showEventsInChat();
      if (cmd.kind === "draft") {
        if (!state.draft) appendMessage("sys", "No active draft.");
        else appendMessage("sys", JSON.stringify({ event_type: state.draft.event_type, payload: state.draft.payload, missing_fields: state.draft.missing_fields }, null, 2));
        return;
      }
      if (cmd.kind === "finalize") return await doFinalize();

      if (cmd.kind === "ticker") return await setContextTicker(cmd.ticker);

      if (cmd.kind === "initiate") {
        await setContextTicker(cmd.ticker);
        return await startEventDraft("INITIATE", { direction: cmd.direction });
      }
      if (cmd.kind === "close") {
        if (!state.caseId) {
          appendMessage("sys", "No ticker selected.");
          return;
        }
        clearDraft();
        const closed = await closeCase(state.caseId);
        appendMessage("sys", `Closed case for ${closed.ticker}.`);
        await loadRail();
        await renderMiniTimeline();
        return;
      }


      if (cmd.kind === "start_event") {
        if (!state.caseId) {
          appendMessage("sys", "No ticker selected. Use: ticker AAPL");
          return;
        }
        const seed = {};
        if (cmd.eventType === "THESIS_UPDATE" && cmd.text) seed.update_summary = cmd.text;
        if (cmd.eventType === "RISK_NOTE" && cmd.text) seed.note = cmd.text;
        if (cmd.eventType === "RESIZE" && cmd.text) seed.rationale = cmd.text;
        if (cmd.eventType === "TICKER_RULE" && cmd.text) seed.rule_text = cmd.text;
        if (cmd.eventType === "POST_MORTEM" && cmd.text) seed.lesson = cmd.text;
        return await startEventDraft(cmd.eventType, seed);
      }

      // Unknown: call interpret
      return await interpretAndHandleFreeText(cmd.text);
    } catch (err) {
      showError("chatError", String(err.message || err));
      appendMessage("sys", `Error: ${String(err.message || err)}`);
    } finally {
      try {
        await loadRail();
      } catch {
        // ignore
      }
    }
  };
}

window.onload = async () => {
  wireUI();
  await loadRail();
  setContextLine();
  updateRightState();
  appendMessage("sys", "Type: ticker AAPL, long AAPL, update:, risk:, size:, rule:, post:. If you type free text, the interpreter will ask clarifying questions.");
};
