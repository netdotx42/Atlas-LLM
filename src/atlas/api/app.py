import json
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import duckdb
import polars as pl
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError

from atlas import __version__
from atlas.config import Settings
from atlas.explore.ask import answer_question
from atlas.ingest.loader import IngestError, ingest_file
from atlas.metadata.store import DatasetRow, DraftRow, MetadataStore
from atlas.model.draft import build_prompt, parse_draft
from atlas.model.parse import ModelOutputError
from atlas.model.runtime import LlamaCompleter, ModelUnavailable
from atlas.pipeline.preview import PipelineError, Step, apply_steps, preview_frame
from atlas.profile.profiler import profile_dataset
from atlas.quality.checks import quality_report
from atlas.query.run import run_bound_select
from atlas.safety.mask import mask_row
from atlas.safety.sql import SqlRejected, prepare_select
from atlas.sqlgen.compile import compile_spec
from atlas.sqlgen.spec import CompileError, DraftSpec


class SqlBody(BaseModel):
    sql: str = Field(min_length=1, max_length=8000)


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class DecisionBody(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    note: str = Field(default="", max_length=500)


class PipelineBody(BaseModel):
    steps: list[Step] = Field(min_length=1, max_length=8)
    approve: bool = False
    name: str = Field(default="", max_length=200)


def create_app(settings: Settings | None = None, completer=None) -> FastAPI:
    settings = settings or Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.warehouse_dir.mkdir(parents=True, exist_ok=True)
    store = MetadataStore(str(settings.metadata_path))
    completer = completer or LlamaCompleter(settings)

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
            "sql": "SELECT only. Generated SQL is stored as a draft until approved.",
            "pipeline": "Preview does not write. Materialize stays in the local warehouse.",
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
                    "parent_id": row.parent_id,
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
        columns, rows = _execute(store, dataset_id, path, table, statement)
        return {
            "columns": columns,
            "rows": [mask_row(columns, list(item)) for item in rows],
            "row_count": len(rows),
            "limited_to": settings.max_rows,
        }

    @app.post("/datasets/{dataset_id}/ask")
    def ask(dataset_id: str, body: AskBody) -> dict:
        row = _require(store, dataset_id)
        result = answer_question(
            Path(row.storage_path),
            body.question,
            dataset_name=row.name,
            null_error_rate=settings.null_error_rate,
        )
        store.audit(
            "ask",
            outcome="ok" if result["grounded"] else "ungrounded",
            dataset_id=dataset_id,
        )
        return {"id": row.id, **result}

    @app.post("/datasets/{dataset_id}/sql/drafts", status_code=201)
    def create_draft(dataset_id: str, spec: DraftSpec) -> dict:
        row = _require(store, dataset_id)
        columns = _column_names(Path(row.storage_path))
        try:
            sql = compile_spec(spec, set(columns), max_rows=settings.max_rows)
            prepare_select(sql, allow_tables={"dataset"}, max_rows=settings.max_rows)
        except (CompileError, SqlRejected) as exc:
            store.audit("sql_draft", outcome="rejected", dataset_id=dataset_id, detail=str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        draft = DraftRow(
            id=uuid4().hex,
            dataset_id=dataset_id,
            sql=sql,
            status="drafted",
            note="",
            created_at=_now(),
            updated_at=_now(),
        )
        store.add_draft(draft)
        store.audit("sql_draft", outcome="ok", dataset_id=dataset_id, detail=draft.id)
        return _draft_payload(draft)

    @app.get("/datasets/{dataset_id}/sql/drafts")
    def list_drafts(dataset_id: str) -> dict:
        _require(store, dataset_id)
        return {"drafts": [_draft_payload(item) for item in store.list_drafts(dataset_id)]}

    @app.post("/datasets/{dataset_id}/sql/drafts/{draft_id}/decision")
    def decide_draft(dataset_id: str, draft_id: str, body: DecisionBody) -> dict:
        draft = _require_draft(store, dataset_id, draft_id)
        if draft.status != "drafted":
            raise HTTPException(status_code=409, detail=f"Draft is already {draft.status}")
        status = "approved" if body.decision == "approve" else "rejected"
        updated = store.set_draft_status(draft_id, status, body.note)
        store.audit("sql_decision", outcome=status, dataset_id=dataset_id, detail=draft_id)
        return _draft_payload(updated)

    @app.post("/datasets/{dataset_id}/sql/drafts/{draft_id}/execute")
    def execute_draft(dataset_id: str, draft_id: str) -> dict:
        row = _require(store, dataset_id)
        draft = _require_draft(store, dataset_id, draft_id)
        if draft.status != "approved":
            store.audit(
                "sql",
                outcome="rejected",
                dataset_id=dataset_id,
                detail="draft not approved",
            )
            raise HTTPException(status_code=409, detail="Only an approved draft can run")
        table = f"ds_{dataset_id}"
        bound = _bind_dataset(draft.sql, table)
        try:
            statement = prepare_select(bound, allow_tables={table}, max_rows=settings.max_rows)
        except SqlRejected as exc:
            store.audit("sql", outcome="rejected", dataset_id=dataset_id, detail=str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        path = _warehouse_file(settings, row.storage_path)
        columns, rows = _execute(store, dataset_id, path, table, statement)
        store.set_draft_status(draft_id, "executed", draft.note)
        return {
            "draft_id": draft_id,
            "columns": columns,
            "rows": [mask_row(columns, list(item)) for item in rows],
            "row_count": len(rows),
            "limited_to": settings.max_rows,
        }

    @app.post("/datasets/{dataset_id}/pipeline/preview")
    def pipeline_preview(dataset_id: str, body: PipelineBody) -> dict:
        row = _require(store, dataset_id)
        frame = pl.read_parquet(row.storage_path)
        try:
            report = preview_frame(frame, body.steps)
        except PipelineError as exc:
            store.audit(
                "pipeline_preview",
                outcome="rejected",
                dataset_id=dataset_id,
                detail=str(exc),
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.audit(
            "pipeline_preview",
            outcome="ok",
            dataset_id=dataset_id,
            detail=f"rows={report['output_rows']}",
        )
        return {"id": row.id, **report}

    @app.post("/datasets/{dataset_id}/pipeline/materialize", status_code=201)
    def pipeline_materialize(dataset_id: str, body: PipelineBody) -> dict:
        if not body.approve:
            raise HTTPException(
                status_code=400,
                detail="Set approve=true to keep a derived dataset",
            )
        row = _require(store, dataset_id)
        frame = pl.read_parquet(row.storage_path)
        try:
            output, plan = apply_steps(frame, body.steps)
        except PipelineError as exc:
            store.audit(
                "pipeline_materialize",
                outcome="rejected",
                dataset_id=dataset_id,
                detail=str(exc),
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if output.height > settings.max_ingest_rows:
            raise HTTPException(status_code=400, detail="Derived dataset exceeds the row limit")
        child_id = uuid4().hex
        settings.warehouse_dir.mkdir(parents=True, exist_ok=True)
        dest = settings.warehouse_dir / f"{child_id}.parquet"
        output.write_parquet(dest)
        clean = re.sub(r"[^A-Za-z0-9._ -]+", "", body.name).strip() or f"{row.name} pipeline"
        child = DatasetRow(
            id=child_id,
            name=clean[:200],
            source_kind="pipeline",
            filename=f"lineage:{dataset_id}"[:500],
            storage_path=str(dest),
            row_count=output.height,
            column_count=output.width,
            created_at=_now(),
            parent_id=dataset_id,
            lineage=json.dumps([step.model_dump() for step in body.steps]),
        )
        store.add_dataset(child)
        store.audit(
            "pipeline_materialize",
            outcome="ok",
            dataset_id=child_id,
            detail=f"parent={dataset_id} rows={output.height}",
        )
        return {
            "id": child_id,
            "name": child.name,
            "parent_id": dataset_id,
            "row_count": output.height,
            "column_count": output.width,
            "plan": plan,
            "writes_to_production": False,
        }

    @app.get("/model")
    def model_status() -> dict:
        return completer.status()

    @app.post("/datasets/sample", status_code=201)
    def load_sample() -> dict:
        sample = _sample_csv()
        if sample is None:
            raise HTTPException(status_code=404, detail="Sample file is not available")
        try:
            ingested = ingest_file(sample, name="Orders", settings=settings, store=store)
        except IngestError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "id": ingested.id,
            "name": ingested.name,
            "source_kind": ingested.source_kind,
            "row_count": ingested.row_count,
            "column_count": ingested.column_count,
            "columns": ingested.columns,
        }

    @app.post("/datasets/{dataset_id}/model/draft")
    def model_draft(dataset_id: str, body: AskBody) -> dict:
        row = _require(store, dataset_id)
        columns = _column_names(Path(row.storage_path))
        quality = quality_report(Path(row.storage_path), null_error_rate=settings.null_error_rate)
        prompt = build_prompt(body.question, columns, quality["status"])
        try:
            raw = completer.complete(prompt)
            proposal = parse_draft(raw)
        except ModelUnavailable as exc:
            store.audit("model_draft", outcome="unavailable", dataset_id=dataset_id)
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (ModelOutputError, ValidationError, CompileError) as exc:
            store.audit("model_draft", outcome="rejected", dataset_id=dataset_id, detail=str(exc))
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        result: dict = {
            "tool": proposal.tool,
            "executed": False,
            "draft": None,
            "preview": None,
            "answer": None,
        }
        if proposal.tool == "ask":
            result["answer"] = answer_question(
                Path(row.storage_path),
                body.question,
                dataset_name=row.name,
                null_error_rate=settings.null_error_rate,
            )
        elif proposal.tool == "sql" and proposal.spec is not None:
            try:
                sql = compile_spec(proposal.spec, set(columns), max_rows=settings.max_rows)
                prepare_select(sql, allow_tables={"dataset"}, max_rows=settings.max_rows)
            except (CompileError, SqlRejected) as exc:
                store.audit(
                    "model_draft",
                    outcome="rejected",
                    dataset_id=dataset_id,
                    detail=str(exc),
                )
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            draft = DraftRow(
                id=uuid4().hex,
                dataset_id=dataset_id,
                sql=sql,
                status="drafted",
                note="local model",
                created_at=_now(),
                updated_at=_now(),
            )
            store.add_draft(draft)
            result["draft"] = _draft_payload(draft)
        elif proposal.tool == "pipeline" and proposal.steps is not None:
            frame = pl.read_parquet(row.storage_path)
            try:
                result["preview"] = preview_frame(frame, proposal.steps)
            except PipelineError as exc:
                store.audit(
                    "model_draft",
                    outcome="rejected",
                    dataset_id=dataset_id,
                    detail=str(exc),
                )
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            result["steps"] = [step.model_dump() for step in proposal.steps]
        store.audit("model_draft", outcome="ok", dataset_id=dataset_id, detail=proposal.tool)
        return result

    _mount_ui(app, settings.ui_dir)
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


def _execute(store: MetadataStore, dataset_id: str, path: Path, table: str, statement: str):
    try:
        columns, rows = run_bound_select(path, statement, table)
    except duckdb.Error as exc:
        store.audit("sql", outcome="error", dataset_id=dataset_id, detail=str(exc))
        raise HTTPException(status_code=400, detail="Query failed validation at execution") from exc
    store.audit("sql", outcome="ok", dataset_id=dataset_id, detail=f"rows={len(rows)}")
    return columns, rows


def _column_names(path: Path) -> list[str]:
    with duckdb.connect() as con:
        rows = con.execute(
            "SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet(?))",
            [str(path)],
        ).fetchall()
    return [row[0] for row in rows]


def _require_draft(store: MetadataStore, dataset_id: str, draft_id: str) -> DraftRow:
    draft = store.get_draft(draft_id)
    if draft is None or draft.dataset_id != dataset_id:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


def _draft_payload(draft: DraftRow | None) -> dict:
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    return {
        "id": draft.id,
        "dataset_id": draft.dataset_id,
        "sql": draft.sql,
        "status": draft.status,
        "note": draft.note,
        "created_at": draft.created_at,
        "updated_at": draft.updated_at,
    }


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _sample_csv() -> Path | None:
    candidates = [
        Path("samples/orders.csv"),
        Path(__file__).resolve().parents[3] / "samples" / "orders.csv",
    ]
    return next((path for path in candidates if path.is_file()), None)


def _mount_ui(app: FastAPI, ui_dir: Path) -> None:
    index = ui_dir / "index.html"
    if not index.is_file():
        return

    @app.get("/", include_in_schema=False)
    def desk():
        return FileResponse(index)

    @app.get("/{full_path:path}", include_in_schema=False)
    def desk_file(full_path: str):
        root = ui_dir.resolve()
        candidate = (ui_dir / full_path).resolve()
        if candidate.is_file() and (candidate == root or root in candidate.parents):
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
