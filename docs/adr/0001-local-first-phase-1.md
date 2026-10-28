# ADR 0001 — Local-first phase 1

## Status

Accepted

## Context

ATLAS is sold later as an on-prem data-quality toolkit. The first build has to prove profiling and quality checks without paid APIs, and it has to be safe to point at a messy export.

## Decision

Phase 1 is a single Python package:

- FastAPI for the API
- Polars for ingest
- DuckDB for profile, quality, and reviewed SQL
- SQLite (SQLAlchemy) for the dataset registry and audit log
- Pydantic settings for limits

No llama.cpp binary, no embeddings index, and no React app in this commit. Those are sequenced after the deterministic core has tests.

Quality findings are computed, not generated. SQL from any caller is gated before execution.

## Consequences

- `uv sync --extra dev && uv run pytest` is enough to develop.
- A model cannot "fix" a failing check by rewriting the result.
- The UI can be added later against a stable HTTP contract.
