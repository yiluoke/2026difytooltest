from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ScanConfig(BaseModel):
    roots: list[str] = Field(default_factory=list)
    include_extensions: list[str] = Field(default_factory=lambda: [".txt", ".md", ".csv", ".log"])
    exclude_dir_patterns: list[str] = Field(default_factory=list)
    exclude_file_prefixes: list[str] = Field(default_factory=lambda: ["~$"])
    max_file_mb: int = 50
    max_extract_chars_per_file: int = 200_000
    chunk_size: int = 1200
    chunk_overlap: int = 200
    follow_symlinks: bool = False
    full_rescan: bool = False


class MetadataConfig(BaseModel):
    archive_keywords: list[str] = Field(
        default_factory=lambda: [
            "old",
            "backup",
            "bk",
            "退避",
            "廃止",
            "削除",
            "旧",
            "コピー",
            "修正前",
        ]
    )
    latest_positive_keywords: list[str] = Field(
        default_factory=lambda: ["最新版", "最新", "確定", "正式", "現行", "リリース済"]
    )
    document_type_keywords: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "画面設計書": ["画面設計", "画面仕様"],
            "基本設計書": ["基本設計"],
            "詳細設計書": ["詳細設計"],
            "IF設計書": ["IF設計", "インターフェース", "interface"],
            "問い合わせ資料": ["問い合わせ", "問合せ", "QA", "Q&A"],
            "障害対応資料": ["障害", "不具合", "インシデント", "incident", "エラー"],
            "議事録": ["議事録", "打合せ", "会議"],
        }
    )


class SearchConfig(BaseModel):
    default_top_k: int = 10
    max_top_k: int = 50
    default_include_archive: bool = False
    acl_mode: Literal["off", "permissive", "strict"] = "permissive"
    vector_weight: float = 0.35
    keyword_weight: float = 0.45
    metadata_weight: float = 0.20


class AppConfig(BaseModel):
    scan: ScanConfig = Field(default_factory=ScanConfig)
    metadata: MetadataConfig = Field(default_factory=MetadataConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/file_search"
    app_env: str = "local"
    log_level: str = "INFO"
    embedding_provider: Literal["hash", "openai_compatible"] = "hash"
    embedding_dim: int = 1536
    embedding_api_base: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""
    acl_mode: Literal["off", "permissive", "strict"] = "permissive"
    app_config_path: str = "config.yaml"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_app_config(path: str | Path | None) -> AppConfig:
    settings = get_settings()
    if path is None:
        default_path = Path(settings.app_config_path)
        if default_path.exists():
            data = yaml.safe_load(default_path.read_text(encoding="utf-8")) or {}
            config = AppConfig.model_validate(data)
        else:
            config = AppConfig()
    else:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        config = AppConfig.model_validate(data)

    config.search.acl_mode = settings.acl_mode or config.search.acl_mode
    return config
