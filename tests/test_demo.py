from pathlib import Path

from fastapi.testclient import TestClient

from atlas.api.app import create_app
from atlas.config import Settings


def test_demo_is_public_and_cannot_write(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        ui_dir=tmp_path / "missing-ui",
        auth_enabled=True,
    )
    client = TestClient(create_app(settings))
    denied = client.get("/datasets")
    assert denied.status_code == 401
    demo = client.get("/demo")
    assert demo.status_code == 200
    body = demo.json()
    assert body["capped"] is True
    assert body["writes"] is False
    assert body["uploads"] is False
    assert body["keeps"] is False
    assert body["rows"] == 6
    assert [item["id"] for item in body["asks"]] == ["rows", "dupes", "amount"]
    assert all(item["grounded"] for item in body["asks"])
    assert body["pipeline"]["writes"] is False
    assert body["pipeline"]["output_rows"] < body["pipeline"]["input_rows"]
    assert client.get("/datasets").status_code == 401
