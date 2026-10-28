# Local model

ATLAS drafts with Phi-3.5-mini-instruct, about 3.8B parameters, MIT license, quantized Q4_K_M for llama.cpp. The weights are not in git.

```bash
uv sync --extra model
uv run atlas pull-model
```

That downloads `Phi-3.5-mini-instruct-Q4_K_M.gguf` into `var/models/`. Override the location with `ATLAS_MODEL_PATH`.

`POST /datasets/{id}/model/draft` sends column names, a feature-hash ranking of those columns, and the quality status. The model must return one JSON tool call:

- `ask` — the deterministic answer from the file
- `sql` — compiled, gated, and saved as a draft
- `pipeline` — previewed, not written

`executed` is always false. Approve on the SQL tab, or approve a pipeline materialize, before anything runs.

Column ranking uses a local feature-hash embedding. It does not download an embedding model and it does not leave the machine.
