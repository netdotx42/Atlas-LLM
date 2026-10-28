import polars as pl
import pytest

from atlas.pipeline.preview import PipelineError, Step, apply_steps, preview_frame


def test_cast_then_fill_keeps_null_amount() -> None:
    frame = pl.DataFrame({"amount": ["1.5", None], "status": ["paid", None]})
    steps = [
        Step(op="cast", columns=["amount"], dtype="float"),
        Step(op="fill", columns=["status"], fill_value="unknown"),
    ]
    preview = preview_frame(frame, steps)
    output, plan = apply_steps(frame, steps)

    assert preview["writes"] is False
    assert preview["output_rows"] == frame.height == 2
    assert plan == [
        "1. cast amount to float",
        "2. fill nulls in status with unknown",
    ]
    assert output["amount"].dtype == pl.Float64
    assert output["amount"].to_list() == [1.5, None]
    assert isinstance(output["amount"][0], float)
    assert output["status"].to_list() == ["paid", "unknown"]


def test_cast_non_numeric_string_to_int_raises() -> None:
    frame = pl.DataFrame({"amount": ["x"]})
    with pytest.raises(PipelineError):
        apply_steps(frame, [Step(op="cast", columns=["amount"], dtype="int")])


def test_dedupe_still_drops_duplicate_row() -> None:
    frame = pl.DataFrame({"amount": ["1.5", "1.5"], "status": ["paid", "paid"]})
    output, plan = apply_steps(frame, [Step(op="dedupe")])
    assert output.height == 1
    assert output.to_dicts() == [{"amount": "1.5", "status": "paid"}]
    assert plan == ["1. dedupe on the full row"]
    preview = preview_frame(frame, [Step(op="dedupe")])
    assert preview["writes"] is False
    assert preview["output_rows"] == 1
