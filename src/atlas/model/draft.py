from dataclasses import dataclass

from atlas.model.parse import ModelOutputError, extract_json
from atlas.model.prompt import draft_prompt
from atlas.pipeline.preview import Step
from atlas.sqlgen.spec import DraftSpec


@dataclass
class DraftRequest:
    tool: str
    spec: DraftSpec | None = None
    steps: list[Step] | None = None


def parse_draft(text: str) -> DraftRequest:
    payload = extract_json(text)
    tool = payload.get("tool")
    if tool == "ask":
        return DraftRequest(tool="ask")
    if tool == "sql":
        if "spec" not in payload:
            raise ModelOutputError("SQL draft is missing spec")
        return DraftRequest(tool="sql", spec=DraftSpec.model_validate(payload["spec"]))
    if tool == "pipeline":
        raw_steps = payload.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ModelOutputError("Pipeline draft is missing steps")
        return DraftRequest(
            tool="pipeline",
            steps=[Step.model_validate(item) for item in raw_steps],
        )
    raise ModelOutputError("Model tool must be ask, sql, or pipeline")


def build_prompt(question: str, columns: list[str], quality: str) -> str:
    from atlas.model.embed import rank_columns

    focused = rank_columns(question, columns)
    return draft_prompt(question=question, columns=columns, focused=focused, quality=quality)
