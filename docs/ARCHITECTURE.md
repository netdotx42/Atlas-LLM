# Architecture

ATLAS helps analysts understand messy tables and keep reporting pipelines reviewable. DuckDB and Polars do the work. SQLite stores metadata, drafts, and the audit log. Answers and SQL are computed from the file. A local model may only choose a tool; it does not calculate facts and it does not execute.

## Flow

```text
CSV / Parquet
    -> ingest
    -> profile and quality
    -> ask (grounded, or refused)
    -> SQL draft -> approve -> execute
    -> pipeline preview -> approve -> local child dataset
    -> optional local model -> one of the three tools above
```

Hand-written `SELECT` still goes through the same gate. Generated SQL cannot skip the draft. Model output is JSON (`ask`, `sql` spec, or pipeline steps). See [MODEL.md](MODEL.md).

There is no path that writes to a production database. `approve: true` on a pipeline only creates another Parquet file in the local warehouse, with `parent_id` set.

## What the local model is allowed to do

Phi-3.5-mini-instruct (MIT, llama.cpp) returns one JSON object. `ask` is answered by the deterministic router. `sql` is compiled to a `DraftSpec`, gated by `prepare_select`, and stored as `drafted`. `pipeline` is previewed and not written. `executed` is always false. Weights are downloaded by `atlas pull-model` and are not in git. Column ranking uses a local feature-hash embedding.

## Process model

One FastAPI process. DuckDB is opened per query, the file is loaded to an in-memory table, then external access is turned off before the analyst statement runs. The analyst-facing name is `dataset`. The physical name is `ds_<id>`.

Metadata lives in `ATLAS_DATA_DIR/metadata.sqlite`. Warehouse files live in `ATLAS_DATA_DIR/warehouse/<id>.parquet`.
