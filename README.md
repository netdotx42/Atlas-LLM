# ATLAS

Private data-engineering assistant. Python-first, local-first, free to run on data you already have.

ATLAS profiles approved CSV and Parquet files, answers questions from those files, drafts SQL that waits for approval, and previews a small set of transformations before keeping a local copy.

## What it does

- file ingestion, schema profiling, and quality checks
- grounded questions (rows, columns, nulls, duplicates, one-column breakdowns)
- structured SQL drafts with an approve step before execution
- pipeline preview, then an approved child dataset in the local warehouse

It does not call a model API, and it does not write to a production database. The plan is in [docs/UPGRADE.md](docs/UPGRADE.md).

## Develop

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev
uv run pytest
uv run atlas
```

The API listens on `http://127.0.0.1:8000`. Open `/docs`.

```bash
curl -F name=Orders -F file=@samples/orders.csv http://127.0.0.1:8000/datasets
```

Then:

- `POST /datasets/{id}/ask` with `{"question": "Are there duplicates?"}`
- `POST /datasets/{id}/sql/drafts` with columns and metrics, then `.../decision` and `.../execute`
- `POST /datasets/{id}/pipeline/preview` with `{"steps": [{"op": "dedupe"}]}`

Hand-written SQL still uses `POST /datasets/{id}/sql` and the name `dataset`.

## Safety

Read-only toward source systems, query limits, schema allowlists, sensitive-field masking, draft approval, and an audit log. See [docs/SAFETY.md](docs/SAFETY.md) and [SECURITY.md](SECURITY.md).

## Layout

See [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
