from __future__ import annotations

from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import health, market, cases, events, thesis, tickers
from app.api.routes import llm

app = FastAPI()

app.include_router(health.router, prefix="/api")
app.include_router(market.router, prefix="/api")
app.include_router(cases.router, prefix="/api")
app.include_router(events.router, prefix="/api")
app.include_router(thesis.router, prefix="/api")
app.include_router(tickers.router, prefix="/api")
app.include_router(llm.router, prefix="/api")


# Serve app/static/index.html at "/"
BASE_DIR = Path(__file__).resolve().parent  # .../app
STATIC_DIR = BASE_DIR / "static"

app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
