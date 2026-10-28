import re

_SENSITIVE = re.compile(
    r"(email|e-mail|phone|mobile|ssn|social|password|passwd|secret|token|"
    r"api[_-]?key|credit|card|dob|birth|address)",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"^([^@\s]+)@([^@\s]+)$")


def is_sensitive(column: str) -> bool:
    return bool(_SENSITIVE.search(column))


def mask_value(column: str, value: object) -> object:
    if value is None or not is_sensitive(column):
        return value
    text = str(value)
    if text == "":
        return text
    match = _EMAIL.match(text)
    if match:
        local, domain = match.group(1), match.group(2)
        return f"{local[:1]}***@{domain}"
    return "***"


def mask_row(columns: list[str], row: list[object]) -> dict[str, object]:
    return {column: mask_value(column, value) for column, value in zip(columns, row, strict=True)}
