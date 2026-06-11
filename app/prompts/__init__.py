"""Centralized prompt management — re-exports templates + Opik registry."""

from app.prompts.registry import fetch_prompt, register_prompts
from app.prompts.templates import (
    CLASSIFICATION_PROMPT,
    DEFAULT_QUERY_TYPE,
    QUERY_TYPES,
    REWRITE_SYSTEM_PROMPT,
    TEMPLATES,
)

__all__ = [
    "TEMPLATES",
    "QUERY_TYPES",
    "DEFAULT_QUERY_TYPE",
    "CLASSIFICATION_PROMPT",
    "REWRITE_SYSTEM_PROMPT",
    "register_prompts",
    "fetch_prompt",
]
