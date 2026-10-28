import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from atlas.api.app import create_app
from atlas.auth.accounts import stamp
from atlas.config import Settings


def _client(tmp_path: Path, **kwargs) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "data",
        max_rows=50,
        null_error_rate=0.2,
        read_only=True,
        ui_dir=tmp_path / "missing-ui",
        auth_enabled=True,
        stripe_webhook_secret="whsec_test",
        **kwargs,
    )
    return TestClient(create_app(settings))


def _register(client: TestClient, email: str = "ada@example.com") -> None:
    response = client.post("/auth/register", json={"email": email, "password": "correct-horse"})
    assert response.status_code == 201
    assert response.json()["user"]["days_left"] == 14


def test_local_install_stays_open(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", ui_dir=tmp_path / "missing-ui")
    client = TestClient(create_app(settings))
    assert client.get("/auth/session").json()["auth"] is False
    assert client.get("/datasets").status_code == 200


def test_trial_opens_the_desk_and_hides_which_field_failed(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client.get("/datasets").status_code == 401
    _register(client)
    assert client.get("/datasets").status_code == 200
    unknown = client.post(
        "/auth/login", json={"email": "nope@example.com", "password": "correct-horse"}
    )
    wrong = client.post(
        "/auth/login", json={"email": "ada@example.com", "password": "not-the-password"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_five_failures_lock_the_account(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _register(client)
    client.post("/auth/logout")
    for _ in range(5):
        denied = client.post(
            "/auth/login", json={"email": "ada@example.com", "password": "bad-password"}
        )
        assert denied.status_code == 401
    locked = client.post(
        "/auth/login", json={"email": "ada@example.com", "password": "correct-horse"}
    )
    assert locked.status_code == 401
    assert locked.json()["detail"] == "Email or password is wrong"


def test_expired_trial_keeps_files_and_a_pass_reopens(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _register(client)
    store = client.app.state.store
    user = store.user_by_email("ada@example.com")
    user.access_until = stamp(datetime.now(UTC) - timedelta(days=1))
    store.save_user(user)
    blocked = client.get("/datasets")
    assert blocked.status_code == 402
    prices = {item["id"]: item["cents"] for item in client.get("/auth/passes").json()["passes"]}
    assert prices == {"30": 2900, "90": 6900, "365": 17900}
    checkout = client.post("/auth/checkout", json={"plan": "30"})
    assert checkout.status_code == 503
    payload = json.dumps(
        {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_1",
                    "payment_status": "paid",
                    "client_reference_id": user.id,
                    "metadata": {"plan": "30"},
                }
            },
        }
    ).encode()
    signature = _sign("whsec_test", payload)
    paid = client.post("/auth/webhook", content=payload, headers={"stripe-signature": signature})
    assert paid.status_code == 200
    again = client.post("/auth/webhook", content=payload, headers={"stripe-signature": signature})
    assert again.status_code == 200
    fresh = store.get_user(user.id)
    opened = datetime.fromisoformat(fresh.access_until)
    assert opened - datetime.now(UTC) > timedelta(days=29)
    assert client.get("/datasets").status_code == 200


def test_passes_are_public_and_an_open_trial_can_check_out(tmp_path: Path) -> None:
    client = _client(tmp_path)
    public = client.get("/auth/passes")
    assert public.status_code == 200
    assert [item["id"] for item in public.json()["passes"]] == ["30", "90", "365"]
    _register(client)
    checkout = client.post("/auth/checkout", json={"plan": "90"})
    assert checkout.status_code == 503
    assert checkout.json()["detail"] == "Payments are not configured"


def test_bad_webhook_does_not_grant(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post(
        "/auth/webhook", content=b"{}", headers={"stripe-signature": "t=1,v1=nope"}
    )
    assert response.status_code == 400


def _sign(secret: str, payload: bytes) -> str:
    moment = str(int(time.time()))
    digest = hmac.new(secret.encode(), f"{moment}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={moment},v1={digest}"
