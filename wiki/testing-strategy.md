# Testing Strategy

> How the suite is structured, what's expected of new tests, and the patterns to copy.
> Conventions in [[coding-conventions]]; the code under test in [[component-architecture]].

## Framework + layout
- **pytest** (+ `pytest-asyncio` in `auto` mode, `pytest-cov`).
- Config in `pyproject.toml`: `testpaths = ["tests"]`, `pythonpath = [".", "frontend"]`
  (so `import app` and `import api_client` both resolve).
- **~210 test functions** across `tests/` (`test_api`, `test_pipeline`, `test_services`,
  `test_agent`, `test_agent_endpoints`, `test_executor`, `test_security`, `test_components`,
  `test_observability`, `test_registry`, `test_sse_parser`, `test_frontend`, `test_units`,
  `test_integration`, `test_visual`, `test_smoke`).

## Test tiers (markers)
The **default run is hermetic and instant** — no network, no keys, < 10 s. Heavier tiers are
opt-in via markers (`addopts = -m 'not integration and not live and not visual'`):

| Marker | Needs | Run with |
|---|---|---|
| _(default)_ | nothing | `uv run pytest` |
| `integration` | local redis-stack container | `docker compose --profile test up -d redis-test` then `-m integration` |
| `live` | real Qdrant/Voyage/Gemini/Opik keys | `-m live` |
| `visual` | Playwright + chromium | `playwright install chromium` then `-m visual` |
| `slow` | nothing (just long, e.g. executor timeouts) | included by default |

`--strict-markers` is on — an unregistered marker is an error.

## Hermeticity (autouse fixtures in `tests/conftest.py`)
Three autouse fixtures make every test safe and offline by default:
- **`_no_network`** — monkeypatches `socket.connect`/`connect_ex` to raise, so no test can
  accidentally hit the network.
- **`_no_opik`** — forces `OPIK_AVAILABLE = False` and stubs `configure_opik` (live tests
  re-enable it themselves).
- **`_no_dogfood`** — stubs the dogfood append so unit tests never touch the real
  repo-root `dogfood/sessions.jsonl`.

## Fakes + the client builder
`conftest.py` provides lightweight fakes — `FakePipeline`, `FakeCache`, `FakeRouter`, and a
real `ConversationService` on **`fakeredis`** — plus a `build_client(...)` helper and an
`api_client` fixture that wires them into the app via `app.state`. This means:
- **Inject fakes, don't mock internals.** Construct the unit with fake collaborators (the
  agent/executor/pipeline all take their dependencies as args) rather than patching deep.
- Memory + query-rewrite are exercised *for real* against `fakeredis`, not stubbed.

## Key invariants under test
- **SSE contract round-trip** (`test_sse_parser`) — the frontend parser must consume exactly
  what the backend emits; `app/models.py` is the shared source of truth (see [[endpoint-summary]]).
- **Requirements drift tripwire** (`test_smoke`) — every dep in `app/requirements.txt` must
  exist in `pyproject.toml`, so the container image and dev env can't silently diverge.
- **Sandbox denylist** (`test_executor`, `test_security`) — AST escapes (reflection,
  `getattr`/`open`), network, and resource overruns are all asserted blocked.
- **Resilience** — degraded paths (no Redis, no keys) return `degraded`/structured guards,
  never 5xx.

## Coverage expectations
- **90% line coverage gate** on `app/`, enforced in CI (`--cov=app --cov-fail-under=90`).
  Branch coverage is on (`tool.coverage.run`).
- The deliberately-uncovered remainder is live-only code (real Redis/Qdrant/Opik build paths,
  the executor's forked-child `preexec_fn`), reached under `integration`/`live`.
- **New code should ship with tests that keep the gate green.** If a path is only reachable
  live, mark it `integration`/`live` and note why.

## Running
```bash
uv run pytest                 # hermetic (default)
uv run pytest --cov=app --cov-report=term-missing --cov-fail-under=90   # like CI
docker compose --profile test up -d redis-test
REDIS_HOST=localhost REDIS_PORT=6380 REDIS_SSL=false uv run pytest -m integration
```

CI (`.github/workflows/ci.yml`) runs ruff then the hermetic suite with the coverage gate on
every push/PR (see [[overview]] → badges).
