import pytest
from pydantic import ValidationError

from atlas.sqlgen.compile import compile_spec
from atlas.sqlgen.spec import CompileError, DraftSpec, JoinSpec, Metric

_NO_JOIN = 'SELECT "region", count(*) AS "n" FROM dataset GROUP BY "region" ORDER BY "n" DESC'


def test_compile_without_join_keeps_unqualified_columns() -> None:
    sql = compile_spec(
        DraftSpec(
            select=["region"],
            metrics=[Metric(fn="count", alias="n")],
            order_by="n",
        ),
        {"region"},
        max_rows=20,
    )
    assert sql == _NO_JOIN


def test_left_join_qualifies_left_and_uses_physical_name() -> None:
    dataset_id = "ab" * 16
    sql = compile_spec(
        DraftSpec(
            select=["region"],
            metrics=[Metric(fn="count", alias="n")],
            order_by="n",
            join=JoinSpec(dataset_id=dataset_id, left="region", right="region", how="left"),
        ),
        {"region"},
        max_rows=20,
        join_columns={"region"},
    )
    expected = (
        'SELECT dataset."region", count(*) AS "n" FROM dataset '
        f'LEFT JOIN ds_{dataset_id} ON dataset."region" = ds_{dataset_id}."region" '
        'GROUP BY dataset."region" ORDER BY "n" DESC'
    )
    assert sql == expected
    assert f"LEFT JOIN ds_{dataset_id}" in sql
    assert f'ON dataset."region" = ds_{dataset_id}."region"' in sql
    assert dataset_id not in sql.replace(f"ds_{dataset_id}", "")


def test_unknown_right_column_raises() -> None:
    with pytest.raises(CompileError, match="Unknown column: zone"):
        compile_spec(
            DraftSpec(
                select=["region"],
                join=JoinSpec(dataset_id="ab" * 16, left="region", right="zone"),
            ),
            {"region"},
            max_rows=20,
            join_columns={"region"},
        )


def test_inner_join() -> None:
    dataset_id = "ab" * 16
    sql = compile_spec(
        DraftSpec(
            select=["region"],
            join=JoinSpec(dataset_id=dataset_id, left="region", right="region", how="inner"),
        ),
        {"region"},
        max_rows=20,
        join_columns={"region"},
    )
    expected = (
        'SELECT dataset."region" FROM dataset '
        f'INNER JOIN ds_{dataset_id} ON dataset."region" = ds_{dataset_id}."region"'
    )
    assert sql == expected
    assert "INNER JOIN" in sql


def test_join_dataset_id_must_be_32_hex() -> None:
    with pytest.raises(ValidationError):
        JoinSpec(dataset_id="ab" * 15, left="region", right="region")
    with pytest.raises(ValidationError):
        JoinSpec(dataset_id="AB" * 16, left="region", right="region")
    with pytest.raises(ValidationError):
        JoinSpec(dataset_id="g" * 32, left="region", right="region")
