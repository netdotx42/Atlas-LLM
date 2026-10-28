# Safety boundaries

| Control | Where |
| --- | --- |
| Approved formats only | `atlas.ingest.loader` |
| Row and byte caps | `Settings` |
| Simple column identifiers | ingest |
| Read-only flag | ingest refuses when `read_only` is false |
| SELECT-only SQL | `atlas.safety.sql.prepare_select` |
| Schema allowlist | physical table injected server-side |
| Query row limit | LIMIT injected or clamped |
| External file access off for the user statement | DuckDB `enable_external_access` |
| Sensitive-field masking | `atlas.safety.mask` |
| Audit log | `metadata.audit_events` |
| No production writes | no such route exists |

Generated SQL, when a local model is added, must call `prepare_select` and must not be executed on rejection. A small model can draft a transformation. It must not run one.
