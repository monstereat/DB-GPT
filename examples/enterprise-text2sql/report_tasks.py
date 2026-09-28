"""Durable SQLite/PostgreSQL queue for the enterprise analytics report demo."""

import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from threading import Event, Thread
from typing import Callable, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Connection, Engine, make_url


class _ResultAdapter:
    def __init__(self, result):
        self._result = result
        self.rowcount = result.rowcount

    def fetchone(self):
        return self._result.mappings().fetchone() if self._result.returns_rows else None

    def fetchall(self):
        return self._result.mappings().fetchall() if self._result.returns_rows else []


class _ConnectionAdapter:
    """Keep the store's compact qmark SQL portable through SQLAlchemy Core."""

    def __init__(self, connection: Connection, dialect_name: str):
        self._connection = connection
        self.dialect_name = dialect_name

    def execute(self, statement: str, parameters=()):
        if statement == "BEGIN IMMEDIATE":
            if self.dialect_name == "sqlite":
                self._connection.exec_driver_sql(statement)
            return _ResultAdapter(
                self._connection.exec_driver_sql("SELECT 1 WHERE 1 = 0")
            )
        if isinstance(parameters, dict):
            bound = parameters
            query = statement
        else:
            index = 0

            def bind(_match):
                nonlocal index
                name = f"p{index}"
                index += 1
                return f":{name}"

            query = re.sub(r"\?", bind, statement)
            bound = {f"p{i}": value for i, value in enumerate(parameters)}
        return _ResultAdapter(self._connection.execute(text(query), bound))


class _ManagedConnection:
    def __init__(self, engine: Engine):
        self._engine = engine
        self._connection = None
        self._transaction = None
        self.adapter = None

    def __enter__(self):
        self._connection = self._engine.connect()
        self._transaction = self._connection.begin()
        self.adapter = _ConnectionAdapter(self._connection, self._engine.dialect.name)
        if self._engine.dialect.name == "sqlite":
            self.adapter.execute("PRAGMA busy_timeout = 10000")
        return self.adapter

    def __exit__(self, exception_type, exception, traceback):
        try:
            if exception_type is None:
                self._transaction.commit()
            else:
                self._transaction.rollback()
        finally:
            self._connection.close()
        return False


class IdempotencyConflict(ValueError):
    """Raised when a key is reused for a different report request."""


class ReportResultDecryptionError(RuntimeError):
    """Raised when an encrypted result cannot be read with the configured key."""


class ReportResultEncryptionError(RuntimeError):
    """Raised when report results cannot be encrypted at rest."""


class ReportTaskStore:
    """Small persistent queue with atomic claims and expiring worker leases."""

    def __init__(self, database_path: str | Path, max_attempts: int = 2):
        configured_database = str(database_path)
        self.max_attempts = max_attempts
        self._cipher = None
        self._primary_cipher = None
        self._invalid_token = None
        encryption_key = os.getenv("DBGPT_REPORT_ENCRYPTION_KEY")
        encryption_keys = os.getenv("DBGPT_REPORT_ENCRYPTION_KEYS")
        if encryption_key and encryption_keys:
            raise ValueError("Configure only one report result encryption key setting")
        if encryption_key or encryption_keys:
            try:
                from cryptography.fernet import Fernet, InvalidToken, MultiFernet

                key_values = (
                    [encryption_key]
                    if encryption_key
                    else [value.strip() for value in encryption_keys.split(",")]
                )
                if not key_values or any(not value for value in key_values):
                    raise ValueError("Empty key in report result encryption key ring")
                if len(key_values) > 8:
                    raise ValueError("Report result encryption key ring is too large")
                ciphers = [Fernet(value.encode("ascii")) for value in key_values]
                self._primary_cipher = ciphers[0]
                self._cipher = MultiFernet(ciphers)
                self._invalid_token = InvalidToken
            except (ImportError, TypeError, UnicodeEncodeError, ValueError) as exc:
                raise ValueError(
                    "Invalid report result encryption configuration"
                ) from exc
        if "://" in configured_database:
            database_url = make_url(configured_database)
            if (
                database_url.get_backend_name() == "sqlite"
                and database_url.database
                and database_url.database != ":memory:"
            ):
                database_file = Path(database_url.database).expanduser()
                database_file.parent.mkdir(parents=True, exist_ok=True)
                descriptor = os.open(database_file, os.O_CREAT | os.O_RDWR, 0o600)
                os.close(descriptor)
                os.chmod(database_file, 0o600)
            self.database_path = configured_database
            self._engine = create_engine(database_url, pool_pre_ping=True)
        else:
            database_file = Path(configured_database).expanduser().resolve()
            database_file.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(database_file, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(descriptor)
            os.chmod(database_file, 0o600)
            self.database_path = str(database_file)
            self._engine = create_engine(
                URL.create("sqlite", database=self.database_path),
                connect_args={"timeout": 10},
                pool_pre_ping=True,
            )
        if self._engine.dialect.name not in {"sqlite", "postgresql"}:
            raise ValueError("Report task storage supports SQLite and PostgreSQL")
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS report_tasks (
                    task_id TEXT PRIMARY KEY,
                    actor_user_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    identity_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('queued', 'running', 'succeeded', 'failed')
                    ),
                    result_json TEXT,
                    error_code TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL,
                    available_at DOUBLE PRECISION NOT NULL,
                    lease_owner TEXT,
                    lease_expires_at DOUBLE PRECISION,
                    created_at DOUBLE PRECISION NOT NULL,
                    updated_at DOUBLE PRECISION NOT NULL,
                    UNIQUE(actor_user_id, idempotency_key)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS report_tasks_claim_idx "
                "ON report_tasks(status, available_at, created_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS report_tasks_lease_idx "
                "ON report_tasks(status, lease_expires_at)"
            )

    @property
    def result_encryption_enabled(self) -> bool:
        """Whether this store can encrypt report results before persisting them."""
        return self._cipher is not None

    def _connect(self):
        return _ManagedConnection(self._engine)

    @staticmethod
    def _public(row: dict) -> dict:
        request = json.loads(row["request_json"])
        catalog = request.get("metric_catalog") or {}
        template_id = request.get("report_template", {}).get("template", {}).get("id")
        return {
            "task_id": row["task_id"],
            "status": row["status"],
            "attempts": row["attempts"],
            "max_attempts": row["max_attempts"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "has_result": row["result_json"] is not None,
            "metric_catalog_version": catalog.get("catalog_version"),
            "metric_catalog_sha256": request.get("metric_catalog_sha256"),
            "report_template_version": (
                template_id.rsplit("@", 1)[-1] if isinstance(template_id, str) else None
            ),
            "report_template_id": template_id,
            "report_template_sha256": request.get("report_template_sha256"),
            "error_code": row["error_code"],
        }

    def _encode_result(self, result: dict) -> str:
        if self._cipher is None:
            raise ReportResultEncryptionError(
                "Report result encryption key is required"
            )
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        return "enc:v1:" + self._cipher.encrypt(encoded).decode("ascii")

    def _decode_result(self, value: str) -> dict:
        if not value.startswith("enc:v1:"):
            raise ReportResultDecryptionError(
                "Legacy plaintext report result is not served; migrate it with a key"
            )
        if self._cipher is None:
            raise ReportResultDecryptionError(
                "Report result encryption key is required"
            )
        try:
            decoded = self._cipher.decrypt(value[7:].encode("ascii"))
        except UnicodeEncodeError as exc:
            raise ReportResultDecryptionError(
                "Report result cannot be decrypted with the configured key"
            ) from exc
        except self._invalid_token as exc:
            raise ReportResultDecryptionError(
                "Report result cannot be decrypted with the configured key"
            ) from exc
        return json.loads(decoded.decode("utf-8"))

    def migrate_result_encryption(
        self, *, batch_size: int = 100, after_task_id: Optional[str] = None
    ) -> tuple[int, Optional[str]]:
        """Encrypt legacy plaintext and rotate old ciphertext in one bounded batch.

        Configure the active key first in ``DBGPT_REPORT_ENCRYPTION_KEYS``.
        Follow the returned cursor until it is ``None`` before removing any
        previous keys. The cursor advances even when a batch is already current.
        """
        if self._cipher is None or self._primary_cipher is None:
            raise ReportResultDecryptionError(
                "Report result encryption key is required for migration"
            )
        if not isinstance(batch_size, int) or isinstance(batch_size, bool):
            raise ValueError("batch_size must be an integer")
        if not 1 <= batch_size <= 1000:
            raise ValueError("batch_size must be between 1 and 1000")
        if after_task_id is not None and not isinstance(after_task_id, str):
            raise ValueError("after_task_id must be a string or None")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if after_task_id is None:
                rows = connection.execute(
                    "SELECT task_id, result_json FROM report_tasks "
                    "WHERE status = 'succeeded' AND result_json IS NOT NULL "
                    "ORDER BY task_id LIMIT ?",
                    (batch_size,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT task_id, result_json FROM report_tasks "
                    "WHERE status = 'succeeded' AND result_json IS NOT NULL "
                    "AND task_id > ? ORDER BY task_id LIMIT ?",
                    (after_task_id, batch_size),
                ).fetchall()
            migrated = 0
            for row in rows:
                value = row["result_json"]
                if value.startswith("enc:v1:"):
                    try:
                        token = value[7:].encode("ascii")
                    except UnicodeEncodeError as exc:
                        raise ReportResultDecryptionError(
                            "Report result cannot be decrypted with the configured key"
                        ) from exc
                    try:
                        self._primary_cipher.decrypt(token)
                        continue
                    except (UnicodeEncodeError, self._invalid_token):
                        try:
                            decoded = self._cipher.decrypt(token)
                        except (UnicodeEncodeError, self._invalid_token) as exc:
                            raise ReportResultDecryptionError(
                                "Report result cannot be decrypted with "
                                "the configured key"
                            ) from exc
                        encoded = "enc:v1:" + self._primary_cipher.encrypt(
                            decoded
                        ).decode("ascii")
                else:
                    try:
                        decoded = json.dumps(
                            json.loads(value),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    except (TypeError, ValueError) as exc:
                        raise ReportResultDecryptionError(
                            "Legacy report result is not valid JSON"
                        ) from exc
                    encoded = "enc:v1:" + self._primary_cipher.encrypt(decoded).decode(
                        "ascii"
                    )
                connection.execute(
                    "UPDATE report_tasks SET result_json = ?, updated_at = ? "
                    "WHERE task_id = ? AND status = 'succeeded'",
                    (encoded, time.time(), row["task_id"]),
                )
                migrated += 1
            next_cursor = rows[-1]["task_id"] if len(rows) == batch_size else None
            return migrated, next_cursor

    def enqueue(
        self,
        actor_user_id: str,
        idempotency_key: str,
        request: dict,
        identity: dict,
        *,
        now: Optional[float] = None,
    ) -> tuple[dict, bool]:
        if self._cipher is None:
            raise ReportResultEncryptionError(
                "Report result encryption key is required"
            )
        now = time.time() if now is None else now
        identity_json = json.dumps(identity, sort_keys=True, separators=(",", ":"))
        request_json = json.dumps(request, sort_keys=True, separators=(",", ":"))
        request_for_hash = request.get("report_request", request)
        request_hash = hashlib.sha256(
            json.dumps(
                {"request": request_for_hash, "identity": identity},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM report_tasks WHERE actor_user_id = ? "
                "AND idempotency_key = ?",
                (actor_user_id, idempotency_key),
            ).fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflict
                return self._public(existing), False
            task_id = str(uuid.uuid4())
            inserted = connection.execute(
                """
                INSERT INTO report_tasks (
                    task_id, actor_user_id, idempotency_key, request_hash,
                    request_json, identity_json, status, attempts, max_attempts,
                    available_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?, ?, ?)
                ON CONFLICT (actor_user_id, idempotency_key) DO NOTHING
                """,
                (
                    task_id,
                    actor_user_id,
                    idempotency_key,
                    request_hash,
                    request_json,
                    identity_json,
                    self.max_attempts,
                    now,
                    now,
                    now,
                ),
            )
            if inserted.rowcount == 0:
                existing = connection.execute(
                    "SELECT * FROM report_tasks WHERE actor_user_id = ? "
                    "AND idempotency_key = ?",
                    (actor_user_id, idempotency_key),
                ).fetchone()
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflict
                return self._public(existing), False
            row = connection.execute(
                "SELECT * FROM report_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            return self._public(row), True

    def get(self, task_id: str, actor_user_id: str) -> Optional[dict]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM report_tasks WHERE task_id = ? AND actor_user_id = ?",
                (task_id, actor_user_id),
            ).fetchone()
        return self._public(row) if row else None

    def get_result(self, task_id: str, actor_user_id: str) -> Optional[dict]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT result_json FROM report_tasks WHERE task_id = ? "
                "AND actor_user_id = ? AND status = 'succeeded'",
                (task_id, actor_user_id),
            ).fetchone()
        return (
            self._decode_result(row["result_json"])
            if row and row["result_json"]
            else None
        )

    def get_report(self, task_id: str, actor_user_id: str) -> Optional[dict]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT result_json, identity_json FROM report_tasks "
                "WHERE task_id = ? AND actor_user_id = ? AND status = 'succeeded'",
                (task_id, actor_user_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "result": self._decode_result(row["result_json"]),
            "identity": json.loads(row["identity_json"]),
        }

    def count_terminal_tasks_before(self, cutoff_timestamp: float) -> int:
        """Count succeeded/failed tasks older than an explicit UTC timestamp."""
        cutoff = self._validate_retention_cutoff(cutoff_timestamp)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS task_count FROM report_tasks "
                "WHERE status IN ('succeeded', 'failed') AND updated_at < ?",
                (cutoff,),
            ).fetchone()
        return int(row["task_count"])

    def prune_terminal_tasks_before(
        self, cutoff_timestamp: float, *, batch_size: int = 1000
    ) -> int:
        """Delete one bounded batch of terminal tasks before an explicit cutoff.

        Queued and running tasks are never selected. The caller supplies the
        retention cutoff so the store does not invent a data-retention policy.
        """
        cutoff = self._validate_retention_cutoff(cutoff_timestamp)
        if not isinstance(batch_size, int) or isinstance(batch_size, bool):
            raise ValueError("batch_size must be an integer")
        if not 1 <= batch_size <= 1000:
            raise ValueError("batch_size must be between 1 and 1000")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT task_id FROM report_tasks "
                "WHERE status IN ('succeeded', 'failed') AND updated_at < ? "
                "ORDER BY updated_at, task_id LIMIT ?",
                (cutoff, batch_size),
            ).fetchall()
            if not rows:
                return 0
            task_ids = [row["task_id"] for row in rows]
            placeholders = ", ".join("?" for _ in task_ids)
            deleted = connection.execute(
                f"DELETE FROM report_tasks WHERE status IN ('succeeded', 'failed') "
                f"AND task_id IN ({placeholders}) AND updated_at < ?",
                (*task_ids, cutoff),
            )
            return int(deleted.rowcount)

    @staticmethod
    def _validate_retention_cutoff(cutoff_timestamp: float) -> float:
        if isinstance(cutoff_timestamp, bool) or not isinstance(
            cutoff_timestamp, (int, float)
        ):
            raise ValueError("cutoff_timestamp must be a Unix timestamp")
        if cutoff_timestamp != cutoff_timestamp or abs(cutoff_timestamp) == float(
            "inf"
        ):
            raise ValueError("cutoff_timestamp must be finite")
        return float(cutoff_timestamp)

    def get_request(self, task_id: str, actor_user_id: str) -> Optional[dict]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT request_json FROM report_tasks WHERE task_id = ? "
                "AND actor_user_id = ? AND status = 'succeeded'",
                (task_id, actor_user_id),
            ).fetchone()
        return json.loads(row["request_json"]) if row else None

    def claim_next(
        self,
        worker_id: str,
        *,
        now: Optional[float] = None,
        lease_seconds: float = 30,
    ) -> Optional[dict]:
        now = time.time() if now is None else now
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE report_tasks
                SET status = CASE
                        WHEN attempts >= max_attempts THEN 'failed'
                        ELSE 'queued'
                    END,
                    error_code = CASE
                        WHEN attempts >= max_attempts THEN 'worker_lease_expired'
                        ELSE error_code
                    END,
                    available_at = ?, lease_owner = NULL, lease_expires_at = NULL,
                    updated_at = ?
                WHERE status = 'running' AND lease_expires_at <= ?
                """,
                (now, now, now),
            )
            row = connection.execute(
                """
                SELECT task_id FROM report_tasks
                WHERE status = 'queued' AND available_at <= ?
                    AND attempts < max_attempts
                ORDER BY created_at, task_id LIMIT 1
                """
                + (
                    " FOR UPDATE SKIP LOCKED"
                    if self._engine.dialect.name == "postgresql"
                    else ""
                ),
                (now,),
            ).fetchone()
            if row is None:
                return None
            task_id = row["task_id"]
            connection.execute(
                """
                UPDATE report_tasks
                SET status = 'running', attempts = attempts + 1, lease_owner = ?,
                    lease_expires_at = ?, updated_at = ?, error_code = NULL
                WHERE task_id = ? AND status = 'queued'
                """,
                (worker_id, now + lease_seconds, now, task_id),
            )
            claimed = connection.execute(
                "SELECT * FROM report_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        task = dict(claimed)
        task["request"] = json.loads(task.pop("request_json"))
        task["identity"] = json.loads(task.pop("identity_json"))
        return task

    def succeed(self, task_id: str, worker_id: str, result: dict) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE report_tasks
                SET status = 'succeeded', result_json = ?, error_code = NULL,
                    lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
                WHERE task_id = ? AND status = 'running' AND lease_owner = ?
                """,
                (
                    self._encode_result(result),
                    time.time(),
                    task_id,
                    worker_id,
                ),
            )
            return cursor.rowcount == 1

    def renew_lease(self, task_id: str, worker_id: str, lease_seconds: float) -> bool:
        now = time.time()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE report_tasks SET lease_expires_at = ?, updated_at = ?
                WHERE task_id = ? AND status = 'running' AND lease_owner = ?
                """,
                (now + lease_seconds, now, task_id, worker_id),
            )
            return cursor.rowcount == 1

    def fail(
        self,
        task_id: str,
        worker_id: str,
        error_code: str,
        *,
        retry_delay: float = 0.1,
    ) -> bool:
        now = time.time()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT attempts, max_attempts FROM report_tasks "
                "WHERE task_id = ? AND status = 'running' AND lease_owner = ?",
                (task_id, worker_id),
            ).fetchone()
            if row is None:
                return False
            retry = row["attempts"] < row["max_attempts"]
            cursor = connection.execute(
                """
                UPDATE report_tasks
                SET status = ?, error_code = ?, available_at = ?, lease_owner = NULL,
                    lease_expires_at = NULL, updated_at = ?
                WHERE task_id = ? AND status = 'running' AND lease_owner = ?
                """,
                (
                    "queued" if retry else "failed",
                    error_code,
                    now + retry_delay if retry else now,
                    now,
                    task_id,
                    worker_id,
                ),
            )
            return cursor.rowcount == 1


class ReportTaskWorker:
    def __init__(
        self,
        store: ReportTaskStore,
        processor: Callable[[dict], dict],
        *,
        poll_seconds: float = 0.2,
        lease_seconds: float = 30,
    ):
        self.store = store
        self.processor = processor
        self.poll_seconds = poll_seconds
        self.lease_seconds = lease_seconds
        self.worker_id = str(uuid.uuid4())
        self._stop = Event()
        self._thread: Optional[Thread] = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="report-task-worker", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self):
        while not self._stop.is_set():
            task = self.store.claim_next(
                self.worker_id, lease_seconds=self.lease_seconds
            )
            if task is None:
                self._stop.wait(self.poll_seconds)
                continue
            heartbeat_stop = Event()
            heartbeat = Thread(
                target=self._heartbeat,
                args=(task["task_id"], heartbeat_stop),
                name="report-task-lease",
                daemon=True,
            )
            heartbeat.start()
            try:
                result = self.processor(task)
            except Exception:
                self.store.fail(
                    task["task_id"], self.worker_id, "report_generation_failed"
                )
            else:
                self.store.succeed(task["task_id"], self.worker_id, result)
            finally:
                heartbeat_stop.set()
                heartbeat.join(timeout=1)

    def _heartbeat(self, task_id: str, stop: Event):
        interval = max(0.1, self.lease_seconds / 3)
        while not stop.wait(interval):
            if not self.store.renew_lease(task_id, self.worker_id, self.lease_seconds):
                return
