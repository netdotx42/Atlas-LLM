from pathlib import Path

from fastapi.testclient import TestClient

from atlas.api.app import create_app
from atlas.config import Settings
from atlas.sqlgen.compile import compile_spec
from atlas.sqlgen.spec import CompileError, DraftSpec, Filter, Metric


def _client(tmp_path: Path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "data",
        max_rows=50,
        null_error_rate=0.2,
        read_only=True,
    )
    return TestClient(create_app(settings))


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


def test_ask_is_grounded_or_refuses(tmp_path: Path) -> None:
    client = _client(tmp_path)
    dataset_id = _upload(client)

    rows = client.post(f"/datasets/{dataset_id}/ask", json={"question": "How many rows?"})
    assert rows.status_code == 200
    assert rows.json()["grounded"] is True
    assert "6 rows" in rows.json()["answer"]

    dupes = client.post(f"/datasets/{dataset_id}/ask", json={"question": "Are there duplicates?"})
    assert "duplicate" in dupes.json()["answer"]

    values = client.post(
        f"/datasets/{dataset_id}/ask",
        json={"question": "breakdown of region"},
    )
    assert values.json()["grounded"] is True
    assert "north" in values.json()["answer"]

    hidden = client.post(
        f"/datasets/{dataset_id}/ask",
        json={"question": "values of customer_email"},
    )
    assert "ada@" not in hidden.json()["answer"]
    assert hidden.json()["grounded"] is True

    unknown = client.post(
        f"/datasets/{dataset_id}/ask",
        json={"question": "What is the customer's favorite color?"},
    )
    assert unknown.json()["grounded"] is False
    assert unknown.json()["evidence"] == []


def test_generated_sql_cannot_run_until_approved(tmp_path: Path) -> None:
    client = _client(tmp_path)
    dataset_id = _upload(client)
    draft = client.post(
        f"/datasets/{dataset_id}/sql/drafts",
        json={
            "select": ["region"],
            "metrics": [{"fn": "count", "alias": "n"}],
            "where": [{"column": "status", "op": "eq", "value": "paid"}],
            "order_by": "n",
        },
    )
    assert draft.status_code == 201, draft.text
    body = draft.json()
    assert body["status"] == "drafted"
    assert "GROUP BY" in body["sql"]
    draft_id = body["id"]

    early = client.post(f"/datasets/{dataset_id}/sql/drafts/{draft_id}/execute")
    assert early.status_code == 409

    approved = client.post(
        f"/datasets/{dataset_id}/sql/drafts/{draft_id}/decision",
        json={"decision": "approve", "note": "checked the grain"},
    )
    assert approved.json()["status"] == "approved"

    ran = client.post(f"/datasets/{dataset_id}/sql/drafts/{draft_id}/execute")
    assert ran.status_code == 200, ran.text
    counts = {row["region"]: row["n"] for row in ran.json()["rows"]}
    assert counts["north"] == 2
    assert counts["west"] == 1

    again = client.post(f"/datasets/{dataset_id}/sql/drafts/{draft_id}/execute")
    assert again.status_code == 409


def test_compiler_rejects_statement_breakout() -> None:
    spec = DraftSpec(
        select=["region"],
        metrics=[Metric(fn="count", alias="n")],
        where=[Filter(column="status", op="eq", value="paid'; DROP TABLE dataset")],
    )
    try:
        compile_spec(spec, {"region", "status"}, max_rows=20)
    except CompileError:
        return
    raise AssertionError("semicolon value was compiled")


def test_pipeline_preview_does_not_write_until_approved(tmp_path: Path) -> None:
    client = _client(tmp_path)
    dataset_id = _upload(client)
    steps = [{"op": "dedupe"}]

    preview = client.post(f"/datasets/{dataset_id}/pipeline/preview", json={"steps": steps})
    assert preview.status_code == 200, preview.text
    assert preview.json()["writes"] is False
    assert preview.json()["input_rows"] == 6
    assert preview.json()["output_rows"] == 5
    assert len(client.get("/datasets").json()["datasets"]) == 1

    refused = client.post(
        f"/datasets/{dataset_id}/pipeline/materialize",
        json={"steps": steps, "approve": False},
    )
    assert refused.status_code == 400
    assert len(client.get("/datasets").json()["datasets"]) == 1

    kept = client.post(
        f"/datasets/{dataset_id}/pipeline/materialize",
        json={"steps": steps, "approve": True, "name": "Orders deduped"},
    )
    assert kept.status_code == 201, kept.text
    assert kept.json()["parent_id"] == dataset_id
    assert kept.json()["writes_to_production"] is False
    assert kept.json()["row_count"] == 5
    listed = client.get("/datasets").json()["datasets"]
    assert len(listed) == 2
    child = next(item for item in listed if item["id"] == kept.json()["id"])
    assert child["parent_id"] == dataset_id
