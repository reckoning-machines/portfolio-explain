## Architecture

- FastAPI backend with SQLAlchemy and a vanilla HTML + JavaScript frontend, served via FastAPI StaticFiles from `app/static/`.
- Market facts layer stores and serves daily price data from PostgreSQL, sourced via a Yahoo ingestion script and enriched with derived return and volatility metrics.
- Decision OS layer persists investment decision state using an append-only event model:
  - `trade_cases` represent active investment cases.
  - `decision_events` capture time-stamped decisions, updates, risks, and sizing rationales.
  - `thesis_snapshots` store compiled, point-in-time investment theses for replay and diffing.
- Thesis compilation is deterministic and replayable; LLMs (when enabled) act only as downstream compilers of recorded events and facts, not as signal generators.
- Environment configuration is managed via a root `.env` file loaded with `python-dotenv`.
- Alembic manages all database schema and migrations for both market data and decision tables.
