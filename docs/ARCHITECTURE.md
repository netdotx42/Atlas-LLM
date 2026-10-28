# Architecture

ATLAS helps analysts understand messy tables and keep reporting pipelines reviewable. The product is Python-first and local-first: DuckDB and Polars do the work, SQLite stores metadata, and a small model is a later phase — not a dependency of quality results.

## This release (phase 1)

```text
CSV / Parquet
    -> ingest (type check, row cap, identifier check)
    -> Parquet warehouse + SQLite registry
    -> profile (DuckDB SUMMARIZE, masked sample)
    -> quality (null rates, exact duplicate rows)
    -> reviewed SQL (allowlist, keyword gate, LIMIT, masking)
```

There is no path that writes to a production database. `ATLAS_READ_ONLY` defaults to true, and ingest refuses to run if it is turned off, because a write-capable mode is not implemented.

## Later, in order

1. Source-grounded natural language over the profile, using a local ~4B commercially permitted model via llama.cpp. Drafts are text, not executed.
2. SQL generation that must pass the same `prepare_select` gate, with a human approval step stored in the audit log.
3. Sandboxed transformation previews (Polars plans shown before they run). No arbitrary Python `exec`.
4. Repeatable workflow docs, a larger test suite, and deployment packaging beyond the current container.

React/TypeScript is the planned UI. Phase 1 is the API the UI will call.

## Process model

One FastAPI process. DuckDB is opened per request against a parquet file named by dataset id. The analyst-facing table name is always `dataset`; the physical name is `ds_<id>` and is not client-controlled.

Metadata and the audit log live in `ATLAS_DATA_DIR/metadata.sqlite`. Warehouse files live in `ATLAS_DATA_DIR/warehouse/<id>.parquet`.
