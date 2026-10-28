import json


class ModelOutputError(ValueError):
    pass


def extract_json(text: str) -> dict:
    start = text.find("{")
    if start < 0:
        raise ModelOutputError("Model did not return JSON")
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text[start:], start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    payload = json.loads(text[start : index + 1])
                except json.JSONDecodeError as exc:
                    raise ModelOutputError("Model JSON could not be parsed") from exc
                if not isinstance(payload, dict):
                    raise ModelOutputError("Model JSON must be an object")
                return payload
    raise ModelOutputError("Model JSON was incomplete")
