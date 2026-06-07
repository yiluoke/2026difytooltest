from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.config import SearchConfig
from app.db.models import File, FileChunk
from app.schemas.search import ScoreDetail


@dataclass
class Candidate:
    file: File
    chunks: list[FileChunk] = field(default_factory=list)
    keyword_score: float = 0.0
    vector_score: float = 0.0
    metadata_score: float = 0.0


@dataclass(frozen=True)
class QueryInfo:
    terms: list[str]
    document_type: str | None = None
    year_label: str | None = None
    ids: list[str] = field(default_factory=list)
    wants_latest: bool = False


def parse_query(query: str, document_types: list[str]) -> QueryInfo:
    ids = sorted(set(re.findall(r"\b[A-Z]{1,5}\d{2,5}\b", query, flags=re.IGNORECASE)))
    year_match = re.search(r"(20\d{2})\s*(?:年度|年)?", query)
    document_type = next((doc_type for doc_type in document_types if doc_type in query), None)
    terms = [term for term in re.split(r"[\s　、。・/\\]+", query) if len(term) >= 2]
    for identifier in ids:
        if identifier not in terms:
            terms.append(identifier)
    return QueryInfo(
        terms=terms,
        document_type=document_type,
        year_label=f"{year_match.group(1)}年度" if year_match else None,
        ids=ids,
        wants_latest=any(word in query for word in ("最新版", "最新", "現行")),
    )


def rank_candidate(
    candidate: Candidate,
    query_info: QueryInfo,
    config: SearchConfig,
) -> tuple[float, ScoreDetail, list[str]]:
    file = candidate.file
    keyword_score = max(candidate.keyword_score, _term_score(file, candidate.chunks, query_info))
    metadata_score = _metadata_score(file, query_info, candidate.metadata_score)
    recency_score = _recency_score(file.last_modified_at)
    archive_penalty = 0.35 if file.is_archive else 0.0
    latest_bonus = 0.08 if file.is_latest_candidate else 0.0
    latest_penalty = 0.15 if query_info.wants_latest and not file.is_latest_candidate else 0.0
    score = (
        keyword_score * config.keyword_weight
        + candidate.vector_score * config.vector_weight
        + metadata_score * config.metadata_weight
        + recency_score * 0.08
        + latest_bonus
        - archive_penalty
        - latest_penalty
    )
    score = max(0.0, min(1.0, score))
    detail = ScoreDetail(
        keyword_score=round(keyword_score, 4),
        vector_score=round(candidate.vector_score, 4),
        metadata_score=round(metadata_score, 4),
        recency_score=round(recency_score, 4),
        archive_penalty=archive_penalty,
    )
    return round(score, 4), detail, _match_reasons(file, candidate.chunks, query_info)


def _term_score(file: File, chunks: list[FileChunk], query_info: QueryInfo) -> float:
    if not query_info.terms:
        return 0.0
    target = " ".join(
        [
            file.file_name,
            file.file_path,
            file.search_text or "",
            " ".join(chunk.content_text[:500] for chunk in chunks[:3]),
        ]
    ).lower()
    matches = sum(1 for term in query_info.terms if term.lower() in target)
    id_bonus = (
        sum(1 for identifier in query_info.ids if identifier.lower() in file.file_name.lower())
        * 0.2
    )
    return min(1.0, matches / max(1, len(query_info.terms)) + id_bonus)


def _metadata_score(file: File, query_info: QueryInfo, base_score: float) -> float:
    score = base_score
    if query_info.document_type and file.document_type == query_info.document_type:
        score += 0.5
    if query_info.year_label and file.year_label == query_info.year_label:
        score += 0.25
    return min(1.0, score)


def _recency_score(value: datetime | None) -> float:
    if value is None:
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    days = max(0, (datetime.now(UTC) - value).days)
    return math.exp(-days / 730)


def _match_reasons(file: File, chunks: list[FileChunk], query_info: QueryInfo) -> list[str]:
    reasons: list[str] = []
    lower_name = file.file_name.lower()
    lower_path = file.file_path.lower()
    for identifier in query_info.ids:
        if identifier.lower() in lower_name:
            reasons.append(f"ファイル名に '{identifier}' が一致")
    for term in query_info.terms[:8]:
        lower = term.lower()
        if lower in lower_name:
            reasons.append(f"ファイル名に '{term}' が一致")
        elif lower in lower_path:
            reasons.append(f"パスに '{term}' が一致")
    if query_info.document_type and file.document_type == query_info.document_type:
        reasons.append(f"文書種別が '{file.document_type}' と一致")
    if file.system_name and file.system_name.lower() in lower_path:
        reasons.append(f"フォルダに '{file.system_name}' が含まれます")
    if any(chunk.content_text for chunk in chunks):
        reasons.append("本文チャンクに一致候補があります")
    if file.is_latest_candidate:
        reasons.append("同一資料グループ内の最新版候補です")
    if not file.is_archive:
        reasons.append("old/backupフォルダではありません")
    if not reasons:
        reasons.append("メタデータまたは意味検索で候補になりました")
    return _dedupe(reasons)[:8]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
