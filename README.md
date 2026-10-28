# ATLAS

Private data-engineering assistant. Python-first, local-first, free to run on data you already have.

ATLAS profiles approved CSV and Parquet files, explains the schema, flags missing values and duplicate rows, and runs reviewed read-only SQL. Datasets stay on this machine. A small local model can be added later to draft questions and SQL. It is not allowed to execute them.

## Phase 1

This repository is the first build from the product white paper:

- file ingestion
- schema profiling
- deterministic quality checks
- reviewed SQL with a safety gate
- SQLite metadata and an audit log

Not in this phase: llama.cpp, embeddings, a React UI, or any write to a production database.

## Develop

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev
uv run pytest
uv run atlas
```

The API listens on `http://127.0.0.1:8000`. Open `/docs` for the routes.

```bash
curl -F name=Orders -F file=@samples/orders.csv http://127.0.0.1:8000/datasets
```

Then call `/datasets/{id}/profile`, `/datasets/{id}/quality`, and `POST /datasets/{id}/sql` with a body like:

```json
{"sql": "SELECT region, count(*) AS n FROM dataset GROUP BY 1"}
```

Use the name `dataset`. ATLAS binds that to the uploaded file. `DELETE`, other tables, comments, and stacked statements are rejected and audited.

A dev container is in `.devcontainer/` for a clean machine. CI is `.github/workflows/ci.yml`.

## Safety

Read-only by default, query limits, schema allowlists, sensitive-field masking, and an audit log. Details are in [docs/SAFETY.md](docs/SAFETY.md) and [SECURITY.md](SECURITY.md).

## Layout

See [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Agent instructions for this repo live in `.agents/skills/enterprise-developer-setup/SKILL.md`.

## License

Apache-2.0. See [LICENSE](LICENSE).
