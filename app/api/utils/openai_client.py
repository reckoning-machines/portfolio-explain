from __future__ import annotations

import json
from typing import Any, Dict

from openai import OpenAI

from app.config import get_settings


def get_client() -> OpenAI:
    s = get_settings()
    return OpenAI(api_key=s.openai_api_key)


def call_structured(
    *,
    system: str,
    user: str,
    json_schema: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Calls OpenAI with strict structured output. Returns parsed JSON dict.
    Raises on non-JSON outputs (should be rare with strict schemas).
    """
    s = get_settings()
    client = get_client()

    resp = client.chat.completions.create(
        model=s.llm_model,
        temperature=s.llm_temperature,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "pm_decision_os",
                "schema": json_schema,
                "strict": True,
            },
        },
    )

    content = resp.choices[0].message.content or ""
    try:
        return json.loads(content)
    except Exception:
        raise RuntimeError(f"LLM returned non-JSON content: {content[:2000]}")
