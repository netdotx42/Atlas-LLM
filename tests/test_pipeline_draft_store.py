from pathlib import Path

from atlas.metadata.store import MetadataStore, PipelineDraftRow

STEPS = '[{"op":"dedupe","columns":[]}]'


def _row(draft_id: str, created_at: str) -> PipelineDraftRow:
    return PipelineDraftRow(
        id=draft_id,
        dataset_id="ds1",
        steps=STEPS,
        status="drafted",
        note="",
        created_at=created_at,
        updated_at=created_at,
    )


def test_pipeline_draft_persists_status_without_parquet(tmp_path: Path) -> None:
    store = MetadataStore(str(tmp_path / "metadata.sqlite"))
    store.add_pipeline_draft(_row("older", "2026-01-01T00:00:00.000000+00:00"))

    listed = store.list_pipeline_drafts("ds1")
    assert len(listed) == 1
    assert listed[0].id == "older"
    assert listed[0].steps == STEPS
    assert listed[0].status == "drafted"

    updated = store.set_pipeline_status("older", "approved")
    assert updated is not None
    assert updated.status == "approved"

    got = store.get_pipeline_draft("older")
    assert got is not None
    assert got.status == "approved"
    assert got.steps == STEPS

    assert list(tmp_path.rglob("*.parquet")) == []
    assert not (tmp_path / "warehouse").exists()

    store.add_pipeline_draft(_row("newer", "2026-01-02T00:00:00.000000+00:00"))
    ordered = store.list_pipeline_drafts("ds1")
    assert [row.id for row in ordered] == ["newer", "older"]
    assert list(tmp_path.rglob("*.parquet")) == []
