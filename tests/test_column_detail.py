from pathlib import Path

import polars as pl
import pytest

from atlas.profile.profiler import column_detail


def test_column_detail_region_and_sensitive_email(tmp_path: Path) -> None:
    path = tmp_path / "tiny.parquet"
    pl.DataFrame(
        {
            "region": ["north", "north", "south"],
            "customer_email": ["ada@example.com", "ada@example.com", None],
        }
    ).write_parquet(path)

    region = column_detail(path, "region")
    assert region["null_percentage"] == 0.0
    assert region["distinct"] == 2
    assert any(item["value"] == "north" and item["n"] == 2 for item in region["top"])
    assert region["sensitive"] is False

    email = column_detail(path, "customer_email")
    assert email["sensitive"] is True
    assert email["top"] == []
    assert email["min"] is None

    with pytest.raises(ValueError, match="Invalid column"):
        column_detail(path, "1bad")
    with pytest.raises(ValueError, match="Unknown column"):
        column_detail(path, "nope")
