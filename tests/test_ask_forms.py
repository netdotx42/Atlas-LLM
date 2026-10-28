from pathlib import Path

import polars as pl

from atlas.explore.ask import answer_question

ORDERS = Path(__file__).parents[1] / "samples" / "orders.csv"


def _ask(question: str, path: Path = ORDERS, name: str = "Orders") -> dict:
    return answer_question(path, question, dataset_name=name, null_error_rate=0.2)


def test_min_and_max_of_amount() -> None:
    result = _ask("min and max of amount")
    assert result["grounded"] is True
    assert "minimum 15" in result["answer"]
    assert "maximum 120.5" in result["answer"]
    assert len(result["evidence"]) == 2


def test_average_amount_by_region() -> None:
    result = _ask("average amount by region")
    assert result["grounded"] is True
    assert "north (120.5)" in result["answer"]
    assert "west (80)" in result["answer"]
    assert "south (30.125)" in result["answer"]
    assert result["evidence"]


def test_orders_have_no_date_column() -> None:
    result = _ask("rows after 2024-01-01")
    assert result["grounded"] is False
    assert result["evidence"] == []
    assert "no date column" in result["answer"]


def test_average_after_a_date(tmp_path: Path) -> None:
    path = tmp_path / "days.parquet"
    pl.DataFrame(
        {
            "ordered_on": ["2024-01-01", "2024-02-01", "2024-03-01"],
            "amount": [10.0, 20.0, 30.0],
        }
    ).write_parquet(path)
    result = _ask("average amount after 2024-01-15", path, "Days")
    assert result["grounded"] is True
    assert "25" in result["answer"]
    assert result["evidence"][0]["detail"].startswith("avg(amount)=25")


def test_sum_of_amount_still_one_metric() -> None:
    result = _ask("sum of amount")
    assert result["grounded"] is True
    assert "381.25" in result["answer"]


def test_compare_region_lists_values() -> None:
    result = _ask("compare region")
    assert result["grounded"] is True
    assert "north" in result["answer"]
    assert "Top values" in result["answer"]
