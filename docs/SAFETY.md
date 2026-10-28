# Safety boundaries

| Control | Where |
| --- | --- |
| Approved formats only | `atlas.ingest.loader` |
| Row and byte caps | `Settings` |
| Simple column identifiers | ingest and the SQL compiler |
| Read-only external posture | no route writes outside the warehouse |
| SELECT-only SQL | `atlas.safety.sql.prepare_select` |
| Generated SQL is a draft | `sql_drafts.status` must be `approved` |
| Schema allowlist | physical table injected server-side |
| Query row limit | LIMIT injected or clamped |
| External file access off for the user statement | DuckDB `enable_external_access` |
| Sensitive-field masking | `atlas.safety.mask` |
| Grounded answers only | `atlas.explore.ask` returns no evidence when it does not know |
| Pipeline steps are a fixed set | `atlas.pipeline.preview` |
| Preview does not write | materialize requires `approve: true` |
| Audit log | `metadata.audit_events` |
| No production writes | no such route exists |

A small model, when added, may draft a spec. Rejection by the compiler or by a person means nothing runs.
