# app/models/decision_events.py
from __future__ import annotations

from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.db.base import Base

class DecisionEvent(Base):
    __tablename__ = "decision_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("trade_cases.id", ondelete="CASCADE"), nullable=False)

    event_ts = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    event_type = Column(Text, nullable=False)
    payload = Column(JSONB, nullable=False, server_default="{}")

    status = Column(Text, nullable=False, server_default="FINAL")   # new
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())  # new

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_decision_events_case_id", "case_id"),
        Index("ix_decision_events_event_ts", "event_ts"),
        Index("ix_decision_events_case_id_event_ts", "case_id", "event_ts"),
        Index("ix_decision_events_case_type_status", "case_id", "event_type", "status"),  # new
    )
