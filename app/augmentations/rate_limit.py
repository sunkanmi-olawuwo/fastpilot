"""Per-session rate limiter for the Playground (D11).

Fixed 60-second window. Uses a Redis counter when available (so it holds across
workers/restarts) and falls back to an in-process dict — symmetric with the rest of
the Redis degradation story. Never raises into a request: on any Redis error it allows
the call (fail-open is the right default for a friendly rate limit).
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, *, redis_client=None, per_minute: int = 3):
        self.per_minute = per_minute
        self.redis = redis_client
        self._mem: dict[str, list[float]] = {}

    def check(self, session_id: str) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds). Counts this call when allowed."""
        session_id = session_id or "anon"
        if self.redis is not None:
            try:
                return self._check_redis(session_id)
            except Exception as exc:  # noqa: BLE001 - fail open, never block on Redis trouble
                logger.debug("rate-limit redis error, allowing: %s", exc)
                return True, 0
        return self._check_mem(session_id)

    def _check_redis(self, session_id: str) -> tuple[bool, int]:
        bucket = int(time.time()) // 60
        key = f"rl:{session_id}:{bucket}"
        count = self.redis.incr(key)
        if count == 1:
            self.redis.expire(key, 60)
        if count > self.per_minute:
            return False, 60 - int(time.time()) % 60
        return True, 0

    def _check_mem(self, session_id: str) -> tuple[bool, int]:
        now = time.time()
        hits = [t for t in self._mem.get(session_id, []) if now - t < 60]
        if len(hits) >= self.per_minute:
            return False, max(1, int(60 - (now - hits[0])))
        hits.append(now)
        self._mem[session_id] = hits
        return True, 0
