# app/api/routes/events.py
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.decision_events import DecisionEvent

router = APIRouter()

# ---------------------------------------------------------------------
# Enums / allowed values
# ---------------------------------------------------------------------

EVENT_TYPES = {
    "INITIATE",
    "THESIS_UPDATE",
    "RISK_NOTE",
    "RESIZE",
    "TICKER_RULE",  # ticker-scoped pinned rule (no new tables)
    "POST_MORTEM",  # end-of-episode reflection (pattern recognition only)
}

INITIATE_DIRECTIONS = {"LONG", "SHORT"}

THESIS_UPDATE_WHAT_CHANGED = {
    "FUNDAMENTALS",
    "VALUATION",
    "TECHNICALS",
    "POSITIONING",
    "MACRO",
    "DATA",
}

RISK_TYPES = {
    "DRAWDOWN",
    "LIQUIDITY",
    "EARNINGS",
    "MACRO",
    "THESIS_BREAK",
    "POSITIONING",
    "OTHER",
}

RISK_SEVERITIES = {"LOW", "MEDIUM", "HIGH"}
RISK_ACTIONS = {"MONITOR", "HEDGE", "REDUCE", "EXIT", "NONE"}

RESIZE_REASONS = {"RISK", "THESIS", "PRICE", "CONSTRAINTS", "LIQUIDITY", "OTHER"}

TICKER_RULE_STATUS = {"ACTIVE", "INACTIVE"}

POST_MORTEM_OUTCOME = {"WIN", "LOSS", "FLAT"}
POST_MORTEM_THESIS_OUTCOME = {"CONFIRMED", "PARTIALLY_CONFIRMED", "INVALIDATED"}
POST_MORTEM_PROCESS_ADHERENCE = {"HIGH", "MEDIUM", "LOW"}
POST_MORTEM_PRIMARY_REASON = {"THESIS", "TIMING", "RISK_MGMT", "EXOGENOUS"}

STATUS_DRAFT = "DRAFT"
STATUS_FINAL = "FINAL"

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def utcnow() -> datetime:
    """
    Consistent timestamp helper.
    """
    return datetime.utcnow()


def parse_event_ts(value: Any) -> datetime:
    """
    Accept datetime or ISO string; return datetime.
    """
    if value is None:
        return utcnow()

    if isinstance(value, datetime):
        return value

    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            raise HTTPException(400, "event_ts must be ISO datetime string")
    raise HTTPException(400, "event_ts must be ISO string or datetime")


def deep_merge_replace_lists(base: Any, patch: Any) -> Any:
    """
    Deterministic deep merge:
    - dict + dict: recursive merge
    - list in patch: replace entirely
    - scalar in patch: replace
    """
    if patch is None:
        return base

    if isinstance(base, dict) and isinstance(patch, dict):
        out = dict(base)
        for k, v in patch.items():
            if k in out:
                out[k] = deep_merge_replace_lists(out[k], v)
            else:
                out[k] = v
        return out

    if isinstance(patch, list):
        return patch

    return patch


def sa_to_dict(obj: Any) -> Dict[str, Any]:
    """
    Convert a SQLAlchemy model instance to a JSON-safe dict (strip SA internals).
    """
    d = dict(getattr(obj, "__dict__", {}) or {})
    d.pop("_sa_instance_state", None)
    return d


def require_keys(payload: Dict[str, Any], keys: List[str], *, label: str) -> None:
    """
    Assert the payload contains required keys.
    """
    for k in keys:
        if k not in payload:
            raise HTTPException(400, f"Missing {label} payload key '{k}'")


def require_enum(value: Any, allowed: set[str], *, label: str) -> None:
    """
    Assert a scalar value is a member of an allowed set.
    """
    if value not in allowed:
        raise HTTPException(400, f"{label} invalid value")


def require_str(value: Any, *, label: str, allow_empty: bool = False) -> None:
    """
    Assert value is a string (optionally non-empty).
    """
    if not isinstance(value, str):
        raise HTTPException(400, f"{label} must be a string")
    if not allow_empty and not value.strip():
        raise HTTPException(400, f"{label} must be non-empty")


def require_list_of_str(value: Any, *, label: str) -> None:
    """
    Assert value is a list[str].
    """
    if not isinstance(value, list) or not all(isinstance(i, str) for i in value):
        raise HTTPException(400, f"{label} must be an array of strings")


def require_number_or_null(value: Any, *, label: str) -> None:
    """
    Assert value is int/float or None.
    """
    if value is not None and not isinstance(value, (int, float)):
        raise HTTPException(400, f"{label} must be a number or null")


def validate_common(event: Dict[str, Any]) -> None:
    """
    Validate top-level event envelope.
    """
    if "event_ts" not in event or "event_type" not in event or "payload" not in event:
        raise HTTPException(400, "Missing event_ts, event_type, or payload")

    event_type = event["event_type"]
    if event_type not in EVENT_TYPES:
        raise HTTPException(400, f"Invalid event_type. Allowed: {sorted(EVENT_TYPES)}")

    if not isinstance(event["payload"], dict):
        raise HTTPException(400, "payload must be a JSON object")

    if not isinstance(event["event_ts"], (str, datetime)):
        raise HTTPException(400, "event_ts must be ISO string or datetime")


def compute_missing_fields(event_type: str, payload: Dict[str, Any]) -> List[str]:
    """
    Deterministic missing-fields driver for chat Q&A.

    Rules:
    - Missing means key absent OR value is None OR value is empty string OR empty list.
    - For structured objects, missing means object absent or not a dict; deeper validation happens at FINALIZE.
    - Ordering is stable and matches the required field order for each event type.
    """
    required_by_type: Dict[str, List[str]] = {
        "INITIATE": [
            "direction",
            "horizon_days",
            "entry_thesis",
            "key_drivers",
            "key_risks",
            "invalidation_triggers",
            "conviction",
            "position_intent_pct",
        ],
        "THESIS_UPDATE": [
            "what_changed",
            "update_summary",
            "drivers_delta",
            "risks_delta",
            "triggers_delta",
            "conviction_delta",
            "confidence",
        ],
        "RISK_NOTE": [
            "risk_type",
            "severity",
            "note",
            "action",
            "due_by",
        ],
        "RESIZE": [
            "from_pct",
            "to_pct",
            "reason",
            "rationale",
            "constraints",
        ],
        "TICKER_RULE": [
            "ticker",
            "rule_text",
            "tags",
            "status",
        ],
        "POST_MORTEM": [
            "outcome",
            "thesis_outcome",
            "process_adherence",
            "primary_reason",
            "what_worked",
            "what_failed",
            "rule_violations",
            "lesson",
        ],
    }

    required = required_by_type.get(event_type)
    if not required:
        return []

    missing: List[str] = []
    for k in required:
        if k not in payload:
            missing.append(k)
            continue

        v = payload.get(k)

        if v is None:
            missing.append(k)
            continue

        if isinstance(v, str) and not v.strip():
            missing.append(k)
            continue

        if isinstance(v, list) and len(v) == 0:
            missing.append(k)
            continue

        # For dict-typed required keys, ensure it is an object; internal shape is validated at finalize.
        if k in {"drivers_delta", "risks_delta", "triggers_delta", "constraints"}:
            if not isinstance(v, dict):
                missing.append(k)
                continue

    return missing


def event_with_missing_fields(de: DecisionEvent) -> Dict[str, Any]:
    """
    Stable response shape for chat UI.
    """
    d = sa_to_dict(de)
    missing = compute_missing_fields(d["event_type"], d.get("payload") or {})
    return {"event": d, "missing_fields": missing}


# ---------------------------------------------------------------------
# Payload validators
# ---------------------------------------------------------------------


def validate_initiate(payload: Dict[str, Any]) -> None:
    """
    INITIATE schema (episode start): strict types, no inference.
    """
    require_keys(
        payload,
        [
            "direction",
            "horizon_days",
            "entry_thesis",
            "key_drivers",
            "key_risks",
            "invalidation_triggers",
            "conviction",
            "position_intent_pct",
        ],
        label="INITIATE",
    )

    require_enum(payload["direction"], INITIATE_DIRECTIONS, label="INITIATE.direction")
    if not isinstance(payload["horizon_days"], int):
        raise HTTPException(400, "INITIATE.horizon_days must be int")

    require_str(payload["entry_thesis"], label="INITIATE.entry_thesis")
    require_list_of_str(payload["key_drivers"], label="INITIATE.key_drivers")
    require_list_of_str(payload["key_risks"], label="INITIATE.key_risks")
    require_list_of_str(payload["invalidation_triggers"], label="INITIATE.invalidation_triggers")

    if not isinstance(payload["conviction"], int):
        raise HTTPException(400, "INITIATE.conviction must be int")
    if payload["conviction"] < 0 or payload["conviction"] > 100:
        raise HTTPException(400, "INITIATE.conviction out of range (0..100)")

    require_number_or_null(payload["position_intent_pct"], label="INITIATE.position_intent_pct")


def validate_thesis_update(payload: Dict[str, Any]) -> None:
    """
    THESIS_UPDATE schema: delta-based mutation of the thesis record.
    """
    require_keys(
        payload,
        [
            "what_changed",
            "update_summary",
            "drivers_delta",
            "risks_delta",
            "triggers_delta",
            "conviction_delta",
            "confidence",
        ],
        label="THESIS_UPDATE",
    )

    require_enum(payload["what_changed"], THESIS_UPDATE_WHAT_CHANGED, label="THESIS_UPDATE.what_changed")
    require_str(payload["update_summary"], label="THESIS_UPDATE.update_summary")

    for delta_key in ["drivers_delta", "risks_delta", "triggers_delta"]:
        d = payload[delta_key]
        if not isinstance(d, dict) or "add" not in d or "remove" not in d:
            raise HTTPException(400, f"THESIS_UPDATE.{delta_key} must be object with add/remove")
        require_list_of_str(d["add"], label=f"THESIS_UPDATE.{delta_key}.add")
        require_list_of_str(d["remove"], label=f"THESIS_UPDATE.{delta_key}.remove")

    if not isinstance(payload["conviction_delta"], int):
        raise HTTPException(400, "THESIS_UPDATE.conviction_delta must be int")
    if payload["conviction_delta"] < -20 or payload["conviction_delta"] > 20:
        raise HTTPException(400, "THESIS_UPDATE.conviction_delta out of range (-20..20)")

    if not isinstance(payload["confidence"], (int, float)):
        raise HTTPException(400, "THESIS_UPDATE.confidence must be number")
    if payload["confidence"] < 0 or payload["confidence"] > 1:
        raise HTTPException(400, "THESIS_UPDATE.confidence out of range (0..1)")


def validate_risk_note(payload: Dict[str, Any]) -> None:
    """
    RISK_NOTE schema: explicit risk logging and intended action.
    """
    require_keys(payload, ["risk_type", "severity", "note", "action", "due_by"], label="RISK_NOTE")

    require_enum(payload["risk_type"], RISK_TYPES, label="RISK_NOTE.risk_type")
    require_enum(payload["severity"], RISK_SEVERITIES, label="RISK_NOTE.severity")
    require_enum(payload["action"], RISK_ACTIONS, label="RISK_NOTE.action")
    require_str(payload["note"], label="RISK_NOTE.note")

    due_by = payload["due_by"]
    if due_by is not None and not isinstance(due_by, str):
        raise HTTPException(400, "RISK_NOTE.due_by must be YYYY-MM-DD string or null")


def validate_resize(payload: Dict[str, Any]) -> None:
    """
    RESIZE schema: position intent changes with rationale and constraint flags.
    """
    require_keys(payload, ["from_pct", "to_pct", "reason", "rationale", "constraints"], label="RESIZE")

    require_number_or_null(payload["from_pct"], label="RESIZE.from_pct")
    if not isinstance(payload["to_pct"], (int, float)):
        raise HTTPException(400, "RESIZE.to_pct must be number")

    require_enum(payload["reason"], RESIZE_REASONS, label="RESIZE.reason")
    require_str(payload["rationale"], label="RESIZE.rationale")

    c = payload["constraints"]
    if not isinstance(c, dict):
        raise HTTPException(400, "RESIZE.constraints must be object")
    for k in ["adv_cap_binding", "gross_cap_binding", "net_cap_binding"]:
        if k not in c or not isinstance(c[k], bool):
            raise HTTPException(400, f"RESIZE.constraints.{k} must be boolean")


def validate_ticker_rule(payload: Dict[str, Any]) -> None:
    """
    TICKER_RULE schema: pinned, user-authored reminders scoped to a ticker.
    These are not executable trading rules; they are memory artifacts.
    """
    require_keys(payload, ["ticker", "rule_text", "tags", "status"], label="TICKER_RULE")

    require_str(payload["ticker"], label="TICKER_RULE.ticker")
    require_str(payload["rule_text"], label="TICKER_RULE.rule_text")
    require_list_of_str(payload["tags"], label="TICKER_RULE.tags")
    require_enum(payload["status"], TICKER_RULE_STATUS, label="TICKER_RULE.status")


def validate_post_mortem(payload: Dict[str, Any]) -> None:
    """
    POST_MORTEM schema: user-authored, pattern-recognition inputs.
    No forecasting, no recommendations, no causality.
    """
    require_keys(
        payload,
        [
            "outcome",
            "thesis_outcome",
            "process_adherence",
            "primary_reason",
            "what_worked",
            "what_failed",
            "rule_violations",
            "lesson",
        ],
        label="POST_MORTEM",
    )

    require_enum(payload["outcome"], POST_MORTEM_OUTCOME, label="POST_MORTEM.outcome")
    require_enum(payload["thesis_outcome"], POST_MORTEM_THESIS_OUTCOME, label="POST_MORTEM.thesis_outcome")
    require_enum(payload["process_adherence"], POST_MORTEM_PROCESS_ADHERENCE, label="POST_MORTEM.process_adherence")
    require_enum(payload["primary_reason"], POST_MORTEM_PRIMARY_REASON, label="POST_MORTEM.primary_reason")

    require_str(payload["what_worked"], label="POST_MORTEM.what_worked")
    require_str(payload["what_failed"], label="POST_MORTEM.what_failed")

    if not isinstance(payload["rule_violations"], list) or not all(isinstance(x, str) for x in payload["rule_violations"]):
        raise HTTPException(400, "POST_MORTEM.rule_violations must be array of strings")

    lesson = payload["lesson"]
    if lesson is not None:
        require_str(lesson, label="POST_MORTEM.lesson", allow_empty=False)


def validate_payload(event_type: str, payload: Dict[str, Any]) -> None:
    """
    Dispatch payload validation by event type.
    """
    if event_type == "INITIATE":
        validate_initiate(payload)
    elif event_type == "THESIS_UPDATE":
        validate_thesis_update(payload)
    elif event_type == "RISK_NOTE":
        validate_risk_note(payload)
    elif event_type == "RESIZE":
        validate_resize(payload)
    elif event_type == "TICKER_RULE":
        validate_ticker_rule(payload)
    elif event_type == "POST_MORTEM":
        validate_post_mortem(payload)
    else:
        raise HTTPException(400, "Unsupported event_type")


# ---------------------------------------------------------------------
# Draft / Patch / Finalize (V2 chat-first)
# ---------------------------------------------------------------------


@router.post("/cases/{case_id}/drafts")
def create_or_reuse_draft(case_id: UUID, body: dict) -> Dict[str, Any]:
    """
    Create or reuse a DRAFT DecisionEvent for this (case_id, event_type).

    Body:
      - event_type: str (required)
      - seed_payload: dict (optional)
      - event_ts: str|datetime (optional)
    """
    db: Session = SessionLocal()
    try:
        if not isinstance(body, dict):
            raise HTTPException(400, "Body must be a JSON object")

        event_type = str(body.get("event_type", "")).strip()
        if event_type not in EVENT_TYPES:
            raise HTTPException(400, f"Invalid event_type. Allowed: {sorted(EVENT_TYPES)}")

        seed_payload = body.get("seed_payload") or {}
        if not isinstance(seed_payload, dict):
            raise HTTPException(400, "seed_payload must be a JSON object")

        event_ts_dt = parse_event_ts(body.get("event_ts"))

        existing = (
            db.query(DecisionEvent)
            .filter(
                DecisionEvent.case_id == case_id,
                DecisionEvent.event_type == event_type,
                DecisionEvent.status == STATUS_DRAFT,
            )
            .order_by(DecisionEvent.updated_at.desc())
            .first()
        )

        if existing:
            existing_payload = existing.payload or {}

            # Conservative rule: apply seed only if payload is empty
            if existing_payload == {} and seed_payload:
                existing.payload = deep_merge_replace_lists(existing_payload, seed_payload)
                existing.updated_at = utcnow()
                db.add(existing)
                db.commit()
                db.refresh(existing)

            return event_with_missing_fields(existing)

        de = DecisionEvent(
            case_id=case_id,
            event_ts=event_ts_dt,
            event_type=event_type,
            payload=seed_payload,
            status=STATUS_DRAFT,
        )
        de.updated_at = utcnow()
        db.add(de)
        db.commit()
        db.refresh(de)
        return event_with_missing_fields(de)
    finally:
        db.close()


@router.patch("/cases/{case_id}/events/{event_id}")
def patch_draft_event(case_id: UUID, event_id: UUID, body: dict) -> Dict[str, Any]:
    """
    Deep-merge payload_patch into the DRAFT payload.
    Lists are replaced entirely.
    FINAL events are immutable.

    Body:
      - payload_patch: dict (required)
    """
    db: Session = SessionLocal()
    try:
        if not isinstance(body, dict):
            raise HTTPException(400, "Body must be a JSON object")

        payload_patch = body.get("payload_patch")
        if not isinstance(payload_patch, dict):
            raise HTTPException(400, "payload_patch must be a JSON object")

        de = (
            db.query(DecisionEvent)
            .filter(
                DecisionEvent.id == event_id,
                DecisionEvent.case_id == case_id,
            )
            .first()
        )
        if not de:
            raise HTTPException(404, "Not found")

        if de.status != STATUS_DRAFT:
            raise HTTPException(409, "Only DRAFT events can be patched")

        current = de.payload or {}
        de.payload = deep_merge_replace_lists(current, payload_patch)
        de.updated_at = utcnow()

        db.add(de)
        db.commit()
        db.refresh(de)
        return event_with_missing_fields(de)
    finally:
        db.close()


@router.post("/cases/{case_id}/events/{event_id}/finalize")
def finalize_event(case_id: UUID, event_id: UUID) -> Dict[str, Any]:
    """
    Strict validation at finalize-time; flip DRAFT -> FINAL.
    """
    db: Session = SessionLocal()
    try:
        de = (
            db.query(DecisionEvent)
            .filter(
                DecisionEvent.id == event_id,
                DecisionEvent.case_id == case_id,
            )
            .first()
        )
        if not de:
            raise HTTPException(404, "Not found")

        if de.status != STATUS_DRAFT:
            raise HTTPException(409, "Only DRAFT events can be finalized")

        payload = de.payload or {}

        missing = compute_missing_fields(de.event_type, payload)
        if missing:
            raise HTTPException(
                status_code=409,
                detail={"error": "missing_fields", "missing_fields": missing},
            )

        validate_payload(de.event_type, payload)

        de.status = STATUS_FINAL
        de.updated_at = utcnow()

        db.add(de)
        db.commit()
        db.refresh(de)
        return {"event": sa_to_dict(de), "missing_fields": []}
    finally:
        db.close()


# ---------------------------------------------------------------------
# Legacy strict insert + reads
# ---------------------------------------------------------------------


@router.post("/cases/{case_id}/events")
def add_event(case_id: UUID, event: dict) -> Dict[str, Any]:
    """
    Add a new FINAL event for a trade case (strict).

    Notes:
    - This endpoint is intended for structured inserts from the UI/chat layer.
    - Validation is strict to preserve auditability and support stable derived artifacts.
    - This writes FINAL directly (no drafts).
    """
    db: Session = SessionLocal()
    try:
        if not isinstance(event, dict):
            raise HTTPException(400, "Body must be a JSON object")

        validate_common(event)

        event_type = event["event_type"]
        payload = event["payload"]
        validate_payload(event_type, payload)

        de = DecisionEvent(
            case_id=case_id,
            event_ts=parse_event_ts(event.get("event_ts")),
            event_type=event_type,
            payload=payload,
            status=STATUS_FINAL,
        )
        de.updated_at = utcnow()

        db.add(de)
        db.commit()
        db.refresh(de)
        return sa_to_dict(de)
    finally:
        db.close()


@router.get("/cases/{case_id}/events")
def get_events(case_id: UUID) -> List[Dict[str, Any]]:
    """
    Return all FINAL events for a case, ordered chronologically by event_ts.

    Note: Drafts are excluded by default to keep derived artifacts stable.
    """
    db: Session = SessionLocal()
    try:
        events = (
            db.query(DecisionEvent)
            .filter(
                DecisionEvent.case_id == case_id,
                DecisionEvent.status == STATUS_FINAL,
            )
            .order_by(DecisionEvent.event_ts.asc())
            .all()
        )
        return [sa_to_dict(e) for e in events]
    finally:
        db.close()
