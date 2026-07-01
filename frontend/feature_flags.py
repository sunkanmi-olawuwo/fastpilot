"""Runtime feature flags shared by Streamlit views."""

from __future__ import annotations

import os

_FALSE_VALUES = {"0", "false", "no", "off"}


def playground_enabled() -> bool:
    return os.environ.get("PLAYGROUND_ENABLED", "true").strip().lower() not in _FALSE_VALUES
