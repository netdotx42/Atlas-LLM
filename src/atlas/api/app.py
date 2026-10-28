import json
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import duckdb
import polars as pl
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field, ValidationError

from atlas import __version__
from atlas.config import Settings
from atlas.explore.ask import answer_question
from atlas.explore.suggest import suggest_actions
from atlas.ingest.loader import IngestError, ingest_file
from atlas.metadata.store import DatasetRow, DraftRow, MetadataStore, PipelineDraftRow
from atlas.model.draft import build_prompt, parse_draft
from atlas.model.parse import ModelOutputError
from atlas.model.runtime import LlamaCompleter, ModelUnavailable
from atlas.model.score import score_drafter
from atlas.pipeline.preview import PipelineError, Step, apply_steps, preview_frame
from atlas.profile.profiler import column_detail, profile_dataset
from atlas.quality.checks import column_facts, quality_report, schema_delta
from atlas.query.run import run_bound_select
from atlas.review.trail import project_review, review_csv
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


class NameBody(BaseModel):
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


    @app.get("/review")
    def review() -> dict:
        return {"events": _review_rows(store)}

    @app.get("/review.csv")
    def review_export() -> Response:
        return Response(
            review_csv(_review_rows(store)),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=review.csv"},
        )

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
                    "lineage": _lineage(row.lineage),
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
        previous = _previous_same_name(store, row)
        if previous is not None:
            delta = schema_delta(
                column_facts(Path(previous.storage_path)),
                column_facts(Path(row.storage_path)),
            )
            if delta:
                report["issues"] = [*report["issues"], *delta]
                if report["status"] == "pass":
                    report["status"] = "warn"
        store.audit(
            "quality",
            outcome="ok",
            dataset_id=dataset_id,
            detail=report["status"],
        )
        return {"id": row.id, "name": row.name, **report}

    @app.get("/datasets/{dataset_id}/columns/{column}")
    def column(dataset_id: str, column: str) -> dict:
        row = _require(store, dataset_id)
        try:
            detail = column_detail(Path(row.storage_path), column)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return detail

    @app.get("/datasets/{dataset_id}/suggestions")
    def suggestions(dataset_id: str) -> dict:
        row = _require(store, dataset_id)
        report = quality_report(Path(row.storage_path), null_error_rate=settings.null_error_rate)
        return {"actions": suggest_actions(report)}

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
        join_columns: set[str] | None = None
        allow = {"dataset"}
        try:
            if spec.join is not None:
                if spec.join.dataset_id == dataset_id:
                    raise CompileError("Join needs a different dataset")
                other = _require(store, spec.join.dataset_id)
                join_columns = set(_column_names(_warehouse_file(settings, other.storage_path)))
                allow.add(f"ds_{spec.join.dataset_id}")
            sql = compile_spec(
                spec,
                set(columns),
                max_rows=settings.max_rows,
                join_columns=join_columns,
            )
            prepare_select(sql, allow_tables=allow, max_rows=settings.max_rows)
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
            extras = _join_tables(settings, bound, table)
            statement = prepare_select(
                bound,
                allow_tables={table, *extras},
                max_rows=settings.max_rows,
            )
        except SqlRejected as exc:
            store.audit("sql", outcome="rejected", dataset_id=dataset_id, detail=str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        path = _warehouse_file(settings, row.storage_path)
        columns, rows = _execute(
            store,
            dataset_id,
            path,
            table,
            statement,
            extras,
            draft_id=draft_id,
        )
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

    @app.post("/datasets/{dataset_id}/pipeline/drafts", status_code=201)
    def create_pipeline_draft(dataset_id: str, body: PipelineBody) -> dict:
        row = _require(store, dataset_id)
        frame = pl.read_parquet(row.storage_path)
        try:
            report = preview_frame(frame, body.steps)
        except PipelineError as exc:
            store.audit(
                "pipeline_draft",
                outcome="rejected",
                dataset_id=dataset_id,
                detail=str(exc),
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if report.get("writes") is not False:
            raise HTTPException(status_code=400, detail="A pipeline draft cannot write")
        draft = PipelineDraftRow(
            id=uuid4().hex,
            dataset_id=dataset_id,
            steps=json.dumps([step.model_dump() for step in body.steps]),
            status="drafted",
            note="",
            created_at=_now(),
            updated_at=_now(),
        )
        store.add_pipeline_draft(draft)
        store.audit("pipeline_draft", outcome="ok", dataset_id=dataset_id, detail=draft.id)
        return {"preview": report, **_pipeline_payload(draft)}

    @app.get("/datasets/{dataset_id}/pipeline/drafts")
    def list_pipeline_drafts(dataset_id: str) -> dict:
        _require(store, dataset_id)
        drafts = store.list_pipeline_drafts(dataset_id)
        return {"drafts": [_pipeline_payload(item) for item in drafts]}

    @app.post("/datasets/{dataset_id}/pipeline/drafts/{draft_id}/decision")
    def decide_pipeline(dataset_id: str, draft_id: str, body: DecisionBody) -> dict:
        draft = _require_pipeline(store, dataset_id, draft_id)
        if draft.status != "drafted":
            raise HTTPException(status_code=409, detail=f"Draft is already {draft.status}")
        status = "approved" if body.decision == "approve" else "rejected"
        updated = store.set_pipeline_status(draft_id, status, body.note)
        store.audit(
            "pipeline_decision",
            outcome=status,
            dataset_id=dataset_id,
            detail=draft_id,
        )
        return _pipeline_payload(updated)

    @app.post("/datasets/{dataset_id}/pipeline/drafts/{draft_id}/materialize", status_code=201)
    def materialize_pipeline_draft(dataset_id: str, draft_id: str, body: NameBody) -> dict:
        row = _require(store, dataset_id)
        draft = _require_pipeline(store, dataset_id, draft_id)
        if draft.status != "approved":
            store.audit(
                "pipeline_materialize",
                outcome="rejected",
                dataset_id=dataset_id,
                detail="draft not approved",
            )
            raise HTTPException(
                status_code=409,
                detail="Only an approved pipeline draft can be kept",
            )
        steps = [Step.model_validate(item) for item in json.loads(draft.steps)]
        frame = pl.read_parquet(row.storage_path)
        try:
            output, plan = apply_steps(frame, steps)
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
            lineage=draft.steps,
        )
        store.add_dataset(child)
        store.set_pipeline_status(draft_id, "executed", draft.note)
        store.audit(
            "pipeline_materialize",
            outcome="ok",
            dataset_id=child_id,
            detail=f"parent={dataset_id} rows={output.height} draft={draft_id}",
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

    @app.post("/datasets/{dataset_id}/model/score")
    def model_score(dataset_id: str) -> dict:
        row = _require(store, dataset_id)
        if not completer.status().get("ready"):
            store.audit("model_score", outcome="unavailable", dataset_id=dataset_id)
            raise HTTPException(status_code=503, detail="Local model weights are not installed")
        columns = _column_names(Path(row.storage_path))
        quality = quality_report(Path(row.storage_path), null_error_rate=settings.null_error_rate)
        frame = pl.read_parquet(row.storage_path)

        def complete(question: str) -> str:
            return completer.complete(build_prompt(question, columns, quality["status"]))

        report = score_drafter(
            complete,
            columns=set(columns),
            frame=frame,
            max_rows=settings.max_rows,
        )
        store.audit(
            "model_score",
            outcome="ok" if report["failed"] == 0 else "rejected",
            dataset_id=dataset_id,
            detail=f"passed={report['passed']} failed={report['failed']}",
        )
        return report

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


def _lineage(raw: str | None) -> list | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


def _previous_same_name(store: MetadataStore, row: DatasetRow) -> DatasetRow | None:
    earlier = [
        item
        for item in store.list_datasets()
        if item.name == row.name and item.id != row.id and item.created_at < row.created_at
    ]
    if not earlier:
        return None
    return max(earlier, key=lambda item: item.created_at)


def _join_tables(settings: Settings, sql: str, primary: str) -> dict[str, Path]:
    extras: dict[str, Path] = {}
    root = settings.warehouse_dir.resolve()
    for name in set(re.findall(r"\bds_[0-9a-f]{32}\b", sql)):
        if name == primary:
            continue
        path = (root / f"{name[3:]}.parquet").resolve()
        if path.parent != root or not path.is_file():
            raise HTTPException(status_code=400, detail="Join target is outside the warehouse")
        extras[name] = path
    return extras


def _execute(
    store: MetadataStore,
    dataset_id: str,
    path: Path,
    table: str,
    statement: str,
    extras: dict[str, Path] | None = None,
    draft_id: str | None = None,
):
    try:
        columns, rows = run_bound_select(path, statement, table, extras)
    except duckdb.Error as exc:
        store.audit("sql", outcome="error", dataset_id=dataset_id, detail=str(exc))
        raise HTTPException(status_code=400, detail="Query failed validation at execution") from exc
    detail = f"rows={len(rows)}"
    if draft_id:
        detail = f"draft={draft_id} {detail}"
    store.audit("sql", outcome="ok", dataset_id=dataset_id, detail=detail)
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


def _require_pipeline(store: MetadataStore, dataset_id: str, draft_id: str) -> PipelineDraftRow:
    draft = store.get_pipeline_draft(draft_id)
    if draft is None or draft.dataset_id != dataset_id:
        raise HTTPException(status_code=404, detail="Pipeline draft not found")
    return draft


def _pipeline_payload(draft: PipelineDraftRow | None) -> dict:
    if draft is None:
        raise HTTPException(status_code=404, detail="Pipeline draft not found")
    return {
        "id": draft.id,
        "status": draft.status,
        "note": draft.note,
        "steps": json.loads(draft.steps),
        "created_at": draft.created_at,
    }


def _review_rows(store: MetadataStore) -> list[dict]:
    events = [
        {
            "created_at": event.created_at,
            "action": event.action,
            "dataset_id": event.dataset_id,
            "outcome": event.outcome,
            "detail": event.detail,
        }
        for event in store.list_audit(limit=200)
    ]
    datasets = {row.id: row.name for row in store.list_datasets()}
    drafts: dict[str, str] = {}
    for dataset_id in datasets:
        for draft in store.list_drafts(dataset_id):
            drafts[draft.id] = draft.sql
    return project_review(events, datasets=datasets, drafts=drafts)


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
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _share_host(raw: str) -> str:
    host = raw.split(",")[0].strip().split(":")[0].lower()
    if not host or "." not in host or not re.fullmatch(r"[a-z0-9.-]+", host):
        return ""
    if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host):
        return ""
    if host in {"vercel.app", "vercel.com"} or host.endswith((".vercel.app", ".vercel.com")):
        return ""
    return host


def _with_share_tags(html: str, host: str) -> str:
    if not host or 'property="x:game:image"' in html:
        return html
    tags = (
        f'<meta property="og:image" content="https://{host}/og.jpg">'
        '<meta property="og:image:width" content="1200">'
        '<meta property="og:image:height" content="630">'
        '<meta property="og:type" content="x:game">'
        f'<meta property="x:game:image" content="https://{host}/x-banner.jpg">'
        '<meta property="x:game:image:width" content="1200">'
        '<meta property="x:game:image:height" content="264">'
    )
    return html.replace("</head>", tags + "</head>", 1)


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

    def page(request: Request) -> HTMLResponse:
        forwarded = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
        html = _with_share_tags(index.read_text(encoding="utf-8"), _share_host(forwarded))
        return HTMLResponse(html)

    @app.get("/", include_in_schema=False)
    def desk(request: Request) -> HTMLResponse:
        return page(request)

    @app.get("/{full_path:path}", include_in_schema=False, response_model=None)
    def desk_file(full_path: str, request: Request) -> HTMLResponse | FileResponse:
        root = ui_dir.resolve()
        candidate = (ui_dir / full_path).resolve()
        if candidate.is_file() and (candidate == root or root in candidate.parents):
            return FileResponse(candidate)
        return page(request)


app = create_app()
