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
        ui_dir=Path(__file__).parents[1] / "ui" / "dist",
    )
    return TestClient(create_app(settings))


def test_public_host_gets_share_cards(tmp_path: Path) -> None:
    client = _client(tmp_path)
    page = client.get("/", headers={"x-forwarded-host": "atlas.example"})
    assert page.status_code == 200
    assert 'property="og:image" content="https://atlas.example/og.jpg"' in page.text
    assert 'property="x:game:image" content="https://atlas.example/x-banner.jpg"' in page.text
    assert 'property="og:image:width" content="1200"' in page.text
    assert 'property="x:game:image:height" content="264"' in page.text


def test_local_and_vercel_hosts_get_no_absolute_card(tmp_path: Path) -> None:
    client = _client(tmp_path)
    local = client.get("/", headers={"host": "127.0.0.1:8080"})
    assert 'property="x:game:image"' not in local.text
    vercel = client.get("/", headers={"x-forwarded-host": "atlas.vercel.app"})
    assert 'property="og:image"' not in vercel.text
