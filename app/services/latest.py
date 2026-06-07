from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import MetadataConfig
from app.db.models import File


def refresh_latest_candidates(db: Session, metadata_config: MetadataConfig) -> None:
    keys = db.execute(
        select(File.latest_group_key)
        .where(File.status == "active", File.latest_group_key.is_not(None))
        .distinct()
    ).scalars()
    for key in keys:
        files = (
            db.execute(select(File).where(File.status == "active", File.latest_group_key == key))
            .scalars()
            .all()
        )
        if not files:
            continue
        best = max(files, key=lambda file: _latest_score(file, metadata_config))
        db.execute(
            update(File).where(File.latest_group_key == key).values(is_latest_candidate=False)
        )
        best.is_latest_candidate = True
    db.flush()


def _latest_score(file: File, metadata_config: MetadataConfig) -> float:
    score = 0.0
    if file.last_modified_at:
        modified = file.last_modified_at
        if modified.tzinfo is None:
            modified = modified.replace(tzinfo=UTC)
        age_days = max(0.0, (datetime.now(UTC) - modified).days)
        score += max(0.0, 1000.0 - age_days)
    lower_name = file.file_name.lower()
    for keyword in metadata_config.latest_positive_keywords:
        if keyword.lower() in lower_name:
            score += 500.0
    if file.is_archive:
        score -= 2000.0
    lower_path = file.file_path.lower()
    for keyword in metadata_config.archive_keywords:
        if keyword.lower() in lower_path:
            score -= 500.0
    return score
