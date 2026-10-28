import pytest

from atlas.safety.mask import is_sensitive, mask_value
from atlas.safety.sql import SqlRejected, prepare_select


def test_select_is_limited_and_allowlisted() -> None:
    sql = prepare_select("SELECT * FROM dataset", allow_tables={"dataset"}, max_rows=25)
    assert sql.endswith("LIMIT 25")


def test_limit_is_clamped() -> None:
    sql = prepare_select(
        "SELECT amount FROM dataset LIMIT 99999",
        allow_tables={"dataset"},
        max_rows=100,
    )
    assert sql.endswith("LIMIT 100")


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM dataset",
        "SELECT * FROM dataset; DROP TABLE dataset",
        "SELECT * FROM other",
        "SELECT * FROM dataset -- comment",
        "UPDATE dataset SET amount = 1",
        "COPY dataset TO 'out.csv'",
        "",
    ],
)
def test_unsafe_sql_is_rejected(statement: str) -> None:
    with pytest.raises(SqlRejected):
        prepare_select(statement, allow_tables={"dataset"}, max_rows=10)


def test_sensitive_values_are_masked() -> None:
    assert is_sensitive("customer_email")
    assert mask_value("customer_email", "ada@example.com") == "a***@example.com"
    assert mask_value("amount", 12) == 12
    assert mask_value("api_key", "super-secret") == "***"
