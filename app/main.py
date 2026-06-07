from __future__ import annotations

import logging

from fastapi import FastAPI

from app.api.routes import files, health, search
from app.config import get_settings

settings = get_settings()
logging.basicConfig(level=settings.log_level)

app = FastAPI(title="File Search Backend", version="0.1.0")
app.include_router(health.router)
app.include_router(search.router)
app.include_router(files.router)

