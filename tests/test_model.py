from pathlib import Path

from fastapi.testclient import TestClient

from atlas.api.app import create_app
from atlas.config import Settings
from atlas.model.embed import rank_columns
from atlas.model.parse import extract_json
from atlas.model.runtime import model_url


class ScriptedModel:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def status(self) -> dict:
        return {"ready": True, "executes": False, "embeddings": "feature-hash"}

    def complete(self, prompt: str) -> str:
        self.calls += 1
        assert "Columns:" in prompt
        return self.text


def _client(tmp_path: Path, model: ScriptedModel) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "data",
        max_rows=50,
        null_error_rate=0.2,
        read_only=True,
    )
    return TestClient(create_app(settings, completer=model))


def _upload(client: TestClient) -> str:
    sample = Path(__file__).parents[1] / "samples" / "orders.csv"
    with sample.open("rb") as handle:
        created = client.post(
            "/datasets",
            data={"name": "Orders"},
            files={"file": ("orders.csv", handle, "text/csv")},
        )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def test_feature_hash_ranks_the_named_column() -> None:
    ranked = rank_columns("breakdown of region", ["amount", "region", "notes"])
    assert ranked[0] == "region"


def test_model_url_points_at_the_mit_gguf() -> None:
    url = model_url(Settings())
    assert url.startswith("https://huggingface.co/bartowski/Phi-3.5-mini-instruct-GGUF/")
    assert url.endswith("Phi-3.5-mini-instruct-Q4_K_M.gguf")


def test_extracts_json_from_model_chatter() -> None:
    payload = extract_json('Here you go:\n{"tool":"ask"}\nThanks')
    assert payload == {"tool": "ask"}


def test_sql_draft_is_stored_and_not_executed(tmp_path: Path) -> None:
    model = ScriptedModel(
        '{"tool":"sql","spec":{"select":["region"],"metrics":[{"fn":"count","alias":"n"}]}}'
    )
    client = _client(tmp_path, model)
    dataset_id = _upload(client)
    drafted = client.post(
        f"/datasets/{dataset_id}/model/draft",
        json={"question": "count rows by region"},
    )
    assert drafted.status_code == 200, drafted.text
    body = drafted.json()
    assert body["executed"] is False
    assert body["tool"] == "sql"
    assert body["draft"]["status"] == "drafted"
    draft_id = body["draft"]["id"]
    ran = client.post(f"/datasets/{dataset_id}/sql/drafts/{draft_id}/execute")
    assert ran.status_code == 409


def test_pipeline_draft_previews_without_writing(tmp_path: Path) -> None:
    model = ScriptedModel('{"tool":"pipeline","steps":[{"op":"dedupe"}]}')
    client = _client(tmp_path, model)
    dataset_id = _upload(client)
    drafted = client.post(
        f"/datasets/{dataset_id}/model/draft",
        json={"question": "remove duplicate orders"},
    )
    assert drafted.status_code == 200, drafted.text
    assert drafted.json()["preview"]["writes"] is False
    assert drafted.json()["preview"]["output_rows"] == 5
    assert len(client.get("/datasets").json()["datasets"]) == 1


def test_bad_model_json_is_rejected(tmp_path: Path) -> None:
    model = ScriptedModel("I would drop the table.")
    client = _client(tmp_path, model)
    dataset_id = _upload(client)
    drafted = client.post(
        f"/datasets/{dataset_id}/model/draft",
        json={"question": "clean this"},
    )
    assert drafted.status_code == 422
    assert client.get(f"/datasets/{dataset_id}/sql/drafts").json()["drafts"] == []
