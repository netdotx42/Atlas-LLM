---
name: enterprise-developer-setup
description: Use when scaffolding or extending the ATLAS repository. Sets the local-first Python toolchain, safety gates, CI, and review rules before new features.
---

# Enterprise developer setup

Follow this when creating or changing the ATLAS repo. Do not add a paid API, a hosted warehouse, or an unreviewed write path.

## Toolchain

- Python 3.12, pinned in `.python-version`
- `uv` and `pyproject.toml` (no loose `requirements.txt`)
- Ruff for lint and format
- pytest, including one test that a forbidden SQL statement never executes
- GitHub Actions on push and pull request
- Dependabot for uv, actions, and Docker
- Dev container so a new machine can `uv sync --extra dev`
- `.env.example` only. Real `.env` stays gitignored

## Package layout

`src/atlas/` with hatchling. Domains stay separate: `ingest`, `profile`, `quality`, `safety`, `metadata`, `api`.

## Safety, before the feature

1. Ingest only approved file types, under the byte and row caps.
2. Keep `read_only` true until an approval workflow exists.
3. Run analyst SQL through `prepare_select`. Allowlist tables. Clamp `LIMIT`.
4. Mask sensitive column names in anything returned to a caller.
5. Audit ingest, profile, quality, and SQL, including rejections.
6. Do not execute model-written code. A later local model may draft text only.

## Review files

Update `SECURITY.md` if a control changes. Note the decision in `docs/adr/` if the boundary moves. The PR template safety checklist is mandatory.

## Done

`uv run ruff check .`, `uv run ruff format --check .`, and `uv run pytest` pass.
