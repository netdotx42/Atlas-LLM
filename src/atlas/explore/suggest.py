def suggest_actions(report: dict) -> list[dict]:
    """Map quality issues to reviewable actions. Does not run them."""
    actions: list[dict] = []
    for issue in report.get("issues") or []:
        code = issue.get("code")
        column = issue.get("column")
        detail = issue.get("detail")
        if code == "duplicate_rows":
            actions.append(
                {
                    "id": "dedupe",
                    "label": "Preview dedupe",
                    "reason": detail,
                    "steps": [{"op": "dedupe"}],
                }
            )
        elif code == "missing_values" and column:
            actions.append(
                {
                    "id": f"drop-nulls-{column}",
                    "label": f"Preview drop nulls on {column}",
                    "reason": detail,
                    "steps": [{"op": "drop_nulls", "columns": [column]}],
                }
            )
        elif code == "constant_column" and column:
            actions.append(
                {
                    "id": f"constant-{column}",
                    "label": f"{column} is a single value",
                    "reason": detail,
                    "steps": [],
                }
            )
    return actions
