# raw/ — immutable source documents

**Do not edit files in this directory.** They are point-in-time source artifacts and
API contracts that the rest of the wiki is *derived from*. Treat them as append-only:
to capture a newer version, add a new dated file (e.g. `openapi-2026-07.json`) rather
than overwriting an existing one.

This rule is enforced by convention (see [[CLAUDE.md]] rule 5) so that the wiki always
has a stable reference point even as the living pages evolve.

## Contents

| File | What it is | Captured |
|---|---|---|
| `openapi.json` | The FastAPI backend's full OpenAPI 3.1 contract (all routes + Pydantic schemas), generated from `app.openapi()`. The authoritative request/response spec. | 2026-06-20 |

## Regenerating a snapshot (additively)

```bash
uv run python -c "import json; from app.main import app; print(json.dumps(app.openapi(), indent=2))" \
  > wiki/raw/openapi-$(date +%Y-%m-%d).json
```

The living, human-readable version of this contract is [[endpoint-summary]].
