def draft_prompt(*, question: str, columns: list[str], focused: list[str], quality: str) -> str:
    column_list = ", ".join(columns) if columns else "(none)"
    focus = ", ".join(focused[:8]) if focused else column_list
    return (
        "You draft data-desk actions. You do not calculate new facts and you do not write prose.\n"
        "Return one JSON object and nothing else.\n"
        'Tools: {"tool":"ask"} or '
        '{"tool":"sql","spec":{"select":[],"metrics":[{"fn":"count","alias":"n","column":null}],'
        '"where":[],"order_by":null,"descending":true}} or '
        '{"tool":"pipeline","steps":[{"op":"dedupe","columns":[]}]}.\n'
        "sql spec fields: select (column names), metrics (fn is count, count_distinct, sum, avg, "
        "min, or max; count may omit column), where (op is eq, neq, gt, gte, lt, lte, is_null, "
        "is_not_null), order_by (a select name or metric alias).\n"
        "pipeline op is select, drop_nulls, dedupe, rename, filter, sort, cast, or fill.\n"
        "Use only the columns listed. Never invent tables or SQL text.\n"
        f"Columns: {column_list}\n"
        f"Closest columns: {focus}\n"
        f"Quality: {quality}\n"
        f"Question: {question}"
    )
