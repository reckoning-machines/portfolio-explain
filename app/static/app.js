let currentCaseId = null;

function splitCsv(val) {
  return String(val || '')
    .split(',')
    .map(s => s.trim())
    .filter(Boolean);
}

function parseOptionalNumber(val) {
  const s = String(val ?? '').trim();
  if (s === '') return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

function showError(elId, msg) {
  const el = document.getElementById(elId);
  if (!el) return;
  if (!msg) {
    el.style.display = 'none';
    el.textContent = '';
    return;
  }
  el.style.display = '';
  el.textContent = msg;
}

function isoFromDatetimeLocal(value) {
  // value like "2025-12-27T08:30"
  // Interpret as local time; convert to ISO string.
  if (!value) return new Date().toISOString();
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return new Date().toISOString();
  return d.toISOString();
}

async function apiJson(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(txt || `HTTP ${res.status}`);
  }
  return await res.json();
}

async function loadCases() {
  showError('caseCreateError', null);

  const cases = await apiJson('/api/cases');
  const caseList = document.getElementById('caseList');
  caseList.innerHTML = '';

  cases.forEach(c => {
    const li = document.createElement('li');
    li.textContent = `${c.ticker} [${c.status}]`;
    li.onclick = () => selectCase(c.id);
    caseList.appendChild(li);
  });
}

async function selectCase(caseId) {
  currentCaseId = caseId;

  document.getElementById('caseDetailSection').style.display = '';
  document.getElementById('rightPanel').style.display = '';

  const c = await apiJson(`/api/cases/${caseId}`);
  document.getElementById('caseHeader').textContent = `${c.ticker} • ${c.status}${c.book ? ` • ${c.book}` : ''}`;

  await loadEvents(caseId);

  // default timestamps for event + thesis compile
  const now = new Date();
  const dtLocal = new Date(now.getTime() - now.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
  document.getElementById('eventTsInput').value = dtLocal;
  document.getElementById('thesisAsofInput').value = dtLocal;
}

function summarizeEvent(e) {
  // Keep this deliberately simple for MVP.
  const t = e.event_type;
  const p = e.payload || {};
  if (t === 'INITIATE') return p.entry_thesis || '';
  if (t === 'THESIS_UPDATE') return p.update_summary || '';
  if (t === 'RISK_NOTE') return `${p.severity || ''} ${p.risk_type || ''} ${p.note || ''}`.trim();
  if (t === 'RESIZE') return `${p.from_pct ?? ''} → ${p.to_pct ?? ''} ${p.reason || ''} ${p.rationale || ''}`.trim();
  return '';
}

async function loadEvents(caseId) {
  showError('eventsError', null);

  const events = await apiJson(`/api/cases/${caseId}/events`);
  const tbody = document.getElementById('eventTableBody');
  tbody.innerHTML = '';

  events.forEach(e => {
    const tr = document.createElement('tr');

    const tdTs = document.createElement('td');
    tdTs.textContent = e.event_ts ? String(e.event_ts) : '';
    tr.appendChild(tdTs);

    const tdType = document.createElement('td');
    tdType.textContent = e.event_type;
    tr.appendChild(tdType);

    const tdSum = document.createElement('td');
    tdSum.textContent = summarizeEvent(e);
    tr.appendChild(tdSum);

    tbody.appendChild(tr);
  });
}

async function postEvent(event) {
  if (!currentCaseId) throw new Error('Select a case first.');
  await apiJson(`/api/cases/${currentCaseId}/events`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(event)
  });
}

function setActiveForm(eventType) {
  const map = {
    INITIATE: 'formInitiate',
    THESIS_UPDATE: 'formThesisUpdate',
    RISK_NOTE: 'formRiskNote',
    RESIZE: 'formResize'
  };
  Object.values(map).forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });
  const activeId = map[eventType] || 'formInitiate';
  const active = document.getElementById(activeId);
  if (active) active.style.display = '';
}

function buildPayloadForType(eventType) {
  if (eventType === 'INITIATE') {
    return {
      direction: document.getElementById('initDirection').value,
      horizon_days: Number(document.getElementById('initHorizonDays').value),
      entry_thesis: document.getElementById('initEntryThesis').value,
      key_drivers: splitCsv(document.getElementById('initKeyDrivers').value),
      key_risks: splitCsv(document.getElementById('initKeyRisks').value),
      invalidation_triggers: splitCsv(document.getElementById('initInvalidationTriggers').value),
      conviction: Number(document.getElementById('initConviction').value),
      position_intent_pct: parseOptionalNumber(document.getElementById('initPositionIntentPct').value)
    };
  }

  if (eventType === 'THESIS_UPDATE') {
    return {
      what_changed: document.getElementById('tuWhatChanged').value,
      update_summary: document.getElementById('tuSummary').value,
      drivers_delta: {
        add: splitCsv(document.getElementById('tuDriversAdd').value),
        remove: splitCsv(document.getElementById('tuDriversRemove').value)
      },
      risks_delta: {
        add: splitCsv(document.getElementById('tuRisksAdd').value),
        remove: splitCsv(document.getElementById('tuRisksRemove').value)
      },
      triggers_delta: {
        add: splitCsv(document.getElementById('tuTriggersAdd').value),
        remove: splitCsv(document.getElementById('tuTriggersRemove').value)
      },
      conviction_delta: Number(document.getElementById('tuConvictionDelta').value),
      confidence: Number(document.getElementById('tuConfidence').value)
    };
  }

  if (eventType === 'RISK_NOTE') {
    const due = document.getElementById('rnDueBy').value;
    return {
      risk_type: document.getElementById('rnRiskType').value,
      severity: document.getElementById('rnSeverity').value,
      note: document.getElementById('rnNote').value,
      action: document.getElementById('rnAction').value,
      due_by: due && String(due).trim() !== '' ? due : null
    };
  }

  if (eventType === 'RESIZE') {
    return {
      from_pct: parseOptionalNumber(document.getElementById('rsFromPct').value),
      to_pct: Number(document.getElementById('rsToPct').value),
      reason: document.getElementById('rsReason').value,
      rationale: document.getElementById('rsRationale').value,
      constraints: {
        adv_cap_binding: !!document.getElementById('rsAdvBinding').checked,
        gross_cap_binding: !!document.getElementById('rsGrossBinding').checked,
        net_cap_binding: !!document.getElementById('rsNetBinding').checked
      }
    };
  }

  return {};
}

function updatePayloadPreview() {
  const eventType = document.getElementById('eventTypeSelect').value;
  const payload = buildPayloadForType(eventType);
  document.getElementById('payloadPreview').value = JSON.stringify(payload, null, 2);
}

function wireEventForm() {
  const eventTypeSelect = document.getElementById('eventTypeSelect');
  eventTypeSelect.addEventListener('change', () => {
    setActiveForm(eventTypeSelect.value);
    updatePayloadPreview();
  });

  // Update payload preview on any input changes inside the form
  document.getElementById('eventForm').addEventListener('input', () => {
    updatePayloadPreview();
  });

  document.getElementById('eventForm').onsubmit = async (e) => {
    e.preventDefault();
    showError('eventSubmitError', null);

    try {
      const eventType = document.getElementById('eventTypeSelect').value;
      const eventTs = isoFromDatetimeLocal(document.getElementById('eventTsInput').value);
      const payload = buildPayloadForType(eventType);

      const event = {
        event_type: eventType,
        event_ts: eventTs,
        payload
      };

      await postEvent(event);
      await loadEvents(currentCaseId);

      // Do not reset timestamps; reset only the active form fields
      // Simple approach: reset full form, then re-apply type + timestamps
      const keepType = eventTypeSelect.value;
      const keepTs = document.getElementById('eventTsInput').value;

      e.target.reset();

      eventTypeSelect.value = keepType;
      document.getElementById('eventTsInput').value = keepTs;

      setActiveForm(keepType);
      updatePayloadPreview();
    } catch (err) {
      showError('eventSubmitError', err.message);
    }
  };

  // initial state
  setActiveForm(eventTypeSelect.value);
  updatePayloadPreview();
}

function wireCreateCaseForm() {
  document.getElementById('createCaseForm').onsubmit = async (e) => {
    e.preventDefault();
    showError('caseCreateError', null);

    const ticker = document.getElementById('tickerInput').value.trim();
    if (!ticker) {
      showError('caseCreateError', 'Ticker is required.');
      return;
    }

    try {
      await apiJson('/api/cases', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker })
      });

      document.getElementById('tickerInput').value = '';
      await loadCases();
    } catch (err) {
      showError('caseCreateError', err.message);
    }
  };
}

function wireCompileThesis() {
  document.getElementById('compileThesisForm').onsubmit = async (e) => {
    e.preventDefault();
    showError('compileError', null);

    if (!currentCaseId) {
      showError('compileError', 'Select a case first.');
      return;
    }

    const asofIso = isoFromDatetimeLocal(document.getElementById('thesisAsofInput').value);

    try {
      const snapshot = await apiJson(
        `/api/cases/${currentCaseId}/thesis/compile?asof=${encodeURIComponent(asofIso)}`,
        { method: 'POST' }
      );

      document.getElementById('snapshotBox').style.display = '';
      document.getElementById('snapshotMeta').textContent = `as-of ${asofIso}`;
      document.getElementById('snapshotJson').textContent = JSON.stringify(snapshot, null, 2);
      document.getElementById('snapshotNarrative').textContent = snapshot.narrative || '';
    } catch (err) {
      showError('compileError', err.message);
    }
  };
}

window.onload = async () => {
  wireCreateCaseForm();
  wireEventForm();
  wireCompileThesis();
  await loadCases();
};
