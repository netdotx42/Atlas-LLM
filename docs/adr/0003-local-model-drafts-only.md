# ADR 0003 — Local model drafts only

## Status

Accepted

## Context

The desk needs a commercially permitted model near 4B parameters, running on the same machine as the warehouse. Answers must stay reproducible when the weights are absent.

## Decision

Use Phi-3.5-mini-instruct (MIT) through llama.cpp. The optional extra is `llama-cpp-python`. Weights download into `var/models/` via `atlas pull-model` and are not committed.

The model returns one JSON tool: `ask`, `sql`, or `pipeline`. Facts for `ask` come from the deterministic router. `sql` is compiled and saved as `drafted`. `pipeline` calls preview only. The response field `executed` is always false. A missing model or invalid JSON does not fall through to an execution path.

Column hints in the prompt are ranked with a local feature-hash embedding. No embedding weights are downloaded.

## Consequences

- Default `uv sync` and CI do not install llama.cpp or download the GGUF.
- Tests inject a scripted completer and never load weights.
- Operators who want drafts run `uv sync --extra model` and `atlas pull-model`.
