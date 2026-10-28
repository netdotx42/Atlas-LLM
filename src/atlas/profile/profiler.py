from pathlib import Path

import duckdb

from atlas.safety.mask import is_sensitive, mask_row


def profile_dataset(storage_path: Path, *, sample_rows: int = 5) -> dict:
    path = str(storage_path)
    with duckdb.connect() as con:
        summary = _records(con, "SUMMARIZE SELECT * FROM read_parquet(?)", [path])
        described = _records(
            con,
            "SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet(?))",
            [path],
        )
        columns = [row["column_name"] for row in described]
        sample_cursor = con.execute(
            f"SELECT * FROM read_parquet(?) LIMIT {int(sample_rows)}",
            [path],
        )
        sample = sample_cursor.fetchall()

    profiled = []
    for record in summary:
        name = str(record["column_name"])
        sensitive = is_sensitive(name)
        profiled.append(
            {
                "column": name,
                "type": record["column_type"],
                "count": _num(record["count"]),
                "null_percentage": None if sensitive else _num(record["null_percentage"]),
                "approx_unique": None if sensitive else _num(record["approx_unique"]),
                "min": None if sensitive else _text(record["min"]),
                "max": None if sensitive else _text(record["max"]),
                "sensitive": sensitive,
            }
        )
    masked = [mask_row(columns, list(row)) for row in sample]
    return {"columns": profiled, "sample": masked}


def _records(con: duckdb.DuckDBPyConnection, sql: str, params: list) -> list[dict]:
    cursor = con.execute(sql, params)
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _num(value: object) -> float | int | None:
    if value is None:
        return None
    number = float(value)
    if number.is_integer():
        return int(number)
    return round(number, 4)


def _text(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
