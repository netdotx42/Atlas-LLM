import re
from pathlib import Path

import duckdb

_TABLE = re.compile(r"^ds_[0-9a-f]{32}$")


def run_bound_select(
    storage_path: Path,
    statement: str,
    table: str,
) -> tuple[list[str], list[tuple]]:
    if not _TABLE.fullmatch(table):
        raise duckdb.Error("Refusing an unexpected table name")
    path = str(storage_path.resolve()).replace("'", "''")
    with duckdb.connect() as con:
        con.execute(f"CREATE TABLE \"{table}\" AS SELECT * FROM read_parquet('{path}')")
        con.execute("SET enable_external_access=false")
        cursor = con.execute(statement)
        columns = [item[0] for item in cursor.description]
        return columns, cursor.fetchall()
