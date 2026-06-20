# plans/ — implementation plans

This folder holds **forward-looking implementation plans** — one markdown file per
planned feature or refactor, written *before* the work starts and kept until the work
ships (then summarized into [[feature-coverage]] and [[log]]).

It starts empty by design. The capstone's historical week-by-week plans live in the
original course monorepo and are intentionally **not** imported here — this repo is the
clean product, and its history is captured in `git log` + [[log]].

## Conventions

- One plan per file, kebab-case name describing the work (e.g. `docker-sandbox-backend.md`).
- Start each plan with: **Goal**, **Why now**, **Approach**, **Acceptance checks**.
- When a plan ships, move its essence into [[feature-coverage]] and add a [[log]] entry,
  then delete or archive the plan file.
- Cross-link related pages with `[[page-name]]`.

## Open plans

_None yet._ See [[feature-coverage]] for the deferred-work list (Docker sandbox backend,
Playground autocomplete, broader multi-user dogfooding).
