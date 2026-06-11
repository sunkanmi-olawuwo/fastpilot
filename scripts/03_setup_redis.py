"""Verify Redis has the Search module (RediSearch) and create the semantic-cache
HNSW index. Idempotent — safe to run repeatedly.

Fails loudly if Redis is plain (no Search module): the semantic cache needs
``FT.CREATE`` / ``FT.SEARCH`` KNN, which a vanilla redis image does not ship.
Use Redis Cloud (Search & Query capability) or the ``redis/redis-stack-server``
test container — never plain ``redis``.

Usage (from repo root):
    uv run python final-submission/scripts/03_setup_redis.py

Point it at the local test container instead of Redis Cloud with:
    REDIS_HOST=localhost REDIS_PORT=6380 REDIS_SSL=false \\
        uv run python final-submission/scripts/03_setup_redis.py
"""

from __future__ import annotations

import sys

import _bootstrap  # noqa: F401

from app.config import get_settings
from app.services.semantic_cache import INDEX_NAME, create_cache_index


def main() -> int:
    print("=" * 60)
    print("  FastPilot — Redis setup (semantic-cache HNSW index)")
    print("=" * 60)

    settings = get_settings()

    try:
        import redis  # noqa: F401 - availability check for a friendly message
    except ImportError:
        print("  FAIL  redis not installed — `uv sync`.")
        return 1

    from app.redis_client import make_redis_client

    client = make_redis_client(settings, decode_responses=False)

    # 1. Connectivity
    host_port = f"{settings.redis_host}:{settings.redis_port}"
    try:
        client.ping()
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL  could not reach Redis at {host_port}: {exc}")
        return 1
    print(f"  PASS  connected to {host_port} (ssl={settings.redis_ssl})")

    # 2. Search module present?  (the load-bearing check)
    try:
        modules = {m.get(b"name", m.get("name", b"")) for m in client.module_list()}
        modules = {m.decode() if isinstance(m, bytes) else m for m in modules}
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL  MODULE LIST failed: {exc}")
        return 1
    if "search" not in modules:
        print(f"  FAIL  RediSearch module absent (modules: {sorted(modules)}).")
        print("        Use Redis Cloud (Search & Query) or redis/redis-stack-server,")
        print("        never plain redis — the semantic cache needs FT.CREATE/FT.SEARCH.")
        return 1
    print(f"  PASS  RediSearch module present (modules: {sorted(modules)})")

    # 3. Create the HNSW index (idempotent) — shared with the cache service so the
    #    pre-flight script and the runtime never drift on schema or index name.
    dim = settings.voyage_dimension
    try:
        created = create_cache_index(client, dimension=dim)
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL  FT.CREATE failed: {exc}")
        return 1
    if created:
        print(f"  PASS  created index '{INDEX_NAME}' (HNSW, COSINE, DIM={dim})")
    else:
        print(f"  PASS  index '{INDEX_NAME}' already exists (idempotent)")

    print("=" * 60)
    print("  Redis ready for the semantic cache.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
