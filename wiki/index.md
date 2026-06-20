# FastPilot Wiki — Index

The developer wiki for **FastPilot** — a production RAG learning companion for FastAPI.
New here? Start with [[onboarding]], then [[overview]]. This index lists every page; keep it
current when you add or rename one (see [[CLAUDE.md]] rule 3).

## Pages

| Page | What it covers |
|---|---|
| [[onboarding]] | Read-me-first article: mental model + how to get productive fast. |
| [[overview]] | High-level project map — purpose, tech stack, system architecture. |
| [[component-architecture]] | The building blocks under `app/` (services, components, augmentations, prompts) and how they collaborate. |
| [[endpoint-summary]] | HTTP API surface, request/response schemas, and data flow (SSE contracts). |
| [[coding-conventions]] | The house style — typing, lint rules, patterns, error handling. |
| [[testing-strategy]] | Test tiers/markers, hermetic fixtures, fakes, coverage gate. |
| [[feature-coverage]] | Inventory of implemented vs deferred features + measured results + honest limitations. |
| [[log]] | Chronological record of sessions and notable changes. |

## Folders

| Folder | Purpose |
|---|---|
| `raw/` | **Immutable** source documents / API contracts. Never edited — see [[raw/README]]. Holds `openapi.json` (the live OpenAPI 3.1 contract). |
| `plans/` | Forward-looking implementation plans, one per file. Starts empty — see [[plans/README]]. |
| `assets/` | Diagram/image assets referenced by wiki pages (most diagrams are inline Mermaid). |

## Related docs (outside the wiki)
- `README.md` — public-facing project landing page.
- `docs/` — original design-decision essays: `scoping`, `chunking-strategy`,
  `retrieval-strategy`, `production-decisions`, `augmentation-decisions`, `evaluation-strategy`,
  `iteration-log`.
- `submission.md` — full write-up + calibrated self-assessment.
- `DEPLOY.md` — Railway deploy + demo-recording guide.
- `evaluations/` — eval results (evidence) + dogfood log.
