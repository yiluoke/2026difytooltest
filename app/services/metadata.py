from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from app.config import MetadataConfig


@dataclass(frozen=True)
class MetadataResult:
    system_name: str | None
    project_name: str | None
    document_type: str | None
    year_label: str | None
    version_label: str | None
    folder_keywords: list[str]
    path_keywords: list[str]
    is_archive: bool
    archive_reason: str | None
    latest_group_key: str
    search_text: str
    content_preview: str
    content_hash: str


DATE_PATTERNS = [
    re.compile(r"20\d{6}"),
    re.compile(r"20\d{2}[-_/年.](?:0?[1-9]|1[0-2])[-_/月.](?:0?[1-9]|[12]\d|3[01])日?"),
]
VERSION_PATTERN = re.compile(r"\b(?:v|ver|rev)\s*\d+(?:\.\d+)?\b", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"(20\d{2})\s*(?:年度|年)?")
ID_PATTERN = re.compile(r"\b[A-Z]{1,5}\d{2,5}\b", re.IGNORECASE)


def normalize_path(path: Path) -> str:
    raw_path = str(path.resolve() if path.exists() else path)
    return unicodedata.normalize("NFKC", raw_path).replace("\\", "/")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def infer_metadata(path: Path, content_text: str, config: MetadataConfig) -> MetadataResult:
    normalized = normalize_path(path)
    file_name = path.name
    parent_parts = [part for part in Path(normalized).parent.parts if part not in {"/", "\\"}]
    folder_keywords = _dedupe(
        [_clean_keyword(part) for part in parent_parts if _clean_keyword(part)]
    )
    path_keywords = _dedupe(
        folder_keywords + [_clean_keyword(path.stem)] + ID_PATTERN.findall(file_name)
    )
    preview = " ".join(content_text.split())[:1000]
    haystacks = {
        "file_name": file_name,
        "path": normalized,
        "preview": preview,
    }
    document_type = _infer_document_type(haystacks, config.document_type_keywords)
    is_archive, archive_reason = _detect_archive(normalized, config.archive_keywords)
    year_label = _find_year(f"{file_name} {normalized} {preview}")
    version_label = _find_version(file_name)
    system_name = _guess_system_name(parent_parts, document_type)
    project_name = _guess_project_name(parent_parts)
    latest_group_key = _latest_group_key(path, parent_parts)
    search_text = "\n".join(
        part
        for part in [
            file_name,
            normalized,
            " ".join(folder_keywords),
            document_type or "",
            system_name or "",
            year_label or "",
            preview,
        ]
        if part
    )
    return MetadataResult(
        system_name=system_name,
        project_name=project_name,
        document_type=document_type,
        year_label=year_label,
        version_label=version_label,
        folder_keywords=folder_keywords,
        path_keywords=path_keywords,
        is_archive=is_archive,
        archive_reason=archive_reason,
        latest_group_key=latest_group_key,
        search_text=search_text,
        content_preview=preview,
        content_hash=sha256_text(content_text),
    )


def _infer_document_type(haystacks: dict[str, str], mapping: dict[str, list[str]]) -> str | None:
    best_type: str | None = None
    best_score = 0
    weights = {"file_name": 5, "path": 3, "preview": 1}
    for doc_type, keywords in mapping.items():
        score = 0
        for name, text in haystacks.items():
            normalized = text.lower()
            for keyword in keywords:
                if keyword.lower() in normalized:
                    score += weights[name]
        if score > best_score:
            best_type = doc_type
            best_score = score
    return best_type


def _detect_archive(text: str, keywords: list[str]) -> tuple[bool, str | None]:
    normalized = unicodedata.normalize("NFKC", text).lower()
    for keyword in keywords:
        key = keyword.lower()
        if key.isascii() and re.search(rf"(^|[/_\-\s.]){re.escape(key)}($|[/_\-\s.])", normalized):
            return True, keyword
        if not key.isascii() and key in normalized:
            return True, keyword
    return False, None


def _find_year(text: str) -> str | None:
    match = YEAR_PATTERN.search(text)
    return f"{match.group(1)}年度" if match else None


def _find_version(text: str) -> str | None:
    match = VERSION_PATTERN.search(text)
    return match.group(0) if match else None


def _guess_system_name(parent_parts: list[str], document_type: str | None) -> str | None:
    ignored = {"設計", "設計書", "保守", "障害", "問い合わせ", "資料", "old", "backup", "bk"}
    for part in reversed(parent_parts):
        cleaned = _clean_keyword(part)
        if cleaned and cleaned.lower() not in ignored and cleaned != document_type:
            return cleaned
    return None


def _guess_project_name(parent_parts: list[str]) -> str | None:
    for part in parent_parts:
        cleaned = _clean_keyword(part)
        if cleaned:
            return cleaned
    return None


def _latest_group_key(path: Path, parent_parts: list[str]) -> str:
    stem = unicodedata.normalize("NFKC", path.stem).lower()
    for pattern in DATE_PATTERNS:
        stem = pattern.sub("", stem)
    stem = VERSION_PATTERN.sub("", stem)
    for noise in ("最新版", "最新", "確定", "正式", "コピー", "修正前", "旧"):
        stem = stem.replace(noise.lower(), "")
    stem = re.sub(r"[\s_\-().（）\[\]【】]+", "", stem)
    useful_parent = "/".join(
        _clean_keyword(part).lower() for part in parent_parts[-3:] if _clean_keyword(part)
    )
    return sha256_text(f"{useful_parent}/{stem}")


def _clean_keyword(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().strip("/\\")


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
