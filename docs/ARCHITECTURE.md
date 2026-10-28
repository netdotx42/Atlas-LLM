# Architecture

ATLAS helps analysts understand messy tables and keep reporting pipelines reviewable. DuckDB and Polars do the work. SQLite stores metadata, drafts, and the audit log. Answers and SQL are computed from the file. A model is not on the path.

## Flow

```text
CSV / Parquet
    -> ingest
    -> profile and quality
    -> ask (grounded, or refused)
    -> SQL draft -> approve -> execute
    -> pipeline preview -> approve -> local child dataset
```

Hand-written `SELECT` still goes through the same gate. Generated SQL cannot skip the draft.

There is no path that writes to a production database. `approve: true` on a pipeline only creates another Parquet file in the local warehouse, with `parent_id` set.

## What a later model is allowed to do

Emit a `DraftSpec` or a list of pipeline steps. It must not emit SQL or Python that runs without `prepare_select` and, for generated SQL, a stored approval.

## Process model

One FastAPI process. DuckDB is opened per query, the file is loaded to an in-memory table, then external access is turned off before the analyst statement runs. The analyst-facing name is `dataset`. The physical name is `ds_<id>`.

Metadata lives in `ATLAS_DATA_DIR/metadata.sqlite`. Warehouse files live in `ATLAS_DATA_DIR/warehouse/<id>.parquet`.
