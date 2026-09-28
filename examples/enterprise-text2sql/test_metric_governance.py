import json
import sqlite3

from api import create_app
from ecommerce_demo import create_demo_database
from fastapi.testclient import TestClient
from metric_governance import MetricReleaseStore
from semantic_metrics import _CATALOG

from dbgpt_serve.utils.auth import UserRequest, get_user_from_headers


def _new_sales_release():
    definition = dict(_CATALOG["metrics"][0])
    definition["version"] = "2.0.0"
    definition["definition"] = "Approved release 2 definition."
    return definition


def test_release_store_requires_a_different_reviewer_and_publishes_runtime_default(
    tmp_path,
):
    database = create_demo_database(tmp_path / "demo.sqlite")
    store = MetricReleaseStore(database)
    submitted = store.submit(
        _new_sales_release(),
        actor_user_id="submitter",
        actor_role="admin",
        tenant_id="tenant-a",
        reason="Clarify business semantics",
    )

    assert submitted["status"] == "draft"
    assert len(submitted["content_sha256"]) == 64
    try:
        store.review(
            "sales_amount",
            "2.0.0",
            approve=True,
            actor_user_id="submitter",
            actor_role="admin",
            tenant_id="tenant-a",
            reason="self approval",
        )
    except PermissionError as exc:
        assert "cannot review" in str(exc)
    else:
        raise AssertionError("Submitter must not approve their own release")

    store.review(
        "sales_amount",
        "2.0.0",
        approve=True,
        actor_user_id="reviewer",
        actor_role="admin",
        tenant_id="tenant-b",
        reason="Definition reviewed",
    )
    catalog = store.snapshot()

    assert catalog["default_metric_versions"]["sales_amount"] == "2.0.0"
    assert (
        next(
            item
            for item in catalog["metrics"]
            if item["id"] == "sales_amount" and item["version"] == "2.0.0"
        )["definition"]
        == "Approved release 2 definition."
    )
    events = store.audit_events("sales_amount")
    assert [event["action"] for event in events] == [
        "submitted",
        "self_review_denied",
        "approved",
    ]
    assert events[0]["actor_user_id"] == "submitter"
    assert events[0]["tenant_id"] == "tenant-a"
    assert events[0]["reason"] == "Clarify business semantics"
    assert events[0]["content_sha256"] == submitted["content_sha256"]
    assert events[1]["actor_user_id"] == "submitter"
    assert events[2]["actor_user_id"] == "reviewer"
    assert events[2]["tenant_id"] == "tenant-b"
    assert events[2]["occurred_at"]


def test_release_content_and_audit_are_persisted(tmp_path):
    database = create_demo_database(tmp_path / "demo.sqlite")
    MetricReleaseStore(database).submit(
        _new_sales_release(),
        actor_user_id="submitter",
        actor_role="admin",
        tenant_id="tenant-a",
        reason="New version",
    )

    with sqlite3.connect(database) as connection:
        definition = connection.execute(
            "SELECT definition_json FROM metric_releases "
            "WHERE metric_id=? AND version=?",
            ("sales_amount", "2.0.0"),
        ).fetchone()[0]
        event_count = connection.execute(
            "SELECT COUNT(*) FROM metric_release_audit WHERE metric_id=?",
            ("sales_amount",),
        ).fetchone()[0]

    assert json.loads(definition)["version"] == "2.0.0"
    assert event_count == 1


def test_metric_release_api_enforces_admin_review_separation_and_runtime_publish(
    tmp_path,
):
    database = create_demo_database(tmp_path / "demo.sqlite")
    app = create_app(database)
    identity = UserRequest(user_id="submitter", tenant_id="tenant-a", role="admin")
    app.dependency_overrides[get_user_from_headers] = lambda: identity

    with TestClient(app) as client:
        app.dependency_overrides[get_user_from_headers] = lambda: UserRequest(
            user_id="analyst", tenant_id="tenant-a", role="normal"
        )
        denied = client.get("/metrics/catalog")
        normal_submission = client.post(
            "/metrics/releases",
            json={"definition": _new_sales_release(), "reason": "New version"},
        )
        app.dependency_overrides[get_user_from_headers] = lambda: UserRequest(
            user_id=None, tenant_id="tenant-a", role="admin"
        )
        anonymous_admin = client.post(
            "/metrics/releases",
            json={"definition": _new_sales_release(), "reason": "New version"},
        )
        app.dependency_overrides[get_user_from_headers] = lambda: identity
        submitted = client.post(
            "/metrics/releases",
            json={"definition": _new_sales_release(), "reason": "New version"},
        )
        self_review = client.post(
            "/metrics/releases/sales_amount/2.0.0/review",
            json={"approve": True, "reason": "review"},
        )
        app.dependency_overrides[get_user_from_headers] = lambda: UserRequest(
            user_id="reviewer", tenant_id="tenant-b", role="admin"
        )
        approved = client.post(
            "/metrics/releases/sales_amount/2.0.0/review",
            json={"approve": True, "reason": "Definition verified"},
        )
        catalog = client.get("/metrics/catalog")
        queried = client.post(
            "/metrics/query",
            json={
                "metric_id": "sales_amount",
                "start_date": "2026-04-01",
                "end_date": "2026-07-01",
            },
        )

    assert denied.status_code == 403
    assert normal_submission.status_code == 403
    assert anonymous_admin.status_code == 403
    assert submitted.status_code == 200
    assert self_review.status_code == 403
    assert approved.status_code == 200
    assert catalog.status_code == 200
    assert catalog.json()["default_metric_versions"]["sales_amount"] == "2.0.0"
    assert queried.status_code == 200
    assert queried.json()["metric"]["metric_version"] == "2.0.0"
    assert queried.json()["metric"]["definition"] == "Approved release 2 definition."
