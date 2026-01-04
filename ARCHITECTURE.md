# Architecture — PM Decision OS (Investor Demo MVP)

PM Decision OS is an investor-demo MVP for **portfolio judgment consistency**: a “chat-with-yourself” console that records structured portfolio decision events and produces deterministic derived artifacts (replay, diffs, pattern counts). It is **not** a recommendation engine. The system may use LLMs for *interaction quality* (command interpretation, prompts, summaries, consistency questions), but the **system of record** is always deterministic and audit-grade.

---

## 1. Product scope and non-goals

### 1.1 Goals
- Provide a **ticker-scoped chat console** for recording portfolio decision events.
- Maintain **append-only, immutable FINAL events** that form an audit-grade journal.
- Support **drafting** (partial, editable records) so the chat can update continuously without producing incomplete history.
- Produce **deterministic** derived artifacts:
  - timelines (replay)
  - structured diffs across snapshots
  - pattern recognition summaries (counts, frequencies, sequences)
- Integrate market data as a **facts layer** (prices, returns, basic vol metrics).

### 1.2 Non-goals (explicit)
- No trade recommendations.
- No forecasting.
- No causal explanations (unless explicitly user-authored).
- No “AI-generated thesis” that invents content.
- No complex rule engine. “Ticker rules” are pinned notes, not executable logic.

---

## 2. Stack

### 2.1 Backend
- Python + FastAPI
- PostgreSQL (AWS RDS planned)
- SQLAlchemy ORM + Alembic migrations
- `.env` config loaded via `python-dotenv`
- Ubuntu on AWS EC2 planned

### 2.2 Frontend
- Vanilla HTML/JS
- Dark-mode, ChatGPT-like layout:
  - Left rail: tickers/cases (like “project / chat history”)
  - Center: chat transcript + single input
  - Right rail: command cheatsheet + state + mini timeline
- Served by FastAPI `StaticFiles`

### 2.3 LLM usage (OpenAI API)
- LLMs are used for **bounded assistance**:
  - interpret natural language into a small set of allowed actions
  - generate friendly prompts for missing fields
  - produce concise event summaries for readability
  - ask consistency-check questions (not advice)
- LLM outputs are **non-authoritative** and never directly write FINAL events.

---

## 3. Core domain model

### 3.1 TradeCase (episode)
A case is a **trade episode** for a ticker:
- A ticker can have multiple cases over time (episodes).
- A case is OPEN until closed; “long-running memory” across cases is derived later.

Table: `trade_cases`
- `id` UUID PK
- `ticker` TEXT
- `book` TEXT (default `default`)
- `status` TEXT (`OPEN`/`CLOSED`)
- `opened_at` TIMESTAMPTZ (default `now()`)
- `closed_at` TIMESTAMPTZ nullable
- `created_at` TIMESTAMPTZ (default `now()`)

### 3.2 DecisionEvent (append-only journal entry)
Each case has an append-only stream of decision events.

Key property: **FINAL events are immutable**.

Table: `decision_events`
- `id` UUID PK
- `case_id` UUID FK → `trade_cases.id` (ON DELETE CASCADE)
- `event_ts` TIMESTAMPTZ (the “as-of” time for the event)
- `event_type` TEXT
- `payload` JSONB
- `status` TEXT (`DRAFT` or `FINAL`, default `FINAL`)
- `updated_at` TIMESTAMPTZ (default `now()`)
- `created_at` TIMESTAMPTZ (default `now()`)

Indexes:
- `ix_decision_events_case_id`
- `ix_decision_events_event_ts`
- `ix_decision_events_case_id_event_ts`
- `ix_decision_events_case_type_status` on `(case_id, event_type, status)`

### 3.3 ThesisSnapshot (deterministic compiled state)
Snapshots are deterministic transforms of FINAL events (no invented content).

Table: `thesis_snapshots`
- `id` UUID PK
- `case_id` UUID FK → `trade_cases.id` (ON DELETE CASCADE)
- `asof_ts` TIMESTAMPTZ
- `compiled_json` JSONB
- `narrative` TEXT nullable (may be empty or LLM-formatted, but must remain grounded)
- `model` TEXT nullable (optional provenance)
- `created_at` TIMESTAMPTZ default now()

Indexes:
- `ix_thesis_snapshots_case_id`
- `ix_thesis_snapshots_asof_ts`
- `ix_thesis_snapshots_case_id_asof_ts`

### 3.4 Market facts
Market prices (facts layer) are ingested from Yahoo via `yfinance` into:
- `market_prices_daily` (planned/implemented in market routes)

These facts are used for deterministic calculations (returns, vol metrics) and context, not forecasting.

---

## 4. Event types and strict validation

Events are validated strictly at FINALIZE time. Drafts may be partial.

Allowed `event_type`:
- `INITIATE`
- `THESIS_UPDATE`
- `RISK_NOTE`
- `RESIZE`
- `TICKER_RULE`
- `POST_MORTEM`

Validation policy:
- Draft payloads can be incomplete.
- Final payloads must match strict schema (types, enums, required keys).
- Unknown keys are discouraged; strictness can be increased over time.

### 4.1 INITIATE
Required keys:
- `direction` (`LONG`/`SHORT`)
- `horizon_days` int
- `entry_thesis` str
- `key_drivers` list[str]
- `key_risks` list[str]
- `invalidation_triggers` list[str]
- `conviction` int (0..100)
- `position_intent_pct` number|null

### 4.2 THESIS_UPDATE
Required keys:
- `what_changed` enum
- `update_summary` str
- `drivers_delta` object `{add: list[str], remove: list[str]}`
- `risks_delta` object `{add: list[str], remove: list[str]}`
- `triggers_delta` object `{add: list[str], remove: list[str]}`
- `conviction_delta` int (-20..20)
- `confidence` number (0..1)

### 4.3 RISK_NOTE
Required keys:
- `risk_type` enum
- `severity` enum
- `note` str
- `action` enum
- `due_by` YYYY-MM-DD string|null

### 4.4 RESIZE
Required keys:
- `from_pct` number|null
- `to_pct` number
- `reason` enum
- `rationale` str
- `constraints` object with boolean flags:
  - `adv_cap_binding`
  - `gross_cap_binding`
  - `net_cap_binding`

### 4.5 TICKER_RULE
Required keys:
- `ticker` str (uppercase expected)
- `rule_text` str
- `tags` list[str]
- `status` enum (`ACTIVE`/`INACTIVE`)

Note: Ticker rules are pinned notes; they are not executable constraints.

### 4.6 POST_MORTEM
Required keys:
- `outcome` enum
- `thesis_outcome` enum
- `process_adherence` enum
- `primary_reason` enum
- `what_worked` str
- `what_failed` str
- `rule_violations` list[str]
- `lesson` str|null

---

## 5. Drafts and FINALIZE semantics (“Finalize is commit”)

Drafting exists to support chat-based progressive entry while preserving an audit-grade timeline.

### 5.1 Draft definition
A draft is a `DecisionEvent` row with:
- `status = DRAFT`
- payload can be partial
- PATCH allowed

Drafts are not shown in the official timeline endpoints by default.

### 5.2 FINAL definition
A final event is a `DecisionEvent` row with:
- `status = FINAL`
- payload is complete and strictly validated
- immutable: PATCH should return 409

### 5.3 “One draft per (case_id, event_type)”
For UX stability, the system reuses an existing draft for the same case/event_type rather than creating multiple drafts. This matches “one in-progress worksheet” per event type.

### 5.4 Lifecycle
1. **Start draft**:
   - `POST /api/cases/{case_id}/drafts`
2. **Progressively update**:
   - `PATCH /api/cases/{case_id}/events/{event_id}`
   - deep merge, lists replaced
3. **Finalize commit**:
   - `POST /api/cases/{case_id}/events/{event_id}/finalize`
   - compute missing fields
   - strict validate
   - flip to FINAL

A useful analogy:
- draft = working tree
- PATCH = edits
- finalize = git commit

---

## 6. API surface (V2 chat-first)

### 6.1 Cases
- `POST /api/cases`
  - create case directly (legacy/dev convenience)
- `POST /api/cases/ensure`
  - ensure an OPEN case exists for `(ticker, book)`
  - response: `{ case, created }`
- `POST /api/cases/{case_id}/close`
  - set `status=CLOSED`, `closed_at=now()`
- `GET /api/cases?status=OPEN&limit=150`
  - list cases, newest-first
- `GET /api/cases/{case_id}`
  - fetch case by id

### 6.2 Events
- `POST /api/cases/{case_id}/drafts`
  - create or reuse a draft for an event type
  - returns `{ event, missing_fields }`
- `PATCH /api/cases/{case_id}/events/{event_id}`
  - deep-merge patch into draft payload (lists replaced)
  - DRAFT-only
  - returns `{ event, missing_fields }`
- `POST /api/cases/{case_id}/events/{event_id}/finalize`
  - strict validate and flip to FINAL
  - returns `{ event, missing_fields: [] }`
- `GET /api/cases/{case_id}/events`
  - returns FINAL events only (chronological)

### 6.3 Thesis
- `POST /api/cases/{case_id}/thesis/compile?asof=...`
  - compile deterministic snapshot as-of time
  - store in `thesis_snapshots`

### 6.4 LLM routes (bounded assistance)
- `POST /api/llm/event_summary`
  - input: `{ event_id }`
  - output: `{ headline, bullets, tags }`
  - used for UI readability; cached in frontend
- `POST /api/llm/missing_field_prompts`
  - input: `{ event_type, missing_fields }`
  - output: `{ prompts: [{field, prompt}] }`
- `POST /api/llm/coach`
  - input: `{ event_type, payload }`
  - output: `{ questions[], checks[], warnings[] }`
  - questions/checks only; no advice
- `POST /api/llm/interpret`
  - strict command interpretation (see below)

---

## 7. LLM interpreter: “cannot surprise you”

The LLM interpreter maps free text to a small set of actions, or asks clarification.

### 7.1 Allowed actions
The interpreter output is constrained to one of:

- `SET_CONTEXT` (ticker required)
- `START_EVENT` (event_type required; seed payload restricted)
- `ANSWER_FIELD` (only allowed if pending field exists)
- `FINALIZE_DRAFT`
- `SHOW_EVENTS`
- `SHOW_DRAFT`
- `CANCEL`

No other action types exist.

### 7.2 Uppercase tickers only
The interpreter may only use tickers that:
- appear as uppercase ticker tokens in the user text
- are included in `allowed_tickers` passed by the client

No company-name resolution is performed.

### 7.3 Clarification-first policy
If ambiguous, interpreter must return `CLARIFY` with clickable choices.

### 7.4 Deterministic gating (server-side)
Even after the LLM returns JSON:
- tickers are validated against `allowed_tickers`
- event_type is validated against allowlist
- seed_payload keys are filtered by a strict allowlist
- `ANSWER_FIELD` is only accepted when it matches `pending_field`

This means the worst failure mode is asking too many clarifying questions—not executing surprising actions.

---

## 8. Frontend architecture (chat console)

### 8.1 Layout
- Left rail: list OPEN cases (recent) + quick switch
- Center: chat transcript + input
- Right rail:
  - cheatsheet (power commands)
  - state (ticker, case, draft, next field)
  - mini timeline (last 10 FINAL events)

### 8.2 Chat state machine
The UI is always in one of these states:
1. No context (no ticker/case)
2. Context set (ticker/case)
3. Draft active (pending missing field)
4. Awaiting clarification (LLM interpret returned CLARIFY)

### 8.3 Input handling order
On each user message:
1. If awaiting clarification: user must click a choice (safe).
2. Else if draft has `pendingField`: treat message as answer, PATCH draft.
3. Else try deterministic command parsing (`ticker`, `update:`, `close`, etc.).
4. Else call `/api/llm/interpret`:
   - EXECUTE: run the action deterministically
   - CLARIFY: show choices
   - NOOP: show safe help text

### 8.4 Caching
Event summaries are requested via `/api/llm/event_summary` and cached in-memory:
- `eventSummaryCache` map
- `eventSummaryInflight` map to dedupe concurrent requests
Cache is cleared when switching context to reduce memory and avoid stale display during DB resets.

---

## 9. Configuration

### 9.1 `.env` (root)
- `DATABASE_URL` (or `PG_URL` as fallback)
- `OPENAI_API_KEY`
- `PMDOS_LLM_MODEL`
- `PMDOS_LLM_TEMPERATURE`
- `PMDOS_LLM_PROMPT_VERSION`

`.env` should not be committed. Add to `.gitignore`.

### 9.2 Settings loading
`app/config.py` loads `.env` using `python-dotenv` and exposes a typed settings object used by LLM client.

---

## 10. Data integrity and audit posture

### 10.1 Immutable FINAL events
- FINAL events are never modified.
- Corrections are new events.
- This preserves replayability and auditability.

### 10.2 Deterministic derived artifacts
- Snapshots and diffs should be computed from FINAL events + market facts.
- LLM may format output but must not add facts.
- If LLM output violates guardrails, fall back to deterministic formatting.

### 10.3 Provenance and reproducibility
- Prompt versioning via `PMDOS_LLM_PROMPT_VERSION`
- Optional future enhancement: `derived_artifacts` table with input hashes (not required for MVP)

---

## 11. Migrations (Alembic)

### 11.1 0001_core_decision_tables
Creates:
- `trade_cases`
- `decision_events`
- `thesis_snapshots`
with indexes and FK CASCADE rules.

### 11.2 0002_decision_events_status
Adds:
- `decision_events.status` (default `'FINAL'`)
- `decision_events.updated_at` (default `now()`)
- index on `(case_id, event_type, status)`
Optional recommended:
- partial unique index enforcing one draft per `(case_id, event_type)` where status='DRAFT'

---

## 12. Operational notes

### 12.1 Running locally
- Ensure `.env` exists with `DATABASE_URL` and `OPENAI_API_KEY`
- Run migrations:
  - `alembic upgrade head`
- Start server:
  - `uvicorn app.main:app --reload`

### 12.2 Deployment (planned)
- EC2 Ubuntu host
- Postgres on AWS RDS
- Systemd service for FastAPI
- Nginx optional (reverse proxy + TLS)

---

## 13. MVP demo script (recommended narrative)

A clean investor demo sequence:
1. `ticker AAPL`
2. `long AAPL` → complete INITIATE via chat → `finalize`
3. `update: comps improved` → fill missing fields → `finalize`
4. `risk: earnings week` → fill missing fields → `finalize`
5. `events` → show timeline with clean LLM headlines
6. `close` → case closes, disappears from OPEN list
7. `ticker TGT` → “Created new case … first time seen …”
8. Repeat quickly to show scalability and consistency.

---

## 14. Future extensions (post-MVP, not required)
- Derived artifacts table with input hashes for reproducible LLM outputs
- Cross-case “ticker memory” derived views (no rule engine)
- Pattern dashboards (counts/sequences) computed deterministically
- “Undo/revert context” clarification for new tickers (UI only)
- Improved timeline filtering (by event_type, date range)
- Exportable audit report (PDF/MD) for a case episode
