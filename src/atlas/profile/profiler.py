import re
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


_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def column_detail(storage_path: Path, column: str, *, limit: int = 8) -> dict:
    if _COLUMN.fullmatch(column) is None:
        raise ValueError("Invalid column")
    path = str(storage_path)
    with duckdb.connect() as con:
        described = _records(
            con,
            "SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM read_parquet(?))",
            [path],
        )
        types = {str(row["column_name"]): str(row["column_type"]) for row in described}
        if column not in types:
            raise ValueError("Unknown column")
        row_count = int(con.execute("SELECT count(*) FROM read_parquet(?)", [path]).fetchone()[0])
        nulls = int(
            con.execute(
                f'SELECT count(*) FROM read_parquet(?) WHERE "{column}" IS NULL',
                [path],
            ).fetchone()[0]
        )
        distinct = int(
            con.execute(
                f'SELECT count(DISTINCT "{column}") FROM read_parquet(?)',
                [path],
            ).fetchone()[0]
        )
        sensitive = is_sensitive(column)
        if sensitive:
            minimum = None
            maximum = None
            top: list[dict] = []
        else:
            bounds = con.execute(
                f'SELECT min("{column}") AS min_value, max("{column}") AS max_value '
                "FROM read_parquet(?)",
                [path],
            ).fetchone()
            minimum = _text(bounds[0])
            maximum = _text(bounds[1])
            ranked = con.execute(
                f'SELECT "{column}" AS value, count(*) AS n FROM read_parquet(?) '
                f"GROUP BY 1 ORDER BY n DESC LIMIT {int(limit)}",
                [path],
            ).fetchall()
            top = [{"value": _text(value), "n": int(count)} for value, count in ranked]
    if row_count == 0:
        null_percentage = 0.0
    else:
        null_percentage = round(nulls / row_count * 100, 1)
    return {
        "column": column,
        "type": types[column],
        "nulls": nulls,
        "null_percentage": float(null_percentage),
        "distinct": distinct,
        "min": minimum,
        "max": maximum,
        "sensitive": sensitive,
        "top": top,
    }
