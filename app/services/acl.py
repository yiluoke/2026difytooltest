from __future__ import annotations

from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import FileAcl

AclFilter = None | tuple[Literal["permissive", "strict"], set, set]


def allowed_file_ids_subquery(
    db: Session,
    user_id: str | None,
    group_ids: list[str],
    acl_mode: str,
) -> AclFilter:
    if acl_mode == "off":
        return None

    principals: list[tuple[str, str]] = []
    if user_id:
        principals.append(("user", user_id))
    principals.extend(("group", group_id) for group_id in group_ids)

    if not principals and acl_mode == "strict":
        return ("strict", set(), set())

    readable = select(FileAcl.file_id).where(
        FileAcl.can_read.is_(True),
        or_(
            *[
                (FileAcl.principal_type == principal_type)
                & (FileAcl.principal_name == principal_name)
                for principal_type, principal_name in principals
            ]
        )
        if principals
        else False,
    )
    acl_exists = select(FileAcl.file_id).distinct().subquery()
    readable_ids = set(db.execute(readable).scalars().all()) if principals else set()
    files_with_acl = set(db.execute(select(acl_exists.c.file_id)).scalars().all())
    return ("strict" if acl_mode == "strict" else "permissive", readable_ids, files_with_acl)


def is_acl_allowed(file_id, acl_filter: AclFilter) -> bool:
    if acl_filter is None:
        return True
    mode, readable_ids, files_with_acl = acl_filter
    if mode == "strict":
        return file_id in readable_ids
    return file_id in readable_ids or file_id not in files_with_acl
