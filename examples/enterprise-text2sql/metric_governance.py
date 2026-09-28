"""SQLite-backed approval and immutable audit trail for semantic metric releases."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from semantic_metrics import _CATALOG, validate_metric_catalog


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class MetricReleaseStore:
    """Persist draft, approval and publication state alongside the demo database."""

    def __init__(self, database_path: str | Path):
        self.database_path = str(database_path)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self):
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metric_releases (
                    metric_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    definition_json TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(
                        status IN ('draft', 'published', 'rejected')
                    ),
                    is_default INTEGER NOT NULL DEFAULT 0 CHECK(is_default IN (0, 1)),
                    submitted_by TEXT NOT NULL,
                    submitted_role TEXT NOT NULL,
                    submitted_tenant_id TEXT,
                    submitted_at TEXT NOT NULL,
                    reviewed_by TEXT,
                    reviewed_role TEXT,
                    reviewed_tenant_id TEXT,
                    reviewed_at TEXT,
                    review_reason TEXT,
                    PRIMARY KEY(metric_id, version)
                );
                CREATE TABLE IF NOT EXISTS metric_release_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    metric_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor_user_id TEXT NOT NULL,
                    actor_role TEXT NOT NULL,
                    tenant_id TEXT,
                    reason TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS metric_release_audit_no_update
                BEFORE UPDATE ON metric_release_audit
                BEGIN SELECT RAISE(ABORT, 'metric release audit is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS metric_release_audit_no_delete
                BEFORE DELETE ON metric_release_audit
                BEGIN SELECT RAISE(ABORT, 'metric release audit is append-only'); END;
                """
            )
            existing = connection.execute(
                "SELECT COUNT(*) FROM metric_releases"
            ).fetchone()[0]
            if existing:
                return
            defaults = _CATALOG["default_metric_versions"]
            for metric in _CATALOG["metrics"]:
                definition = dict(metric)
                content = _canonical_json(definition)
                connection.execute(
                    """INSERT INTO metric_releases
                       (metric_id, version, definition_json, content_sha256,
                        status, is_default, submitted_by, submitted_role,
                        submitted_at, reviewed_by, reviewed_role, reviewed_at,
                        review_reason)
                       VALUES (?, ?, ?, ?, 'published', ?, 'system-seed', 'system',
                               ?, 'system-seed', 'system', ?, 'Initial catalog')""",
                    (
                        metric["id"],
                        metric["version"],
                        content,
                        hashlib.sha256(content.encode("utf-8")).hexdigest(),
                        int(defaults.get(metric["id"]) == metric["version"]),
                        _now(),
                        _now(),
                    ),
                )

    def _catalog(self, connection: sqlite3.Connection) -> dict[str, Any]:
        rows = connection.execute(
            "SELECT * FROM metric_releases WHERE status='published' "
            "ORDER BY metric_id, version"
        ).fetchall()
        metrics = [json.loads(row["definition_json"]) for row in rows]
        defaults = {
            row["metric_id"]: row["version"] for row in rows if row["is_default"]
        }
        content_hashes = {
            f"{row['metric_id']}@{row['version']}": row["content_sha256"]
            for row in rows
        }
        digest_source = "".join(
            f"{row['metric_id']}@{row['version']}:{row['content_sha256']}\n"
            for row in rows
            if row["is_default"]
        )
        catalog = {
            "catalog_version": hashlib.sha256(digest_source.encode()).hexdigest()[:16],
            "default_metric_versions": defaults,
            "metrics": metrics,
            "metric_content_sha256": content_hashes,
            "dimensions": _CATALOG["dimensions"],
        }
        validate_metric_catalog(catalog)
        return catalog

    def snapshot(self) -> dict[str, Any]:
        with self._connect() as connection:
            return self._catalog(connection)

    def releases(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT metric_id, version, content_sha256, status, is_default,
                          submitted_by, submitted_role, submitted_tenant_id,
                          submitted_at,
                          reviewed_by, reviewed_role, reviewed_tenant_id, reviewed_at,
                          review_reason
                   FROM metric_releases ORDER BY metric_id, version"""
            ).fetchall()
            return [dict(row) for row in rows]

    def submit(
        self,
        definition: dict[str, Any],
        *,
        actor_user_id: str,
        actor_role: str,
        tenant_id: str | None,
        reason: str,
    ) -> dict[str, Any]:
        if actor_role != "admin" or not actor_user_id:
            raise PermissionError(
                "Metric release submission requires an identified admin"
            )
        if not reason.strip():
            raise ValueError("Submission reason is required")
        definition = {
            key: value for key, value in definition.items() if key != "status"
        }
        metric_id, version = definition.get("id"), definition.get("version")
        if not isinstance(metric_id, str) or not isinstance(version, str):
            raise ValueError("Metric ID and version are required")
        content = _canonical_json(definition)
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM metric_releases WHERE metric_id=? AND version=?",
                (metric_id, version),
            ).fetchone():
                raise ValueError("Metric version already exists and is immutable")
            candidate = self._catalog(connection)
            candidate["metrics"].append({**definition, "status": "published"})
            candidate["default_metric_versions"].setdefault(metric_id, version)
            validate_metric_catalog(candidate)
            timestamp = _now()
            connection.execute(
                """INSERT INTO metric_releases
                   (metric_id, version, definition_json, content_sha256, status,
                    submitted_by, submitted_role, submitted_tenant_id, submitted_at)
                   VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?)""",
                (
                    metric_id,
                    version,
                    content,
                    content_hash,
                    actor_user_id,
                    actor_role,
                    tenant_id,
                    timestamp,
                ),
            )
            self._audit(
                connection,
                metric_id,
                version,
                content_hash,
                "submitted",
                actor_user_id,
                actor_role,
                tenant_id,
                reason.strip(),
                timestamp,
            )
        return {
            "metric_id": metric_id,
            "version": version,
            "content_sha256": content_hash,
            "status": "draft",
        }

    def review(
        self,
        metric_id: str,
        version: str,
        *,
        approve: bool,
        actor_user_id: str,
        actor_role: str,
        tenant_id: str | None,
        reason: str,
    ) -> dict[str, Any]:
        if actor_role != "admin" or not actor_user_id:
            raise PermissionError("Metric release review requires an identified admin")
        if not reason.strip():
            raise ValueError("Review reason is required")
        denied_self_review = False
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM metric_releases WHERE metric_id=? AND version=?",
                (metric_id, version),
            ).fetchone()
            if row is None or row["status"] != "draft":
                raise ValueError("Only an existing draft can be reviewed")
            if row["submitted_by"] == actor_user_id:
                self._audit(
                    connection,
                    metric_id,
                    version,
                    row["content_sha256"],
                    "self_review_denied",
                    actor_user_id,
                    actor_role,
                    tenant_id,
                    reason.strip(),
                    _now(),
                )
                denied_self_review = True
            if denied_self_review:
                pass
            else:
                status = "published" if approve else "rejected"
                timestamp = _now()
                if approve:
                    candidate = self._catalog(connection)
                    candidate["metrics"].append(json.loads(row["definition_json"]))
                    candidate["metrics"][-1]["status"] = "published"
                    candidate["default_metric_versions"][metric_id] = version
                    validate_metric_catalog(candidate)
                    connection.execute(
                        "UPDATE metric_releases SET is_default=0 WHERE metric_id=?",
                        (metric_id,),
                    )
                connection.execute(
                    """UPDATE metric_releases SET status=?, is_default=?, reviewed_by=?,
                              reviewed_role=?, reviewed_tenant_id=?, reviewed_at=?,
                              review_reason=?
                       WHERE metric_id=? AND version=? AND status='draft'""",
                    (
                        status,
                        int(approve),
                        actor_user_id,
                        actor_role,
                        tenant_id,
                        timestamp,
                        reason.strip(),
                        metric_id,
                        version,
                    ),
                )
                self._audit(
                    connection,
                    metric_id,
                    version,
                    row["content_sha256"],
                    "approved" if approve else "rejected",
                    actor_user_id,
                    actor_role,
                    tenant_id,
                    reason.strip(),
                    timestamp,
                )
        if denied_self_review:
            raise PermissionError("Submitter cannot review their own release")
        return {"metric_id": metric_id, "version": version, "status": status}

    @staticmethod
    def _audit(
        connection,
        metric_id,
        version,
        content_hash,
        action,
        actor,
        role,
        tenant,
        reason,
        timestamp,
    ):
        connection.execute(
            """INSERT INTO metric_release_audit
               (metric_id, version, content_sha256, action, actor_user_id,
                actor_role, tenant_id, reason, occurred_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                metric_id,
                version,
                content_hash,
                action,
                actor,
                role,
                tenant,
                reason,
                timestamp,
            ),
        )

    def audit_events(self, metric_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as connection:
            if metric_id:
                rows = connection.execute(
                    "SELECT * FROM metric_release_audit WHERE metric_id=? ORDER BY id",
                    (metric_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM metric_release_audit ORDER BY id"
                ).fetchall()
            return [dict(row) for row in rows]
