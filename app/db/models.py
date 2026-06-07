from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ScanRun(Base):
    __tablename__ = "t_scan_run"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'success', 'failed', 'partial_success')",
            name="chk_scan_run_status",
        ),
    )

    scan_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running")
    root_paths: Mapped[list[str]] = mapped_column(JSONB, default=list)
    total_files_found: Mapped[int] = mapped_column(Integer, default=0)
    inserted_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    deleted_marked_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class File(Base):
    __tablename__ = "t_file"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'deleted', 'error', 'skipped')",
            name="chk_t_file_status",
        ),
    )

    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    file_path: Mapped[str] = mapped_column(Text)
    normalized_path: Mapped[str] = mapped_column(Text)
    path_hash: Mapped[str] = mapped_column(String(64), unique=True)
    file_name: Mapped[str] = mapped_column(Text)
    extension: Mapped[str] = mapped_column(String(20))
    parent_path: Mapped[str] = mapped_column(Text)
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    last_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    file_hash: Mapped[str | None] = mapped_column(String(64))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="active")
    is_archive: Mapped[bool] = mapped_column(Boolean, default=False)
    archive_reason: Mapped[str | None] = mapped_column(Text)
    system_name: Mapped[str | None] = mapped_column(Text)
    project_name: Mapped[str | None] = mapped_column(Text)
    document_type: Mapped[str | None] = mapped_column(Text)
    year_label: Mapped[str | None] = mapped_column(Text)
    version_label: Mapped[str | None] = mapped_column(Text)
    latest_group_key: Mapped[str | None] = mapped_column(Text)
    is_latest_candidate: Mapped[bool] = mapped_column(Boolean, default=False)
    folder_keywords: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    path_keywords: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    search_text: Mapped[str] = mapped_column(Text, default="")
    content_preview: Mapped[str | None] = mapped_column(Text)
    file_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    first_seen_scan_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_scan_run.scan_run_id")
    )
    last_seen_scan_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_scan_run.scan_run_id")
    )
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chunks: Mapped[list[FileChunk]] = relationship(
        back_populates="file", cascade="all, delete-orphan", order_by="FileChunk.chunk_index"
    )
    acls: Mapped[list[FileAcl]] = relationship(back_populates="file", cascade="all, delete-orphan")


class FileChunk(Base):
    __tablename__ = "t_file_chunk"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('body', 'sheet', 'page', 'slide', 'text', 'metadata')",
            name="chk_t_file_chunk_source_type",
        ),
    )

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("t_file.file_id"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    source_type: Mapped[str] = mapped_column(String(30), default="body")
    sheet_name: Mapped[str | None] = mapped_column(Text)
    page_no: Mapped[int | None] = mapped_column(Integer)
    slide_no: Mapped[int | None] = mapped_column(Integer)
    heading: Mapped[str | None] = mapped_column(Text)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    content_text: Mapped[str] = mapped_column(Text)
    content_summary: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    file: Mapped[File] = relationship(back_populates="chunks")


class FileAcl(Base):
    __tablename__ = "t_file_acl"

    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_file.file_id"), primary_key=True
    )
    principal_type: Mapped[str] = mapped_column(String(20), primary_key=True)
    principal_name: Mapped[str] = mapped_column(Text, primary_key=True)
    permission: Mapped[str] = mapped_column(String(30), primary_key=True, default="read")
    can_read: Mapped[bool] = mapped_column(Boolean, default=True)
    inherited: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    file: Mapped[File] = relationship(back_populates="acls")


class ScanError(Base):
    __tablename__ = "t_scan_error"

    scan_error_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    scan_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("t_scan_run.scan_run_id")
    )
    file_path: Mapped[str | None] = mapped_column(Text)
    error_type: Mapped[str] = mapped_column(Text)
    error_message: Mapped[str] = mapped_column(Text)
    traceback: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SearchLog(Base):
    __tablename__ = "t_search_log"
    __table_args__ = (
        CheckConstraint(
            "search_mode IN ('hybrid', 'keyword', 'vector', 'metadata')",
            name="chk_t_search_log_search_mode",
        ),
    )

    search_log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[str | None] = mapped_column(Text)
    query: Mapped[str] = mapped_column(Text)
    filters: Mapped[dict] = mapped_column(JSONB, default=dict)
    search_mode: Mapped[str] = mapped_column(String(20), default="hybrid")
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    top_file_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
