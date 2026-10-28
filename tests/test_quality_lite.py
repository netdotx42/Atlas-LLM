from pathlib import Path

import polars as pl

from atlas.quality.checks import quality_report, schema_delta


def test_lite_flags_key_constant_and_missing(tmp_path: Path) -> None:
    frame = pl.DataFrame(
        {
            "id": [1, 2, 3, 4, 5],
            "flag": ["x", "x", "x", "x", "x"],
            "note": ["a", "b", None, "d", "e"],
        }
    )
    path = tmp_path / "tiny.parquet"
    frame.write_parquet(path)

    report = quality_report(path, null_error_rate=0.5)
    by_code: dict[str, list[dict]] = {}
    for issue in report["issues"]:
        by_code.setdefault(issue["code"], []).append(issue)

    key = next(item for item in by_code["candidate_key"] if item["column"] == "id")
    assert key["severity"] == "info"
    assert key["metric"] == 5
    assert key["detail"] == "id is unique across 5 rows"

    constant = next(item for item in by_code["constant_column"] if item["column"] == "flag")
    assert constant["severity"] == "warning"
    assert constant["metric"] == 1
    assert constant["detail"] == "flag has a single value"

    missing = next(item for item in by_code["missing_values"] if item["column"] == "note")
    assert missing["severity"] == "warning"
    assert report["status"] == "warn"


def test_info_only_candidate_key_stays_pass(tmp_path: Path) -> None:
    frame = pl.DataFrame({"region": ["north", "south", "east"]})
    path = tmp_path / "clean.parquet"
    frame.write_parquet(path)
    report = quality_report(path, null_error_rate=0.5)
    assert [item["code"] for item in report["issues"]] == ["candidate_key"]
    assert report["issues"][0]["detail"] == "region is unique across 3 rows"
    assert report["status"] == "pass"


def test_schema_delta_removed_type_changed_and_added() -> None:
    previous = {
        "status": {"type": "VARCHAR", "nulls": 0},
        "amount": {"type": "BIGINT", "nulls": 0},
    }
    current = {
        "amount": {"type": "VARCHAR", "nulls": 0},
        "notes": {"type": "VARCHAR", "nulls": 1},
    }
    issues = schema_delta(previous, current)
    assert [(item["code"], item["column"]) for item in issues] == [
        ("schema_removed", "status"),
        ("schema_type_changed", "amount"),
        ("schema_added", "notes"),
    ]
    assert issues[0]["detail"] == "status was removed"
    assert issues[0]["severity"] == "warning"
    assert issues[0]["metric"] == 1
    assert issues[1]["detail"] == "amount type changed from BIGINT to VARCHAR"
    assert issues[1]["metric"] == 1
    assert issues[2]["detail"] == "notes was added"
    assert issues[2]["metric"] == 1
    assert not any(item["code"] == "schema_nulls_gained" for item in issues)


def test_schema_delta_nulls_gained() -> None:
    previous = {"status": {"type": "VARCHAR", "nulls": 0}}
    current = {"status": {"type": "VARCHAR", "nulls": 1}}
    issues = schema_delta(previous, current)
    assert len(issues) == 1
    assert issues[0]["code"] == "schema_nulls_gained"
    assert issues[0]["column"] == "status"
    assert issues[0]["detail"] == "status gained nulls (0 -> 1)"
    assert issues[0]["metric"] == 1
    assert issues[0]["severity"] == "warning"
