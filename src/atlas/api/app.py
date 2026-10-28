import re
from pathlib import Path

import duckdb
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from atlas import __version__
from atlas.config import Settings
from atlas.ingest.loader import IngestError, ingest_file
from atlas.metadata.store import MetadataStore
from atlas.profile.profiler import profile_dataset
from atlas.quality.checks import quality_report
from atlas.safety.mask import mask_row
from atlas.safety.sql import SqlRejected, prepare_select


class SqlBody(BaseModel):
    sql: str = Field(min_length=1, max_length=8000)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.warehouse_dir.mkdir(parents=True, exist_ok=True)
    store = MetadataStore(str(settings.metadata_path))

    app = FastAPI(
        title="ATLAS",
        version=__version__,
        summary="Private data-engineering assistant. Read-only by default.",
    )
    app.state.settings = settings
    app.state.store = store

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__, "read_only": settings.read_only}

    @app.get("/safety")
    def safety() -> dict:
        return {
            "read_only": settings.read_only,
            "max_rows": settings.max_rows,
            "max_ingest_rows": settings.max_ingest_rows,
            "writes_to_production": False,
            "sql": "SELECT only, allowlisted dataset, comments rejected, LIMIT clamped",
        }

    @app.get("/audit")
    def audit() -> dict:
        events = store.list_audit()
        return {
            "events": [
                {
                    "id": event.id,
                    "created_at": event.created_at,
                    "action": event.action,
                    "dataset_id": event.dataset_id,
                    "outcome": event.outcome,
                    "detail": event.detail,
                }
                for event in events
            ]
        }

    @app.post("/datasets", status_code=201)
    async def create_dataset(name: str = Form(...), file: UploadFile = File(...)) -> dict:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".csv", ".parquet"}:
            raise HTTPException(status_code=400, detail="Only CSV and Parquet files are approved")
        payload = await file.read()
        if len(payload) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="File exceeds the upload limit")
        staging = settings.data_dir / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        staged = staging / f"upload{suffix}"
        staged.write_bytes(payload)
        try:
            ingested = ingest_file(staged, name=name, settings=settings, store=store)
        except IngestError as exc:
            store.audit("ingest", outcome="rejected", detail=str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            staged.unlink(missing_ok=True)
        return {
            "id": ingested.id,
            "name": ingested.name,
            "source_kind": ingested.source_kind,
            "row_count": ingested.row_count,
            "column_count": ingested.column_count,
            "columns": ingested.columns,
        }

    @app.get("/datasets")
    def list_datasets() -> dict:
        rows = store.list_datasets()
        return {
            "datasets": [
                {
                    "id": row.id,
                    "name": row.name,
                    "source_kind": row.source_kind,
                    "row_count": row.row_count,
                    "column_count": row.column_count,
                    "created_at": row.created_at,
                }
                for row in rows
            ]
        }

    @app.get("/datasets/{dataset_id}/profile")
    def profile(dataset_id: str) -> dict:
        row = _require(store, dataset_id)
        report = profile_dataset(Path(row.storage_path))
        store.audit("profile", outcome="ok", dataset_id=dataset_id)
        return {"id": row.id, "name": row.name, **report}

    @app.get("/datasets/{dataset_id}/quality")
    def quality(dataset_id: str) -> dict:
        row = _require(store, dataset_id)
        report = quality_report(Path(row.storage_path), null_error_rate=settings.null_error_rate)
        store.audit(
            "quality",
            outcome="ok",
            dataset_id=dataset_id,
            detail=report["status"],
        )
        return {"id": row.id, "name": row.name, **report}

    @app.post("/datasets/{dataset_id}/sql")
    def query(dataset_id: str, body: SqlBody) -> dict:
        row = _require(store, dataset_id)
        table = f"ds_{dataset_id}"
        bound = _bind_dataset(body.sql, table)
        try:
            statement = prepare_select(
                bound,
                allow_tables={table},
                max_rows=settings.max_rows,
            )
        except SqlRejected as exc:
            store.audit("sql", outcome="rejected", dataset_id=dataset_id, detail=str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        path = _warehouse_file(settings, row.storage_path)
        try:
            with duckdb.connect() as con:
                escaped = str(path).replace("'", "''")
                con.execute(f"CREATE TABLE \"{table}\" AS SELECT * FROM read_parquet('{escaped}')")
                con.execute("SET enable_external_access=false")
                cursor = con.execute(statement)
                columns = [item[0] for item in cursor.description]
                rows = cursor.fetchall()
        except duckdb.Error as exc:
            store.audit("sql", outcome="error", dataset_id=dataset_id, detail=str(exc))
            raise HTTPException(
                status_code=400,
                detail="Query failed validation at execution",
            ) from exc
        store.audit("sql", outcome="ok", dataset_id=dataset_id, detail=f"rows={len(rows)}")
        return {
            "columns": columns,
            "rows": [mask_row(columns, list(item)) for item in rows],
            "row_count": len(rows),
            "limited_to": settings.max_rows,
        }

    return app


def _warehouse_file(settings: Settings, storage_path: str) -> Path:
    path = Path(storage_path).resolve()
    root = settings.warehouse_dir.resolve()
    if path.parent != root or path.suffix != ".parquet" or not path.stem.isalnum():
        raise HTTPException(status_code=400, detail="Dataset is outside the warehouse")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Dataset file is missing")
    return path


def _require(store: MetadataStore, dataset_id: str):
    row = store.get_dataset(dataset_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    if not Path(row.storage_path).is_file():
        raise HTTPException(status_code=404, detail="Dataset file is missing")
    return row


def _bind_dataset(sql: str, table: str) -> str:
    """Analysts write `dataset`. The physical table name never comes from the client."""
    return re.sub(r"\bdataset\b", table, sql, flags=re.IGNORECASE)


app = create_app()
