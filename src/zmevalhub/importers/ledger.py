"""Local import claim and recovery marker; Phoenix remains the data store."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, String, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class ImportLedger(Base):
    __tablename__ = "zm_import_ledger"
    __table_args__ = (
        UniqueConstraint("source", "source_run_id", "importer_version"),
        CheckConstraint("status IN ('PENDING', 'DATASET_CALL', 'DATASET_READY', "
                        "'EXPERIMENT_CALL', 'EXPERIMENT_READY', 'RUNS', 'COMPLETE')"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(100))
    source_run_id: Mapped[str] = mapped_column(String(500))
    importer_version: Mapped[str] = mapped_column(String(100))
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    content_sha256: Mapped[str] = mapped_column(String(64))
    dataset_content_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    dataset_id: Mapped[str | None] = mapped_column(String(255))
    dataset_version_id: Mapped[str | None] = mapped_column(String(255))
    experiment_id: Mapped[str | None] = mapped_column(String(255))
    inflight_run_key: Mapped[str | None] = mapped_column(String(1000))


def open_ledger(path: str):
    engine = create_engine(f"sqlite:///{path}", connect_args={"timeout": 30})
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
