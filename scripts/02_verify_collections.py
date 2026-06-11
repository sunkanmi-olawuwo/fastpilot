"""Verify the Week-3 hybrid Qdrant collection is reachable and populated.

Usage (from repo root):
    uv run python final-submission/scripts/02_verify_collections.py

Exits 0 if the collection exists with points, 1 otherwise.
"""

from __future__ import annotations

import sys

import _bootstrap  # noqa: F401

from app.config import get_settings

EXPECTED_MIN_POINTS = 4_000  # week3_hybrid was indexed at 4,232 chunks


def main() -> int:
    print("=" * 60)
    print("  FastPilot — Qdrant collection check")
    print("=" * 60)

    settings = get_settings()
    if not settings.qdrant_url or not settings.qdrant_api_key:
        print("  FAIL  Qdrant credentials not set — run 01_verify_environment.py first.")
        return 1

    try:
        from qdrant_client import QdrantClient
    except ImportError:
        print("  FAIL  qdrant-client not installed — `uv sync`.")
        return 1

    client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=30)
    name = settings.qdrant_collection

    try:
        existing = {c.name for c in client.get_collections().collections}
    except Exception as exc:  # noqa: BLE001 — surface any connectivity error plainly
        print(f"  FAIL  could not reach Qdrant: {exc}")
        return 1

    if name not in existing:
        print(f"  FAIL  collection '{name}' not found. Available: {sorted(existing)}")
        return 1

    count = client.count(collection_name=name, exact=True).count
    if count == 0:
        print(f"  FAIL  '{name}' exists but is empty — run the Week 3 indexing pipeline.")
        print("=" * 60)
        return 1
    if count < EXPECTED_MIN_POINTS:
        # A warning, not a failure: the collection works, the count just drifted
        # below the indexing-time figure (e.g. dedup variance on a re-index).
        print(f"  WARN  '{name}' has {count} points (< {EXPECTED_MIN_POINTS} expected) — re-index?")
    else:
        print(f"  PASS  '{name}' reachable with {count} points")

    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
