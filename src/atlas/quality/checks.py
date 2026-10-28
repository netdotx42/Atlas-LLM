import re
from pathlib import Path

import duckdb

from atlas.safety.mask import is_sensitive

_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quality_report(storage_path: Path, *, null_error_rate: float) -> dict:
    path = str(storage_path)
    issues: list[dict] = []
    with duckdb.connect() as con:
        row_count = con.execute("SELECT count(*) FROM read_parquet(?)", [path]).fetchone()[0]
        described = con.execute(
            "SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet(?))",
            [path],
        ).fetchall()
        columns = [row[0] for row in described]
        if row_count == 0:
            issues.append(_issue("empty_dataset", "error", None, "Dataset has no rows", 0))
        quoted = ", ".join(f'"{column}"' for column in columns)
        distinct = con.execute(
            f"SELECT count(*) - count(DISTINCT ({quoted})) FROM read_parquet(?)",
            [path],
        ).fetchone()[0]
        if distinct:
            issues.append(
                _issue(
                    "duplicate_rows",
                    "warning",
                    None,
                    f"{int(distinct)} extra rows repeat an earlier row",
                    int(distinct),
                )
            )
        for column in columns:
            if is_sensitive(column) or not _COLUMN.fullmatch(column):
                continue
            nulls, n_distinct = con.execute(
                f'SELECT count(*) FILTER (WHERE "{column}" IS NULL), '
                f'count(DISTINCT "{column}") FROM read_parquet(?)',
                [path],
            ).fetchone()
            nulls = int(nulls or 0)
            n_distinct = int(n_distinct or 0)
            if nulls and row_count:
                rate = nulls / row_count
                severity = "error" if rate >= null_error_rate else "warning"
                issues.append(
                    _issue(
                        "missing_values",
                        severity,
                        column,
                        f"{int(nulls)} missing values ({rate:.1%})",
                        round(rate, 4),
                    )
                )
            if nulls == 0 and n_distinct == row_count and row_count > 0:
                issues.append(
                    _issue(
                        "candidate_key",
                        "info",
                        column,
                        f"{column} is unique across {int(row_count)} rows",
                        n_distinct,
                    )
                )
            if nulls == 0 and n_distinct == 1 and row_count > 1:
                issues.append(
                    _issue(
                        "constant_column",
                        "warning",
                        column,
                        f"{column} has a single value",
                        1,
                    )
                )
    errors = sum(1 for item in issues if item["severity"] == "error")
    warnings = sum(1 for item in issues if item["severity"] == "warning")
    return {
        "row_count": int(row_count),
        "column_count": len(columns),
        "status": "fail" if errors else "warn" if warnings else "pass",
        "issues": issues,
    }


def column_facts(storage_path: Path) -> dict[str, dict]:
    """Column name to type and null count. Used to compare two uploads."""
    path = str(storage_path)
    facts: dict[str, dict] = {}
    with duckdb.connect() as con:
        described = con.execute(
            "SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM read_parquet(?))",
            [path],
        ).fetchall()
        for name, column_type in described:
            if not _COLUMN.fullmatch(str(name)):
                continue
            nulls = con.execute(
                f'SELECT count(*) FROM read_parquet(?) WHERE "{name}" IS NULL',
                [path],
            ).fetchone()[0]
            facts[str(name)] = {"type": str(column_type), "nulls": int(nulls)}
    return facts


def schema_delta(previous: dict[str, dict], current: dict[str, dict]) -> list[dict]:
    issues: list[dict] = []
    for column in previous:
        if column not in current:
            issues.append(_issue("schema_removed", "warning", column, f"{column} was removed", 1))
    for column, spec in current.items():
        if column not in previous:
            issues.append(_issue("schema_added", "warning", column, f"{column} was added", 1))
            continue
        previous_spec = previous[column]
        if previous_spec["type"] != spec["type"]:
            issues.append(
                _issue(
                    "schema_type_changed",
                    "warning",
                    column,
                    f"{column} type changed from {previous_spec['type']} to {spec['type']}",
                    1,
                )
            )
        previous_nulls = int(previous_spec["nulls"])
        current_nulls = int(spec["nulls"])
        if current_nulls > previous_nulls:
            issues.append(
                _issue(
                    "schema_nulls_gained",
                    "warning",
                    column,
                    f"{column} gained nulls ({previous_nulls} -> {current_nulls})",
                    current_nulls - previous_nulls,
                )
            )
    return issues


def _issue(code: str, severity: str, column: str | None, detail: str, metric: float) -> dict:
    return {
        "code": code,
        "severity": severity,
        "column": column,
        "detail": detail,
        "metric": metric,
    }
