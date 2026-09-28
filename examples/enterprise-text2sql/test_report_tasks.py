import json
import os
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from report_tasks import (
    IdempotencyConflict,
    ReportResultDecryptionError,
    ReportResultEncryptionError,
    ReportTaskStore,
)


@pytest.fixture(autouse=True)
def configure_report_result_encryption(monkeypatch):
    monkeypatch.setenv(
        "DBGPT_REPORT_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii")
    )
    monkeypatch.delenv("DBGPT_REPORT_ENCRYPTION_KEYS", raising=False)


def test_persistent_idempotency_and_expired_lease_recovery(tmp_path):
    task_db = tmp_path / "report-tasks.sqlite"
    store = ReportTaskStore(task_db)
    assert stat.S_IMODE(task_db.stat().st_mode) == 0o600
    request = {"metrics": [{"metric_id": "sales_amount"}]}
    identity = {"user_id": "analyst-a", "tenant_id": "tenant-a"}

    task, created = store.enqueue("analyst-a", "request-1", request, identity, now=100)
    assert created is True
    reopened = ReportTaskStore(task_db)
    duplicate, created = reopened.enqueue("analyst-a", "request-1", request, identity)
    assert created is False
    assert duplicate["task_id"] == task["task_id"]
    with pytest.raises(IdempotencyConflict):
        reopened.enqueue(
            "analyst-a",
            "request-1",
            {"metrics": [{"metric_id": "refund_rate"}]},
            identity,
        )
    with pytest.raises(IdempotencyConflict):
        reopened.enqueue(
            "analyst-a", "request-1", request, {**identity, "tenant_id": "tenant-b"}
        )

    first_claim = reopened.claim_next("worker-old", now=100, lease_seconds=5)
    assert first_claim["request"] == request
    assert first_claim["identity"] == identity
    assert reopened.claim_next("worker-too-early", now=104, lease_seconds=5) is None

    # A new process can recover the durable task after its lease expires.
    restarted = ReportTaskStore(task_db)
    second_claim = restarted.claim_next("worker-new", now=105, lease_seconds=5)
    assert second_claim["task_id"] == task["task_id"]
    assert second_claim["attempts"] == 2
    assert restarted.succeed(task["task_id"], "worker-old", {"rows": []}) is False
    assert restarted.succeed(task["task_id"], "worker-new", {"rows": [[1]]}) is True
    final = restarted.get(task["task_id"], "analyst-a")
    assert final["status"] == "succeeded"
    assert final["has_result"] is True
    assert restarted.get(task["task_id"], "analyst-b") is None


def test_sqlite_sqlalchemy_url_matches_path_behavior(tmp_path):
    task_db = tmp_path / "report-tasks.sqlite"
    store = ReportTaskStore(f"sqlite:///{task_db}")
    task, created = store.enqueue(
        "analyst-a", "request-1", {"metric": "sales_amount"}, {"user_id": "analyst-a"}
    )
    assert created is True
    claimed = store.claim_next("worker-1")
    assert claimed["task_id"] == task["task_id"]
    assert store.succeed(task["task_id"], "worker-1", {"rows": [[1]]}) is True
    assert store.get_result(task["task_id"], "analyst-a") == {"rows": [[1]]}


def test_claim_is_atomic_across_workers(tmp_path):
    store = ReportTaskStore(tmp_path / "report-tasks.sqlite")
    store.enqueue(
        "analyst-a",
        "request-1",
        {"metric": "sales_amount"},
        {"user_id": "analyst-a", "tenant_id": "tenant-a"},
    )
    barrier = threading.Barrier(3)
    claimed = []

    def claim(worker_id):
        barrier.wait()
        claimed.append(store.claim_next(worker_id))

    workers = [
        threading.Thread(target=claim, args=(f"worker-{index}",)) for index in range(2)
    ]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join(timeout=2)

    assert sum(task is not None for task in claimed) == 1


def test_concurrent_duplicate_enqueue_is_idempotent(tmp_path):
    store = ReportTaskStore(tmp_path / "report-tasks.sqlite")
    barrier = threading.Barrier(3)
    results = []

    def enqueue():
        barrier.wait()
        results.append(
            store.enqueue(
                "analyst-a",
                "same-key",
                {"metric": "sales_amount"},
                {"user_id": "analyst-a"},
            )
        )

    workers = [threading.Thread(target=enqueue) for _ in range(2)]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join(timeout=2)

    assert len(results) == 2
    assert sum(created for _task, created in results) == 1
    assert results[0][0]["task_id"] == results[1][0]["task_id"]


@pytest.mark.skipif(
    not os.getenv("DBGPT_TEST_REPORT_TASK_POSTGRES_URL"),
    reason="requires an isolated PostgreSQL task database",
)
def test_postgresql_shared_store_claims_and_idempotency():
    database_url = os.environ["DBGPT_TEST_REPORT_TASK_POSTGRES_URL"]
    stores = [ReportTaskStore(database_url), ReportTaskStore(database_url)]
    actor_user_id = f"report-task-test-{uuid.uuid4()}"
    identity = {"user_id": actor_user_id}
    request = {"metric": "sales_amount"}
    barrier = threading.Barrier(3)
    enqueue_results = []

    def enqueue(store):
        barrier.wait()
        enqueue_results.append(
            store.enqueue(actor_user_id, "same-key", request, identity)
        )

    enqueuers = [threading.Thread(target=enqueue, args=(store,)) for store in stores]
    for thread in enqueuers:
        thread.start()
    barrier.wait()
    for thread in enqueuers:
        thread.join(timeout=5)

    assert len(enqueue_results) == 2
    assert sum(created for _task, created in enqueue_results) == 1
    assert enqueue_results[0][0]["task_id"] == enqueue_results[1][0]["task_id"]

    for index in range(9):
        stores[index % len(stores)].enqueue(
            actor_user_id, f"task-{index}", {"task": index}, identity
        )

    claim_barrier = threading.Barrier(3)
    claimed = []

    def claim_all(store):
        claim_barrier.wait()
        while task := store.claim_next(str(uuid.uuid4())):
            claimed.append(task["task_id"])

    claimers = [threading.Thread(target=claim_all, args=(store,)) for store in stores]
    for thread in claimers:
        thread.start()
    claim_barrier.wait()
    for thread in claimers:
        thread.join(timeout=5)

    assert len(claimed) == 10
    assert len(set(claimed)) == 10


def test_expired_task_fails_after_max_attempts(tmp_path):
    store = ReportTaskStore(tmp_path / "report-tasks.sqlite", max_attempts=1)
    task, _ = store.enqueue(
        "analyst-a", "request-1", {}, {"user_id": "analyst-a"}, now=10
    )
    assert store.claim_next("worker-1", now=10, lease_seconds=1)
    assert store.claim_next("worker-2", now=11, lease_seconds=1) is None
    status = store.get(task["task_id"], "analyst-a")
    assert status["status"] == "failed"
    assert status["error_code"] == "worker_lease_expired"


def test_failed_attempt_is_retried_then_succeeds(tmp_path):
    store = ReportTaskStore(tmp_path / "report-tasks.sqlite", max_attempts=2)
    task, _ = store.enqueue("analyst-a", "request-1", {}, {"user_id": "analyst-a"})
    first = store.claim_next("worker-1")
    assert store.fail(task["task_id"], "worker-1", "report_generation_failed")
    before_retry = store.get(task["task_id"], "analyst-a")
    assert before_retry["status"] == "queued"
    assert before_retry["attempts"] == 1
    time.sleep(0.12)
    second = store.claim_next("worker-2")
    assert second["task_id"] == first["task_id"]
    assert second["attempts"] == 2
    assert store.fail(task["task_id"], "worker-2", "report_generation_failed")
    final = store.get(task["task_id"], "analyst-a")
    assert final["status"] == "failed"
    assert final["attempts"] == 2


def test_report_result_encryption_at_rest_and_key_enforcement(tmp_path, monkeypatch):
    task_db = tmp_path / "report-tasks.sqlite"
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("DBGPT_REPORT_ENCRYPTION_KEY", key)
    store = ReportTaskStore(task_db)
    task, _ = store.enqueue("analyst-a", "request-1", {}, {"user_id": "analyst-a"})
    store.claim_next("worker-1")
    result = {"rows": [["private-report-value"]]}
    assert store.succeed(task["task_id"], "worker-1", result)

    with sqlite3.connect(task_db) as connection:
        stored = connection.execute(
            "SELECT result_json FROM report_tasks WHERE task_id = ?",
            (task["task_id"],),
        ).fetchone()[0]
    assert stored.startswith("enc:v1:")
    assert "private-report-value" not in stored
    assert store.get_result(task["task_id"], "analyst-a") == result
    assert store.get_report(task["task_id"], "analyst-a")["result"] == result
    assert ReportTaskStore(task_db).get_result(task["task_id"], "analyst-a") == result

    monkeypatch.setenv("DBGPT_REPORT_ENCRYPTION_KEY", Fernet.generate_key().decode())
    wrong_key_store = ReportTaskStore(task_db)
    with pytest.raises(ReportResultDecryptionError, match="cannot be decrypted"):
        wrong_key_store.get_result(task["task_id"], "analyst-a")

    monkeypatch.delenv("DBGPT_REPORT_ENCRYPTION_KEY")
    no_key_store = ReportTaskStore(task_db)
    with pytest.raises(ReportResultDecryptionError, match="key is required"):
        no_key_store.get_result(task["task_id"], "analyst-a")


def test_encryption_key_fails_closed_for_legacy_plaintext_results(
    tmp_path, monkeypatch
):
    task_db = tmp_path / "legacy-report-tasks.sqlite"
    store = ReportTaskStore(task_db)
    task, _ = store.enqueue("analyst-a", "request-1", {}, {"user_id": "analyst-a"})
    store.claim_next("worker-1")
    assert store.succeed(task["task_id"], "worker-1", {"rows": [["legacy-plaintext"]]})
    with sqlite3.connect(task_db) as connection:
        connection.execute(
            "UPDATE report_tasks SET result_json = ? WHERE task_id = ?",
            ('{"rows":[["legacy-plaintext"]]}', task["task_id"]),
        )
    encrypted_store = ReportTaskStore(task_db)
    with pytest.raises(ReportResultDecryptionError, match="not served"):
        encrypted_store.get_result(task["task_id"], "analyst-a")

    monkeypatch.delenv("DBGPT_REPORT_ENCRYPTION_KEY")
    no_key_store = ReportTaskStore(task_db)
    with pytest.raises(ReportResultDecryptionError, match="not served"):
        no_key_store.get_result(task["task_id"], "analyst-a")


def test_report_results_cannot_be_enqueued_without_encryption_key(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("DBGPT_REPORT_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("DBGPT_REPORT_ENCRYPTION_KEYS", raising=False)
    store = ReportTaskStore(tmp_path / "report-tasks.sqlite")

    with pytest.raises(ReportResultEncryptionError, match="key is required"):
        store.enqueue("analyst-a", "request-1", {}, {"user_id": "analyst-a"})

    assert store.get("request-1", "analyst-a") is None


def test_report_encryption_key_ring_reads_old_and_writes_with_primary_key(
    tmp_path, monkeypatch
):
    old_key = Fernet.generate_key().decode("ascii")
    new_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("DBGPT_REPORT_ENCRYPTION_KEY", old_key)
    monkeypatch.delenv("DBGPT_REPORT_ENCRYPTION_KEYS", raising=False)
    task_db = tmp_path / "rotated-report-tasks.sqlite"
    old_store = ReportTaskStore(task_db)
    old_task, _ = old_store.enqueue(
        "analyst-a", "old-request", {}, {"user_id": "analyst-a"}
    )
    old_store.claim_next("worker-old")
    old_result = {"rows": [["old-key-result"]]}
    assert old_store.succeed(old_task["task_id"], "worker-old", old_result)

    monkeypatch.delenv("DBGPT_REPORT_ENCRYPTION_KEY")
    monkeypatch.setenv("DBGPT_REPORT_ENCRYPTION_KEYS", f"{new_key},{old_key}")
    rotated_store = ReportTaskStore(task_db)
    assert rotated_store.get_result(old_task["task_id"], "analyst-a") == old_result

    new_task, _ = rotated_store.enqueue(
        "analyst-a", "new-request", {}, {"user_id": "analyst-a"}
    )
    rotated_store.claim_next("worker-new")
    new_result = {"rows": [["new-key-result"]]}
    assert rotated_store.succeed(new_task["task_id"], "worker-new", new_result)

    with sqlite3.connect(task_db) as connection:
        new_token = (
            connection.execute(
                "SELECT result_json FROM report_tasks WHERE task_id = ?",
                (new_task["task_id"],),
            )
            .fetchone()[0][7:]
            .encode("ascii")
        )
    assert Fernet(new_key.encode("ascii")).decrypt(new_token)
    assert rotated_store.get_result(new_task["task_id"], "analyst-a") == new_result


def test_migrate_legacy_plaintext_and_rotate_ciphertext_in_batches(
    tmp_path, monkeypatch
):
    task_db = tmp_path / "report-migration.sqlite"
    old_key = Fernet.generate_key().decode("ascii")
    new_key = Fernet.generate_key().decode("ascii")
    plaintext_store = ReportTaskStore(task_db)
    plaintext_task, _ = plaintext_store.enqueue(
        "analyst-a", "plaintext", {}, {"user_id": "analyst-a"}
    )
    plaintext_store.claim_next("worker-plain")
    plaintext_result = {"rows": [["legacy"]]}
    assert plaintext_store.succeed(
        plaintext_task["task_id"], "worker-plain", plaintext_result
    )
    with sqlite3.connect(task_db) as connection:
        connection.execute(
            "UPDATE report_tasks SET result_json = ? WHERE task_id = ?",
            (json.dumps(plaintext_result), plaintext_task["task_id"]),
        )

    monkeypatch.setenv("DBGPT_REPORT_ENCRYPTION_KEY", old_key)
    old_key_store = ReportTaskStore(task_db)
    encrypted_task, _ = old_key_store.enqueue(
        "analyst-a", "old-key", {}, {"user_id": "analyst-a"}
    )
    old_key_store.claim_next("worker-old")
    encrypted_result = {"rows": [["rotate-me"]]}
    assert old_key_store.succeed(
        encrypted_task["task_id"], "worker-old", encrypted_result
    )

    monkeypatch.delenv("DBGPT_REPORT_ENCRYPTION_KEY")
    monkeypatch.setenv("DBGPT_REPORT_ENCRYPTION_KEYS", f"{new_key},{old_key}")
    rotating_store = ReportTaskStore(task_db)
    cursor = None
    migrated = 0
    while True:
        count, cursor = rotating_store.migrate_result_encryption(
            batch_size=1, after_task_id=cursor
        )
        migrated += count
        if cursor is None:
            break

    assert migrated == 2
    assert rotating_store.get_result(plaintext_task["task_id"], "analyst-a") == (
        plaintext_result
    )
    assert rotating_store.get_result(encrypted_task["task_id"], "analyst-a") == (
        encrypted_result
    )
    with sqlite3.connect(task_db) as connection:
        stored_values = connection.execute(
            "SELECT result_json FROM report_tasks WHERE status = 'succeeded'"
        ).fetchall()
    assert all(value.startswith("enc:v1:") for (value,) in stored_values)
    assert all(
        Fernet(new_key.encode("ascii")).decrypt(value[7:].encode("ascii"))
        for (value,) in stored_values
    )


def test_retention_prunes_only_bounded_expired_terminal_tasks(tmp_path):
    task_db = tmp_path / "report-retention.sqlite"
    store = ReportTaskStore(task_db, max_attempts=1)
    succeeded, _ = store.enqueue(
        "analyst-a", "old-success", {}, {"user_id": "analyst-a"}, now=1
    )
    store.claim_next("worker-success", now=1)
    assert store.succeed(succeeded["task_id"], "worker-success", {"rows": []})

    failed, _ = store.enqueue(
        "analyst-a", "old-failure", {}, {"user_id": "analyst-a"}, now=2
    )
    store.claim_next("worker-failure", now=2, lease_seconds=1)
    assert store.claim_next("worker-reaper", now=3) is None

    queued, _ = store.enqueue(
        "analyst-a", "queued", {}, {"user_id": "analyst-a"}, now=4
    )
    with sqlite3.connect(task_db) as connection:
        connection.execute(
            "UPDATE report_tasks SET updated_at = 100 WHERE task_id IN (?, ?)",
            (succeeded["task_id"], failed["task_id"]),
        )

    assert store.count_terminal_tasks_before(200) == 2
    assert store.prune_terminal_tasks_before(200, batch_size=1) == 1
    assert store.count_terminal_tasks_before(200) == 1
    assert store.prune_terminal_tasks_before(200, batch_size=1) == 1
    assert store.count_terminal_tasks_before(200) == 0
    assert store.get(queued["task_id"], "analyst-a")["status"] == "queued"


def test_retention_cli_dry_run_and_explicit_apply(tmp_path):
    task_db = tmp_path / "report-retention-cli.sqlite"
    store = ReportTaskStore(task_db)
    task, _ = store.enqueue(
        "analyst-a", "old-report", {}, {"user_id": "analyst-a"}, now=1
    )
    store.claim_next("worker-1", now=1)
    assert store.succeed(task["task_id"], "worker-1", {"rows": []})
    with sqlite3.connect(task_db) as connection:
        connection.execute(
            "UPDATE report_tasks SET updated_at = 100 WHERE task_id = ?",
            (task["task_id"],),
        )

    script = Path(__file__).with_name("prune_report_tasks.py")
    arguments = [
        sys.executable,
        str(script),
        "--database",
        str(task_db),
        "--before",
        "1970-01-01T00:03:20Z",
    ]
    dry_run = subprocess.run(arguments, capture_output=True, text=True, check=True)
    assert "Would prune 1" in dry_run.stdout
    assert store.count_terminal_tasks_before(200) == 1

    applied = subprocess.run(
        [*arguments, "--apply"], capture_output=True, text=True, check=True
    )
    assert "Pruned 1" in applied.stdout
    assert store.count_terminal_tasks_before(200) == 0
