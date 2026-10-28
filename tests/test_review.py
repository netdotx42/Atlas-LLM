from atlas.review.trail import project_review, review_csv

_DRAFT = "a1b2c3d4" * 4


def _event(
    at: str,
    action: str,
    outcome: str,
    detail: str,
    dataset_id: str | None = "ds1",
) -> dict:
    return {
        "created_at": at,
        "action": action,
        "dataset_id": dataset_id,
        "outcome": outcome,
        "detail": detail,
    }


def test_sql_decision_maps_draft_sql_and_dataset() -> None:
    events = [
        _event(
            "2026-01-01T00:00:00Z",
            "sql_decision",
            "approved",
            f"  {_DRAFT}  ",
            dataset_id="ds1",
        )
    ]
    rows = project_review(
        events,
        datasets={"ds1": "Orders"},
        drafts={_DRAFT: "SELECT order_id FROM dataset"},
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["at"] == "2026-01-01T00:00:00Z"
    assert row["dataset_id"] == "ds1"
    assert row["dataset"] == "Orders"
    assert row["action"] == "sql_decision"
    assert row["decision"] == "approved"
    assert row["draft"] == _DRAFT
    assert row["sql"] == "SELECT order_id FROM dataset"
    assert row["rows"] is None
    assert row["detail"] == f"  {_DRAFT}  "


def test_sql_detail_sets_draft_and_rows() -> None:
    events = [_event("2026-01-01T00:00:00Z", "sql", "ok", "draft=abc rows=4")]
    rows = project_review(events, datasets={"ds1": "Orders"}, drafts={"abc": "SELECT 1"})
    assert rows[0]["draft"] == "abc"
    assert rows[0]["rows"] == 4
    assert rows[0]["sql"] == "SELECT 1"


def test_pipeline_materialize_reads_rows_not_parent() -> None:
    events = [
        _event(
            "2026-01-01T00:00:00Z",
            "pipeline_materialize",
            "ok",
            "parent=aaa rows=5",
            dataset_id="child",
        )
    ]
    rows = project_review(
        events,
        datasets={"child": "Derived", "aaa": "Parent"},
        drafts={},
    )
    assert rows[0]["rows"] == 5
    assert rows[0]["draft"] == ""
    assert rows[0]["sql"] == ""
    assert rows[0]["dataset_id"] == "child"
    assert rows[0]["dataset"] == "Derived"


def test_model_draft_drops_ok_and_keeps_rejected() -> None:
    events = [
        _event("2026-01-02T00:00:00Z", "model_draft", "ok", "sql"),
        _event("2026-01-01T00:00:00Z", "model_draft", "rejected", "bad json"),
    ]
    rows = project_review(events, datasets={"ds1": "Orders"}, drafts={})
    assert len(rows) == 1
    assert rows[0]["action"] == "model_draft"
    assert rows[0]["decision"] == "rejected"
    assert rows[0]["draft"] == ""
    assert rows[0]["rows"] is None
    assert rows[0]["detail"] == "bad json"


def test_profile_events_are_dropped() -> None:
    events = [_event("2026-01-01T00:00:00Z", "profile", "ok", "")]
    assert project_review(events, datasets={"ds1": "Orders"}, drafts={}) == []


def test_review_csv_quotes_comma_in_detail() -> None:
    rows = project_review(
        [_event("2026-01-01T00:00:00Z", "sql", "rejected", "bad, query")],
        datasets={"ds1": "Orders"},
        drafts={},
    )
    text = review_csv(rows)
    assert text == (
        "at,dataset,action,decision,draft,rows,detail\n"
        '2026-01-01T00:00:00Z,Orders,sql,rejected,,,"bad, query"\n'
    )


def test_order_is_newest_first_and_stable() -> None:
    events = [
        _event("2026-01-01T00:00:00Z", "sql", "ok", "rows=1"),
        _event("2026-01-01T00:00:00Z", "sql", "rejected", "nope"),
        _event("2026-01-03T00:00:00Z", "sql", "ok", "rows=3"),
        _event(
            "2026-01-02T00:00:00Z",
            "pipeline_materialize",
            "rejected",
            "parent=aaa rows=2",
        ),
        _event("2026-01-04T00:00:00Z", "profile", "ok", ""),
        _event("2026-01-04T00:00:00Z", "sql", "error", "boom"),
    ]
    rows = project_review(events, datasets={}, drafts={})
    assert [row["at"] for row in rows] == [
        "2026-01-03T00:00:00Z",
        "2026-01-02T00:00:00Z",
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:00Z",
    ]
    assert [row["detail"] for row in rows][-2:] == ["rows=1", "nope"]
    assert rows[-2]["rows"] == 1
    assert rows[-1]["rows"] is None
    assert rows[1]["rows"] == 2
