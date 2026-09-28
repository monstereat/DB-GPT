import json
import os
import threading
import uuid
from pathlib import Path

import pytest
from api import (
    REPORT_DEFINITION_FIELDS,
    REPORT_EXPORT_POLICY,
    REPORT_RESULT_FIELDS,
    create_app,
)
from ecommerce_demo import create_demo_database
from fastapi.testclient import TestClient
from report_template_governance import ReportTemplateReleaseStore
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from dbgpt_serve.utils.auth import UserRequest, get_user_from_headers

TEMPLATE_PATH = Path(__file__).with_name("report_templates.json")


def _sales_template():
    catalog = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    template = dict(catalog["templates"][0])
    template["id"] = "sales-standard@1.0.1"
    return template


def _store(database):
    return ReportTemplateReleaseStore(
        database,
        allowed_metrics=REPORT_EXPORT_POLICY,
        definition_fields=REPORT_DEFINITION_FIELDS,
        result_fields=REPORT_RESULT_FIELDS,
        seed_path=TEMPLATE_PATH,
    )


@pytest.fixture
def postgres_template_database_url():
    database_url = os.getenv("DBGPT_TEST_REPORT_TEMPLATE_POSTGRES_URL")
    if not database_url:
        pytest.skip("requires an isolated PostgreSQL template database")
    schema = f"template_test_{uuid.uuid4().hex}"
    base_url = make_url(database_url)
    engine = create_engine(base_url)
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated_url = base_url.set(
        query={**base_url.query, "options": f"-csearch_path={schema}"}
    )
    try:
        yield isolated_url.render_as_string(hide_password=False)
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def test_store_seeds_defaults_and_requires_independent_approval(tmp_path):
    database = create_demo_database(tmp_path / "demo.sqlite")
    store = _store(database)
    initial = store.snapshot()
    assert {item["id"] for item in initial["templates"]} == {
        "sales-standard@1.0.0",
        "sales-compact@1.0.0",
        "admin-margin@1.0.0",
    }

    submitted = store.submit(
        _sales_template(),
        actor_user_id="author",
        actor_role="admin",
        reason="Add an approved standard layout",
    )
    assert submitted["status"] == "draft"
    assert submitted["content_sha256"]
    with pytest.raises(PermissionError, match="cannot review"):
        store.review(
            submitted["template_id"],
            approve=True,
            actor_user_id="author",
            actor_role="admin",
            reason="self review",
        )
    assert len(store.snapshot()["templates"]) == 3

    store.review(
        submitted["template_id"],
        approve=True,
        actor_user_id="reviewer",
        actor_role="admin",
        reason="Reviewed layout",
    )
    published = store.snapshot()
    assert len(published["templates"]) == 4
    assert published["catalog_version"] != initial["catalog_version"]
    assert [
        event["action"] for event in store.audit_events(submitted["template_id"])
    ] == [
        "submitted",
        "self_review_denied",
        "approved",
    ]


def test_store_rejects_unknown_fields_and_non_admin_margin_access(tmp_path):
    database = create_demo_database(tmp_path / "demo.sqlite")
    store = _store(database)
    template = _sales_template()
    template["result_fields"].append("internal_cost_cents")
    with pytest.raises(ValueError, match="result_fields"):
        store.submit(
            template,
            actor_user_id="author",
            actor_role="admin",
            reason="Unsafe field",
        )
    template = dict(json.loads(TEMPLATE_PATH.read_text())["templates"][2])
    template["id"] = "sales-margin@1.0.0"
    template["allowed_roles"] = ["admin", "normal"]
    with pytest.raises(ValueError, match="not allowed"):
        store.submit(
            template,
            actor_user_id="author",
            actor_role="admin",
            reason="Attempt to grant margin access",
        )


def test_two_stores_share_seed_submissions_approvals_and_rejections(tmp_path):
    database = tmp_path / "shared-templates.sqlite"
    first = _store(database)
    second = _store(database)
    assert first.snapshot() == second.snapshot()
    assert len(first.audit_events()) == 3

    published = first.submit(
        _sales_template(),
        actor_user_id="author",
        actor_role="admin",
        reason="Publish shared template",
    )
    assert second.releases()[-1]["status"] == "draft"
    second.review(
        published["template_id"],
        approve=True,
        actor_user_id="reviewer",
        actor_role="admin",
        reason="Approve shared template",
    )
    assert published["template_id"] in {
        item["id"] for item in second.snapshot()["templates"]
    }

    rejected_definition = _sales_template()
    rejected_definition["id"] = "sales-standard@1.0.2"
    rejected = second.submit(
        rejected_definition,
        actor_user_id="author",
        actor_role="admin",
        reason="Submit template for rejection",
    )
    first.review(
        rejected["template_id"],
        approve=False,
        actor_user_id="reviewer",
        actor_role="admin",
        reason="Reject template",
    )
    assert rejected["template_id"] not in {
        item["id"] for item in first.snapshot()["templates"]
    }


def test_concurrent_store_initialization_seeds_once(tmp_path):
    database = tmp_path / "concurrent-seed.sqlite"
    barrier = threading.Barrier(3)
    stores = []
    errors = []

    def initialize():
        barrier.wait()
        try:
            stores.append(_store(database))
        except Exception as exc:  # keep worker exceptions visible to the assertion
            errors.append(exc)

    workers = [threading.Thread(target=initialize) for _ in range(2)]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join(timeout=5)

    assert not errors
    assert all(not worker.is_alive() for worker in workers)
    assert len(stores) == 2
    assert stores[0].snapshot() == stores[1].snapshot()
    assert len(stores[0].audit_events()) == 3


def test_template_audit_is_append_only(tmp_path):
    store = _store(tmp_path / "audit.sqlite")
    with pytest.raises(SQLAlchemyError, match="append-only"):
        with store._engine.begin() as connection:
            connection.execute(
                text("UPDATE report_template_audit SET reason='tampered'")
            )


def test_concurrent_duplicate_reviews_transition_once(tmp_path):
    database = tmp_path / "concurrent-templates.sqlite"
    first, second = _store(database), _store(database)
    submitted = first.submit(
        _sales_template(),
        actor_user_id="author",
        actor_role="admin",
        reason="Concurrent review",
    )
    barrier = threading.Barrier(3)
    outcomes = []

    def review(store, reviewer):
        barrier.wait()
        try:
            outcomes.append(
                store.review(
                    submitted["template_id"],
                    approve=True,
                    actor_user_id=reviewer,
                    actor_role="admin",
                    reason="Approve concurrently",
                )
            )
        except ValueError as exc:
            outcomes.append(exc)

    workers = [
        threading.Thread(target=review, args=(first, "reviewer-a")),
        threading.Thread(target=review, args=(second, "reviewer-b")),
    ]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join(timeout=5)

    assert all(not worker.is_alive() for worker in workers)
    assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1
    assert sum(isinstance(outcome, ValueError) for outcome in outcomes) == 1
    assert [
        event["action"] for event in first.audit_events(submitted["template_id"])
    ] == [
        "submitted",
        "approved",
    ]


def test_app_uses_explicit_template_database_without_reusing_task_database(
    tmp_path, monkeypatch
):
    demo_database = create_demo_database(tmp_path / "demo.sqlite")
    template_database = tmp_path / "shared-templates.sqlite"
    task_database = tmp_path / "tasks.sqlite"
    monkeypatch.setenv(
        "DBGPT_REPORT_TEMPLATE_DATABASE_URL", f"sqlite:///{template_database}"
    )
    monkeypatch.setenv("DBGPT_REPORT_TASK_DATABASE_URL", f"sqlite:///{task_database}")
    app = create_app(demo_database)
    assert app.state.report_template_store.database_path == (
        f"sqlite:///{template_database}"
    )
    assert (
        app.state.report_task_store.database_path
        != app.state.report_template_store.database_path
    )
    assert len(_store(template_database).snapshot()["templates"]) == 3


@pytest.mark.skipif(
    not os.getenv("DBGPT_TEST_REPORT_TEMPLATE_POSTGRES_URL"),
    reason="requires an isolated PostgreSQL template database",
)
def test_postgresql_template_store_shares_seed_release_and_concurrent_review(
    postgres_template_database_url,
):
    database_url = postgres_template_database_url
    barrier = threading.Barrier(3)
    stores = []
    errors = []

    def initialize():
        barrier.wait()
        try:
            stores.append(_store(database_url))
        except Exception as exc:  # keep worker exceptions visible to the assertion
            errors.append(exc)

    initializers = [threading.Thread(target=initialize) for _ in range(2)]
    for initializer in initializers:
        initializer.start()
    barrier.wait()
    for initializer in initializers:
        initializer.join(timeout=10)

    assert not errors
    assert all(not initializer.is_alive() for initializer in initializers)
    assert len(stores) == 2
    first, second = stores
    assert first.snapshot() == second.snapshot()
    assert sum(event["action"] == "seeded" for event in first.audit_events()) == 3

    template = _sales_template()
    template["id"] = f"sales-standard@2.0.{uuid.uuid4().int % 1_000_000}"
    submitted = first.submit(
        template,
        actor_user_id="author",
        actor_role="admin",
        reason="PostgreSQL shared review",
    )
    with pytest.raises(PermissionError, match="cannot review"):
        second.review(
            submitted["template_id"],
            approve=True,
            actor_user_id="author",
            actor_role="admin",
            reason="self review",
        )
    barrier = threading.Barrier(3)
    outcomes = []

    def review(store, reviewer):
        barrier.wait()
        try:
            outcomes.append(
                store.review(
                    submitted["template_id"],
                    approve=True,
                    actor_user_id=reviewer,
                    actor_role="admin",
                    reason="Approve concurrently",
                )
            )
        except ValueError as exc:
            outcomes.append(exc)

    workers = [
        threading.Thread(target=review, args=(first, "reviewer-a")),
        threading.Thread(target=review, args=(second, "reviewer-b")),
    ]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join(timeout=10)

    assert all(not worker.is_alive() for worker in workers)
    assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1
    assert sum(isinstance(outcome, ValueError) for outcome in outcomes) == 1
    assert submitted["template_id"] in {
        item["id"] for item in second.snapshot()["templates"]
    }
    assert [
        event["action"] for event in first.audit_events(submitted["template_id"])
    ] == [
        "submitted",
        "self_review_denied",
        "approved",
    ]

    rejected_template = _sales_template()
    rejected_template["id"] = f"sales-standard@3.0.{uuid.uuid4().int % 1_000_000}"
    rejected = second.submit(
        rejected_template,
        actor_user_id="author",
        actor_role="admin",
        reason="Submit for rejection",
    )
    first.review(
        rejected["template_id"],
        approve=False,
        actor_user_id="reviewer",
        actor_role="admin",
        reason="Reject template",
    )
    assert rejected["template_id"] not in {
        item["id"] for item in second.snapshot()["templates"]
    }
    assert [
        event["action"] for event in first.audit_events(rejected["template_id"])
    ] == [
        "submitted",
        "rejected",
    ]
    with pytest.raises(SQLAlchemyError, match="append-only"):
        with first._engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE report_template_audit SET reason='tampered' "
                    "WHERE template_id=:template_id"
                ),
                {"template_id": rejected["template_id"]},
            )


def test_report_template_api_requires_admin_and_publishes_release(tmp_path):
    database = create_demo_database(tmp_path / "demo.sqlite")
    app = create_app(database)
    app.dependency_overrides[get_user_from_headers] = lambda: UserRequest(
        user_id="author", tenant_id="tenant-a", role="admin"
    )

    with TestClient(app) as client:
        initial = client.get("/reports/templates/available").json()
        assert len(initial["templates"]) == 3
        response = client.post(
            "/reports/templates/releases",
            json={"definition": _sales_template(), "reason": "New standard layout"},
        )
        assert response.status_code == 200
        template_id = response.json()["template_id"]

        self_review = client.post(
            f"/reports/templates/releases/{template_id}/review",
            json={"approve": True, "reason": "self review"},
        )
        assert self_review.status_code == 403
        assert len(client.get("/reports/templates/available").json()["templates"]) == 3

        app.dependency_overrides[get_user_from_headers] = lambda: UserRequest(
            user_id="reviewer", tenant_id="tenant-a", role="admin"
        )
        approved = client.post(
            f"/reports/templates/releases/{template_id}/review",
            json={"approve": True, "reason": "Reviewed"},
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "published"
        assert len(client.get("/reports/templates/available").json()["templates"]) == 4
        export = client.post(
            "/reports/export",
            json={
                "template_id": template_id,
                "metrics": [
                    {
                        "metric_id": "sales_amount",
                    }
                ],
                "start_date": "2026-06-01",
                "end_date": "2026-07-01",
            },
        )
        assert export.status_code == 200
        assert export.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        app.dependency_overrides[get_user_from_headers] = lambda: UserRequest(
            user_id="analyst", tenant_id="tenant-a", role="normal"
        )
        assert client.get("/reports/templates/releases").status_code == 403
