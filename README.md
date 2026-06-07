# File Search Backend

社内ファイルサーバー上の設計書、問い合わせ資料、障害対応資料などを索引化し、FastAPI から検索できるバックエンドです。

Dify 連携は後続工程の想定です。この実装では、Dify の Tool Node から呼び出しやすい JSON 形式の検索 API までを提供します。

## Architecture

```text
File server / local folders
  -> Python scanner CLI
  -> text extraction / metadata inference / chunking / embedding
  -> PostgreSQL + pgvector
  -> FastAPI search API
```

検索は以下を組み合わせます。

- メタデータ検索: システム名、文書種別、拡張子、更新日、最新版候補
- キーワード検索: ファイル名、パス、抽出本文
- ベクトル検索: pgvector の cosine distance
- 再ランキング: 一致理由、最新版候補、archive 除外、更新日時

## Setup

```bash
cp .env.example .env
cp config.example.yaml config.yaml
docker compose up -d postgres
alembic upgrade head
uvicorn app.main:app --reload
```

Docker で API も起動する場合:

```bash
docker compose up --build
```

## Scan

```bash
python -m app.cli scan --config config.yaml
python -m app.cli scan --config config.yaml --full
python -m app.cli show-config --config config.yaml
```

ACL CSV を取り込む場合:

```bash
python -m app.cli load-acl-csv --csv acl.csv
```

CSV カラム:

```csv
file_id,principal_type,principal_name,permission,can_read,inherited
```

## Search API

Health check:

```bash
curl http://localhost:8000/health
```

Search:

```bash
curl -X POST http://localhost:8000/search \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "顧客管理システムのA001画面設計書はどこにある？",
    "user_id": "user001",
    "group_ids": ["dev_team"],
    "top_k": 10,
    "search_mode": "hybrid",
    "filters": {
      "include_archive": false,
      "latest_only": false
    }
  }'
```

レスポンスには `file_name`, `file_path`, `score`, `match_reason`, `matched_chunks` が含まれます。API は DB に登録されているファイル名・パスだけを返し、存在しないパスは生成しません。

## Config

`config.yaml` では以下を調整できます。

- `scan.roots`: スキャン対象フォルダ
- `scan.include_extensions`: 対象拡張子
- `scan.exclude_dir_patterns`: 除外ディレクトリ
- `scan.max_extract_chars_per_file`: 1ファイルあたりの最大抽出文字数
- `scan.chunk_size`, `scan.chunk_overlap`: チャンク分割設定
- `metadata.document_type_keywords`: 文書種別推定キーワード
- `search.vector_weight`, `search.keyword_weight`, `search.metadata_weight`: 再ランキング重み

## Embedding

デフォルトは `HashEmbeddingProvider` です。外部通信せず安定した疑似ベクトルを生成するため、開発・疎通確認には使えますが、意味検索の品質はありません。

本番では `EMBEDDING_PROVIDER=openai_compatible` を設定し、OpenAI 互換の embeddings API を指定してください。API キーや抽出本文はログ出力しません。

## PGroonga

PGroonga は任意です。標準の `docker-compose.yml` では `pgvector/pgvector:pg16` を使うため、PGroonga は含まれません。日本語全文検索を強化する場合は、PostgreSQL イメージに別途 PGroonga を導入してください。PGroonga がなくても、pg_trgm、ILIKE、pgvector で起動できます。

## ACL_MODE

- `off`: ACL を無視
- `permissive`: ACL レコードがないファイルは閲覧可能。ACL がある場合は `user_id` または `group_ids` の一致が必要
- `strict`: `user_id` または `group_ids` に一致する read 権限が必須

## Known Limitations

- `.xls` は初期実装では非対応
- パスワード付き Office/PDF は抽出不可
- 画像 PDF の OCR は初期実装では非対応
- Windows ACL の完全自動取得は初期実装では非対応
- HashEmbeddingProvider は意味検索品質を提供しない
