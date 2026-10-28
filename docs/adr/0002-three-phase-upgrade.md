# ADR 0002 — Three-phase upgrade without a model runtime

## Status

Accepted

## Context

The white paper's next work is grounded exploration, reviewed SQL generation, and pipeline previews. A ~4B local model is the planned drafting aid, but downloading and serving weights is a packaging choice, and quality answers must not depend on it.

## Decision

Ship three API phases on the phase-1 warehouse:

1. A deterministic question router whose only sources are schema, aggregates, and the quality report.
2. A structured SQL compiler plus an approval row in SQLite. Execution re-enters `prepare_select`.
3. A fixed set of Polars steps. Preview is side-effect free. Materialize needs `approve: true` and writes only a child dataset.

## Consequences

- Tests can prove a draft does not run early and a preview does not add a dataset.
- A future model is constrained to `DraftSpec` and `Step`. It does not receive a code-execution tool.
- Production writes remain unimplemented.
