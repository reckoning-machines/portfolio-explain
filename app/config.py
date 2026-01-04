from __future__ import annotations

from dataclasses import dataclass
from dotenv import load_dotenv
import os


load_dotenv()


@dataclass(frozen=True)
class Settings:
    database_url: str
    openai_api_key: str
    llm_model: str
    llm_temperature: float
    llm_prompt_version: str


def get_settings() -> Settings:
    database_url = os.getenv("DATABASE_URL") or os.getenv("PG_URL") or ""
    if not database_url:
        raise RuntimeError("Missing DATABASE_URL (or PG_URL)")

    openai_api_key = os.getenv("OPENAI_API_KEY") or ""
    if not openai_api_key:
        raise RuntimeError("Missing OPENAI_API_KEY")

    llm_model = os.getenv("PMDOS_LLM_MODEL", "gpt-4.1")
    llm_temperature = float(os.getenv("PMDOS_LLM_TEMPERATURE", "0.2"))
    llm_prompt_version = os.getenv("PMDOS_LLM_PROMPT_VERSION", "dev")

    return Settings(
        database_url=database_url,
        openai_api_key=openai_api_key,
        llm_model=llm_model,
        llm_temperature=llm_temperature,
        llm_prompt_version=llm_prompt_version,
    )
