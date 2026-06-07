from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

SearchMode = Literal["hybrid", "keyword", "vector", "metadata"]


class SearchFilters(BaseModel):
    system_name: str | None = None
    document_type: str | None = None
    extension: str | None = None
    updated_from: date | None = None
    updated_to: date | None = None
    include_archive: bool | None = None
    latest_only: bool = False


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    user_id: str | None = None
    group_ids: list[str] = Field(default_factory=list)
    top_k: int = Field(default=10, ge=1, le=50)
    search_mode: SearchMode = "hybrid"
    filters: SearchFilters = Field(default_factory=SearchFilters)
    debug: bool = False


class ScoreDetail(BaseModel):
    keyword_score: float = 0.0
    vector_score: float = 0.0
    metadata_score: float = 0.0
    recency_score: float = 0.0
    archive_penalty: float = 0.0


class MatchedChunk(BaseModel):
    chunk_id: UUID
    source_type: str
    sheet_name: str | None = None
    page_no: int | None = None
    slide_no: int | None = None
    heading: str | None = None
    excerpt: str


class SearchResult(BaseModel):
    rank: int
    file_id: UUID
    file_name: str
    file_path: str
    extension: str
    system_name: str | None = None
    document_type: str | None = None
    last_modified_at: datetime | None = None
    is_latest_candidate: bool
    is_archive: bool
    score: float
    score_detail: ScoreDetail
    match_reason: list[str]
    matched_chunks: list[MatchedChunk]


class SearchResponse(BaseModel):
    query: str
    search_mode: SearchMode
    elapsed_ms: int
    result_count: int
    results: list[SearchResult]

