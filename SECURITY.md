# Security

ATLAS is a local-first data tool. Datasets, metadata, and audit logs stay on the machine that runs it.

## Defaults

- Connections and SQL are read-only. This phase has no production write API.
- Uploads are limited to CSV and Parquet, with a size cap and a row cap.
- User SQL is rejected unless it is a single `SELECT`/`WITH` against the allowlisted `dataset` name.
- Comments, stacked statements, and write/admin keywords are rejected before DuckDB sees them.
- Query results are row-limited. DuckDB external access is disabled after the dataset view is bound.
- Columns whose names look like email, phone, secret, token, or similar are masked in profiles, samples, and query results.
- Ingest, profile, quality, and SQL attempts are written to the SQLite audit log.

## Reporting

Open a private security advisory on this repository. Do not file a public issue for an unfixed vulnerability.

Do not send sample rows that contain real personal data.
