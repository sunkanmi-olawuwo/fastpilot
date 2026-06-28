"""One place to build a Redis client from settings.

Conversation memory, the semantic cache, and ``scripts/03_setup_redis.py`` all
connect with the same host/port/auth/TLS options — keeping that construction in a
single factory means a new option (e.g. ``ssl_ca_certs``, or a switch to
``REDIS_URL``) is added once, not in three places that can silently drift.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import redis

if TYPE_CHECKING:
    from app.config import Settings


def make_redis_client(settings: "Settings", *, decode_responses: bool) -> "redis.Redis":
    """Build a Redis client. ``decode_responses=True`` for JSON-string stores
    (conversation), ``False`` for raw embedding bytes (semantic cache).

    ``protocol=2`` (RESP2) is pinned deliberately. Redis 8.x negotiates RESP3 by
    default, and redis-py 8.0's ``FT.SEARCH`` result parser misreads the RESP3
    response map when ``decode_responses=False`` (its keys arrive as ``bytes``),
    silently reporting **0 results** for every KNN query. That degrades the
    semantic cache to a permanent 0% hit rate while ``ping``/``is_healthy`` stay
    green. Forcing RESP2 keeps the search-result parsing correct for both the
    bytes (cache) and decoded (conversation) clients.
    """
    return redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        username=settings.redis_username or None,
        password=settings.redis_password or None,
        ssl=settings.redis_ssl,
        decode_responses=decode_responses,
        protocol=2,
    )
