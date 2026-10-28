import math
import re
from typing import Literal

from pydantic import BaseModel, Field

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class CompileError(ValueError):
    pass


class Filter(BaseModel):
    column: str
    op: Literal["eq", "neq", "gt", "gte", "lt", "lte", "is_null", "is_not_null"]
    value: str | int | float | None = None


class Metric(BaseModel):
    fn: Literal["count", "count_distinct", "sum", "avg", "min", "max"]
    alias: str
    column: str | None = None


class DraftSpec(BaseModel):
    select: list[str] = Field(default_factory=list)
    metrics: list[Metric] = Field(default_factory=list)
    where: list[Filter] = Field(default_factory=list)
    order_by: str | None = None
    descending: bool = True
    limit: int | None = Field(default=None, ge=1, le=100_000)


def quote_ident(name: str) -> str:
    if not _IDENT.fullmatch(name):
        raise CompileError(f"Invalid identifier: {name}")
    return f'"{name}"'


def sql_literal(value: object) -> str:
    if isinstance(value, bool) or value is None:
        raise CompileError("This filter needs a string or number")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CompileError("Non-finite numbers are not supported")
        return repr(value)
    if isinstance(value, str):
        blocked = any(ord(char) < 32 for char in value) or any(
            token in value for token in (";", "--", "/*")
        )
        if blocked:
            raise CompileError("Value contains a character the SQL gate rejects")
        return "'" + value.replace("'", "''") + "'"
    raise CompileError("Unsupported filter value")
