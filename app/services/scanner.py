from __future__ import annotations

import csv
import hashlib
import logging
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.db.models import File, FileAcl, FileChunk, ScanError, ScanRun
from app.services.chunker import chunk_sections
from app.services.embedder import EmbeddingProvider
from app.services.extractor import extract_sections
from app.services.latest import refresh_latest_candidates
from app.services.metadata import infer_metadata, normalize_path, sha256_text

logger = logging.getLogger(__name__)


@dataclass
class ScanSummary:
    scan_run_id: str
    status: str
    total_files_found: int
    inserted_count: int
    updated_count: int
    skipped_count: int
    deleted_marked_count: int
    error_count: int


class FileScanner:
    def __init__(self, db: Session, config: AppConfig, embedder: EmbeddingProvider) -> None:
        self.db = db
        self.config = config
        self.embedder = embedder

    def scan(self, full: bool = False) -> ScanSummary:
        scan_run = ScanRun(root_paths=self.config.scan.roots, status="running")
        self.db.add(scan_run)
        self.db.commit()
        self.db.refresh(scan_run)

        seen_hashes: set[str] = set()
        try:
            for path in self._iter_files():
                scan_run.total_files_found += 1
                try:
                    path_hash = sha256_text(normalize_path(path))
                    seen_hashes.add(path_hash)
                    outcome = self._index_file(
                        path,
                        scan_run,
                        full=full or self.config.scan.full_rescan,
                    )
                    if outcome == "inserted":
                        scan_run.inserted_count += 1
                    elif outcome == "updated":
                        scan_run.updated_count += 1
                    else:
                        scan_run.skipped_count += 1
                    self.db.commit()
                except Exception as exc:  # noqa: BLE001 - scanning must continue.
                    self.db.rollback()
                    scan_run.error_count += 1
                    self._record_error(scan_run, path, exc)
                    self.db.commit()

            scan_run.deleted_marked_count = self._mark_deleted(seen_hashes, scan_run)
            refresh_latest_candidates(self.db, self.config.metadata)
            scan_run.status = "partial_success" if scan_run.error_count else "success"
            scan_run.finished_at = datetime.now(UTC)
            self.db.commit()
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            scan_run.status = "failed"
            scan_run.message = str(exc)
            scan_run.finished_at = datetime.now(UTC)
            self.db.add(scan_run)
            self.db.commit()
            raise

        return ScanSummary(
            scan_run_id=str(scan_run.scan_run_id),
            status=scan_run.status,
            total_files_found=scan_run.total_files_found,
            inserted_count=scan_run.inserted_count,
            updated_count=scan_run.updated_count,
            skipped_count=scan_run.skipped_count,
            deleted_marked_count=scan_run.deleted_marked_count,
            error_count=scan_run.error_count,
        )

    def _iter_files(self):
        include_extensions = {
            extension.lower() for extension in self.config.scan.include_extensions
        }
        max_bytes = self.config.scan.max_file_mb * 1024 * 1024
        for root in self.config.scan.roots:
            root_path = Path(root)
            if not root_path.exists():
                logger.warning("scan root does not exist: %s", root_path)
                continue
            for path in root_path.rglob("*"):
                if path.is_dir():
                    continue
                if not self.config.scan.follow_symlinks and path.is_symlink():
                    continue
                if self._is_excluded(path):
                    continue
                if path.suffix.lower() not in include_extensions:
                    continue
                try:
                    if path.stat().st_size > max_bytes:
                        continue
                except OSError:
                    continue
                yield path

    def _is_excluded(self, path: Path) -> bool:
        lower_parts = [part.lower() for part in path.parts]
        for pattern in self.config.scan.exclude_dir_patterns:
            lower = pattern.lower()
            if any(lower in part for part in lower_parts[:-1]):
                return True
        return any(
            path.name.startswith(prefix) for prefix in self.config.scan.exclude_file_prefixes
        )

    def _index_file(self, path: Path, scan_run: ScanRun, full: bool) -> str:
        stat = path.stat()
        modified_at = datetime.fromtimestamp(stat.st_mtime, UTC)
        normalized = normalize_path(path)
        path_hash = sha256_text(normalized)
        existing = self.db.execute(
            select(File).where(File.path_hash == path_hash)
        ).scalar_one_or_none()
        if existing and not full and _unchanged(existing, stat.st_size, modified_at):
            existing.last_seen_scan_run_id = scan_run.scan_run_id
            existing.status = "active"
            return "skipped"

        sections = extract_sections(path, self.config.scan.max_extract_chars_per_file)
        content_text = "\n".join(section.text for section in sections)
        chunks = chunk_sections(
            sections,
            chunk_size=self.config.scan.chunk_size,
            overlap=self.config.scan.chunk_overlap,
        )
        metadata = infer_metadata(path, content_text, self.config.metadata)
        file_hash = _sha256_file(path)
        file = existing or File(
            file_path=str(path),
            normalized_path=normalized,
            path_hash=path_hash,
            file_name=path.name,
            extension=path.suffix.lower(),
            parent_path=str(path.parent),
            first_seen_scan_run_id=scan_run.scan_run_id,
        )
        file.file_path = str(path)
        file.normalized_path = normalized
        file.file_name = path.name
        file.extension = path.suffix.lower()
        file.parent_path = str(path.parent)
        file.file_size = stat.st_size
        file.last_modified_at = modified_at
        file.file_hash = file_hash
        file.content_hash = metadata.content_hash
        file.status = "active"
        file.is_archive = metadata.is_archive
        file.archive_reason = metadata.archive_reason
        file.system_name = metadata.system_name
        file.project_name = metadata.project_name
        file.document_type = metadata.document_type
        file.year_label = metadata.year_label
        file.version_label = metadata.version_label
        file.latest_group_key = metadata.latest_group_key
        file.folder_keywords = metadata.folder_keywords
        file.path_keywords = metadata.path_keywords
        file.search_text = metadata.search_text
        file.content_preview = metadata.content_preview
        file.file_metadata = {"source": "scanner"}
        file.last_seen_scan_run_id = scan_run.scan_run_id
        file.indexed_at = datetime.now(UTC)
        if existing is None:
            self.db.add(file)
            self.db.flush()
            outcome = "inserted"
        else:
            outcome = "updated"

        self.db.execute(delete(FileChunk).where(FileChunk.file_id == file.file_id))
        for chunk in chunks:
            self.db.add(
                FileChunk(
                    file_id=file.file_id,
                    chunk_index=chunk.chunk_index,
                    source_type=chunk.source_type,
                    sheet_name=chunk.sheet_name,
                    page_no=chunk.page_no,
                    slide_no=chunk.slide_no,
                    heading=chunk.heading,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    content_text=chunk.text,
                    content_hash=chunk.content_hash,
                    embedding=self.embedder.embed(chunk.text),
                    token_count=chunk.token_count,
                )
            )
        return outcome

    def _mark_deleted(self, seen_hashes: set[str], scan_run: ScanRun) -> int:
        root_conditions = []
        for root in self.config.scan.roots:
            root_conditions.append(File.normalized_path.ilike(f"{normalize_path(Path(root))}%"))
        if not seen_hashes or not root_conditions:
            return 0
        result = self.db.execute(
            update(File)
            .where(
                File.status == "active",
                or_(*root_conditions),
                File.path_hash.not_in(seen_hashes),
            )
            .values(status="deleted", last_seen_scan_run_id=scan_run.scan_run_id)
        )
        return int(result.rowcount or 0)

    def _record_error(self, scan_run: ScanRun, path: Path, exc: Exception) -> None:
        self.db.add(
            ScanError(
                scan_run_id=scan_run.scan_run_id,
                file_path=str(path),
                error_type=exc.__class__.__name__,
                error_message=str(exc),
                traceback=traceback.format_exc(),
            )
        )


def load_acl_csv(db: Session, csv_path: Path) -> int:
    count = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            file_id = row["file_id"]
            db.merge(
                FileAcl(
                    file_id=file_id,
                    principal_type=row.get("principal_type", "group"),
                    principal_name=row["principal_name"],
                    permission=row.get("permission", "read"),
                    can_read=row.get("can_read", "true").lower() in {"1", "true", "yes", "y"},
                    inherited=row.get("inherited", "true").lower() in {"1", "true", "yes", "y"},
                )
            )
            count += 1
    db.commit()
    return count


def _unchanged(file: File, size: int, modified_at: datetime) -> bool:
    if file.file_size != size or file.last_modified_at is None:
        return False
    existing = file.last_modified_at
    if existing.tzinfo is None:
        existing = existing.replace(tzinfo=UTC)
    return abs((existing - modified_at).total_seconds()) < 1


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
