# app/api/routes/cases.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.trade_cases import TradeCase

router = APIRouter()


def utcnow() -> datetime:
    """
    Consistent UTC timestamp helper.
    """
    return datetime.now(timezone.utc)


def sa_to_dict(obj: Any) -> Dict[str, Any]:
    """
    Convert a SQLAlchemy model instance to a JSON-safe dict, stripping SQLAlchemy internals.
    """
    d = dict(getattr(obj, "__dict__", {}) or {})
    d.pop("_sa_instance_state", None)
    return d


def normalize_case_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure a stable response shape for UI consumption.
    """
    out = dict(d)
    if "case_id" in out and "id" not in out:
        out["id"] = out["case_id"]
    return out


def require_body_dict(body: Any) -> Dict[str, Any]:
    """
    Enforce JSON object bodies for these MVP endpoints.
    """
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be a JSON object")
    return body


def normalize_ticker(value: Any) -> str:
    """
    Normalize tickers to uppercase, trimmed.
    """
    t = str(value or "").strip().upper()
    if not t:
        raise HTTPException(400, "Missing required field: ticker")
    return t


def normalize_book(value: Any) -> str:
    """
    Normalize book to a trimmed string; default 'default'.
    """
    b = str(value or "default").strip()
    return b or "default"


@router.post("/cases")
def create_case(case: dict) -> Dict[str, Any]:
    """
    Create a new trade case.
    """
    db: Session = SessionLocal()
    try:
        case = require_body_dict(case)

        ticker = normalize_ticker(case.get("ticker"))
        book = normalize_book(case.get("book", "default"))

        allowed = {"ticker", "book", "status", "opened_at"}
        payload: Dict[str, Any] = {k: case[k] for k in allowed if k in case}

        payload["ticker"] = ticker
        payload.setdefault("book", book)
        payload.setdefault("status", "OPEN")
        payload.setdefault("opened_at", utcnow())

        tc = TradeCase(**payload)
        db.add(tc)
        db.commit()
        db.refresh(tc)

        return normalize_case_dict(sa_to_dict(tc))
    finally:
        db.close()


@router.post("/cases/ensure")
def ensure_case(body: dict) -> Dict[str, Any]:
    """
    Ensure there is an OPEN case for (ticker, book).
    If one exists, return it; otherwise create a new OPEN case.

    Response shape:
      - case: TradeCase (dict)
      - created: bool
    """
    db: Session = SessionLocal()
    try:
        body = require_body_dict(body)

        ticker = normalize_ticker(body.get("ticker"))
        book = normalize_book(body.get("book", "default"))

        existing = (
            db.query(TradeCase)
            .filter(
                TradeCase.ticker == ticker,
                TradeCase.book == book,
                TradeCase.status == "OPEN",
            )
            .order_by(TradeCase.opened_at.desc())
            .first()
        )
        if existing:
            return {"case": normalize_case_dict(sa_to_dict(existing)), "created": False}

        tc = TradeCase(
            ticker=ticker,
            book=book,
            status="OPEN",
            opened_at=utcnow(),
        )
        db.add(tc)
        db.commit()
        db.refresh(tc)
        return {"case": normalize_case_dict(sa_to_dict(tc)), "created": True}
    finally:
        db.close()


@router.post("/cases/{case_id}/close")
def close_case(case_id: UUID) -> Dict[str, Any]:
    """
    Close a case (end an episode).
    Deterministic: status -> CLOSED, closed_at -> now().
    """
    db: Session = SessionLocal()
    try:
        tc = db.query(TradeCase).filter(TradeCase.id == case_id).first()
        if not tc:
            raise HTTPException(404, "Not found")

        if tc.status == "CLOSED":
            return normalize_case_dict(sa_to_dict(tc))

        tc.status = "CLOSED"
        tc.closed_at = utcnow()

        db.add(tc)
        db.commit()
        db.refresh(tc)

        return normalize_case_dict(sa_to_dict(tc))
    finally:
        db.close()


@router.get("/cases")
def list_cases(
    status: str | None = Query(default=None, description="Filter by status, e.g. OPEN or CLOSED"),
    limit: int = Query(default=100, ge=1, le=500, description="Max cases to return"),
) -> List[Dict[str, Any]]:
    """
    List cases (optionally filtered), newest-first by opened_at.
    """
    db: Session = SessionLocal()
    try:
        q = db.query(TradeCase)

        if status is not None:
            s = str(status).strip().upper()
            q = q.filter(TradeCase.status == s)

        cases = q.order_by(TradeCase.opened_at.desc()).limit(limit).all()
        return [normalize_case_dict(sa_to_dict(c)) for c in cases]
    finally:
        db.close()


@router.get("/cases/{case_id}")
def get_case(case_id: UUID) -> Dict[str, Any]:
    """
    Fetch a single case by id.
    """
    db: Session = SessionLocal()
    try:
        case = db.query(TradeCase).filter(TradeCase.id == case_id).first()
        if not case:
            raise HTTPException(404, "Not found")
        return normalize_case_dict(sa_to_dict(case))
    finally:
        db.close()
