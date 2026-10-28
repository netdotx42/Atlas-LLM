from atlas.explore.suggest import suggest_actions


def test_suggests_dedupe_then_drop_nulls() -> None:
    report = {
        "issues": [
            {
                "code": "duplicate_rows",
                "severity": "warning",
                "column": None,
                "detail": "1 extra rows repeat an earlier row",
                "metric": 1,
            },
            {
                "code": "missing_values",
                "severity": "warning",
                "column": "amount",
                "detail": "1 missing values (16.7%)",
                "metric": 0.1667,
            },
        ]
    }
    actions = suggest_actions(report)
    assert len(actions) == 2
    assert actions[0]["id"] == "dedupe"
    assert actions[0]["label"] == "Preview dedupe"
    assert actions[0]["reason"] == "1 extra rows repeat an earlier row"
    assert actions[0]["steps"] == [{"op": "dedupe"}]
    assert actions[1]["id"] == "drop-nulls-amount"
    assert actions[1]["label"] == "Preview drop nulls on amount"
    assert actions[1]["steps"] == [{"op": "drop_nulls", "columns": ["amount"]}]
