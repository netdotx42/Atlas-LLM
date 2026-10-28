import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import polars as pl

from atlas.config import Settings
from atlas.metadata.store import DatasetRow, MetadataStore

_NAME = re.compile(r"[^A-Za-z0-9._ -]+")
_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_APPROVED = {".csv": "csv", ".parquet": "parquet"}


class IngestError(ValueError):
    pass


@dataclass(frozen=True)
class Ingested:
    id: str
    name: str
    source_kind: str
    row_count: int
    column_count: int
    columns: list[str]
    storage_path: Path


def ingest_file(
    source: Path,
    *,
    name: str,
    settings: Settings,
    store: MetadataStore,
) -> Ingested:
    if not settings.read_only:
        raise IngestError("Refusing to ingest while read_only is disabled in this phase")
    kind = _APPROVED.get(source.suffix.lower())
    if kind is None:
        raise IngestError("Only CSV and Parquet files are approved")
    size = source.stat().st_size
    if size > settings.max_upload_bytes:
        raise IngestError("File exceeds the upload limit")
    if size == 0:
        raise IngestError("File is empty")

    frame = _read(source, kind)
    if frame.height > settings.max_ingest_rows:
        raise IngestError("File exceeds the row limit")
    if frame.width == 0:
        raise IngestError("File has no columns")
    bad = [column for column in frame.columns if not _COLUMN.match(column)]
    if bad:
        raise IngestError(f"Column names must be simple identifiers: {', '.join(bad)}")

    dataset_id = uuid4().hex
    settings.warehouse_dir.mkdir(parents=True, exist_ok=True)
    dest = settings.warehouse_dir / f"{dataset_id}.parquet"
    frame.write_parquet(dest)

    clean_name = _NAME.sub("", name).strip() or source.stem
    row = DatasetRow(
        id=dataset_id,
        name=clean_name[:200],
        source_kind=kind,
        filename=source.name[:500],
        storage_path=str(dest),
        row_count=frame.height,
        column_count=frame.width,
        created_at=_stamp(),
    )
    store.add_dataset(row)
    store.audit(
        "ingest",
        outcome="ok",
        dataset_id=dataset_id,
        detail=f"{kind} rows={frame.height} cols={frame.width}",
    )
    return Ingested(
        id=dataset_id,
        name=row.name,
        source_kind=kind,
        row_count=frame.height,
        column_count=frame.width,
        columns=frame.columns,
        storage_path=dest,
    )


def _read(source: Path, kind: str) -> pl.DataFrame:
    try:
        if kind == "csv":
            return pl.read_csv(source, infer_schema_length=10_000)
        return pl.read_parquet(source)
    except Exception as exc:  # polars raises several parser errors
        raise IngestError(f"Could not read file: {exc}") from exc


def _stamp() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds")
