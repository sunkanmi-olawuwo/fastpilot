"""Small presentation helpers shared by the API layer and the prompt builder."""

from __future__ import annotations


def source_label(meta: dict) -> str:
    """Best available human source for a chunk. Collections vary in which key
    holds the filename (file_path / file / title / source_id) — fall through them,
    then to the broad source/category, so the sources panel is never blank."""
    for key in ("file_path", "file", "title", "source_id", "name"):
        value = meta.get(key)
        if value:
            return str(value)
    return str(meta.get("source") or meta.get("category") or "unknown")
