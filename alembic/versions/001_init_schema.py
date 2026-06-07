from __future__ import annotations

from alembic import op

revision = "001_init_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'pgroonga') THEN
            CREATE EXTENSION IF NOT EXISTS pgroonga;
          END IF;
        END $$;
        """
    )
    op.execute(
        """
        CREATE TABLE t_scan_run (
            scan_run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ,
            status VARCHAR(20) NOT NULL DEFAULT 'running',
            root_paths JSONB NOT NULL DEFAULT '[]'::jsonb,
            total_files_found INTEGER NOT NULL DEFAULT 0,
            inserted_count INTEGER NOT NULL DEFAULT 0,
            updated_count INTEGER NOT NULL DEFAULT 0,
            skipped_count INTEGER NOT NULL DEFAULT 0,
            deleted_marked_count INTEGER NOT NULL DEFAULT 0,
            error_count INTEGER NOT NULL DEFAULT 0,
            message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT chk_scan_run_status
              CHECK (status IN ('running', 'success', 'failed', 'partial_success'))
        )
        """
    )
    op.execute(
        """
        CREATE TABLE t_file (
            file_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            file_path TEXT NOT NULL,
            normalized_path TEXT NOT NULL,
            path_hash CHAR(64) NOT NULL,
            file_name TEXT NOT NULL,
            extension VARCHAR(20) NOT NULL,
            parent_path TEXT NOT NULL,
            file_size BIGINT NOT NULL DEFAULT 0,
            last_modified_at TIMESTAMPTZ,
            file_hash CHAR(64),
            content_hash CHAR(64),
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            is_archive BOOLEAN NOT NULL DEFAULT FALSE,
            archive_reason TEXT,
            system_name TEXT,
            project_name TEXT,
            document_type TEXT,
            year_label TEXT,
            version_label TEXT,
            latest_group_key TEXT,
            is_latest_candidate BOOLEAN NOT NULL DEFAULT FALSE,
            folder_keywords TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
            path_keywords TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
            search_text TEXT NOT NULL DEFAULT '',
            content_preview TEXT,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            first_seen_scan_run_id UUID REFERENCES t_scan_run(scan_run_id),
            last_seen_scan_run_id UUID REFERENCES t_scan_run(scan_run_id),
            indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_t_file_path_hash UNIQUE (path_hash),
            CONSTRAINT chk_t_file_status CHECK (status IN ('active', 'deleted', 'error', 'skipped'))
        )
        """
    )
    op.execute(
        """
        CREATE TABLE t_file_chunk (
            chunk_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            file_id UUID NOT NULL REFERENCES t_file(file_id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            source_type VARCHAR(30) NOT NULL DEFAULT 'body',
            sheet_name TEXT,
            page_no INTEGER,
            slide_no INTEGER,
            heading TEXT,
            char_start INTEGER,
            char_end INTEGER,
            content_text TEXT NOT NULL,
            content_summary TEXT,
            content_hash CHAR(64),
            embedding vector(1536),
            token_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_t_file_chunk_file_index UNIQUE (file_id, chunk_index),
            CONSTRAINT chk_t_file_chunk_source_type
              CHECK (source_type IN ('body', 'sheet', 'page', 'slide', 'text', 'metadata'))
        )
        """
    )
    op.execute(
        """
        CREATE TABLE t_file_acl (
            file_id UUID NOT NULL REFERENCES t_file(file_id) ON DELETE CASCADE,
            principal_type VARCHAR(20) NOT NULL,
            principal_name TEXT NOT NULL,
            permission VARCHAR(30) NOT NULL DEFAULT 'read',
            can_read BOOLEAN NOT NULL DEFAULT TRUE,
            inherited BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (file_id, principal_type, principal_name, permission),
            CONSTRAINT chk_t_file_acl_principal_type CHECK (principal_type IN ('user', 'group')),
            CONSTRAINT chk_t_file_acl_permission
              CHECK (permission IN ('read', 'write', 'full_control'))
        )
        """
    )
    op.execute(
        """
        CREATE TABLE t_scan_error (
            scan_error_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            scan_run_id UUID REFERENCES t_scan_run(scan_run_id) ON DELETE CASCADE,
            file_path TEXT,
            error_type TEXT NOT NULL,
            error_message TEXT NOT NULL,
            traceback TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE t_search_log (
            search_log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id TEXT,
            query TEXT NOT NULL,
            filters JSONB NOT NULL DEFAULT '{}'::jsonb,
            search_mode VARCHAR(20) NOT NULL DEFAULT 'hybrid',
            result_count INTEGER NOT NULL DEFAULT 0,
            top_file_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
            elapsed_ms INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT chk_t_search_log_search_mode
              CHECK (search_mode IN ('hybrid', 'keyword', 'vector', 'metadata'))
        )
        """
    )
    statements = [
        "CREATE INDEX idx_t_file_normalized_path ON t_file (normalized_path)",
        "CREATE UNIQUE INDEX idx_t_file_path_hash ON t_file (path_hash)",
        "CREATE INDEX idx_t_file_file_name_lower ON t_file (lower(file_name))",
        "CREATE INDEX idx_t_file_extension ON t_file (extension)",
        "CREATE INDEX idx_t_file_status ON t_file (status)",
        "CREATE INDEX idx_t_file_last_modified_at ON t_file (last_modified_at DESC)",
        "CREATE INDEX idx_t_file_system_name ON t_file (system_name)",
        "CREATE INDEX idx_t_file_document_type ON t_file (document_type)",
        "CREATE INDEX idx_t_file_latest_group_key ON t_file (latest_group_key)",
        "CREATE INDEX idx_t_file_is_latest_candidate ON t_file (is_latest_candidate)",
        "CREATE INDEX idx_t_file_is_archive ON t_file (is_archive)",
        "CREATE INDEX idx_t_file_folder_keywords ON t_file USING GIN (folder_keywords)",
        "CREATE INDEX idx_t_file_path_keywords ON t_file USING GIN (path_keywords)",
        "CREATE INDEX idx_t_file_metadata ON t_file USING GIN (metadata)",
        "CREATE INDEX idx_t_file_search_text_trgm ON t_file USING GIN (search_text gin_trgm_ops)",
        "CREATE INDEX idx_t_file_chunk_file_id ON t_file_chunk (file_id)",
        "CREATE INDEX idx_t_file_chunk_content_text_trgm "
        "ON t_file_chunk USING GIN (content_text gin_trgm_ops)",
        "CREATE INDEX idx_t_file_chunk_embedding_hnsw "
        "ON t_file_chunk USING hnsw (embedding vector_cosine_ops)",
        "CREATE INDEX idx_t_file_acl_principal "
        "ON t_file_acl (principal_type, principal_name, can_read)",
        "CREATE INDEX idx_t_scan_error_scan_run_id ON t_scan_error (scan_run_id)",
        "CREATE INDEX idx_t_search_log_created_at ON t_search_log (created_at DESC)",
    ]
    for statement in statements:
        op.execute(statement)
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pgroonga') THEN
            EXECUTE 'CREATE INDEX idx_t_file_search_text_pgroonga '
                    'ON t_file USING pgroonga (search_text)';
            EXECUTE 'CREATE INDEX idx_t_file_chunk_content_text_pgroonga '
                    'ON t_file_chunk USING pgroonga (content_text)';
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS t_search_log")
    op.execute("DROP TABLE IF EXISTS t_scan_error")
    op.execute("DROP TABLE IF EXISTS t_file_acl")
    op.execute("DROP TABLE IF EXISTS t_file_chunk")
    op.execute("DROP TABLE IF EXISTS t_file")
    op.execute("DROP TABLE IF EXISTS t_scan_run")
