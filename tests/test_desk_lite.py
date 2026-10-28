from pathlib import Path

from fastapi.testclient import TestClient

from atlas.api.app import create_app
from atlas.config import Settings


def _client(tmp_path: Path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "data",
        max_rows=50,
        null_error_rate=0.2,
        read_only=True,
    )
    return TestClient(create_app(settings))


def _upload(client: TestClient, name: str, filename: str, body: str) -> str:
    created = client.post(
        "/datasets",
        data={"name": name},
        files={"file": (filename, body.encode(), "text/csv")},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def test_column_detail_suggestions_and_percent(tmp_path: Path) -> None:
    client = _client(tmp_path)
    sample = (Path(__file__).parents[1] / "samples" / "orders.csv").read_text()
    dataset_id = _upload(client, "Orders", "orders.csv", sample)
    detail = client.get(f"/datasets/{dataset_id}/columns/region")
    assert detail.status_code == 200, detail.text
    assert detail.json()["null_percentage"] == 0.0
    assert detail.json()["top"][0]["value"] == "north"
    masked = client.get(f"/datasets/{dataset_id}/columns/customer_email")
    assert masked.json()["sensitive"] is True
    assert masked.json()["top"] == []
    actions = client.get(f"/datasets/{dataset_id}/suggestions")
    assert actions.status_code == 200
    ids = [item["id"] for item in actions.json()["actions"]]
    assert "dedupe" in ids
    assert any(item.startswith("drop-nulls-") for item in ids)


def test_second_upload_reports_schema_delta(tmp_path: Path) -> None:
    client = _client(tmp_path)
    first = _upload(client, "Orders", "a.csv", "id,status\n1,ok\n")
    second = _upload(client, "Orders", "b.csv", "id,amount\n1,5\n")
    quality = client.get(f"/datasets/{second}/quality")
    assert quality.status_code == 200, quality.text
    codes = {issue["code"] for issue in quality.json()["issues"]}
    assert "schema_removed" in codes
    assert "schema_added" in codes
    untouched = client.get(f"/datasets/{first}/quality")
    assert "schema_removed" not in {issue["code"] for issue in untouched.json()["issues"]}


def test_join_draft_runs_only_after_approval(tmp_path: Path) -> None:
    client = _client(tmp_path)
    orders = (Path(__file__).parents[1] / "samples" / "orders.csv").read_text()
    left = _upload(client, "Orders", "orders.csv", orders)
    right = _upload(
        client,
        "Labels",
        "labels.csv",
        "region,label\nnorth,North\nsouth,South\nwest,West\n",
    )
    drafted = client.post(
        f"/datasets/{left}/sql/drafts",
        json={
            "select": ["region"],
            "metrics": [{"fn": "count", "alias": "n"}],
            "order_by": "n",
            "join": {"dataset_id": right, "left": "region", "right": "region", "how": "left"},
        },
    )
    assert drafted.status_code == 201, drafted.text
    assert "JOIN ds_" in drafted.json()["sql"]
    draft_id = drafted.json()["id"]
    blocked = client.post(f"/datasets/{left}/sql/drafts/{draft_id}/execute")
    assert blocked.status_code == 409
    approved = client.post(
        f"/datasets/{left}/sql/drafts/{draft_id}/decision",
        json={"decision": "approve"},
    )
    assert approved.status_code == 200
    ran = client.post(f"/datasets/{left}/sql/drafts/{draft_id}/execute")
    assert ran.status_code == 200, ran.text
    counts = {row["region"]: row["n"] for row in ran.json()["rows"]}
    assert counts["north"] == 3


def test_cast_preview_does_not_write(tmp_path: Path) -> None:
    client = _client(tmp_path)
    dataset_id = _upload(client, "Amounts", "amounts.csv", "amount,status\n1.5,\n2,paid\n")
    preview = client.post(
        f"/datasets/{dataset_id}/pipeline/preview",
        json={
            "steps": [
                {"op": "cast", "columns": ["amount"], "dtype": "float"},
                {"op": "fill", "columns": ["status"], "fill_value": "unknown"},
            ]
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["writes"] is False
    assert len(client.get("/datasets").json()["datasets"]) == 1
