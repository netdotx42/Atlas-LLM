from pathlib import Path

import duckdb

from atlas.safety.mask import is_sensitive


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
            if is_sensitive(column):
                continue
            nulls = con.execute(
                f'SELECT count(*) FROM read_parquet(?) WHERE "{column}" IS NULL',
                [path],
            ).fetchone()[0]
            if not nulls or not row_count:
                continue
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
    errors = sum(1 for item in issues if item["severity"] == "error")
    warnings = sum(1 for item in issues if item["severity"] == "warning")
    return {
        "row_count": int(row_count),
        "column_count": len(columns),
        "status": "fail" if errors else "warn" if warnings else "pass",
        "issues": issues,
    }


def _issue(code: str, severity: str, column: str | None, detail: str, metric: float) -> dict:
    return {
        "code": code,
        "severity": severity,
        "column": column,
        "detail": detail,
        "metric": metric,
    }
