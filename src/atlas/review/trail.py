"""Turn audit events into a review list a person can read, plus a CSV export."""

import re

_OUTCOMES: dict[str, frozenset[str] | None] = {
    "sql_decision": None,
    "sql": frozenset({"ok", "rejected"}),
    "pipeline_materialize": None,
    "model_draft": frozenset({"rejected", "unavailable"}),
}

_SQL_DRAFT_ROWS = re.compile(r"^draft=(\S+)\s+rows=(\d+)$")
_SQL_ROWS = re.compile(r"^rows=(\d+)$")
_ROWS = re.compile(r"rows=(\d+)")


def project_review(
    events: list[dict],
    *,
    datasets: dict[str, str],
    drafts: dict[str, str],
) -> list[dict]:
    """Keep reviewable audit events and shape them for a person to read."""
    rows: list[dict] = []
    for event in events:
        action = event.get("action")
        if action not in _OUTCOMES:
            continue
        allowed = _OUTCOMES[action]
        outcome = event.get("outcome")
        if allowed is not None and outcome not in allowed:
            continue
        dataset_id = event.get("dataset_id") or ""
        detail = event.get("detail")
        if detail is None:
            detail = ""
        draft_id, row_count = _parse_detail(action, detail)
        rows.append(
            {
                "at": event.get("created_at"),
                "dataset_id": dataset_id,
                "dataset": datasets.get(dataset_id, ""),
                "action": action,
                "decision": outcome,
                "draft": draft_id,
                "sql": drafts.get(draft_id, "") if draft_id else "",
                "rows": row_count,
                "detail": detail,
            }
        )
    rows.sort(key=lambda item: item["at"], reverse=True)
    return rows


def review_csv(rows: list[dict]) -> str:
    """Render review rows as CSV. The rows column is blank when unknown."""
    header = ["at", "dataset", "action", "decision", "draft", "rows", "detail"]
    lines = [_csv_line(header)]
    for row in rows:
        count = "" if row["rows"] is None else row["rows"]
        lines.append(
            _csv_line(
                [
                    row["at"],
                    row["dataset"],
                    row["action"],
                    row["decision"],
                    row["draft"],
                    count,
                    row["detail"],
                ]
            )
        )
    return "\n".join(lines) + "\n"


def _parse_detail(action: str, detail: str) -> tuple[str, int | None]:
    if action == "sql_decision":
        return detail.strip(), None
    if action == "sql":
        matched = _SQL_DRAFT_ROWS.fullmatch(detail.strip())
        if matched:
            return matched.group(1), int(matched.group(2))
        matched = _SQL_ROWS.fullmatch(detail.strip())
        if matched:
            return "", int(matched.group(1))
        return "", None
    if action == "pipeline_materialize":
        matched = _ROWS.search(detail)
        return "", int(matched.group(1)) if matched else None
    return "", None


def _csv_line(fields: list[object]) -> str:
    return ",".join(_csv_field(field) for field in fields)


def _csv_field(value: object) -> str:
    text = "" if value is None else str(value)
    if "," in text or '"' in text or "\n" in text:
        return '"' + text.replace('"', '""') + '"'
    return text
