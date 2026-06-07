from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.search import SearchRequest, SearchResponse
from app.services.search_service import SearchService

router = APIRouter(tags=["search"])
DbSession = Annotated[Session, Depends(get_db)]


@router.post("/search", response_model=SearchResponse)
def search_files(request: SearchRequest, db: DbSession) -> SearchResponse:
    return SearchService(db).search(request)
