from pathlib import Path

from fastapi.testclient import TestClient

from atlas.api.app import create_app
from atlas.config import Settings


class SuiteModel:
    def status(self) -> dict:
        return {"ready": True, "executes": False, "embeddings": "feature-hash"}

    def complete(self, prompt: str) -> str:
        if "Are there duplicates?" in prompt:
            return '{"tool":"ask"}'
        if "count orders by region" in prompt:
            return (
                '{"tool":"sql","spec":{"select":["region"],'
                '"metrics":[{"fn":"count","alias":"n"}],"order_by":"n"}}'
            )
        if "dedupe these rows" in prompt:
            return '{"tool":"pipeline","steps":[{"op":"dedupe","columns":[]}]}'
        return "not json"


def _client(tmp_path: Path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "data",
        max_rows=50,
        null_error_rate=0.2,
        read_only=True,
    )
    return TestClient(create_app(settings, completer=SuiteModel()))


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


def test_two_metrics_and_comparison(tmp_path: Path) -> None:
    client = _client(tmp_path)
    dataset_id = _upload(client)
    both = client.post(
        f"/datasets/{dataset_id}/ask",
        json={"question": "min and max of amount"},
    )
    assert both.status_code == 200
    assert both.json()["grounded"] is True
    assert "minimum 15" in both.json()["answer"]
    compared = client.post(
        f"/datasets/{dataset_id}/ask",
        json={"question": "average amount by region"},
    )
    assert "north (120.5)" in compared.json()["answer"]
    missing_date = client.post(
        f"/datasets/{dataset_id}/ask",
        json={"question": "rows after 2024-01-01"},
    )
    assert missing_date.json()["grounded"] is False


def test_pipeline_draft_does_not_write_until_approved(tmp_path: Path) -> None:
    client = _client(tmp_path)
    dataset_id = _upload(client)
    saved = client.post(
        f"/datasets/{dataset_id}/pipeline/drafts",
        json={"steps": [{"op": "dedupe", "columns": []}]},
    )
    assert saved.status_code == 201, saved.text
    body = saved.json()
    assert body["status"] == "drafted"
    assert body["preview"]["writes"] is False
    assert len(client.get("/datasets").json()["datasets"]) == 1
    early = client.post(
        f"/datasets/{dataset_id}/pipeline/drafts/{body['id']}/materialize",
        json={"name": "Deduped"},
    )
    assert early.status_code == 409
    approved = client.post(
        f"/datasets/{dataset_id}/pipeline/drafts/{body['id']}/decision",
        json={"decision": "approve"},
    )
    assert approved.json()["status"] == "approved"
    kept = client.post(
        f"/datasets/{dataset_id}/pipeline/drafts/{body['id']}/materialize",
        json={"name": "Deduped"},
    )
    assert kept.status_code == 201, kept.text
    assert kept.json()["writes_to_production"] is False
    assert kept.json()["row_count"] == 5
    assert len(client.get("/datasets").json()["datasets"]) == 2


def test_review_shows_decision_and_row_count(tmp_path: Path) -> None:
    client = _client(tmp_path)
    dataset_id = _upload(client)
    draft = client.post(
        f"/datasets/{dataset_id}/sql/drafts",
        json={"select": ["region"], "metrics": [{"fn": "count", "alias": "n"}], "order_by": "n"},
    )
    assert draft.status_code == 201, draft.text
    draft_id = draft.json()["id"]
    client.post(
        f"/datasets/{dataset_id}/sql/drafts/{draft_id}/decision",
        json={"decision": "approve"},
    )
    ran = client.post(f"/datasets/{dataset_id}/sql/drafts/{draft_id}/execute")
    assert ran.status_code == 200, ran.text
    events = client.get("/review").json()["events"]
    decision = next(item for item in events if item["action"] == "sql_decision")
    assert decision["decision"] == "approved"
    assert decision["dataset"] == "Orders"
    assert "region" in decision["sql"]
    executed = next(
        item for item in events if item["action"] == "sql" and item["draft"] == draft_id
    )
    assert executed["rows"] == ran.json()["row_count"]
    exported = client.get("/review.csv")
    assert exported.status_code == 200
    assert "sql_decision" in exported.text
    assert "Orders" in exported.text


def test_model_score_is_one_pass_and_writes_nothing(tmp_path: Path) -> None:
    client = _client(tmp_path)
    dataset_id = _upload(client)
    scored = client.post(f"/datasets/{dataset_id}/model/score")
    assert scored.status_code == 200, scored.text
    body = scored.json()
    assert body["passed"] == 3
    assert body["failed"] == 0
    assert all(item["attempts"] == 1 and item["writes"] is False for item in body["cases"])
    assert len(client.get("/datasets").json()["datasets"]) == 1
