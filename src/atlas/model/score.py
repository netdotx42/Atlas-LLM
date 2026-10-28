"""Score a local drafter once per case. A miss is a rejection; nothing is executed."""

from collections.abc import Callable
from typing import Literal, NamedTuple

import polars as pl
from pydantic import ValidationError

from atlas.model.draft import DraftRequest, parse_draft
from atlas.model.parse import ModelOutputError
from atlas.pipeline.preview import PipelineError, preview_frame
from atlas.safety.sql import SqlRejected, prepare_select
from atlas.sqlgen.compile import compile_spec
from atlas.sqlgen.spec import CompileError

Expect = Literal["ask", "sql", "pipeline"]


class Case(NamedTuple):
    id: str
    question: str
    expect: Expect


CASES: tuple[Case, ...] = (
    Case(id="duplicates", question="Are there duplicates?", expect="ask"),
    Case(id="count-region", question="count orders by region", expect="sql"),
    Case(id="dedupe", question="dedupe these rows", expect="pipeline"),
)


def judge(
    raw: str,
    *,
    columns: set[str],
    frame: pl.DataFrame,
    max_rows: int = 1000,
    expect: str | None = None,
) -> dict:
    """Judge one draft. parse_draft runs once; there is no retry and no execution."""
    try:
        proposal = parse_draft(raw)
    except (ModelOutputError, ValidationError) as exc:
        return _verdict(tool=None, outcome="reject", reason=str(exc), compiled=False)

    if expect is not None and proposal.tool != expect:
        return _verdict(
            tool=proposal.tool,
            outcome="reject",
            reason=f"expected {expect}, got {proposal.tool}",
            compiled=False,
        )

    if proposal.tool == "ask":
        return _verdict(tool="ask", outcome="pass", reason="", compiled=False)
    if proposal.tool == "sql":
        return _judge_sql(proposal, columns, max_rows)
    if proposal.tool == "pipeline":
        return _judge_pipeline(frame, proposal)
    return _verdict(
        tool=proposal.tool,
        outcome="reject",
        reason=f"expected ask, sql, or pipeline, got {proposal.tool}",
        compiled=False,
    )


def score_drafter(
    complete: Callable[[str], str],
    *,
    columns: set[str],
    frame: pl.DataFrame,
    max_rows: int = 1000,
) -> dict:
    """Score each case with one completer call. A raised completer is a rejection."""
    scored: list[dict] = []
    for case in CASES:
        try:
            raw = complete(case.question)
        except Exception as exc:
            judged = _verdict(tool=None, outcome="reject", reason=str(exc), compiled=False)
        else:
            judged = judge(
                raw,
                columns=columns,
                frame=frame,
                max_rows=max_rows,
                expect=case.expect,
            )
        scored.append(
            {
                "id": case.id,
                "question": case.question,
                "expect": case.expect,
                **judged,
            }
        )
    passed = sum(item["outcome"] == "pass" for item in scored)
    total = len(CASES)
    return {"cases": scored, "passed": passed, "failed": total - passed, "total": total}


def _judge_sql(proposal: DraftRequest, columns: set[str], max_rows: int) -> dict:
    try:
        if proposal.spec is None:
            raise CompileError("SQL draft is missing spec")
        sql = compile_spec(proposal.spec, columns, max_rows=max_rows)
        prepare_select(sql, allow_tables={"dataset"}, max_rows=max_rows)
    except (CompileError, SqlRejected) as exc:
        return _verdict(tool="sql", outcome="reject", reason=str(exc), compiled=False)
    return _verdict(tool="sql", outcome="pass", reason="", compiled=True)


def _judge_pipeline(frame: pl.DataFrame, proposal: DraftRequest) -> dict:
    try:
        report = preview_frame(frame, proposal.steps or [])
    except PipelineError as exc:
        return _verdict(tool="pipeline", outcome="reject", reason=str(exc), compiled=False)
    if report.get("writes") is not False:
        return _verdict(
            tool="pipeline",
            outcome="reject",
            reason="pipeline draft tried to write",
            compiled=False,
        )
    return _verdict(tool="pipeline", outcome="pass", reason="", compiled=True)


def _verdict(*, tool: str | None, outcome: str, reason: str, compiled: bool) -> dict:
    return {
        "tool": tool,
        "outcome": outcome,
        "reason": reason,
        "attempts": 1,
        "writes": False,
        "compiled": compiled,
    }
