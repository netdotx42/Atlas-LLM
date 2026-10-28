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


def test_health_is_read_only(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["read_only"] is True


def test_ingest_profile_quality_and_sql(tmp_path: Path) -> None:
    client = _client(tmp_path)
    sample = Path(__file__).parents[1] / "samples" / "orders.csv"
    with sample.open("rb") as handle:
        created = client.post(
            "/datasets",
            data={"name": "Orders"},
            files={"file": ("orders.csv", handle, "text/csv")},
        )
    assert created.status_code == 201, created.text
    dataset_id = created.json()["id"]
    assert created.json()["row_count"] == 6

    profile = client.get(f"/datasets/{dataset_id}/profile")
    assert profile.status_code == 200
    columns = {item["column"]: item for item in profile.json()["columns"]}
    assert columns["customer_email"]["sensitive"] is True
    assert columns["customer_email"]["min"] is None
    assert "ada@" not in str(profile.json()["sample"])

    quality = client.get(f"/datasets/{dataset_id}/quality")
    assert quality.status_code == 200
    body = quality.json()
    assert body["status"] == "warn"
    codes = {issue["code"] for issue in body["issues"]}
    assert "duplicate_rows" in codes
    assert "missing_values" in codes

    queried = client.post(
        f"/datasets/{dataset_id}/sql",
        json={"sql": "SELECT order_id, customer_email, amount FROM dataset"},
    )
    assert queried.status_code == 200, queried.text
    emails = [row["customer_email"] for row in queried.json()["rows"]]
    assert "a***@example.com" in emails
    assert "ada@example.com" not in emails

    rejected = client.post(
        f"/datasets/{dataset_id}/sql",
        json={"sql": "DELETE FROM dataset"},
    )
    assert rejected.status_code == 400

    audit = client.get("/audit")
    actions = [event["action"] for event in audit.json()["events"]]
    assert "ingest" in actions
    assert "sql" in actions


def test_rejects_unapproved_extension(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post(
        "/datasets",
        data={"name": "notes"},
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
