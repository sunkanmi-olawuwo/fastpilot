"""Security guards (Week-6 port).

InputGuard      — regex prompt-injection detector, runs pre-retrieval on every query.
OutputValidator — PII redaction on generated text (used on agent output in Phase 3).

Both are deterministic and dependency-free (stdlib ``re``), matching the week-6
component style. A blocked query gets a polite, structured refusal — never a 500.
"""

from __future__ import annotations

import re
from typing import Optional


class InputGuard:
    """Regex-based prompt-injection detector. ``check`` returns (is_safe, pattern_name)."""

    # Patterns are deliberately *narrow* — a false refusal on a real FastAPI
    # question is a worse failure than a missed exotic injection. No DOTALL (so
    # `.` can't span a whole multi-clause query), and `DAN` is matched
    # case-sensitively via (?-i:…) since "dan" is also a common name/word.
    PATTERNS = [
        ("instruction_override", r"ignore\s+(all\s+)?previous\s+(instructions|context|rules)"),
        ("instruction_override_alt", r"disregard\s+(all\s+)?(prior|previous|above)\s+(instructions|context|rules)"),
        ("system_prompt_extract", r"(output|reveal|show|print|display)\s+(me\s+)?(the\s+)?system\s+prompt"),
        ("role_hijack", r"you\s+are\s+now\s+(?!able|going|ready)"),
        ("delimiter_injection", r"---\s*\n\s*(SYSTEM|USER|ASSISTANT)\s*:"),
        ("template_injection", r"\{\{\s*\w*\s*(system|prompt|config|admin)\w*\s*\}\}"),
        ("context_extraction", r"(list|dump|show|reveal)\s+(all\s+)?(api\s+keys?|credentials?|secrets?|tokens?)"),
        ("context_dump", r"(dump|output|print)\s+(all\s+)?(your\s+)?(context|documents|memory)"),
        ("encoding_bypass", r"(base64|hex)\s+(encode|decode)\s+(this|the\s+following)"),
        ("jailbreak_dan", r"(?-i:\bDAN\b)\s+(mode|persona|character)"),
        ("jailbreak_developer", r"developer\s+mode\s+(enabled|activated|on)"),
        ("forget_instruction", r"forget\s+(everything|all\s+previous|all\s+prior|your\s+(instructions|rules|context))"),
        ("new_instruction", r"new\s+(instruction|directive|rule)s?\s*:"),
    ]

    def __init__(self) -> None:
        self._compiled = [(name, re.compile(p, re.IGNORECASE)) for name, p in self.PATTERNS]

    def check(self, query: str) -> tuple[bool, Optional[str]]:
        for name, regex in self._compiled:
            if regex.search(query or ""):
                return False, name
        return True, None


class OutputValidator:
    """Redacts PII from generated text. ``redact`` returns (clean_text, [tags])."""

    REDACTION_PATTERNS = [
        ("SSN", r"\b\d{3}-\d{2}-\d{4}\b"),
        ("EMAIL", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        ("CREDIT_CARD", r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
        ("PHONE", r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
        ("API_KEY_SK", r"\bsk-[A-Za-z0-9]{20,}\b"),
        ("API_KEY_AWS", r"\bAKIA[A-Z0-9]{16}\b"),
    ]

    def __init__(self) -> None:
        self._compiled = [(tag, re.compile(p, re.IGNORECASE)) for tag, p in self.REDACTION_PATTERNS]

    def redact(self, text: str) -> tuple[str, list[str]]:
        cleaned = text or ""
        tags: list[str] = []
        for tag, regex in self._compiled:
            if regex.search(cleaned):
                cleaned = regex.sub(f"[REDACTED-{tag}]", cleaned)
                if tag not in tags:
                    tags.append(tag)
        return cleaned, tags


REFUSAL_MESSAGE = (
    "That request looks like it's trying to change my instructions, so I can't run it. "
    "Ask me about FastAPI instead — routing, validation, auth, testing, deployment."
)

_input_guard: Optional[InputGuard] = None


def get_input_guard() -> InputGuard:
    """Singleton InputGuard (compiled patterns are reused across requests)."""
    global _input_guard
    if _input_guard is None:
        _input_guard = InputGuard()
    return _input_guard
