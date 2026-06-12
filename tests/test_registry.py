"""Opik prompt registry (D8) — register + hot-swap fetch, with graceful fallback.

Driven by a fake opik so the active register/fetch paths run without a network; the
default (Opik-off) path is covered by the autouse `_no_opik` fixture in conftest.
"""

from __future__ import annotations

from types import SimpleNamespace

from app import observability
from app.prompts import registry


# --- register_prompts -----------------------------------------------------
def test_register_prompts_pushes_every_template(monkeypatch):
    pushed: list[tuple[str, str]] = []

    class _Prompt:
        def __init__(self, name, prompt):
            pushed.append((name, prompt))

    monkeypatch.setattr(observability, "OPIK_AVAILABLE", True)
    monkeypatch.setattr(registry, "opik", SimpleNamespace(Prompt=_Prompt))
    registry.register_prompts()

    assert len(pushed) == len(registry.TEMPLATES)
    assert all(name.startswith("rag-") for name, _ in pushed)  # rag-factual, rag-how-to, ...


def test_register_prompts_noop_when_opik_off():
    # OPIK_AVAILABLE is False (autouse) → returns before touching opik, never raises.
    registry.register_prompts()


def test_register_prompts_swallows_opik_errors(monkeypatch):
    def _boom(name, prompt):
        raise RuntimeError("opik unreachable")

    monkeypatch.setattr(observability, "OPIK_AVAILABLE", True)
    monkeypatch.setattr(registry, "opik", SimpleNamespace(Prompt=_boom))
    registry.register_prompts()  # registration failure is non-fatal (hardcoded fallback still works)


# --- fetch_prompt ---------------------------------------------------------
def test_fetch_prompt_returns_fallback_when_opik_off():
    registry.reset_prompt_cache()
    text, obj = registry.fetch_prompt("FACTUAL")
    assert obj is None
    assert text == registry.TEMPLATES["FACTUAL"]


def test_fetch_prompt_unknown_type_uses_factual_fallback():
    text, obj = registry.fetch_prompt("NOT_A_REAL_TYPE")
    assert obj is None
    assert text == registry.TEMPLATES["FACTUAL"]


def test_fetch_prompt_falls_back_when_prompt_missing(monkeypatch):
    class _Client:
        def get_prompt(self, name):
            return None  # Opik has no such prompt yet

    monkeypatch.setattr(observability, "OPIK_AVAILABLE", True)
    monkeypatch.setattr(observability, "opik_client", lambda: _Client())
    registry.reset_prompt_cache()

    text, obj = registry.fetch_prompt("HOW_TO")
    assert obj is None
    assert text == registry.TEMPLATES["HOW_TO"]
    registry.reset_prompt_cache()


def test_fetch_prompt_falls_back_on_opik_error(monkeypatch):
    class _Client:
        def get_prompt(self, name):
            raise RuntimeError("opik 500")

    monkeypatch.setattr(observability, "OPIK_AVAILABLE", True)
    monkeypatch.setattr(observability, "opik_client", lambda: _Client())
    registry.reset_prompt_cache()

    text, obj = registry.fetch_prompt("TROUBLESHOOTING")
    assert obj is None
    assert text == registry.TEMPLATES["TROUBLESHOOTING"]
    registry.reset_prompt_cache()


def test_prompt_name_slugifies_query_type():
    assert registry._prompt_name("CODE_GENERATION") == "rag-code-generation"
    assert registry._prompt_name("FACTUAL") == "rag-factual"
