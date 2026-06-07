from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class FileChunkSummary(BaseModel):
    chunk_id: UUID
    chunk_index: int
    source_type: str
    sheet_name: str | None = None
    page_no: int | None = None
    slide_no: int | None = None
    heading: str | None = None
    excerpt: str


class FileDetail(BaseModel):
    file_id: UUID
    file_name: str
    file_path: str
    extension: str
    size: int
    last_modified_at: datetime | None = None
    system_name: str | None = None
    document_type: str | None = None
    is_latest_candidate: bool
    is_archive: bool
    content_preview: str | None = None
    metadata: dict
    chunks: list[FileChunkSummary]

