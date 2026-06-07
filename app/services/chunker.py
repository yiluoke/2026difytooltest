from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.services.extractor import ExtractedSection


@dataclass(frozen=True)
class Chunk:
    chunk_index: int
    source_type: str
    text: str
    content_hash: str
    token_count: int
    sheet_name: str | None = None
    page_no: int | None = None
    slide_no: int | None = None
    heading: str | None = None
    char_start: int | None = None
    char_end: int | None = None


def chunk_sections(sections: list[ExtractedSection], chunk_size: int, overlap: int) -> list[Chunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    overlap = max(0, min(overlap, chunk_size - 1))
    chunks: list[Chunk] = []
    for section in sections:
        text = section.text.strip()
        if not text:
            continue
        for start, end, part in _split_text(text, chunk_size, overlap):
            chunks.append(
                Chunk(
                    chunk_index=len(chunks),
                    source_type=section.source_type,
                    text=part,
                    content_hash=hashlib.sha256(part.encode("utf-8")).hexdigest(),
                    token_count=max(1, len(part) // 2),
                    sheet_name=section.sheet_name,
                    page_no=section.page_no,
                    slide_no=section.slide_no,
                    heading=section.heading,
                    char_start=start,
                    char_end=end,
                )
            )
    return chunks


def _split_text(text: str, chunk_size: int, overlap: int) -> list[tuple[int, int, str]]:
    if len(text) <= chunk_size:
        return [(0, len(text), text)]
    result: list[tuple[int, int, str]] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        part = text[start:end].strip()
        if part:
            result.append((start, end, part))
        if end >= len(text):
            break
        start = end - overlap
    return result

