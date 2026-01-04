# app/api/routes/llm.py
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import SessionLocal
from app.models.decision_events import DecisionEvent

from app.api.utils.openai_client import call_structured
from app.api.utils.llm_guardrails import contains_forbidden_text, deterministic_event_fallback

router = APIRouter()

# -----------------------------
# JSON Schemas (strict)
# -----------------------------

EVENT_SUMMARY_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "headline": {"type": "string"},
        "bullets": {"type": "array", "items": {"type": "string"}},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "bullets", "tags"],
}

MISSING_PROMPTS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "prompts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "field": {"type": "string"},
                    "prompt": {"type": "string"},
                },
                "required": ["field", "prompt"],
            },
        }
    },
    "required": ["prompts"],
}

COACH_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "questions": {"type": "array", "items": {"type": "string"}},
        "checks": {"type": "array", "items": {"type": "string"}},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["questions", "checks", "warnings"],
}

INTERPRET_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "mode": {"type": "string", "enum": ["EXECUTE", "CLARIFY", "NOOP"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "action": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "properties": {
                "type": {
                    "type": "string",
                    "enum": [
                        "SET_CONTEXT",
                        "START_EVENT",
                        "ANSWER_FIELD",
                        "FINALIZE_DRAFT",
                        "SHOW_EVENTS",
                        "SHOW_DRAFT",
                        "CANCEL",
                    ],
                },
                "ticker": {"type": ["string", "null"]},
                "event_type": {
                    "type": ["string", "null"],
                    "enum": [None, "INITIATE", "THESIS_UPDATE", "RISK_NOTE", "RESIZE", "TICKER_RULE", "POST_MORTEM"],
                },
                "field": {"type": ["string", "null"]},
                "answer_text": {"type": ["string", "null"]},
                "seed_payload": {"type": ["object", "null"]},
            },
            "required": ["type", "ticker", "event_type", "field", "answer_text", "seed_payload"],
        },
        "clarify": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "properties": {
                "question": {"type": "string", "minLength": 1, "maxLength": 200},
                "choices": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "label": {"type": "string", "minLength": 1, "maxLength": 60},
                            "action": {"$ref": "#/properties/action"},
                        },
                        "required": ["label", "action"],
                    },
                },
            },
            "required": ["question", "choices"],
        },
        "message": {"type": ["string", "null"], "maxLength": 200},
    },
    "required": ["mode", "confidence", "action", "clarify", "message"],
}

# -----------------------------
# Helpers
# -----------------------------

_TICKER_TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9]{0,5}(?:\.[A-Z])?\b")

ALLOWED_EVENT_TYPES = {"INITIATE", "THESIS_UPDATE", "RISK_NOTE", "RESIZE", "TICKER_RULE", "POST_MORTEM"}

# Only allow these keys to be seeded by interpret. Everything else is dropped.
SEED_ALLOWLIST: Dict[str, List[str]] = {
    "INITIATE": [],
    "THESIS_UPDATE": ["update_summary"],
    "RISK_NOTE": ["note"],
    "RESIZE": ["rationale"],
    "TICKER_RULE": ["rule_text"],
    "POST_MORTEM": ["lesson"],
}


def sa_to_dict(obj: Any) -> Dict[str, Any]:
    d = dict(getattr(obj, "__dict__", {}) or {})
    d.pop("_sa_instance_state", None)
    return d


def extract_allowed_tickers(text: str) -> List[str]:
    """
    Enforce: tickers must be explicit uppercase tokens in the user text.
    Company names are not resolved.
    """
    if not text:
        return []
    found = _TICKER_TOKEN_RE.findall(text)
    # stable unique order
    out: List[str] = []
    seen = set()
    for t in found:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _sanitize_seed_payload(event_type: Optional[str], seed: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not seed or not isinstance(seed, dict) or not event_type:
        return None
    allowed_keys = set(SEED_ALLOWLIST.get(event_type, []))
    if not allowed_keys:
        return None
    return {k: seed[k] for k in seed.keys() if k in allowed_keys}


def _action_ok_against_allowlists(
    action: Dict[str, Any],
    *,
    allowed_tickers: List[str],
    pending_field: Optional[str],
    allow_answer_fields: Optional[List[str]],
) -> bool:
    """
    Deterministic gating so LLM cannot surprise you.
    """
    a_type = action.get("type")

    # Ticker gating
    ticker = action.get("ticker")
    if ticker is not None and ticker not in allowed_tickers:
        return False

    # Event type gating
    ev = action.get("event_type")
    if ev is not None and ev not in ALLOWED_EVENT_TYPES:
        return False

    # Field gating: default to only the pending field if provided.
    field = action.get("field")
    if a_type == "ANSWER_FIELD":
        if not field or not isinstance(field, str):
            return False
        if pending_field:
            return field == pending_field
        if allow_answer_fields is not None:
            return field in allow_answer_fields
        return False

    return True


def _default_noop() -> Dict[str, Any]:
    return {
        "mode": "NOOP",
        "confidence": 0.0,
        "action": None,
        "clarify": None,
        "message": "Use an uppercase ticker (e.g., AAPL) and commands like: ticker AAPL, long AAPL, update:, risk:, size:, rule:, post:.",
    }


# ---------------------------------------------------------------------
# Existing endpoints
# ---------------------------------------------------------------------


@router.post("/llm/event_summary")
def llm_event_summary(body: dict) -> Dict[str, Any]:
    """
    Non-authoritative: returns a headline + bullets based strictly on an existing event payload.
    """
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be a JSON object")

    event_id = body.get("event_id")
    if not event_id:
        raise HTTPException(400, "Missing event_id")

    db: Session = SessionLocal()
    try:
        de = db.query(DecisionEvent).filter(DecisionEvent.id == UUID(str(event_id))).first()
        if not de:
            raise HTTPException(404, "Not found")

        payload = de.payload or {}
        event_type = de.event_type

        s = get_settings()

        system = (
            "You are a portfolio journaling assistant. "
            "You must not introduce new facts, predictions, causal claims, or recommendations. "
            "You may only restate and format the provided event payload. "
            "Never use the words: should, recommend, buy, sell, likely, expect, forecast."
            f" Prompt version: {s.llm_prompt_version}."
        )

        user = (
            "Produce a concise summary for a chat transcript.\n"
            f"event_type: {event_type}\n"
            f"payload: {payload}\n"
            "Return JSON strictly matching the schema."
        )

        out = call_structured(system=system, user=user, json_schema=EVENT_SUMMARY_SCHEMA)

        if contains_forbidden_text(out):
            return deterministic_event_fallback(event_type, payload)

        headline = (out.get("headline") or "")[:120]
        bullets = [(b or "")[:120] for b in (out.get("bullets") or [])][:6]
        tags = [(t or "")[:32] for t in (out.get("tags") or [])][:8]

        return {"headline": headline, "bullets": bullets, "tags": tags}
    finally:
        db.close()


@router.post("/llm/missing_field_prompts")
def llm_missing_field_prompts(body: dict) -> Dict[str, Any]:
    """
    Non-authoritative: returns friendly prompts for missing_fields.
    """
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be a JSON object")

    event_type = str(body.get("event_type", "")).strip()
    missing_fields = body.get("missing_fields") or []
    if not event_type:
        raise HTTPException(400, "Missing event_type")
    if not isinstance(missing_fields, list) or not all(isinstance(x, str) for x in missing_fields):
        raise HTTPException(400, "missing_fields must be array of strings")

    s = get_settings()
    system = (
        "You generate short, clear prompts for completing a structured portfolio journal event. "
        "No advice, no predictions, no recommendations, no new facts. "
        "Return JSON strictly matching the schema."
        f" Prompt version: {s.llm_prompt_version}."
    )
    user = (
        f"event_type: {event_type}\n"
        f"missing_fields: {missing_fields}\n"
        "Write one short prompt per missing field."
    )

    out = call_structured(system=system, user=user, json_schema=MISSING_PROMPTS_SCHEMA)
    if contains_forbidden_text(out):
        return {"prompts": [{"field": f, "prompt": f"Provide {event_type}.{f}"} for f in missing_fields]}

    prompt_map = {
        p["field"]: p["prompt"]
        for p in out.get("prompts", [])
        if isinstance(p, dict) and "field" in p and "prompt" in p
    }
    return {"prompts": [{"field": f, "prompt": (prompt_map.get(f) or f"Provide {event_type}.{f}")[:160]} for f in missing_fields]}


@router.post("/llm/coach")
def llm_coach(body: dict) -> Dict[str, Any]:
    """
    Strong guidance without recommendations:
    - questions: clarifying questions
    - checks: consistency checks grounded in payload
    - warnings: neutral warnings (no advice)
    """
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be a JSON object")

    event_type = str(body.get("event_type", "")).strip()
    payload = body.get("payload") or {}
    if not event_type:
        raise HTTPException(400, "Missing event_type")
    if not isinstance(payload, dict):
        raise HTTPException(400, "payload must be a JSON object")

    s = get_settings()
    system = (
        "You are a portfolio journaling coach. "
        "You MUST NOT provide trade recommendations, predictions, or causal explanations. "
        "You may only ask clarifying questions and provide consistency checks based on the provided payload. "
        "Never use the words: should, recommend, buy, sell, likely, expect, forecast. "
        "Return JSON strictly matching the schema."
        f" Prompt version: {s.llm_prompt_version}."
    )
    user = (
        f"event_type: {event_type}\n"
        f"payload: {payload}\n"
        "Generate:\n"
        "1) questions (max 5)\n"
        "2) checks (max 5)\n"
        "3) warnings (max 3)\n"
        "All must be grounded in the payload fields and phrased neutrally."
    )

    out = call_structured(system=system, user=user, json_schema=COACH_SCHEMA)
    if contains_forbidden_text(out):
        return {"questions": [], "checks": [], "warnings": []}

    questions = [(q or "")[:160] for q in (out.get("questions") or [])][:5]
    checks = [(c or "")[:160] for c in (out.get("checks") or [])][:5]
    warnings = [(w or "")[:160] for w in (out.get("warnings") or [])][:3]
    return {"questions": questions, "checks": checks, "warnings": warnings}


# ---------------------------------------------------------------------
# New: LLM interpret (tight schema + deterministic gating)
# ---------------------------------------------------------------------


@router.post("/llm/interpret")
def llm_interpret(body: dict) -> Dict[str, Any]:
    """
    Translate user free text into a small set of allowed intents.
    This endpoint never executes. The UI applies deterministic gating and execution.

    Inputs expected:
      - text: str (required)
      - allowed_tickers: list[str] (optional; if omitted, extracted from text)
      - context: {ticker?: str, case_id?: str} (optional)
      - draft: {event_type?: str, pending_field?: str, missing_fields?: list[str]} (optional)
    """
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be a JSON object")

    text = str(body.get("text", "")).strip()
    if not text:
        return _default_noop()

    allowed_tickers = body.get("allowed_tickers")
    if allowed_tickers is None:
        allowed_tickers = extract_allowed_tickers(text)

    if not isinstance(allowed_tickers, list) or not all(isinstance(x, str) for x in allowed_tickers):
        raise HTTPException(400, "allowed_tickers must be array of strings")

    # Strict: uppercase tickers only, explicit in allowed_tickers.
    allowed_tickers = [t for t in allowed_tickers if _TICKER_TOKEN_RE.match(t)]
    if not allowed_tickers:
        # No explicit uppercase tickers present; refuse to guess.
        return {
            "mode": "CLARIFY",
            "confidence": 0.6,
            "action": None,
            "clarify": {
                "question": "Enter an uppercase ticker (e.g., AAPL). Company names are not supported.",
                "choices": [
                    {
                        "label": "OK",
                        "action": {
                            "type": "CANCEL",
                            "ticker": None,
                            "event_type": None,
                            "field": None,
                            "answer_text": None,
                            "seed_payload": None,
                        },
                    },
                    {
                        "label": "Show commands",
                        "action": {
                            "type": "SHOW_DRAFT",
                            "ticker": None,
                            "event_type": None,
                            "field": None,
                            "answer_text": None,
                            "seed_payload": None,
                        },
                    },
                ],
            },
            "message": None,
        }

    draft = body.get("draft") or {}
    if not isinstance(draft, dict):
        draft = {}

    pending_field = draft.get("pending_field")
    if pending_field is not None and not isinstance(pending_field, str):
        pending_field = None

    allow_answer_fields = draft.get("missing_fields")
    if allow_answer_fields is not None:
        if not isinstance(allow_answer_fields, list) or not all(isinstance(x, str) for x in allow_answer_fields):
            allow_answer_fields = None

    s = get_settings()

    system = (
        "You are a strict command interpreter for a portfolio journaling console. "
        "You MUST output JSON matching the schema exactly. "
        "You MUST NOT introduce or guess tickers. "
        "You may only use tickers from allowed_tickers. "
        "If intent is ambiguous, return CLARIFY with 2-5 choices. "
        "You MUST NOT provide recommendations, predictions, or advice. "
        f"Prompt version: {s.llm_prompt_version}."
    )

    user = (
        f"text: {text}\n"
        f"allowed_tickers: {allowed_tickers}\n"
        f"pending_field: {pending_field}\n"
        f"missing_fields: {allow_answer_fields}\n"
        "Interpret into one safe intent.\n"
        "If multiple tickers appear and context is unclear, ask CLARIFY.\n"
        "If user is answering a pending field, choose ANSWER_FIELD.\n"
        "If user wants to switch tickers, choose SET_CONTEXT.\n"
        "If user wants to log an event, choose START_EVENT with minimal seed_payload (allowed keys only).\n"
        "Do not invent event payload structure."
    )

    out = call_structured(system=system, user=user, json_schema=INTERPRET_SCHEMA)

    # Hard normalization + gating.
    if not isinstance(out, dict):
        return _default_noop()

    mode = out.get("mode")
    conf = float(out.get("confidence") or 0.0)

    # Confidence policy: force ambiguity into CLARIFY / NOOP
    EXECUTE_MIN = 0.80
    CLARIFY_MIN = 0.40

    if mode not in {"EXECUTE", "CLARIFY", "NOOP"}:
        return _default_noop()

    if mode == "EXECUTE" and conf < EXECUTE_MIN:
        mode = "CLARIFY"
    if mode == "CLARIFY" and conf < CLARIFY_MIN:
        return _default_noop()

    action = out.get("action")
    clarify = out.get("clarify")
    message = out.get("message")

    if mode == "NOOP":
        return {
            "mode": "NOOP",
            "confidence": conf,
            "action": None,
            "clarify": None,
            "message": (message or _default_noop()["message"])[:200],
        }

    if mode == "EXECUTE":
        if not isinstance(action, dict):
            return _default_noop()

        # sanitize seed payload
        ev = action.get("event_type")
        seed = action.get("seed_payload")
        action["seed_payload"] = _sanitize_seed_payload(ev, seed)

        if not _action_ok_against_allowlists(
            action,
            allowed_tickers=allowed_tickers,
            pending_field=pending_field,
            allow_answer_fields=allow_answer_fields,
        ):
            return _default_noop()

        return {
            "mode": "EXECUTE",
            "confidence": conf,
            "action": action,
            "clarify": None,
            "message": None,
        }

    # CLARIFY
    if not isinstance(clarify, dict):
        return _default_noop()

    q = clarify.get("question")
    choices = clarify.get("choices")

    if not isinstance(q, str) or not isinstance(choices, list) or not (2 <= len(choices) <= 5):
        return _default_noop()

    cleaned_choices = []
    for ch in choices:
        if not isinstance(ch, dict):
            continue
        label = ch.get("label")
        ch_action = ch.get("action")
        if not isinstance(label, str) or not isinstance(ch_action, dict):
            continue

        # sanitize seed payload
        ev = ch_action.get("event_type")
        seed = ch_action.get("seed_payload")
        ch_action["seed_payload"] = _sanitize_seed_payload(ev, seed)

        if not _action_ok_against_allowlists(
            ch_action,
            allowed_tickers=allowed_tickers,
            pending_field=pending_field,
            allow_answer_fields=allow_answer_fields,
        ):
            continue

        cleaned_choices.append({"label": label[:60], "action": ch_action})

    if len(cleaned_choices) < 2:
        return _default_noop()

    return {
        "mode": "CLARIFY",
        "confidence": conf,
        "action": None,
        "clarify": {"question": q[:200], "choices": cleaned_choices[:5]},
        "message": None,
    }
