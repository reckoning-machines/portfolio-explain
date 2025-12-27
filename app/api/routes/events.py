from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.db.session import SessionLocal
from app.models.decision_events import DecisionEvent
from typing import Any

router = APIRouter()

@router.post("/cases/{case_id}/events")
def add_event(case_id: UUID, event: dict):
    """Add a new event for a trade case."""
    db: Session = SessionLocal()
    if "event_ts" not in event or "event_type" not in event or "payload" not in event:
        db.close()
        raise HTTPException(400, "Missing event_ts, event_type, or payload")

    # Strict schema validation ONLY for INITIATE event
    if event["event_type"] == "INITIATE":
        payload = event["payload"]
        expected = {
            "direction": (str, ["LONG", "SHORT"]),
            "horizon_days": (int, None),
            "entry_thesis": (str, None),
            "key_drivers": (list, None),
            "key_risks": (list, None),
            "invalidation_triggers": (list, None),
            "conviction": (int, None),
            "position_intent_pct": ((int, float, type(None)), None)
        }
        for k in expected:
            if k not in payload:
                db.close()
                raise HTTPException(400, f"Missing INITIATE payload key '{k}'")
            typ, opts = expected[k]
            if not isinstance(payload[k], typ):
                db.close()
                raise HTTPException(400, f"INITIATE payload '{k}' wrong type")
            if opts and payload[k] not in opts:
                db.close()
                raise HTTPException(400, f"INITIATE payload '{k}' invalid value")
        # All list fields must be lists of str
        for lf in ["key_drivers", "key_risks", "invalidation_triggers"]:
            if not all(isinstance(i, str) for i in payload[lf]):
                db.close()
                raise HTTPException(400, f"INITIATE payload '{lf}' must be array of strings")
    de = DecisionEvent(case_id=case_id, **event)
    db.add(de)
    db.commit()
    db.refresh(de)
    db.close()
    return de

@router.get("/cases/{case_id}/events")
def get_events(case_id: UUID):
    db: Session = SessionLocal()
    events = db.query(DecisionEvent).filter(DecisionEvent.case_id == case_id).order_by(DecisionEvent.event_ts).all()
    db.close()
    return [e.__dict__ for e in events]
