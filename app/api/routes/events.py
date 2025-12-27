from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.decision_events import DecisionEvent

router = APIRouter()

ALLOWED_EVENT_TYPES = {"INITIATE", "THESIS_UPDATE", "RISK_NOTE", "RESIZE"}


def sa_to_dict(obj: Any) -> Dict[str, Any]:
    d = dict(getattr(obj, "__dict__", {}) or {})
    d.pop("_sa_instance_state", None)
    return d


def validate_common(event: Dict[str, Any]) -> None:
    if "event_ts" not in event or "event_type" not in event or "payload" not in event:
        raise HTTPException(400, "Missing event_ts, event_type, or payload")

    if event["event_type"] not in ALLOWED_EVENT_TYPES:
        raise HTTPException(400, f"Invalid event_type. Allowed: {sorted(ALLOWED_EVENT_TYPES)}")

    if not isinstance(event["payload"], dict):
        raise HTTPException(400, "payload must be a JSON object")

    # event_ts can arrive as ISO string; SQLAlchemy model should accept datetime.
    # If it arrives as string, we leave conversion to FastAPI/Pydantic upstream;
    # for MVP, accept string and rely on model/DB driver conversion or error.
    if not isinstance(event["event_ts"], (str, datetime)):
        raise HTTPException(400, "event_ts must be ISO string or datetime")


def validate_initiate(payload: Dict[str, Any]) -> None:
    expected = {
        "direction": (str, ["LONG", "SHORT"]),
        "horizon_days": (int, None),
        "entry_thesis": (str, None),
        "key_drivers": (list, None),
        "key_risks": (list, None),
        "invalidation_triggers": (list, None),
        "conviction": (int, None),
        "position_intent_pct": ((int, float, type(None)), None),
    }

    for k, (typ, opts) in expected.items():
        if k not in payload:
            raise HTTPException(400, f"Missing INITIATE payload key '{k}'")
        if not isinstance(payload[k], typ):
            raise HTTPException(400, f"INITIATE payload '{k}' wrong type")
        if opts and payload[k] not in opts:
            raise HTTPException(400, f"INITIATE payload '{k}' invalid value")

    for lf in ["key_drivers", "key_risks", "invalidation_triggers"]:
        if not all(isinstance(i, str) for i in payload[lf]):
            raise HTTPException(400, f"INITIATE payload '{lf}' must be array of strings")


def validate_thesis_update(payload: Dict[str, Any]) -> None:
    required = ["what_changed", "update_summary", "drivers_delta", "risks_delta", "triggers_delta", "conviction_delta", "confidence"]
    for k in required:
        if k not in payload:
            raise HTTPException(400, f"Missing THESIS_UPDATE payload key '{k}'")

    if payload["what_changed"] not in {"FUNDAMENTALS", "VALUATION", "TECHNICALS", "POSITIONING", "MACRO", "DATA"}:
        raise HTTPException(400, "THESIS_UPDATE what_changed invalid")

    for delta_key in ["drivers_delta", "risks_delta", "triggers_delta"]:
        d = payload[delta_key]
        if not isinstance(d, dict) or "add" not in d or "remove" not in d:
            raise HTTPException(400, f"THESIS_UPDATE {delta_key} must be object with add/remove")
        if not isinstance(d["add"], list) or not isinstance(d["remove"], list):
            raise HTTPException(400, f"THESIS_UPDATE {delta_key}.add/remove must be arrays")
        if not all(isinstance(i, str) for i in d["add"]) or not all(isinstance(i, str) for i in d["remove"]):
            raise HTTPException(400, f"THESIS_UPDATE {delta_key}.add/remove must be arrays of strings")

    if not isinstance(payload["conviction_delta"], int):
        raise HTTPException(400, "THESIS_UPDATE conviction_delta must be int")
    if payload["conviction_delta"] < -20 or payload["conviction_delta"] > 20:
        raise HTTPException(400, "THESIS_UPDATE conviction_delta out of range (-20..20)")

    if not isinstance(payload["confidence"], (int, float)):
        raise HTTPException(400, "THESIS_UPDATE confidence must be number")
    if payload["confidence"] < 0 or payload["confidence"] > 1:
        raise HTTPException(400, "THESIS_UPDATE confidence out of range (0..1)")


def validate_risk_note(payload: Dict[str, Any]) -> None:
    required = ["risk_type", "severity", "note", "action", "due_by"]
    for k in required:
        if k not in payload:
            raise HTTPException(400, f"Missing RISK_NOTE payload key '{k}'")

    if payload["risk_type"] not in {"DRAWDOWN", "LIQUIDITY", "EARNINGS", "MACRO", "THESIS_BREAK", "POSITIONING", "OTHER"}:
        raise HTTPException(400, "RISK_NOTE risk_type invalid")

    if payload["severity"] not in {"LOW", "MEDIUM", "HIGH"}:
        raise HTTPException(400, "RISK_NOTE severity invalid")

    if payload["action"] not in {"MONITOR", "HEDGE", "REDUCE", "EXIT", "NONE"}:
        raise HTTPException(400, "RISK_NOTE action invalid")

    if not isinstance(payload["note"], str) or not payload["note"].strip():
        raise HTTPException(400, "RISK_NOTE note must be non-empty string")

    due_by = payload["due_by"]
    if due_by is not None and not isinstance(due_by, str):
        raise HTTPException(400, "RISK_NOTE due_by must be YYYY-MM-DD string or null")


def validate_resize(payload: Dict[str, Any]) -> None:
    required = ["from_pct", "to_pct", "reason", "rationale", "constraints"]
    for k in required:
        if k not in payload:
            raise HTTPException(400, f"Missing RESIZE payload key '{k}'")

    if payload["from_pct"] is not None and not isinstance(payload["from_pct"], (int, float)):
        raise HTTPException(400, "RESIZE from_pct must be number or null")
    if not isinstance(payload["to_pct"], (int, float)):
        raise HTTPException(400, "RESIZE to_pct must be number")

    if payload["reason"] not in {"RISK", "THESIS", "PRICE", "CONSTRAINTS", "LIQUIDITY", "OTHER"}:
        raise HTTPException(400, "RESIZE reason invalid")
    if not isinstance(payload["rationale"], str) or not payload["rationale"].strip():
        raise HTTPException(400, "RESIZE rationale must be non-empty string")

    c = payload["constraints"]
    if not isinstance(c, dict):
        raise HTTPException(400, "RESIZE constraints must be object")
    for k in ["adv_cap_binding", "gross_cap_binding", "net_cap_binding"]:
        if k not in c or not isinstance(c[k], bool):
            raise HTTPException(400, f"RESIZE constraints.{k} must be boolean")


@router.post("/cases/{case_id}/events")
def add_event(case_id: UUID, event: dict) -> Dict[str, Any]:
    """
    Add a new event for a trade case.
    """
    db: Session = SessionLocal()
    try:
        if not isinstance(event, dict):
            raise HTTPException(400, "Body must be a JSON object")

        validate_common(event)
        payload = event["payload"]

        if event["event_type"] == "INITIATE":
            validate_initiate(payload)
        elif event["event_type"] == "THESIS_UPDATE":
            validate_thesis_update(payload)
        elif event["event_type"] == "RISK_NOTE":
            validate_risk_note(payload)
        elif event["event_type"] == "RESIZE":
            validate_resize(payload)

        de = DecisionEvent(case_id=case_id, **event)
        db.add(de)
        db.commit()
        db.refresh(de)
        return sa_to_dict(de)
    finally:
        db.close()


@router.get("/cases/{case_id}/events")
def get_events(case_id: UUID) -> List[Dict[str, Any]]:
    db: Session = SessionLocal()
    try:
        events = (
            db.query(DecisionEvent)
            .filter(DecisionEvent.case_id == case_id)
            .order_by(DecisionEvent.event_ts.asc())
            .all()
        )
        return [sa_to_dict(e) for e in events]
    finally:
        db.close()
