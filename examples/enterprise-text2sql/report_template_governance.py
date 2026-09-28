"""SQLite/PostgreSQL-backed two-person approval for report templates."""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    text,
)
from sqlalchemy.engine import URL, Connection, make_url
from sqlalchemy.exc import IntegrityError

_TEMPLATE_ID = re.compile(r"^[a-z][a-z0-9-]*@\d+\.\d+\.\d+$")
_ROLES = {"admin", "normal", "sales"}
_METADATA = MetaData()
_RELEASES = Table(
    "report_template_releases",
    _METADATA,
    Column("template_id", String, primary_key=True),
    Column("definition_json", Text, nullable=False),
    Column("content_sha256", String, nullable=False),
    Column(
        "status",
        String,
        CheckConstraint("status IN ('draft', 'published', 'rejected')"),
        nullable=False,
    ),
    Column("submitted_by", String, nullable=False),
    Column("submitted_at", String, nullable=False),
    Column("reviewed_by", String),
    Column("reviewed_at", String),
    Column("review_reason", String),
)
_AUDIT = Table(
    "report_template_audit",
    _METADATA,
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True),
    Column("template_id", String, nullable=False),
    Column("content_sha256", String, nullable=False),
    Column("action", String, nullable=False),
    Column("actor_user_id", String, nullable=False),
    Column("actor_role", String, nullable=False),
    Column("reason", String, nullable=False),
    Column("occurred_at", String, nullable=False),
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class _ResultAdapter:
    def __init__(self, result):
        self._result = result
        self.rowcount = result.rowcount

    def fetchone(self):
        return self._result.mappings().fetchone() if self._result.returns_rows else None

    def fetchall(self):
        return self._result.mappings().fetchall() if self._result.returns_rows else []


def _execute(connection: Connection, statement: str, parameters=()) -> _ResultAdapter:
    if isinstance(parameters, dict):
        query = statement
        bound = parameters
    else:
        index = 0

        def bind(_match):
            nonlocal index
            name = f"p{index}"
            index += 1
            return f":{name}"

        query = re.sub(r"\?", bind, statement)
        bound = {f"p{i}": value for i, value in enumerate(parameters)}
    return _ResultAdapter(connection.execute(text(query), bound))


class ReportTemplateReleaseStore:
    """Persist immutable template definitions and their approval history."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        allowed_metrics: dict[str, set[str]],
        definition_fields: tuple[str, ...],
        result_fields: tuple[str, ...],
        seed_path: str | Path,
    ):
        configured_database = str(database_path)
        self.allowed_metrics = allowed_metrics
        self.definition_fields = set(definition_fields)
        self.result_fields = set(result_fields)
        self.seed_path = Path(seed_path)
        if "://" in configured_database:
            database_url = make_url(configured_database)
            if (
                database_url.get_backend_name() == "sqlite"
                and database_url.database
                and database_url.database != ":memory:"
            ):
                Path(database_url.database).expanduser().parent.mkdir(
                    parents=True, exist_ok=True
                )
            self.database_path = configured_database
            self._engine = create_engine(
                database_url,
                connect_args=(
                    {"timeout": 10}
                    if database_url.get_backend_name() == "sqlite"
                    else {}
                ),
                pool_pre_ping=True,
            )
        else:
            database_file = Path(configured_database).expanduser().resolve()
            database_file.parent.mkdir(parents=True, exist_ok=True)
            self.database_path = str(database_file)
            self._engine = create_engine(
                URL.create("sqlite", database=self.database_path),
                connect_args={"timeout": 10},
                pool_pre_ping=True,
            )
        if self._engine.dialect.name not in {"sqlite", "postgresql"}:
            raise ValueError("Report template storage supports SQLite and PostgreSQL")
        self._initialize()

    @contextmanager
    def _connect(self, *, immediate: bool = False) -> Iterator[Connection]:
        with self._engine.connect() as connection:
            with connection.begin():
                if immediate and self._engine.dialect.name == "sqlite":
                    connection.exec_driver_sql("BEGIN IMMEDIATE")
                yield connection

    def _validate(self, template: dict[str, Any]) -> dict[str, Any]:
        required = {
            "id",
            "allowed_roles",
            "allowed_metric_ids",
            "definition_fields",
            "result_fields",
        }
        if not isinstance(template, dict) or set(template) != required:
            raise ValueError("Template must contain only the registered fields")
        template_id = template["id"]
        if not isinstance(template_id, str) or not _TEMPLATE_ID.fullmatch(template_id):
            raise ValueError("Template ID must include a semantic version")
        normalized = {"id": template_id}
        for name, allowed in (
            ("allowed_roles", _ROLES),
            ("definition_fields", self.definition_fields),
            ("result_fields", self.result_fields),
        ):
            values = template[name]
            if (
                not isinstance(values, list)
                or not values
                or any(
                    not isinstance(value, str) or value not in allowed
                    for value in values
                )
                or len(values) != len(set(values))
            ):
                raise ValueError(f"Template {name} contains invalid values")
            normalized[name] = list(values)

        metric_ids = template["allowed_metric_ids"]
        if (
            not isinstance(metric_ids, list)
            or not metric_ids
            or any(
                not isinstance(metric_id, str) or metric_id not in self.allowed_metrics
                for metric_id in metric_ids
            )
            or len(metric_ids) != len(set(metric_ids))
        ):
            raise ValueError("Template allowed_metric_ids contains invalid values")
        roles = set(normalized["allowed_roles"])
        for metric_id in metric_ids:
            if not roles <= self.allowed_metrics[metric_id]:
                raise ValueError(
                    "Template grants a role not allowed to export a metric"
                )
        normalized["allowed_metric_ids"] = list(metric_ids)
        return normalized

    def _audit(
        self,
        connection: Connection,
        template_id: str,
        content_sha256: str,
        action: str,
        actor_user_id: str,
        actor_role: str,
        reason: str,
        occurred_at: str,
    ):
        _execute(
            connection,
            """INSERT INTO report_template_audit
               (template_id, content_sha256, action, actor_user_id, actor_role,
                reason, occurred_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                template_id,
                content_sha256,
                action,
                actor_user_id,
                actor_role,
                reason,
                occurred_at,
            ),
        )

    def _initialize(self):
        with self._connect(immediate=True) as connection:
            if self._engine.dialect.name == "postgresql":
                # Serialize first-start DDL/seed work across API instances.
                connection.execute(text("SELECT pg_advisory_xact_lock(741903112)"))
            _METADATA.create_all(connection)
            if self._engine.dialect.name == "sqlite":
                connection.exec_driver_sql(
                    "CREATE TRIGGER IF NOT EXISTS "
                    "report_template_audit_no_update BEFORE UPDATE "
                    "ON report_template_audit BEGIN SELECT RAISE(ABORT, "
                    "'report template audit is append-only'); END"
                )
                connection.exec_driver_sql(
                    "CREATE TRIGGER IF NOT EXISTS "
                    "report_template_audit_no_delete BEFORE DELETE "
                    "ON report_template_audit BEGIN SELECT RAISE(ABORT, "
                    "'report template audit is append-only'); END"
                )
            else:
                connection.exec_driver_sql(
                    """CREATE OR REPLACE FUNCTION report_template_audit_immutable()
                       RETURNS trigger LANGUAGE plpgsql AS $$
                       BEGIN
                           RAISE EXCEPTION 'report template audit is append-only';
                       END;
                       $$"""
                )
                connection.exec_driver_sql(
                    """DO $$ BEGIN
                       IF NOT EXISTS (
                           SELECT 1 FROM pg_trigger
                           WHERE tgname = 'report_template_audit_no_update'
                             AND tgrelid = 'report_template_audit'::regclass
                       ) THEN
                           CREATE TRIGGER report_template_audit_no_update
                           BEFORE UPDATE ON report_template_audit
                           FOR EACH ROW EXECUTE FUNCTION
                           report_template_audit_immutable();
                       END IF;
                       IF NOT EXISTS (
                           SELECT 1 FROM pg_trigger
                           WHERE tgname = 'report_template_audit_no_delete'
                             AND tgrelid = 'report_template_audit'::regclass
                       ) THEN
                           CREATE TRIGGER report_template_audit_no_delete
                           BEFORE DELETE ON report_template_audit
                           FOR EACH ROW EXECUTE FUNCTION
                           report_template_audit_immutable();
                       END IF;
                       END $$"""
                )

            seed = json.loads(self.seed_path.read_text(encoding="utf-8"))
            for raw_template in seed["templates"]:
                template = self._validate(raw_template)
                content = _canonical_json(template)
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                now = _now()
                if self._engine.dialect.name == "postgresql":
                    result = connection.execute(
                        text(
                            """INSERT INTO report_template_releases
                               (template_id, definition_json, content_sha256, status,
                                submitted_by, submitted_at, reviewed_by, reviewed_at,
                                review_reason)
                               VALUES (:id, :content, :digest, 'published',
                                       'system-seed', :now, 'system-seed', :now,
                                       'Initial catalog')
                               ON CONFLICT (template_id) DO NOTHING"""
                        ),
                        {
                            "id": template["id"],
                            "content": content,
                            "digest": digest,
                            "now": now,
                        },
                    )
                else:
                    result = connection.execute(
                        text(
                            """INSERT OR IGNORE INTO report_template_releases
                               (template_id, definition_json, content_sha256, status,
                                submitted_by, submitted_at, reviewed_by, reviewed_at,
                                review_reason)
                               VALUES (:id, :content, :digest, 'published',
                                       'system-seed', :now, 'system-seed', :now,
                                       'Initial catalog')"""
                        ),
                        {
                            "id": template["id"],
                            "content": content,
                            "digest": digest,
                            "now": now,
                        },
                    )
                if result.rowcount == 1:
                    self._audit(
                        connection,
                        template["id"],
                        digest,
                        "seeded",
                        "system-seed",
                        "system",
                        "Initial catalog",
                        now,
                    )

    def snapshot(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = _execute(
                connection,
                "SELECT template_id, definition_json, content_sha256 "
                "FROM report_template_releases WHERE status='published' "
                "ORDER BY template_id",
            ).fetchall()
        templates = [json.loads(row["definition_json"]) for row in rows]
        digest_source = "".join(
            f"{row['template_id']}:{row['content_sha256']}\n" for row in rows
        )
        return {
            "catalog_version": hashlib.sha256(digest_source.encode()).hexdigest()[:16],
            "templates": templates,
            "template_content_sha256": {
                row["template_id"]: row["content_sha256"] for row in rows
            },
        }

    def releases(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = _execute(
                connection,
                """SELECT template_id, content_sha256, status, submitted_by,
                          submitted_at, reviewed_by, reviewed_at, review_reason
                   FROM report_template_releases ORDER BY template_id""",
            ).fetchall()
        return [dict(row) for row in rows]

    def audit_events(self, template_id: str | None = None) -> list[dict[str, Any]]:
        query = """SELECT template_id, content_sha256, action, actor_user_id,
                          actor_role, reason, occurred_at FROM report_template_audit"""
        parameters: tuple = ()
        if template_id:
            query += " WHERE template_id=?"
            parameters = (template_id,)
        query += " ORDER BY id"
        with self._connect() as connection:
            rows = _execute(connection, query, parameters).fetchall()
        return [dict(row) for row in rows]

    def submit(
        self,
        definition: dict[str, Any],
        *,
        actor_user_id: str,
        actor_role: str,
        reason: str,
    ) -> dict[str, Any]:
        if actor_role != "admin" or not actor_user_id:
            raise PermissionError("Template release submission requires an admin")
        if not reason.strip() or len(reason) > 500:
            raise ValueError(
                "A submission reason of at most 500 characters is required"
            )
        template = self._validate(definition)
        content = _canonical_json(template)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        now = _now()
        try:
            with self._connect(immediate=True) as connection:
                _execute(
                    connection,
                    """INSERT INTO report_template_releases
                       (template_id, definition_json, content_sha256, status,
                        submitted_by, submitted_at)
                       VALUES (?, ?, ?, 'draft', ?, ?)""",
                    (template["id"], content, digest, actor_user_id, now),
                )
                self._audit(
                    connection,
                    template["id"],
                    digest,
                    "submitted",
                    actor_user_id,
                    actor_role,
                    reason,
                    now,
                )
        except IntegrityError as exc:
            raise ValueError("Template ID already exists") from exc
        return {
            "template_id": template["id"],
            "status": "draft",
            "content_sha256": digest,
        }

    def review(
        self,
        template_id: str,
        *,
        approve: bool,
        actor_user_id: str,
        actor_role: str,
        reason: str,
    ) -> dict[str, Any]:
        if actor_role != "admin" or not actor_user_id:
            raise PermissionError("Template review requires an admin")
        if not reason.strip() or len(reason) > 500:
            raise ValueError("A review reason of at most 500 characters is required")
        self_review = False
        with self._connect(immediate=True) as connection:
            query = (
                "SELECT content_sha256, status, submitted_by FROM "
                "report_template_releases WHERE template_id=?"
            )
            if self._engine.dialect.name == "postgresql":
                query += " FOR UPDATE"
            row = _execute(connection, query, (template_id,)).fetchone()
            if row is None:
                raise ValueError("Template release not found")
            if row["status"] != "draft":
                raise ValueError("Template release is not pending review")
            if row["submitted_by"] == actor_user_id:
                self._audit(
                    connection,
                    template_id,
                    row["content_sha256"],
                    "self_review_denied",
                    actor_user_id,
                    actor_role,
                    reason,
                    _now(),
                )
                self_review = True
            else:
                status = "published" if approve else "rejected"
                now = _now()
                updated = _execute(
                    connection,
                    """UPDATE report_template_releases
                       SET status=?, reviewed_by=?, reviewed_at=?, review_reason=?
                       WHERE template_id=? AND status='draft'""",
                    (status, actor_user_id, now, reason, template_id),
                )
                if updated.rowcount != 1:
                    raise ValueError("Template release is not pending review")
                self._audit(
                    connection,
                    template_id,
                    row["content_sha256"],
                    "approved" if approve else "rejected",
                    actor_user_id,
                    actor_role,
                    reason,
                    now,
                )
        if self_review:
            raise PermissionError("Template submitter cannot review it")
        return {"template_id": template_id, "status": status}
