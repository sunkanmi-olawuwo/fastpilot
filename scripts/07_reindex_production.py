"""Build the clean production Qdrant collection (file_path + category + hybrid vectors).

Why this exists: the original ``week3_hybrid`` collection's per-chunk ``meta`` was
flattened to ``{category}`` by the week-3 category step (``set_payload`` with a whole
``meta`` dict *replaced* the original, wiping ``file_path``). The dense/sparse vectors
were fine, but the sources panel, the exact-file dogfood probes, and the Week-4
``expected_file_hit`` story all need ``file_path``.

This re-runs the *proven* week-3 hybrid pipeline (same AST chunker, Voyage-4-lite dense,
Qdrant/BM25 sparse, ``text-dense``/``text-sparse`` named vectors) into a fresh collection,
but attaches BOTH ``file_path`` and ``category`` to each document's meta *before* chunking
so both propagate onto every chunk — the merge the original step should have done.

Usage (from repo root, with live QDRANT/VOYAGE keys in .env):
    uv run python scripts/07_reindex_production.py --full
    uv run python scripts/07_reindex_production.py --test    # 5 docs/source
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from types import ModuleType

from haystack import Document

NEW_COLLECTION = "rag_accelerator_capstone_final"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
W3_INDEXING = REPO_ROOT / "week-3" / "scripts" / "indexing"
W3_SCRIPTS = REPO_ROOT / "week-3" / "scripts"
W1BC_SCRIPTS = REPO_ROOT / "week-1-bettercorpus" / "scripts"
CATEGORY_MAP = REPO_ROOT / "week-3" / "data_preparation" / "outputs" / "category_map.json"

for p in (REPO_ROOT, W3_SCRIPTS, W3_INDEXING, W1BC_SCRIPTS):
    sys.path.insert(0, str(p))

SOURCES = ("official_docs", "template_repo", "github_issue", "github_discussion")
TEST_PER_SOURCE = 5


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _synthesize_file_path(doc: Document) -> None:
    """Canonical ``meta.file_path`` per document (matches week-3 + category_map keys)."""
    if doc.meta.get("file_path"):
        return
    if doc.meta.get("source") == "template_repo" and doc.meta.get("file"):
        doc.meta["file_path"] = doc.meta["file"]
        return
    source = doc.meta.get("source", "unknown")
    source_id = doc.meta.get("source_id", doc.id)
    doc.meta["file_path"] = f"{source}::{source_id}"


def _stratified_subset(docs: list[Document], per_source: int) -> list[Document]:
    counters: dict[str, int] = defaultdict(int)
    out: list[Document] = []
    for doc in docs:
        src = doc.meta.get("source", "unknown")
        if counters[src] < per_source:
            out.append(doc)
            counters[src] += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-index the clean production collection.")
    ap.add_argument("--full", action="store_true", help="Index every harmonized document.")
    ap.add_argument("--test", action="store_true", help=f"Stratified subset ({TEST_PER_SOURCE}/source).")
    ap.add_argument("--collection", default=NEW_COLLECTION, help="Target Qdrant collection.")
    args = ap.parse_args()
    if not (args.full or args.test):
        ap.error("choose --full or --test")

    build_documents = _load_module("build_documents", W1BC_SCRIPTS / "05_build_documents.py")
    pipeline_mod = _load_module("create_hybrid_pipeline", W3_INDEXING / "01_create_hybrid_pipeline.py")

    catmap = json.loads(CATEGORY_MAP.read_text()).get("files", {})

    docs = list(build_documents.load_documents())
    if args.test:
        docs = _stratified_subset(docs, TEST_PER_SOURCE)

    cat_hits = 0
    for doc in docs:
        _synthesize_file_path(doc)
        entry = catmap.get(doc.meta["file_path"])
        if entry and entry.get("category"):
            doc.meta["category"] = entry["category"]
            cat_hits += 1

    print(f"Documents: {len(docs)}  |  file_path set: {len(docs)}  |  category matched: {cat_hits}")
    counts = Counter(d.meta.get("source", "?") for d in docs)
    print("By source:", dict(counts))

    pipeline, cfg = pipeline_mod.create_hybrid_pipeline(collection_name=args.collection)
    result = pipeline.run(data={"chunker": {"documents": docs}})
    written = result["writer"]["documents_written"]

    print("=" * 70)
    print(f"  Indexed {written} chunks → '{args.collection}'")
    print(f"  dense={cfg['voyage_model']} ({cfg['embedding_dimension']}d)  sparse={cfg['sparse_model']}")
    print("  meta on every chunk: file_path + category + source")
    print("=" * 70)
    print(f"\nNext: set QDRANT_COLLECTION={args.collection} in .env")
    return 0


if __name__ == "__main__":
    sys.exit(main())
