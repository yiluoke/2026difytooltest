from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from app.config import load_app_config
from app.db.session import SessionLocal
from app.services.embedder import get_embedding_provider
from app.services.scanner import FileScanner, load_acl_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="File search backend CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan")
    scan_parser.add_argument("--config", required=True)
    scan_parser.add_argument("--full", action="store_true")

    show_config_parser = subparsers.add_parser("show-config")
    show_config_parser.add_argument("--config", required=True)

    acl_parser = subparsers.add_parser("load-acl-csv")
    acl_parser.add_argument("--csv", required=True)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    if args.command == "show-config":
        config = load_app_config(args.config)
        print(config.model_dump_json(indent=2))
        return

    if args.command == "scan":
        config = load_app_config(args.config)
        with SessionLocal() as db:
            summary = FileScanner(db, config, get_embedding_provider()).scan(full=args.full)
        print(json.dumps(summary.__dict__, ensure_ascii=False, indent=2))
        return

    if args.command == "load-acl-csv":
        with SessionLocal() as db:
            count = load_acl_csv(db, Path(args.csv))
        print(json.dumps({"loaded": count}, ensure_ascii=False))


if __name__ == "__main__":
    main()

