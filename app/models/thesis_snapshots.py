import uuid
from sqlalchemy import Column, DateTime, ForeignKey, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.db.base import Base

class ThesisSnapshot(Base):
    __tablename__ = "thesis_snapshots"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("trade_cases.id"), nullable=False, index=True)
    asof_ts = Column(DateTime, nullable=False, index=True)
    compiled_json = Column(JSON, nullable=False)
    narrative = Column(Text, nullable=True)
    model = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
