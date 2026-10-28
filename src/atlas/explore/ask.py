import re
import tempfile
from pathlib import Path

import duckdb

from atlas.quality.checks import quality_report
from atlas.safety.mask import is_sensitive

_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NUMERIC_TYPE = re.compile(
    r"^(?:TINYINT|SMALLINT|INTEGER|BIGINT|HUGEINT|UTINYINT|USMALLINT|UINTEGER|"
    r"UBIGINT|UHUGEINT|FLOAT|REAL|DOUBLE|DECIMAL|NUMERIC)\b",
    re.IGNORECASE,
)
_STAT_WORDS = {
    "average": "avg",
    "mean": "avg",
    "minimum": "min",
    "maximum": "max",
    "min": "min",
    "max": "max",
}
_STAT_LABEL = {"avg": "average", "min": "minimum", "max": "maximum"}
_STAT_SQL = {"avg": "avg", "min": "min", "max": "max"}
_NAME_A_COLUMN = "Name a column that exists on this dataset."


def answer_question(
    storage_path: Path,
    question: str,
    *,
    dataset_name: str,
    null_error_rate: float,
) -> dict:
    text = " ".join(question.lower().split())
    if storage_path.suffix.lower() == ".parquet":
        return _answer(
            storage_path,
            text,
            dataset_name=dataset_name,
            null_error_rate=null_error_rate,
        )
    with tempfile.TemporaryDirectory() as directory:
        dest = Path(directory) / "dataset.parquet"
        with duckdb.connect() as con:
            con.execute(
                "COPY (SELECT * FROM read_csv_auto(?)) TO ? (FORMAT PARQUET)",
                [str(storage_path), str(dest)],
            )
        return _answer(dest, text, dataset_name=dataset_name, null_error_rate=null_error_rate)


def _answer(
    path: Path,
    text: str,
    *,
    dataset_name: str,
    null_error_rate: float,
) -> dict:
    report = quality_report(path, null_error_rate=null_error_rate)
    columns = _columns(path)
    asked = _asked_column(text, columns)

    # Distinct-count phrases also contain "distinct", which _wants_values() treats
    # as a breakdown. Resolve the count first so it never lists values.
    if _wants_distinct_count(text):
        if asked is None:
            return _no(_NAME_A_COLUMN)
        return _distinct_count(path, dataset_name, asked)
    if _wants_key(text) and not _wants_values(text):
        if asked is None:
            return _no(_NAME_A_COLUMN)
        return _candidate_key(path, dataset_name, asked)
    if asked and is_sensitive(asked):
        return _sensitive(asked)
    if _wants_values(text) and asked:
        return _breakdown(path, dataset_name, asked)
    if _wants_values(text) and not asked:
        return _no(_NAME_A_COLUMN)
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
    stat = _stat_kind(text)
    if stat is not None:
        if asked is None:
            return _no(_NAME_A_COLUMN)
        return _numeric_stat(path, dataset_name, asked, stat)
    if re.search(r"\b(summarize|summary|overview|describe)\b", text):
        return _summary(dataset_name, report, columns)
    return _no(
        "ATLAS only answers from this dataset's schema, profile, and quality checks. "
        "Ask about rows, columns, missing values, duplicates, a breakdown of one column, "
        "min, max, average, distinct count, or a candidate key."
    )


def _breakdown(path: Path, dataset_name: str, column: str) -> dict:
    quoted = _quote_ident(column)
    with duckdb.connect() as con:
        rows = con.execute(
            f"SELECT {quoted}, count(*) AS n FROM read_parquet(?) "
            "GROUP BY 1 ORDER BY n DESC LIMIT 10",
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


def _distinct_count(path: Path, dataset_name: str, column: str) -> dict:
    quoted = _quote_ident(column)
    with duckdb.connect() as con:
        count = con.execute(
            f"SELECT count(DISTINCT {quoted}) FROM read_parquet(?)",
            [str(path)],
        ).fetchone()[0]
    distinct = int(count)
    return _yes(
        f"{column} has {distinct} distinct values in {dataset_name}.",
        [{"source": "aggregate", "detail": f"count_distinct({column})={distinct}"}],
    )


def _candidate_key(path: Path, dataset_name: str, column: str) -> dict:
    quoted = _quote_ident(column)
    with duckdb.connect() as con:
        rows, distinct, nulls = con.execute(
            f"SELECT count(*), count(DISTINCT {quoted}), count(*) - count({quoted}) "
            "FROM read_parquet(?)",
            [str(path)],
        ).fetchone()
    rows, distinct, nulls = int(rows), int(distinct), int(nulls)
    evidence = [
        {"source": "aggregate", "detail": f"rows={rows} distinct={distinct} nulls={nulls}"},
    ]
    if distinct == rows and nulls == 0:
        answer = (
            f"{column} is a candidate key in {dataset_name}: "
            f"{distinct} distinct values across {rows} rows, {nulls} nulls."
        )
    else:
        answer = (
            f"{column} is not a candidate key in {dataset_name}: "
            f"{distinct} distinct values across {rows} rows, {nulls} nulls."
        )
    return _yes(answer, evidence)


def _numeric_stat(path: Path, dataset_name: str, column: str, kind: str) -> dict:
    if is_sensitive(column):
        return _sensitive(column)
    label = _STAT_LABEL[kind]
    sql_fn = _STAT_SQL[kind]
    if not _NUMERIC_TYPE.match(_column_type(path, column)):
        return _no(f"{column} is not numeric, so its {label} cannot be computed.")
    quoted = _quote_ident(column)
    try:
        with duckdb.connect() as con:
            value = con.execute(
                f"SELECT {sql_fn}({quoted}) FROM read_parquet(?)",
                [str(path)],
            ).fetchone()[0]
    except Exception:
        return _no(f"{column} is not numeric, so its {label} cannot be computed.")
    if value is None:
        return _no(f"{column} has no non-null values, so its {label} cannot be computed.")
    shown = _format_number(value)
    return _yes(
        f"The {label} of {column} in {dataset_name} is {shown}.",
        [{"source": "aggregate", "detail": f"{sql_fn}({column})={shown}"}],
    )


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


def _column_type(path: Path, column: str) -> str:
    with duckdb.connect() as con:
        row = con.execute(
            """
            SELECT column_type
            FROM (DESCRIBE SELECT * FROM read_parquet(?))
            WHERE column_name = ?
            """,
            [str(path), column],
        ).fetchone()
    return "" if row is None else str(row[0])


def _asked_column(text: str, columns: list[str]) -> str | None:
    for column in sorted(columns, key=len, reverse=True):
        if re.search(rf"\b{re.escape(column.lower())}\b", text):
            return column
    return None


def _wants_values(text: str) -> bool:
    return bool(re.search(r"\b(values|breakdown|distinct)\b", text))


def _wants_distinct_count(text: str) -> bool:
    return bool(re.search(r"\b(?:how many distinct|distinct count|number of distinct)\b", text))


def _wants_key(text: str) -> bool:
    return bool(re.search(r"\b(?:unique|candidate key|a key)\b", text))


def _stat_kind(text: str) -> str | None:
    match = re.search(r"\b(average|mean|minimum|maximum|min|max)\b", text)
    if match is None:
        return None
    return _STAT_WORDS[match.group(1)]


def _quote_ident(column: str) -> str:
    if not _COLUMN.fullmatch(column):
        raise ValueError("column name is not a simple identifier")
    return f'"{column}"'


def _format_number(value: object) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        rendered = format(value, ".12f").rstrip("0").rstrip(".")
        return rendered or "0"
    text = str(value)
    if "." in text:
        stripped = text.rstrip("0").rstrip(".")
        return stripped or text
    return text


def _sensitive(column: str) -> dict:
    return _yes(
        f"{column} is treated as sensitive, so ATLAS will not list its values.",
        [{"source": "policy", "detail": f"{column} is masked"}],
    )


def _yes(answer: str, evidence: list[dict]) -> dict:
    return {"grounded": True, "answer": answer, "evidence": evidence}


def _no(answer: str) -> dict:
    return {"grounded": False, "answer": answer, "evidence": []}
