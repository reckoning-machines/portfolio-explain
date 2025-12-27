## Architecture

- FastAPI backend with SQLAlchemy and vanilla HTML+JS frontend.
- Market facts layer stores and serves daily prices from Postgres.
- Env config via .env and python-dotenv.
- Ingestion script loads Yahoo prices into DB, with returns and vol stats.
- Alembic for schema/migrations.
