from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from app.db.models import File
from app.db.session import get_db
from app.schemas.files import FileChunkSummary, FileDetail

router = APIRouter(tags=["files"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/files/{file_id}", response_model=FileDetail)
def get_file(file_id: UUID, db: DbSession) -> FileDetail:
    file = (
        db.query(File)
        .options(selectinload(File.chunks))
        .filter(File.file_id == file_id, File.status == "active")
        .one_or_none()
    )
    if file is None:
        raise HTTPException(status_code=404, detail="file not found")

    return FileDetail(
        file_id=file.file_id,
        file_name=file.file_name,
        file_path=file.file_path,
        extension=file.extension,
        size=file.file_size,
        last_modified_at=file.last_modified_at,
        system_name=file.system_name,
        document_type=file.document_type,
        is_latest_candidate=file.is_latest_candidate,
        is_archive=file.is_archive,
        content_preview=file.content_preview,
        metadata=file.file_metadata or {},
        chunks=[
            FileChunkSummary(
                chunk_id=chunk.chunk_id,
                chunk_index=chunk.chunk_index,
                source_type=chunk.source_type,
                sheet_name=chunk.sheet_name,
                page_no=chunk.page_no,
                slide_no=chunk.slide_no,
                heading=chunk.heading,
                excerpt=_excerpt(chunk.content_text),
            )
            for chunk in file.chunks[:20]
        ],
    )


def _excerpt(text: str, limit: int = 180) -> str:
    compact = " ".join(text.split())
    return compact[:limit]
