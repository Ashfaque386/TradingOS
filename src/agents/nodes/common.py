"""Shared helpers for LangGraph agent nodes (Phase 2 Epic E2.3)."""


def extract_json(text: str) -> str:
    """LLMs sometimes wrap JSON in markdown code fences; strip those before parsing."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()
