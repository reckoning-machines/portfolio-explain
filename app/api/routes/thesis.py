from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.thesis_snapshots import ThesisSnapshot
from app.models.decision_events import DecisionEvent
from app.models.trade_cases import TradeCase
from app.models.market_prices import MarketPriceDaily

router = APIRouter()


def sa_to_dict(obj: Any) -> Dict[str, Any]:
    d = dict(getattr(obj, "__dict__", {}) or {})
    d.pop("_sa_instance_state", None)
    return d


@router.post("/cases/{case_id}/thesis/compile")
def compile_thesis(case_id: UUID, asof: datetime = Query(...)) -> Dict[str, Any]:
    """
    Deterministic stub: events up to asof, plus latest market summary for case.ticker asof.
    Produces a stable compiled_json + narrative for UI.
    """
    db: Session = SessionLocal()
    try:
        case = db.query(TradeCase).filter(TradeCase.id == case_id).first()
        if not case:
            raise HTTPException(404, "Case not found")

        events = (
            db.query(DecisionEvent)
            .filter(DecisionEvent.case_id == case_id, DecisionEvent.event_ts <= asof)
            .order_by(DecisionEvent.event_ts.asc())
            .all()
        )

        mp = (
            db.query(MarketPriceDaily)
            .filter(MarketPriceDaily.ticker == case.ticker, MarketPriceDaily.date <= asof.date())
            .order_by(MarketPriceDaily.date.desc())
            .first()
        )

        event_types = [e.event_type for e in events]
        compiled = {
            "thesis": f"Case for {case.ticker}. Events: {event_types}",
            "risks": ["market risk", "liquidity risk"] if event_types else [],
            "triggers": ["exit" if "CLOSE" in event_types else "monitor"],
            "confidence": 0.7 if events else 0.4,
            "market": {"date": str(mp.date), "close": float(mp.close)} if mp else None,
        }

        narrative = f"Compiled from {len(events)} events through {asof.isoformat()} for {case.ticker}."

        snapshot = ThesisSnapshot(
            case_id=case_id,
            asof_ts=asof,
            compiled_json=compiled,
            narrative=narrative,
            model="stub",
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)
        return sa_to_dict(snapshot)
    finally:
        db.close()


@router.get("/cases/{case_id}/replay")
def replay(case_id: UUID, asof: datetime = Query(...)) -> Dict[str, Any]:
    """
    Replay case state as of a point in time (case, events, latest snapshot, market summary).
    """
    db: Session = SessionLocal()
    try:
        case = db.query(TradeCase).filter(TradeCase.id == case_id).first()
        if not case:
            raise HTTPException(404, "Case not found")

        events = (
            db.query(DecisionEvent)
            .filter(DecisionEvent.case_id == case_id, DecisionEvent.event_ts <= asof)
            .order_by(DecisionEvent.event_ts.asc())
            .all()
        )

        snapshot = (
            db.query(ThesisSnapshot)
            .filter(ThesisSnapshot.case_id == case_id, ThesisSnapshot.asof_ts <= asof)
            .order_by(ThesisSnapshot.asof_ts.desc())
            .first()
        )

        mp = (
            db.query(MarketPriceDaily)
            .filter(MarketPriceDaily.ticker == case.ticker, MarketPriceDaily.date <= asof.date())
            .order_by(MarketPriceDaily.date.desc())
            .first()
        )

        return {
            "case": sa_to_dict(case),
            "events": [sa_to_dict(e) for e in events],
            "latest_snapshot": sa_to_dict(snapshot) if snapshot else None,
            "market_summary": {"date": str(mp.date), "close": float(mp.close)} if mp else None,
        }
    finally:
        db.close()
