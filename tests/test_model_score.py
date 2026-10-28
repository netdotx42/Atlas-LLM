import polars as pl

from atlas.model.score import judge, score_drafter

FRAME = pl.read_csv("/tmp/atlas/samples/orders.csv")
COLUMNS = set(FRAME.columns)

_ANSWERS = {
    "Are there duplicates?": '{"tool":"ask"}',
    "count orders by region": (
        '{"tool":"sql","spec":{"select":["region"],'
        '"metrics":[{"fn":"count","alias":"n"}],"order_by":"n"}}'
    ),
    "dedupe these rows": '{"tool":"pipeline","steps":[{"op":"dedupe","columns":[]}]}',
}


def test_perfect_drafter_passes_once_per_case() -> None:
    assert {"region", "status", "amount"} <= COLUMNS
    calls = {"n": 0}

    def complete(question: str) -> str:
        calls["n"] += 1
        return _ANSWERS[question]

    result = score_drafter(complete, columns=COLUMNS, frame=FRAME)
    assert result["passed"] == 3
    assert result["failed"] == 0
    assert result["total"] == 3
    assert calls["n"] == 3
    compiled = {"ask": False, "sql": True, "pipeline": True}
    for case in result["cases"]:
        assert case["attempts"] == 1
        assert case["writes"] is False
        assert case["outcome"] == "pass"
        assert case["tool"] == case["expect"]
        assert case["compiled"] is compiled[case["expect"]]
        assert case["reason"] == ""


def test_chatter_is_rejected_without_retry() -> None:
    calls = {"n": 0}

    def complete(question: str) -> str:
        calls["n"] += 1
        return "sure, I would drop the table"

    result = score_drafter(complete, columns=COLUMNS, frame=FRAME)
    assert calls["n"] == 3
    assert result["passed"] == 0
    assert result["failed"] == 3
    assert result["total"] == 3
    for case in result["cases"]:
        assert case["attempts"] == 1
        assert case["writes"] is False
        assert case["outcome"] == "reject"
        assert case["compiled"] is False
        assert case["tool"] is None


def test_unknown_sql_column_is_rejected() -> None:
    raw = (
        '{"tool":"sql","spec":{"select":["not_a_column"],'
        '"metrics":[{"fn":"count","alias":"n"}]}}'
    )
    judged = judge(raw, columns=COLUMNS, frame=FRAME, expect="sql")
    assert judged["outcome"] == "reject"
    assert judged["compiled"] is False
    assert judged["attempts"] == 1
    assert judged["writes"] is False
    assert judged["tool"] == "sql"


def test_exec_pipeline_step_is_rejected() -> None:
    judged = judge(
        '{"tool":"pipeline","steps":[{"op":"exec","columns":[]}]}',
        columns=COLUMNS,
        frame=FRAME,
    )
    assert judged["outcome"] == "reject"
    assert judged["compiled"] is False
    assert judged["attempts"] == 1
    assert judged["writes"] is False
    assert judged["tool"] is None
