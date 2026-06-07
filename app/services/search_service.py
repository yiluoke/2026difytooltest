from __future__ import annotations

import time
from collections import defaultdict
from datetime import UTC, datetime
from datetime import time as datetime_time
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, selectinload

from app.config import load_app_config
from app.db.models import File, FileChunk, SearchLog
from app.schemas.search import MatchedChunk, SearchRequest, SearchResponse, SearchResult
from app.services.acl import allowed_file_ids_subquery, is_acl_allowed
from app.services.embedder import get_embedding_provider
from app.services.ranking import Candidate, parse_query, rank_candidate


class SearchService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.app_config = load_app_config(None)
        self.embedder = get_embedding_provider()

    def search(self, request: SearchRequest) -> SearchResponse:
        started = time.perf_counter()
        top_k = min(request.top_k, self.app_config.search.max_top_k)
        query_info = parse_query(
            request.query,
            list(self.app_config.metadata.document_type_keywords.keys()),
        )
        if request.filters.document_type and query_info.document_type is None:
            query_info = query_info.__class__(
                terms=query_info.terms,
                document_type=request.filters.document_type,
                year_label=query_info.year_label,
                ids=query_info.ids,
                wants_latest=query_info.wants_latest,
            )

        candidates: dict[UUID, Candidate] = {}
        if request.search_mode in {"hybrid", "keyword", "metadata"}:
            self._add_keyword_candidates(candidates, request, query_info, top_k * 5)
        if request.search_mode in {"hybrid", "vector"}:
            self._add_vector_candidates(candidates, request, top_k * 5)

        acl_filter = allowed_file_ids_subquery(
            self.db,
            request.user_id,
            request.group_ids,
            self.app_config.search.acl_mode,
        )
        ranked: list[tuple[float, Candidate, object, list[str]]] = []
        for candidate in candidates.values():
            if not is_acl_allowed(candidate.file.file_id, acl_filter):
                continue
            score, detail, reasons = rank_candidate(candidate, query_info, self.app_config.search)
            ranked.append((score, candidate, detail, reasons))
        ranked.sort(key=lambda item: item[0], reverse=True)

        results = [
            SearchResult(
                rank=index,
                file_id=candidate.file.file_id,
                file_name=candidate.file.file_name,
                file_path=candidate.file.file_path,
                extension=candidate.file.extension,
                system_name=candidate.file.system_name,
                document_type=candidate.file.document_type,
                last_modified_at=candidate.file.last_modified_at,
                is_latest_candidate=candidate.file.is_latest_candidate,
                is_archive=candidate.file.is_archive,
                score=score,
                score_detail=detail,
                match_reason=reasons,
                matched_chunks=_matched_chunks(candidate.chunks),
            )
            for index, (score, candidate, detail, reasons) in enumerate(ranked[:top_k], start=1)
        ]
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        self._write_search_log(request, results, elapsed_ms)
        return SearchResponse(
            query=request.query,
            search_mode=request.search_mode,
            elapsed_ms=elapsed_ms,
            result_count=len(results),
            results=results,
        )

    def _base_file_conditions(self, request: SearchRequest) -> list:
        filters = request.filters
        include_archive = (
            filters.include_archive
            if filters.include_archive is not None
            else self.app_config.search.default_include_archive
        )
        conditions = [File.status == "active"]
        if not include_archive:
            conditions.append(File.is_archive.is_(False))
        if filters.system_name:
            conditions.append(File.system_name == filters.system_name)
        if filters.document_type:
            conditions.append(File.document_type == filters.document_type)
        if filters.extension:
            extension = (
                filters.extension if filters.extension.startswith(".") else f".{filters.extension}"
            )
            conditions.append(File.extension == extension.lower())
        if filters.updated_from:
            conditions.append(
                File.last_modified_at
                >= datetime.combine(filters.updated_from, datetime_time.min, UTC)
            )
        if filters.updated_to:
            conditions.append(
                File.last_modified_at
                <= datetime.combine(filters.updated_to, datetime_time.max, UTC)
            )
        if filters.latest_only:
            conditions.append(File.is_latest_candidate.is_(True))
        return conditions

    def _add_keyword_candidates(
        self,
        candidates: dict[UUID, Candidate],
        request: SearchRequest,
        query_info,
        limit: int,
    ) -> None:
        terms = query_info.terms or [request.query]
        like_conditions = []
        for term in terms[:10]:
            pattern = f"%{_escape_like(term)}%"
            like_conditions.append(File.file_name.ilike(pattern, escape="\\"))
            like_conditions.append(File.file_path.ilike(pattern, escape="\\"))
            like_conditions.append(File.search_text.ilike(pattern, escape="\\"))
            like_conditions.append(FileChunk.content_text.ilike(pattern, escape="\\"))
        statement = (
            select(File, FileChunk)
            .outerjoin(FileChunk, FileChunk.file_id == File.file_id)
            .options(selectinload(File.chunks))
            .where(and_(*self._base_file_conditions(request)))
            .where(or_(*like_conditions) if like_conditions else True)
            .limit(limit * 3)
        )
        rows = self.db.execute(statement).all()
        grouped_chunks: dict[UUID, list[FileChunk]] = defaultdict(list)
        for file, chunk in rows:
            candidate = candidates.setdefault(file.file_id, Candidate(file=file))
            candidate.keyword_score = max(candidate.keyword_score, 0.6)
            candidate.metadata_score = max(
                candidate.metadata_score,
                _metadata_filter_score(file, request),
            )
            if chunk is not None:
                grouped_chunks[file.file_id].append(chunk)
        for file_id, chunks in grouped_chunks.items():
            candidates[file_id].chunks = _dedupe_chunks(candidates[file_id].chunks + chunks)

    def _add_vector_candidates(
        self,
        candidates: dict[UUID, Candidate],
        request: SearchRequest,
        limit: int,
    ) -> None:
        query_vector = self.embedder.embed(request.query)
        distance = FileChunk.embedding.cosine_distance(query_vector).label("distance")
        statement = (
            select(File, FileChunk, distance)
            .join(FileChunk, FileChunk.file_id == File.file_id)
            .where(and_(*self._base_file_conditions(request)))
            .where(FileChunk.embedding.is_not(None))
            .order_by(distance)
            .limit(limit)
        )
        for file, chunk, raw_distance in self.db.execute(statement).all():
            candidate = candidates.setdefault(file.file_id, Candidate(file=file))
            distance_value = float(raw_distance or 1.0)
            candidate.vector_score = max(candidate.vector_score, max(0.0, 1.0 - distance_value))
            candidate.chunks = _dedupe_chunks(candidate.chunks + [chunk])

    def _write_search_log(
        self,
        request: SearchRequest,
        results: list[SearchResult],
        elapsed_ms: int,
    ) -> None:
        self.db.add(
            SearchLog(
                user_id=request.user_id,
                query=request.query,
                filters=request.filters.model_dump(mode="json"),
                search_mode=request.search_mode,
                result_count=len(results),
                top_file_ids=[result.file_id for result in results],
                elapsed_ms=elapsed_ms,
            )
        )
        self.db.commit()


def _metadata_filter_score(file: File, request: SearchRequest) -> float:
    score = 0.0
    if request.filters.system_name and file.system_name == request.filters.system_name:
        score += 0.5
    if request.filters.document_type and file.document_type == request.filters.document_type:
        score += 0.5
    return min(1.0, score)


def _matched_chunks(chunks: list[FileChunk]) -> list[MatchedChunk]:
    return [
        MatchedChunk(
            chunk_id=chunk.chunk_id,
            source_type=chunk.source_type,
            sheet_name=chunk.sheet_name,
            page_no=chunk.page_no,
            slide_no=chunk.slide_no,
            heading=chunk.heading,
            excerpt=" ".join(chunk.content_text.split())[:240],
        )
        for chunk in chunks[:3]
    ]


def _dedupe_chunks(chunks: list[FileChunk]) -> list[FileChunk]:
    seen: set[UUID] = set()
    result: list[FileChunk] = []
    for chunk in chunks:
        if chunk.chunk_id not in seen:
            seen.add(chunk.chunk_id)
            result.append(chunk)
    return result


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
