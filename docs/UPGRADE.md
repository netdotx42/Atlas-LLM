# Three-phase upgrade

The first release ingests files, profiles them, and runs checks. This upgrade adds exploration, generated SQL, and pipelines without a paid model and without a write to any system outside the local warehouse.

A local 4B model is intentionally not required. Facts come from DuckDB and Polars. A later model may only fill the same structured request. It never gets a path that executes its own text.

## Phase 1 — Grounded answers

`POST /datasets/{id}/ask`

Questions about row count, columns, missing values, duplicates, a short summary, or the breakdown of one column are answered from that dataset. The response includes the evidence used. Anything else returns `grounded: false` and no invented fact. Sensitive columns are named, not listed.

## Phase 2 — SQL drafts that cannot run early

`POST /datasets/{id}/sql/drafts`

The caller sends columns, metrics, and filters. ATLAS compiles one `SELECT` against `dataset`, then runs it through `prepare_select` before saving it. Status starts at `drafted`.

`POST /datasets/{id}/sql/drafts/{draft_id}/decision` with `approve` or `reject` is the human step and is audited.

`POST .../execute` runs only an `approved` draft, masks the result, and marks it `executed`. A second run is refused. Hand-written SQL on `POST /datasets/{id}/sql` is unchanged: the person sending it is the review.

## Phase 3 — Pipeline preview, then a local copy

Steps are `select`, `drop_nulls`, `dedupe`, `rename`, `filter`, and `sort`. There is no Python `exec`.

`POST /datasets/{id}/pipeline/preview` returns the plan, row counts, and a masked sample. It does not create a dataset.

`POST /datasets/{id}/pipeline/materialize` writes a new Parquet file only when `approve` is true. The child records `parent_id` and the step list. That file stays in the warehouse. Nothing is pushed to a production database.

## Still out of scope

- llama.cpp weights and embeddings
- a React UI
- writes back to source databases
