from sqlalchemy import Column, String, Date, Numeric, BigInteger, TIMESTAMP, text
from app.db.base import Base

class MarketPriceDaily(Base):
    __tablename__ = "market_prices_daily"
    ticker = Column(String, primary_key=True)
    date = Column(Date, primary_key=True)
    close = Column(Numeric(18, 6))
    adj_close = Column(Numeric(18, 6))
    volume = Column(BigInteger)
    ret_1d = Column(Numeric(18, 8))
    vol_20d = Column(Numeric(18, 8))
    source = Column(String, nullable=False, server_default="yahoo")
    loaded_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
