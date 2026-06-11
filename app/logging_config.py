"""Stdlib logging configured once (AC1.7).

`dictConfig` at startup: one console handler, one format, uvicorn's loggers folded
into the same format so app and server lines look identical. Every module emits via
`logging.getLogger(__name__)` — nothing else configures logging. `DEBUG=true` flips
the level to reveal prompts and SSE internals; at INFO we log one summary line per
request and never a secret or full prompt.
"""

from __future__ import annotations

import logging
from logging.config import dictConfig


def configure_logging(level: str = "INFO") -> None:
    level = level.upper()
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "fastpilot": {
                    "format": "%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                    "datefmt": "%H:%M:%S",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "fastpilot",
                },
            },
            "root": {"handlers": ["console"], "level": level},
            "loggers": {
                # Fold uvicorn into our format; access log stays at WARNING to avoid
                # a line per request on top of our own summary line.
                "uvicorn": {"handlers": ["console"], "level": level, "propagate": False},
                "uvicorn.error": {"handlers": ["console"], "level": level, "propagate": False},
                "uvicorn.access": {"handlers": ["console"], "level": "WARNING", "propagate": False},
                # App logger.
                "app": {"level": level},
            },
        }
    )
    logging.getLogger("app").debug("Logging configured at %s", level)
