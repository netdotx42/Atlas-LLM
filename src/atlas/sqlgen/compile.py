from atlas.sqlgen.spec import CompileError, DraftSpec, quote_ident, sql_literal

_AGG = {
    "sum": "sum",
    "avg": "avg",
    "min": "min",
    "max": "max",
}
_COMPARE = {
    "eq": "=",
    "neq": "<>",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
}
_JOIN = {"left": "LEFT JOIN", "inner": "INNER JOIN"}


def compile_spec(
    spec: DraftSpec,
    columns: set[str],
    *,
    max_rows: int,
    join_columns: set[str] | None = None,
) -> str:
    """Compile a structured spec into a single SELECT against `dataset`."""
    known = set(columns)
    qualify = spec.join is not None
    if not spec.select and not spec.metrics:
        raise CompileError("Choose columns or a metric")
    for name in spec.select:
        _known(name, known)
    if spec.join is not None:
        _known(spec.join.left, known)
        _known(spec.join.right, set() if join_columns is None else set(join_columns))

    metric_sql: list[str] = []
    aliases: set[str] = set()
    for metric in spec.metrics:
        alias = quote_ident(metric.alias)
        if metric.alias in aliases or metric.alias in spec.select:
            raise CompileError(f"Duplicate select name: {metric.alias}")
        aliases.add(metric.alias)
        if metric.fn == "count" and metric.column is None:
            metric_sql.append(f"count(*) AS {alias}")
            continue
        if not metric.column:
            raise CompileError(f"{metric.fn} needs a column")
        _known(metric.column, known)
        quoted = _expr(metric.column, qualify=qualify)
        if metric.fn == "count":
            metric_sql.append(f"count({quoted}) AS {alias}")
        elif metric.fn == "count_distinct":
            metric_sql.append(f"count(DISTINCT {quoted}) AS {alias}")
        else:
            metric_sql.append(f"{_AGG[metric.fn]}({quoted}) AS {alias}")

    chosen = [_expr(name, qualify=qualify) for name in spec.select]
    select_list = ", ".join([*chosen, *metric_sql])
    where = _where(spec, known, qualify=qualify)
    joined = _join(spec) if spec.join is not None else ""
    group = ""
    if spec.metrics and spec.select:
        group = " GROUP BY " + ", ".join(chosen)
    order = ""
    if spec.order_by:
        if spec.order_by not in set(spec.select) and spec.order_by not in aliases:
            raise CompileError("order_by must be a selected column or metric alias")
        direction = "DESC" if spec.descending else "ASC"
        if spec.order_by in aliases:
            order_expr = quote_ident(spec.order_by)
        else:
            order_expr = _expr(spec.order_by, qualify=qualify)
        order = f" ORDER BY {order_expr} {direction}"
    limit = ""
    if spec.limit is not None:
        limit = f" LIMIT {min(spec.limit, max_rows)}"
    return f"SELECT {select_list} FROM dataset{joined}{where}{group}{order}{limit}"


def _expr(name: str, *, qualify: bool) -> str:
    quoted = quote_ident(name)
    if qualify:
        return f"dataset.{quoted}"
    return quoted


def _join(spec: DraftSpec) -> str:
    join = spec.join
    if join is None:
        return ""
    other = f"ds_{join.dataset_id}"
    left = f"dataset.{quote_ident(join.left)}"
    right = f"{other}.{quote_ident(join.right)}"
    return f" {_JOIN[join.how]} {other} ON {left} = {right}"


def _where(spec: DraftSpec, known: set[str], *, qualify: bool) -> str:
    if not spec.where:
        return ""
    parts: list[str] = []
    for item in spec.where:
        _known(item.column, known)
        column = _expr(item.column, qualify=qualify)
        if item.op == "is_null":
            parts.append(f"{column} IS NULL")
        elif item.op == "is_not_null":
            parts.append(f"{column} IS NOT NULL")
        else:
            if item.op in {"gt", "gte", "lt", "lte"} and not isinstance(item.value, int | float):
                raise CompileError(f"{item.op} needs a number")
            if isinstance(item.value, bool):
                raise CompileError(f"{item.op} needs a number")
            parts.append(f"{column} {_COMPARE[item.op]} {sql_literal(item.value)}")
    return " WHERE " + " AND ".join(parts)


def _known(name: str, known: set[str]) -> None:
    quote_ident(name)
    if name not in known:
        raise CompileError(f"Unknown column: {name}")
