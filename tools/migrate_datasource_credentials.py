#!/usr/bin/env python
"""Dry-run-first migration of stored datasource credentials and approval state."""

import argparse
import json
import os
import sys
from typing import Any, Dict

from sqlalchemy import create_engine, inspect, text

from dbgpt_serve.datasource.manages.connector_manager import ConnectorManager
from dbgpt_serve.datasource.security import (
    encrypt_secret,
    is_encrypted_secret,
    privacy_fields_for_type,
)


def _private_fields(manager, db_type: str):
    try:
        return privacy_fields_for_type(db_type, manager)
    except Exception as exc:
        raise ValueError(f"Unsupported datasource type: {db_type}") from exc


def _upgrade_sqlite_schema(connection, dialect: str, *, apply: bool):
    inspector = inspect(connection)
    columns = {item["name"] for item in inspector.get_columns("connect_config")}
    if dialect != "sqlite":
        required = {
            "approval_status",
            "submitted_by",
            "approved_by",
            "approved_at",
            "approval_reason",
        }
        missing = required - columns
        if missing:
            raise RuntimeError(
                "Apply assets/schema/upgrade/v0_8_2/upgrade_to_v0.8.2.sql "
                "before migrating datasource rows"
            )
        return
    if not apply:
        missing = {
            "approval_status",
            "submitted_by",
            "approved_by",
            "approved_at",
            "approval_reason",
        } - columns
        if missing:
            print("SQLite schema changes required: " + ", ".join(sorted(missing)))
        return
    if "approval_status" not in columns:
        connection.execute(
            text(
                "ALTER TABLE connect_config ADD COLUMN approval_status "
                "VARCHAR(32) NOT NULL DEFAULT 'pending'"
            )
        )
    for name, sql_type in (
        ("submitted_by", "VARCHAR(128)"),
        ("approved_by", "VARCHAR(128)"),
        ("approved_at", "DATETIME"),
        ("approval_reason", "TEXT"),
    ):
        if name not in columns:
            connection.execute(
                text(f"ALTER TABLE connect_config ADD COLUMN {name} {sql_type}")
            )
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS datasource_approval_audit ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, db_name VARCHAR(255) NOT NULL, "
            "actor_id VARCHAR(128) NOT NULL, decision VARCHAR(16) NOT NULL, "
            "reason TEXT, created_at DATETIME NOT NULL)"
        )
    )


def _protect_row(row: Dict[str, Any], manager) -> Dict[str, Any]:
    db_type = row["db_type"]
    private_names = _private_fields(manager, db_type)
    password = row.get("db_pwd")
    if password and not is_encrypted_secret(password):
        row["db_pwd"] = encrypt_secret(password)
    ext_config = row.get("ext_config")
    if isinstance(ext_config, str) and ext_config:
        ext_config = json.loads(ext_config)
    if ext_config is None:
        ext_config = {}
    if not isinstance(ext_config, dict):
        raise ValueError("invalid ext_config")
    for name in private_names:
        value = ext_config.get(name)
        if value and not is_encrypted_secret(value):
            ext_config[name] = encrypt_secret(value)
    row["ext_config"] = json.dumps(ext_config, ensure_ascii=False)
    return row


def migrate(database_url: str, *, apply: bool, batch_size: int = 100) -> int:
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    engine = create_engine(database_url)
    manager = ConnectorManager.__new__(ConnectorManager)
    manager.on_init()
    migrated = 0
    try:
        with engine.connect() as connection:
            dialect = engine.dialect.name
            if apply:
                with connection.begin():
                    _upgrade_sqlite_schema(connection, dialect, apply=True)
            else:
                _upgrade_sqlite_schema(connection, dialect, apply=False)
            columns = {
                item["name"]
                for item in inspect(connection).get_columns("connect_config")
            }
            connection.commit()
            approval_column = (
                "approval_status" if "approval_status" in columns else "'pending'"
            )
            scan_statement = text(
                "SELECT id, db_type, db_pwd, ext_config, user_id, "
                f"{approval_column} AS approval_status FROM connect_config "
                "WHERE id > :last_id ORDER BY id LIMIT :batch_size"
            )
            last_id = 0
            datasource_ids = []
            skipped_ids = []
            while True:
                result = connection.execute(
                    scan_statement, {"last_id": last_id, "batch_size": batch_size}
                )
                rows = [dict(row) for row in result.mappings().all()]
                connection.commit()
                if not rows:
                    break
                last_id = rows[-1]["id"]
                updates = []
                for row in rows:
                    needs_migration = row.get("approval_status") != "pending"
                    needs_migration = needs_migration or bool(
                        row.get("db_pwd") and not is_encrypted_secret(row.get("db_pwd"))
                    )
                    try:
                        ext_config = row.get("ext_config")
                        if isinstance(ext_config, str) and ext_config:
                            ext_config = json.loads(ext_config)
                        if ext_config is not None and not isinstance(ext_config, dict):
                            raise ValueError("invalid ext_config")
                        private_names = _private_fields(manager, row["db_type"])
                        if isinstance(ext_config, dict):
                            needs_migration = needs_migration or any(
                                ext_config.get(name)
                                and not is_encrypted_secret(ext_config[name])
                                for name in private_names
                            )
                    except Exception as exc:
                        skipped_ids.append((row["id"], type(exc).__name__))
                        continue
                    if not needs_migration:
                        continue
                    datasource_ids.append(row["id"])
                    if apply:
                        try:
                            updates.append(_protect_row(row, manager))
                        except Exception as exc:
                            skipped_ids.append((row["id"], type(exc).__name__))
                if updates:
                    with connection.begin():
                        for row in updates:
                            connection.execute(
                                text(
                                    "UPDATE connect_config SET db_pwd=:db_pwd, "
                                    "ext_config=:ext_config, "
                                    "approval_status='pending', "
                                    "submitted_by=COALESCE(submitted_by, user_id), "
                                    "approved_by=NULL, approved_at=NULL, "
                                    "approval_reason=NULL WHERE id=:id"
                                ),
                                {
                                    "db_pwd": row.get("db_pwd"),
                                    "ext_config": row.get("ext_config"),
                                    "id": row["id"],
                                },
                            )
                    migrated += len(updates)
            print(f"Rows requiring migration: {len(datasource_ids)}")
            if datasource_ids:
                print("Datasource IDs: " + ", ".join(map(str, datasource_ids)))
            if skipped_ids:
                print(
                    "Skipped datasource IDs: "
                    + ", ".join(f"{row_id}({error})" for row_id, error in skipped_ids)
                )
            if apply:
                print(f"Migrated datasource rows: {migrated}")
            return len(datasource_ids) if not apply else migrated
    finally:
        engine.dispose()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--batch-size", type=int, default=100, help="Rows per commit (1–1000)."
    )
    parser.add_argument(
        "--apply", action="store_true", help="Apply changes; default is dry-run."
    )
    args = parser.parse_args(argv)
    database_url = os.getenv("DBGPT_METADATA_DATABASE_URL")
    if not database_url:
        parser.error("Set DBGPT_METADATA_DATABASE_URL to the metadata DB URL.")
    if args.apply and not os.getenv("DBGPT_DATASOURCE_ENCRYPTION_KEY"):
        parser.error("Set DBGPT_DATASOURCE_ENCRYPTION_KEY before applying migration.")
    try:
        migrate(database_url, apply=args.apply, batch_size=args.batch_size)
    except Exception as exc:
        print(f"Migration failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
