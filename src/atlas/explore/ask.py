import re
from pathlib import Path

import duckdb

from atlas.quality.checks import quality_report
from atlas.safety.mask import is_sensitive

_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def answer_question(
    storage_path: Path,
    question: str,
    *,
    dataset_name: str,
    null_error_rate: float,
) -> dict:
    text = " ".join(question.lower().split())
    report = quality_report(storage_path, null_error_rate=null_error_rate)
    columns = _columns(storage_path)
    asked = _asked_column(text, columns)

    if asked and is_sensitive(asked):
        return _yes(
            f"{asked} is treated as sensitive, so ATLAS will not list its values.",
            [{"source": "policy", "detail": f"{asked} is masked"}],
        )
    if _wants_values(text) and asked:
        return _breakdown(storage_path, dataset_name, asked)
    if _wants_values(text) and not asked:
        return _no("Name a column that exists on this dataset.")
    if re.search(r"\bduplicate", text):
        return _duplicates(dataset_name, report)
    if re.search(r"\b(missing|null|incomplete)\b", text):
        return _missing(dataset_name, report)
    if re.search(r"\b(how many rows|row count|number of rows)\b", text):
        return _yes(
            f"{dataset_name} has {report['row_count']} rows.",
            [{"source": "quality", "detail": f"row_count={report['row_count']}"}],
        )
    if re.search(r"\b(columns|schema|fields)\b", text):
        listed = ", ".join(columns) if columns else "none"
        return _yes(
            f"{dataset_name} has {len(columns)} columns: {listed}.",
            [{"source": "schema", "detail": listed}],
        )
    if re.search(r"\b(summarize|summary|overview|describe)\b", text):
        return _summary(dataset_name, report, columns)
    return _no(
        "ATLAS only answers from this dataset's schema, profile, and quality checks. "
        "Ask about rows, columns, missing values, duplicates, or a breakdown of one column."
    )


def _breakdown(path: Path, dataset_name: str, column: str) -> dict:
    with duckdb.connect() as con:
        rows = con.execute(
            f'SELECT "{column}", count(*) AS n FROM read_parquet(?) '
            f"GROUP BY 1 ORDER BY n DESC LIMIT 10",
            [str(path)],
        ).fetchall()
    parts = []
    evidence = []
    for value, count in rows:
        label = "null" if value is None else str(value)
        parts.append(f"{label} ({int(count)})")
        evidence.append({"source": "aggregate", "detail": f"{column}={label} n={int(count)}"})
    shown = ", ".join(parts) if parts else "no values"
    return _yes(f"Top values of {column} in {dataset_name}: {shown}.", evidence)


def _duplicates(name: str, report: dict) -> dict:
    extra = next((item for item in report["issues"] if item["code"] == "duplicate_rows"), None)
    if extra is None:
        return _yes(
            f"{name} has no exact duplicate rows.",
            [{"source": "quality", "detail": "duplicate_rows=0"}],
        )
    return _yes(
        f"{name} has {int(extra['metric'])} extra duplicate rows.",
        [{"source": "quality", "detail": extra["detail"]}],
    )


def _missing(name: str, report: dict) -> dict:
    issues = [item for item in report["issues"] if item["code"] == "missing_values"]
    if not issues:
        return _yes(
            f"{name} has no missing values in non-sensitive columns.",
            [{"source": "quality", "detail": "missing_values=0"}],
        )
    listed = ", ".join(f"{item['column']} ({item['detail']})" for item in issues)
    evidence = [
        {"source": "quality", "detail": item["detail"], "column": item["column"]} for item in issues
    ]
    return _yes(f"{name} has missing values in {listed}.", evidence)


def _summary(name: str, report: dict, columns: list[str]) -> dict:
    return _yes(
        (
            f"{name}: {report['row_count']} rows, {len(columns)} columns, "
            f"quality {report['status']}, {len(report['issues'])} findings."
        ),
        [
            {"source": "quality", "detail": f"status={report['status']}"},
            {"source": "schema", "detail": ", ".join(columns)},
        ],
    )


def _columns(path: Path) -> list[str]:
    with duckdb.connect() as con:
        rows = con.execute(
            "SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet(?))",
            [str(path)],
        ).fetchall()
    return [row[0] for row in rows if _COLUMN.fullmatch(row[0])]


def _asked_column(text: str, columns: list[str]) -> str | None:
    for column in sorted(columns, key=len, reverse=True):
        if re.search(rf"\b{re.escape(column.lower())}\b", text):
            return column
    return None


def _wants_values(text: str) -> bool:
    return bool(re.search(r"\b(values|breakdown|distinct)\b", text))


def _yes(answer: str, evidence: list[dict]) -> dict:
    return {"grounded": True, "answer": answer, "evidence": evidence}


def _no(answer: str) -> dict:
    return {"grounded": False, "answer": answer, "evidence": []}
