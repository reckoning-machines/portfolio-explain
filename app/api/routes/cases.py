from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.trade_cases import TradeCase

router = APIRouter()


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


@router.post("/cases")
def create_case(case: dict) -> Dict[str, Any]:
    """
    Create a new trade case.

    Minimal required input:
      - ticker: str

    Optional:
      - book: str
      - status: str
      - opened_at: datetime (ISO string accepted by FastAPI/Pydantic if used upstream)

    Note: We prefer defaults in the SQLAlchemy model (Option A). As a safety net,
    we populate missing fields here without overriding model defaults where possible.
    """
    db: Session = SessionLocal()
    try:
        if not isinstance(case, dict):
            raise HTTPException(400, "Body must be a JSON object")

        ticker = str(case.get("ticker", "")).strip()
        if not ticker:
            raise HTTPException(400, "Missing required field: ticker")

        # Whitelist keys to avoid unexpected kwargs
        allowed = {"ticker", "book", "status", "opened_at"}
        payload: Dict[str, Any] = {k: case[k] for k in allowed if k in case}

        # Safety net defaults (model defaults are still recommended)
        payload.setdefault("ticker", ticker.upper())
        payload.setdefault("status", "OPEN")
        payload.setdefault("opened_at", datetime.now(timezone.utc))

        tc = TradeCase(**payload)
        db.add(tc)
        db.commit()
        db.refresh(tc)

        return normalize_case_dict(sa_to_dict(tc))
    finally:
        db.close()


@router.get("/cases")
def list_cases() -> List[Dict[str, Any]]:
    db: Session = SessionLocal()
    try:
        cases = db.query(TradeCase).all()
        return [normalize_case_dict(sa_to_dict(c)) for c in cases]
    finally:
        db.close()


@router.get("/cases/{case_id}")
def get_case(case_id: UUID) -> Dict[str, Any]:
    db: Session = SessionLocal()
    try:
        case = db.query(TradeCase).filter(TradeCase.id == case_id).first()
        if not case:
            raise HTTPException(404, "Not found")
        return normalize_case_dict(sa_to_dict(case))
    finally:
        db.close()

