from typing import Literal

import polars as pl
from pydantic import BaseModel, Field

from atlas.safety.mask import mask_row
from atlas.sqlgen.spec import CompileError, Filter, quote_ident

_COMPARE = {
    "eq": lambda column, value: pl.col(column) == value,
    "neq": lambda column, value: pl.col(column) != value,
    "gt": lambda column, value: pl.col(column) > value,
    "gte": lambda column, value: pl.col(column) >= value,
    "lt": lambda column, value: pl.col(column) < value,
    "lte": lambda column, value: pl.col(column) <= value,
}

_CAST_DTYPES = {
    "string": pl.Utf8,
    "int": pl.Int64,
    "float": pl.Float64,
}


class Step(BaseModel):
    op: Literal["select", "drop_nulls", "dedupe", "rename", "filter", "sort", "cast", "fill"]
    columns: list[str] = Field(default_factory=list)
    rename: dict[str, str] = Field(default_factory=dict)
    where: list[Filter] = Field(default_factory=list)
    descending: bool = False
    dtype: Literal["string", "int", "float"] | None = None
    fill_value: str | int | float | None = None


class PipelineError(ValueError):
    pass


def preview_frame(frame: pl.DataFrame, steps: list[Step], *, sample_rows: int = 5) -> dict:
    output, plan = apply_steps(frame, steps)
    columns = output.columns
    sample = [mask_row(columns, list(row)) for row in output.head(sample_rows).iter_rows()]
    return {
        "plan": plan,
        "input_rows": frame.height,
        "output_rows": output.height,
        "columns": columns,
        "sample": sample,
        "writes": False,
    }


def apply_steps(frame: pl.DataFrame, steps: list[Step]) -> tuple[pl.DataFrame, list[str]]:
    if not steps:
        raise PipelineError("A pipeline needs at least one step")
    plan: list[str] = []
    current = frame
    for index, step in enumerate(steps, start=1):
        current, description = _apply(current, step)
        plan.append(f"{index}. {description}")
    return current, plan


def _apply(frame: pl.DataFrame, step: Step) -> tuple[pl.DataFrame, str]:
    known = set(frame.columns)
    if step.op == "select":
        _require_columns(step.columns, known)
        return frame.select(step.columns), "select " + ", ".join(step.columns)
    if step.op == "drop_nulls":
        _require_columns(step.columns, known, allow_empty=True)
        subset = step.columns or None
        label = ", ".join(step.columns) if step.columns else "all columns"
        return frame.drop_nulls(subset=subset), f"drop nulls on {label}"
    if step.op == "dedupe":
        _require_columns(step.columns, known, allow_empty=True)
        subset = step.columns or None
        label = ", ".join(step.columns) if step.columns else "the full row"
        return frame.unique(subset=subset, keep="first", maintain_order=True), f"dedupe on {label}"
    if step.op == "rename":
        if not step.rename:
            raise PipelineError("rename needs a map")
        for old, new in step.rename.items():
            if old not in known:
                raise PipelineError(f"Unknown column: {old}")
            quote_ident(new)
            if new in known and new not in step.rename:
                raise PipelineError(f"Column already exists: {new}")
        return frame.rename(step.rename), "rename " + ", ".join(
            f"{old}->{new}" for old, new in step.rename.items()
        )
    if step.op == "filter":
        if not step.where:
            raise PipelineError("filter needs at least one condition")
        expr = None
        labels: list[str] = []
        for item in step.where:
            if item.column not in known:
                raise PipelineError(f"Unknown column: {item.column}")
            expr, label = _filter(item, expr)
            labels.append(label)
        return frame.filter(expr), "filter " + " AND ".join(labels)
    if step.op == "sort":
        _require_columns(step.columns, known)
        return (
            frame.sort(step.columns, descending=step.descending),
            "sort " + ", ".join(step.columns),
        )
    if step.op == "cast":
        _require_columns(step.columns, known)
        target = _CAST_DTYPES.get(step.dtype or "")
        if target is None:
            raise PipelineError("cast needs a dtype")
        current = frame
        for name in step.columns:
            try:
                current = current.with_columns(pl.col(name).cast(target, strict=True))
            except (pl.exceptions.PolarsError, TypeError) as exc:
                raise PipelineError(f"Cannot cast {name} to {step.dtype}") from exc
        return current, f"cast {', '.join(step.columns)} to {step.dtype}"
    if step.op == "fill":
        _require_columns(step.columns, known)
        if step.fill_value is None:
            raise PipelineError("fill needs a value")
        current = frame
        for name in step.columns:
            try:
                current = current.with_columns(pl.col(name).fill_null(step.fill_value))
            except (pl.exceptions.PolarsError, TypeError) as exc:
                raise PipelineError(f"Cannot fill {name}") from exc
        return current, f"fill nulls in {', '.join(step.columns)} with {step.fill_value}"
    raise PipelineError(f"Unsupported step: {step.op}")


def _filter(item: Filter, expr: pl.Expr | None) -> tuple[pl.Expr, str]:
    if item.op == "is_null":
        built = pl.col(item.column).is_null()
        label = f"{item.column} is null"
    elif item.op == "is_not_null":
        built = pl.col(item.column).is_not_null()
        label = f"{item.column} is not null"
    else:
        if item.value is None or isinstance(item.value, bool):
            raise PipelineError(f"{item.op} needs a string or number")
        if item.op in {"gt", "gte", "lt", "lte"} and not isinstance(item.value, int | float):
            raise PipelineError(f"{item.op} needs a number")
        try:
            built = _COMPARE[item.op](item.column, item.value)
        except CompileError as exc:
            raise PipelineError(str(exc)) from exc
        label = f"{item.column} {item.op} {item.value}"
    return built if expr is None else expr & built, label


def _require_columns(columns: list[str], known: set[str], *, allow_empty: bool = False) -> None:
    if not columns and not allow_empty:
        raise PipelineError("This step needs columns")
    for name in columns:
        quote_ident(name)
        if name not in known:
            raise PipelineError(f"Unknown column: {name}")
