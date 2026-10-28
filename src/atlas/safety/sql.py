import re

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|copy|export|import|"
    r"pragma|install|load|call|truncate|grant|revoke|merge|replace|vacuum|set)\b",
    re.IGNORECASE,
)
_FROM = re.compile(r"\b(?:from|join)\s+([A-Za-z_][\w]*)", re.IGNORECASE)
_LIMIT = re.compile(r"\blimit\s+(\d+)\b", re.IGNORECASE)


class SqlRejected(ValueError):
    """User SQL failed the read-only gate. Nothing was executed."""


def prepare_select(sql: str, *, allow_tables: set[str], max_rows: int) -> str:
    """Return a single read-only SELECT, or raise SqlRejected.

    Comments, stacked statements, and anything other than SELECT/WITH are refused.
    Referenced tables must be on the allowlist. LIMIT is injected or clamped.
    """
    text = sql.strip()
    if not text:
        raise SqlRejected("SQL is empty")
    if "--" in text or "/*" in text or "*/" in text:
        raise SqlRejected("Comments are not allowed")
    if text.endswith(";"):
        text = text[:-1].rstrip()
    if ";" in text:
        raise SqlRejected("Multiple statements are not allowed")
    if not re.match(r"^(select|with)\b", text, re.IGNORECASE):
        raise SqlRejected("Only read-only SELECT queries are allowed")
    if _FORBIDDEN.search(text):
        raise SqlRejected("Statement contains a forbidden keyword")

    referenced = {name.lower() for name in _FROM.findall(text)}
    allowed = {name.lower() for name in allow_tables}
    unknown = sorted(referenced - allowed)
    if unknown:
        raise SqlRejected(f"Tables not on the allowlist: {', '.join(unknown)}")
    if not referenced:
        raise SqlRejected("Query must read an allowlisted table")

    match = _LIMIT.search(text)
    if match is None:
        return f"{text} LIMIT {max_rows}"
    if int(match.group(1)) > max_rows:
        return _LIMIT.sub(f"LIMIT {max_rows}", text, count=1)
    return text
