from __future__ import annotations

from typing import Any, Dict, List

FORBIDDEN_SUBSTRINGS = [
    "you should",
    "recommend",
    "buy",
    "sell",
    "go long",
    "go short",
    "likely",
    "expect",
    "forecast",
    "outperform",
    "underperform",
]

def contains_forbidden_text(obj: Any) -> bool:
    """
    Recursively scan strings for forbidden phrases.
    """
    if obj is None:
        return False
    if isinstance(obj, str):
        s = obj.lower()
        return any(t in s for t in FORBIDDEN_SUBSTRINGS)
    if isinstance(obj, list):
        return any(contains_forbidden_text(x) for x in obj)
    if isinstance(obj, dict):
        return any(contains_forbidden_text(v) for v in obj.values())
    return False


def deterministic_event_fallback(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deterministic summary, no AI. Used when LLM output violates guardrails.
    """
    headline = f"{event_type}"
    bullets: List[str] = []

    if event_type == "INITIATE":
        headline = f"INITIATE {payload.get('direction', '').strip()}"
        bullets = [
            f"Horizon days: {payload.get('horizon_days')}",
            f"Conviction: {payload.get('conviction')}",
            f"Position intent %: {payload.get('position_intent_pct')}",
        ]
    elif event_type == "THESIS_UPDATE":
        headline = f"THESIS_UPDATE {payload.get('what_changed', '').strip()}"
        bullets = [payload.get("update_summary", "")[:120]]
    elif event_type == "RISK_NOTE":
        headline = f"RISK_NOTE {payload.get('risk_type', '').strip()}"
        bullets = [payload.get("note", "")[:120]]
    elif event_type == "RESIZE":
        headline = "RESIZE"
        bullets = [
            f"From: {payload.get('from_pct')}%",
            f"To: {payload.get('to_pct')}%",
            f"Reason: {payload.get('reason')}",
        ]
    elif event_type == "TICKER_RULE":
        headline = "TICKER_RULE"
        bullets = [payload.get("rule_text", "")[:120]]
    elif event_type == "POST_MORTEM":
        headline = f"POST_MORTEM {payload.get('outcome', '').strip()}"
        bullets = [payload.get("lesson") or ""]

    bullets = [b for b in bullets if isinstance(b, str) and b.strip()]
    return {"headline": headline[:120], "bullets": bullets[:6], "tags": []}
