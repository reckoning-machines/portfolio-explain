from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from dotenv import load_dotenv

# If you have a root .env, this makes `DATABASE_URL` available to Alembic.
load_dotenv()

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# IMPORTANT: import your Base metadata
from app.db.base import Base  # noqa: E402

target_metadata = Base.metadata


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL") or os.getenv("PG_URL")
    if not url:
        raise RuntimeError("Missing DATABASE_URL (or PG_URL) in environment/.env for Alembic")
    return url


def run_migrations_offline() -> None:
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = get_database_url()

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
