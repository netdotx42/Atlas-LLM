from pathlib import Path

import duckdb

from atlas.explore.ask import answer_question

ORDERS = Path(__file__).parents[1] / "samples" / "orders.csv"


def _ask(question: str) -> dict:
    return answer_question(
        ORDERS,
        question,
        dataset_name="Orders",
        null_error_rate=0.2,
    )


def test_average_of_amount() -> None:
    result = _ask("average of amount")
    assert result["grounded"] is True
    assert "76.25" in result["answer"]


def test_max_of_amount() -> None:
    result = _ask("max of amount")
    assert result["grounded"] is True
    assert "120.5" in result["answer"]


def test_how_many_distinct_region_is_not_a_breakdown() -> None:
    result = _ask("how many distinct region")
    assert result["grounded"] is True
    assert "3" in result["answer"]
    assert "Top values" not in result["answer"]
    assert "north" not in result["answer"].lower()


def test_order_id_is_not_a_candidate_key() -> None:
    result = _ask("is order_id a key")
    assert result["grounded"] is True
    assert "not a candidate key" in result["answer"]
    assert "6" in result["answer"]
    assert "5" in result["answer"]


def test_weather_is_ungrounded() -> None:
    result = _ask("what is the weather")
    assert result["grounded"] is False
    assert result["evidence"] == []
    for phrase in ("min", "max", "average", "distinct count", "candidate key"):
        assert phrase in result["answer"]


def test_mean_minimum_and_maximum_aliases() -> None:
    mean = _ask("mean of amount")
    assert mean["grounded"] is True
    assert "76.25" in mean["answer"]
    minimum = _ask("minimum of amount")
    assert minimum["grounded"] is True
    assert "15" in minimum["answer"]
    maximum = _ask("maximum of amount")
    assert maximum["grounded"] is True
    assert "120.5" in maximum["answer"]


def test_distinct_count_phrases() -> None:
    for question in ("distinct count of region", "number of distinct region"):
        result = _ask(question)
        assert result["grounded"] is True
        assert "3" in result["answer"]
        assert "Top values" not in result["answer"]


def test_non_numeric_stat_is_ungrounded() -> None:
    result = _ask("average of region")
    assert result["grounded"] is False
    assert "not numeric" in result["answer"]
    assert result["evidence"] == []


def test_stat_without_a_real_column() -> None:
    for question in ("what is the average", "how many distinct", "is this a key"):
        result = _ask(question)
        assert result["grounded"] is False
        assert result["answer"] == "Name a column that exists on this dataset."


def test_sensitive_stats_are_refused_without_values() -> None:
    result = _ask("average of customer_email")
    assert result["grounded"] is True
    assert "sensitive" in result["answer"]
    assert "ada@" not in result["answer"]


def test_sensitive_uniqueness_is_counts_only() -> None:
    result = _ask("is customer_email a candidate key")
    assert result["grounded"] is True
    assert "candidate key" in result["answer"]
    assert "ada@" not in result["answer"]
    counted = _ask("how many distinct customer_email")
    assert counted["grounded"] is True
    assert "ada@" not in counted["answer"]
    assert "Top values" not in counted["answer"]


def test_existing_routes_still_answer() -> None:
    rows = _ask("how many rows")
    assert rows["grounded"] is True
    assert "6 rows" in rows["answer"]
    breakdown = _ask("breakdown of region")
    assert breakdown["grounded"] is True
    assert breakdown["answer"].startswith("Top values")
    assert "north" in breakdown["answer"]


def test_unique_column_is_a_candidate_key(tmp_path: Path) -> None:
    path = tmp_path / "ids.parquet"
    with duckdb.connect() as con:
        con.execute(
            "COPY (SELECT * FROM (VALUES (1), (2), (3)) t(region_id)) TO ? (FORMAT PARQUET)",
            [str(path)],
        )
    result = answer_question(
        path,
        "is region_id a candidate key",
        dataset_name="Ids",
        null_error_rate=0.2,
    )
    assert result["grounded"] is True
    assert "is a candidate key" in result["answer"]
    assert "not a candidate key" not in result["answer"]
