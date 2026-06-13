"""Application settings (pydantic-settings).

Reads from environment variables (Railway injects these in production) with a
fallback to a local ``.env`` for development. All secret fields default to ``""``
so the app *imports* cleanly without credentials — CI stays hermetic, and the
verify scripts (``scripts/01_verify_environment.py``) are what assert real keys
are present before anything talks to a live service.

Env var names are UPPERCASE (e.g. ``QDRANT_URL``); pydantic maps them to the
lowercase fields below because ``case_sensitive=False``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# final-submission/app/config.py -> app -> final-submission -> repo root
_APP_DIR = Path(__file__).resolve().parent
_SUBMISSION_DIR = _APP_DIR.parent
_REPO_ROOT = _SUBMISSION_DIR.parent

# Repo-root .env carries the shared dev keys (Qdrant/Google/Voyage…); a
# final-submission/.env (if present) overrides. Both are optional — missing
# files are ignored and os.environ wins (Railway).
_ENV_FILES = (_REPO_ROOT / ".env", _SUBMISSION_DIR / ".env")


class Settings(BaseSettings):
    # --- Application ---
    app_name: str = "FastPilot"
    debug: bool = False
    cors_origins: str = "*"  # comma-separated; Phase 1 narrows to the frontend origin
    playground_enabled: bool = True  # D11 kill switch
    dogfood_enabled: bool = True  # write the real-usage log (plan §11.2); off in tests

    # --- Qdrant Cloud (D1) ---
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    qdrant_collection: str = "rag_accelerator_capstone_final"

    # --- LLM: Google Gemini (D5/D8) ---
    google_api_key: str = ""
    llm_model: str = "gemini-2.5-flash"
    llm_fallback_model: str = "gemini-2.5-flash-lite"

    # --- Retrieval models (D1) ---
    voyage_api_key: str = ""
    voyage_embed_model: str = "voyage-4-lite"
    voyage_dimension: int = 2048
    voyage_rerank_model: str = "rerank-2.5"
    sparse_model: str = "Qdrant/bm25"
    dense_prefetch: int = 100
    sparse_prefetch: int = 100
    rerank_input: int = 50  # RRF output handed to the reranker
    rerank_top_k: int = 10  # final contexts to the LLM
    # Retrieval-confidence guard (a latency-free slice of CRAG's "know when retrieval is weak"):
    # if the best reranked chunk scores below this floor, flag low_confidence so the UI can warn
    # the answer may be outside the FastAPI corpus. Conservative — in-domain top scores run ~0.5–0.85.
    retrieval_confidence_min: float = 0.3

    # --- Redis Cloud (D4): memory + semantic cache ---
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_username: str = "default"
    redis_ssl: bool = True  # Redis Cloud public TLS endpoint; false for local redis-test

    # --- Semantic cache ---
    cache_distance_threshold: float = 0.16  # Phase-4 calibrated (10_cache_threshold_experiment): safety-optimal
    # — 4/6 paraphrases hit, 0/6 near-misses (margin 0.068 below the closest near-miss). The bands overlap,
    # so AC4.2's strict 100%/0% is unachievable; we pick for zero wrong-answer serving. Was 0.06 (too tight).
    cache_ttl: int = 86_400  # 24h

    # --- Conversation memory ---
    conversation_window_size: int = 10
    conversation_session_ttl: int = 86_400

    # --- Code executor / Playground (D6/D11) ---
    executor_wall_timeout_s: int = 15
    executor_cpu_seconds: int = 10
    executor_mem_mb: int = 512
    playground_max_code_bytes: int = 10_240  # 10KB
    playground_rate_per_min: int = 3
    agent_budget_s: int = 90  # total wall budget for an agent run before honest-failure

    # --- Opik observability (D8) ---
    opik_api_key: str = ""
    opik_workspace: str = "default"
    opik_project_name: str = "fastpilot"

    # --- Logging ---
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings.

    Also loads the ``.env`` files into ``os.environ`` (without overriding values
    already set — Railway wins). Pydantic reading ``env_file`` does *not* populate
    ``os.environ``, but the Haystack components (Voyage/FastEmbed/Google generators,
    ``voyageai.Client()``) read their keys straight from ``os.environ`` — so we
    mirror the keys there, exactly as the week-3/week-4 cloud scripts do.
    """
    for env_file in _ENV_FILES:
        if env_file.exists():
            load_dotenv(env_file, override=False)
    return Settings()
