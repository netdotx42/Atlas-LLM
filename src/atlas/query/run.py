import re
from pathlib import Path

import duckdb

_TABLE = re.compile(r"^ds_[0-9a-f]{32}$")


def run_bound_select(
    storage_path: Path,
    statement: str,
    table: str,
    extras: dict[str, Path] | None = None,
) -> tuple[list[str], list[tuple]]:
    tables = {table: storage_path}
    if extras:
        tables.update(extras)
    for name in tables:
        if not _TABLE.fullmatch(name):
            raise duckdb.Error("Refusing an unexpected table name")
    with duckdb.connect() as con:
        for name, path in tables.items():
            safe = str(path.resolve()).replace("'", "''")
            con.execute(f"CREATE TABLE \"{name}\" AS SELECT * FROM read_parquet('{safe}')")
        con.execute("SET enable_external_access=false")
        cursor = con.execute(statement)
        columns = [item[0] for item in cursor.description]
        return columns, cursor.fetchall()
