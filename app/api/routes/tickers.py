from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.decision_events import DecisionEvent

router = APIRouter()

def sa_to_dict(obj: Any) -> Dict[str, Any]:
    d = dict(getattr(obj, "__dict__", {}) or {})
    d.pop("_sa_instance_state", None)
    return d

@router.get("/tickers/{ticker}/rules")
def list_ticker_rules(ticker: str) -> List[Dict[str, Any]]:
    t = ticker.strip().upper()
    if not t:
        raise HTTPException(400, "ticker is required")

    db: Session = SessionLocal()
    try:
        # TICKER_RULE events are stored in decision_events with payload.ticker
        rules = (
            db.query(DecisionEvent)
            .filter(
                DecisionEvent.event_type == "TICKER_RULE",
                DecisionEvent.payload["ticker"].astext == t,
                DecisionEvent.payload["status"].astext == "ACTIVE",
            )
            .order_by(DecisionEvent.event_ts.asc())
            .all()
        )
        return [sa_to_dict(r) for r in rules]
    finally:
        db.close()

@router.post("/tickers/{ticker}/rules")
def create_ticker_rule(ticker: str, body: dict) -> Dict[str, Any]:
    t = ticker.strip().upper()
    if not t:
        raise HTTPException(400, "ticker is required")

    rule_text = str(body.get("rule_text", "")).strip()
    if not rule_text:
        raise HTTPException(400, "rule_text is required")

    tags = body.get("tags", [])
    if tags is None:
        tags = []
    if not isinstance(tags, list) or not all(isinstance(x, str) for x in tags):
        raise HTTPException(400, "tags must be an array of strings")

    db: Session = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        ev = DecisionEvent(
            case_id=body.get("case_id"),  # optional; allow linking to a case/post-mortem
            event_ts=now,
            event_type="TICKER_RULE",
            payload={
                "ticker": t,
                "rule_text": rule_text,
                "tags": [s.strip() for s in tags if str(s).strip()],
                "status": "ACTIVE",
            },
        )
        db.add(ev)
        db.commit()
        db.refresh(ev)
        return sa_to_dict(ev)
    finally:
        db.close()

@router.post("/tickers/{ticker}/rules/{event_id}/deactivate")
def deactivate_ticker_rule(ticker: str, event_id: UUID) -> Dict[str, Any]:
    t = ticker.strip().upper()
    db: Session = SessionLocal()
    try:
        ev = db.query(DecisionEvent).filter(DecisionEvent.id == event_id).first()
        if not ev or ev.event_type != "TICKER_RULE":
            raise HTTPException(404, "rule not found")

        payload = dict(ev.payload or {})
        if payload.get("ticker") != t:
            raise HTTPException(400, "ticker mismatch")

        payload["status"] = "INACTIVE"
        ev.payload = payload
        db.commit()
        db.refresh(ev)
        return sa_to_dict(ev)
    finally:
        db.close()
