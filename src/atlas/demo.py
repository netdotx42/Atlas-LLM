"""A public walkthrough of the sample file. It never writes and never accepts a file."""

from pathlib import Path

import polars as pl

from atlas.explore.ask import answer_question
from atlas.pipeline.preview import Step, preview_frame

QUESTIONS = (
    ("rows", "How many rows?"),
    ("dupes", "Are there duplicates?"),
    ("amount", "What is the sum of amount?"),
)


def build_demo(sample: Path, *, null_error_rate: float) -> dict:
    frame = pl.read_csv(sample)
    preview = preview_frame(frame, [Step(op="dedupe")])
    asks = []
    for key, question in QUESTIONS:
        result = answer_question(
            sample,
            question,
            dataset_name="Orders",
            null_error_rate=null_error_rate,
        )
        asks.append(
            {
                "id": key,
                "question": question,
                "grounded": bool(result.get("grounded")),
                "answer": result.get("answer") if result.get("grounded") else None,
            }
        )
    return {
        "capped": True,
        "name": "Orders",
        "rows": frame.height,
        "columns": frame.width,
        "writes": False,
        "uploads": False,
        "keeps": False,
        "asks": asks,
        "pipeline": {
            "plan": preview["plan"],
            "input_rows": preview["input_rows"],
            "output_rows": preview["output_rows"],
            "writes": False,
        },
    }
