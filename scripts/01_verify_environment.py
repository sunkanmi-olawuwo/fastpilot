"""Verify every credential FastPilot needs is present in the environment.

Usage (from repo root):
    uv run python scripts/01_verify_environment.py

Exits 0 if all required keys are set, 1 otherwise. Reads through ``app.config``
so it checks exactly what the app will read.
"""

from __future__ import annotations

import sys

import _bootstrap  # noqa: F401  (sys.path side effect)

from app.config import get_settings

# (field, human label) — required for the app to actually run.
REQUIRED = [
    ("qdrant_url", "Qdrant Cloud URL"),
    ("qdrant_api_key", "Qdrant API key"),
    ("google_api_key", "Google Gemini API key"),
    ("voyage_api_key", "Voyage API key"),
    ("redis_host", "Redis Cloud host"),
    ("redis_password", "Redis Cloud password"),
    ("opik_api_key", "Opik API key"),
]


def _looks_unset(value: object) -> bool:
    """True for empty values and .env.example placeholders.

    Placeholders come in several shapes — "your_google_api_key_here",
    "your-db.cloud.redislabs.com", "https://your-cluster-url..." — so match
    "your" anywhere in the value rather than guessing per-format prefixes.
    Real cluster hosts/keys are random identifiers and never contain it.
    """
    s = str(value).strip().lower()
    return s == "" or "your" in s or s == "changeme"


def main() -> int:
    print("=" * 60)
    print("  FastPilot — environment check")
    print("=" * 60)

    settings = get_settings()
    ok = True

    for field, label in REQUIRED:
        value = getattr(settings, field)
        # redis_host defaulting to "localhost" is fine for the local redis-test
        # container, but for the real run we want a cloud host — warn, don't fail.
        if field == "redis_host" and str(value).strip().lower() == "localhost":
            print(f"  WARN  {label:24s} = localhost (set Redis Cloud host for prod)")
            continue
        if _looks_unset(value):
            print(f"  FAIL  {label:24s} — not set")
            ok = False
        else:
            shown = str(value)
            masked = shown if field.endswith("url") or field.endswith("host") else shown[:4] + "…"
            print(f"  PASS  {label:24s} = {masked}")

    print(f"\n  Collection: {settings.qdrant_collection}")
    print(f"  Opik project: {settings.opik_project_name} / workspace: {settings.opik_workspace}")

    print("-" * 60)
    if ok:
        print("  All required credentials present.")
    else:
        print("  Missing credentials — copy .env.example → .env and fill them in,")
        print("  and create the Redis Cloud DB + Opik account (see README).")
    print("=" * 60)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
