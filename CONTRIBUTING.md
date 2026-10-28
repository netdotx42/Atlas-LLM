# Contributing

## Setup

```bash
uv sync --extra dev
cp .env.example .env
uv run pytest
uv run ruff check .
uv run ruff format .
```

Python 3.12 is the CI version. `uv` installs it from `.python-version`.

Optional hooks:

```bash
uv run pre-commit install
```

## Rules for this repository

1. Keep datasets local. Do not add a paid model API, a managed warehouse, or a connector that meters usage.
2. Do not execute model-written SQL or Python until `atlas.safety.sql.prepare_select` (or a successor with tests) has accepted it.
3. New endpoints that touch data must append an audit event.
4. Sensitive-looking columns stay masked. Add a test if you widen what counts as sensitive.
5. This phase does not write back to source systems. A production write needs an explicit approval step that does not exist yet.
6. Prefer deterministic checks over model output for quality results.

## Layout

| Path | Role |
| --- | --- |
| `src/atlas/ingest` | CSV and Parquet intake |
| `src/atlas/profile` | Schema profile and masked sample |
| `src/atlas/quality` | Missing values and duplicate rows |
| `src/atlas/explore` | Grounded questions |
| `src/atlas/sqlgen` | Structured SQL compiler |
| `src/atlas/pipeline` | Preview and approved local copies |
| `src/atlas/safety` | SQL gate and masking |
| `src/atlas/metadata` | SQLite registry and audit log |
| `src/atlas/api` | FastAPI surface |
| `samples/` | Synthetic data only |
