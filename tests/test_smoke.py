"""Seed smoke test — keeps CI green from day 1 (plan §10.4).

Proves the foundation imports and the app serves /health, with no network, no
credentials, and no dependence on the developer's real .env (hermetic: Settings
is constructed with env files disabled and asserted fields cleared from the
environment). Phase 1 replaces/extends this with the real contract + SSE suite.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

_SUBMISSION_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _SUBMISSION_DIR.parent


def test_config_defaults_are_plan_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Assert the *code defaults* (plan D1), not the ambient environment."""
    from app.config import Settings

    for var in ("APP_NAME", "QDRANT_COLLECTION", "VOYAGE_DIMENSION"):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)  # hermetic: ignore repo/.env entirely
    assert settings.app_name == "FastPilot"
    assert settings.qdrant_collection == "rag_accelerator_capstone_final"
    assert settings.voyage_dimension == 2048


def test_app_factory_and_routes() -> None:
    from app.main import app, create_app

    paths = {route.path for route in app.routes}
    assert {"/", "/health", "/metrics"} <= paths
    # The factory builds independent instances — the Phase 1 testability seam.
    assert create_app() is not app


def test_container_requirements_subset_of_pyproject() -> None:
    """Drift tripwire: every container runtime dep must exist in root pyproject.

    The container installs from app/requirements.txt while dev/CI run from the
    root uv environment — this guards the two lists from silently diverging
    (name-level; version floors may legitimately differ).
    """
    req_names = set()
    for line in (_SUBMISSION_DIR / "app" / "requirements.txt").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            req_names.add(re.split(r"[\[<>=!~]", line, maxsplit=1)[0].strip().lower())

    pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())
    project_names = {
        re.split(r"[\[<>=!~]", dep, maxsplit=1)[0].strip().lower() for dep in pyproject["project"]["dependencies"]
    }

    missing = req_names - project_names
    assert not missing, (
        f"app/requirements.txt deps missing from root pyproject: {sorted(missing)} — "
        "add them to pyproject (dev env) or remove from the container list."
    )
