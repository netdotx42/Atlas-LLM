from datetime import UTC, datetime

from sqlalchemy import Integer, String, Text, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class DatasetRow(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    source_kind: Mapped[str] = mapped_column(String(16))
    filename: Mapped[str] = mapped_column(String(500))
    storage_path: Mapped[str] = mapped_column(String(1000))
    row_count: Mapped[int] = mapped_column(Integer)
    column_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(40))
    parent_id: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    lineage: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)


class DraftRow(Base):
    __tablename__ = "sql_drafts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(32))
    sql: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class AuditRow(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(64))
    dataset_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16))
    detail: Mapped[str] = mapped_column(Text)


class MetadataStore:
    def __init__(self, sqlite_path: str) -> None:
        self.engine = create_engine(f"sqlite:///{sqlite_path}", future=True)
        self._session = sessionmaker(self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)
        _migrate(self.engine)

    def add_dataset(self, row: DatasetRow) -> None:
        with self._session() as session:
            session.add(row)
            session.commit()

    def get_dataset(self, dataset_id: str) -> DatasetRow | None:
        with self._session() as session:
            row = session.get(DatasetRow, dataset_id)
            if row is not None:
                session.expunge(row)
            return row

    def list_datasets(self) -> list[DatasetRow]:
        with self._session() as session:
            rows = session.scalars(select(DatasetRow).order_by(DatasetRow.created_at.desc())).all()
            session.expunge_all()
            return list(rows)

    def audit(
        self,
        action: str,
        *,
        outcome: str,
        dataset_id: str | None = None,
        detail: str = "",
    ) -> None:
        with self._session() as session:
            session.add(
                AuditRow(
                    created_at=_now(),
                    action=action,
                    dataset_id=dataset_id,
                    outcome=outcome,
                    detail=detail[:4000],
                )
            )
            session.commit()

    def list_audit(self, limit: int = 100) -> list[AuditRow]:
        with self._session() as session:
            rows = session.scalars(select(AuditRow).order_by(AuditRow.id.desc()).limit(limit)).all()
            session.expunge_all()
            return list(rows)

    def add_draft(self, row: DraftRow) -> None:
        with self._session() as session:
            session.add(row)
            session.commit()

    def get_draft(self, draft_id: str) -> DraftRow | None:
        with self._session() as session:
            row = session.get(DraftRow, draft_id)
            if row is not None:
                session.expunge(row)
            return row

    def list_drafts(self, dataset_id: str) -> list[DraftRow]:
        with self._session() as session:
            rows = session.scalars(
                select(DraftRow)
                .where(DraftRow.dataset_id == dataset_id)
                .order_by(DraftRow.created_at.desc())
            ).all()
            session.expunge_all()
            return list(rows)

    def set_draft_status(self, draft_id: str, status: str, note: str = "") -> DraftRow | None:
        with self._session() as session:
            row = session.get(DraftRow, draft_id)
            if row is None:
                return None
            row.status = status
            row.note = note[:1000]
            row.updated_at = _now()
            session.commit()
            session.expunge(row)
            return row


def _migrate(engine) -> None:
    with engine.begin() as conn:
        tables = {
            row[0]
            for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
        if "datasets" not in tables:
            return
        have = {row[1] for row in conn.execute(text("PRAGMA table_info(datasets)"))}
        if "parent_id" not in have:
            conn.execute(text("ALTER TABLE datasets ADD COLUMN parent_id VARCHAR(32)"))
        if "lineage" not in have:
            conn.execute(text("ALTER TABLE datasets ADD COLUMN lineage TEXT"))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")
