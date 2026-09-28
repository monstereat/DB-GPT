"""Integration coverage for verified OIDC identity on the ReAct SQL path."""

import json
import sqlite3
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dbgpt_app.openapi.api_v1 import agentic_data_api
from dbgpt_app.openapi.api_v1.business_context import prepare_database_query
from dbgpt_app.openapi.api_v1.subagent.react_tools import make_react_tools
from dbgpt_app.openapi.api_v1.tools.sql_query import make_sql_query
from dbgpt_serve.utils import auth


@pytest.fixture
def oidc_react_client(tmp_path, monkeypatch):
    issuer = "https://issuer.test"
    audience = "dbgpt-test"
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    class _SigningKey:
        key = public_key

    class _JwksClient:
        def get_signing_key_from_jwt(self, token):
            assert token
            return _SigningKey()

    monkeypatch.setattr(auth, "_get_jwks_client", lambda _issuer: _JwksClient())
    monkeypatch.setenv("DBGPT_OIDC_ISSUER", issuer)
    monkeypatch.setenv("DBGPT_OIDC_AUDIENCE", audience)
    monkeypatch.setenv(
        "DBGPT_OIDC_CLAIM_MAPPINGS",
        json.dumps({"tenant_id": "org.tenant", "region_id": "scope.region"}),
    )
    monkeypatch.setenv(
        "DBGPT_OIDC_ROLE_MAPPING", json.dumps({"sales-analyst": "sales"})
    )

    schema_file = tmp_path / "sales-schema.json"
    schema_file.write_text(
        json.dumps(
            {
                "source": {
                    "tenant_column": "tenant_id",
                    "policy_version": "oidc-integration-v1",
                    "region_scope": {"direct": {"orders": "region_id"}},
                },
                "tables": [
                    {
                        "name": "orders",
                        "columns": [
                            {
                                "name": "tenant_id",
                                "classification": "tenant_key",
                                "agent_queryable": False,
                            },
                            {
                                "name": "order_id",
                                "classification": "business",
                                "agent_queryable": True,
                            },
                            {
                                "name": "region_id",
                                "classification": "business",
                                "agent_queryable": True,
                            },
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "DBGPT_DATABASE_SCHEMA_FILES",
        json.dumps({"sales": str(schema_file)}),
    )

    captured = {}

    async def _no_attachments(*_args):
        return None

    async def _capture_stream(*_args, **kwargs):
        captured.update(kwargs)
        yield 'data: {"type":"done"}\n\n'

    monkeypatch.setattr(agentic_data_api, "_open_turn_attachments", _no_attachments)
    monkeypatch.setattr(
        agentic_data_api,
        "_get_authorized_database_connector",
        lambda *_args: object(),
    )
    monkeypatch.setattr(agentic_data_api, "_react_agent_stream", _capture_stream)

    app = FastAPI()
    app.include_router(agentic_data_api.router)
    token = jwt.encode(
        {
            "iss": issuer,
            "aud": audience,
            "sub": "alice",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "employee_number": "E-17",
            "name": "Alice",
            "preferred_username": "alice",
            "role": "sales-analyst",
            "org": {"tenant": "tenant-a"},
            "scope": {"region": "north"},
        },
        private_key,
        algorithm="RS256",
    )
    return TestClient(app), token, captured, private_key


def test_signed_oidc_identity_reaches_react_and_scopes_sql(oidc_react_client):
    client, token, captured, _private_key = oidc_react_client
    response = client.post(
        "/v1/chat/react-agent",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "user_input": "列出订单",
            "ext_info": {
                "database_name": "sales",
                "tenant_id": "tenant-b",
                "region_id": "south",
                "role": "admin",
                "verified_execution_context": {
                    "source": "verified_oidc_jwt",
                    "actor_id": "mallory",
                    "tenant_id": "tenant-b",
                    "region_id": "south",
                    "role": "admin",
                },
            },
        },
    )

    assert response.status_code == 200
    assert captured["identity_context"] == {
        "actor_user_id": "alice",
        "role": "sales",
        "tenant_id": "tenant-a",
        "region_id": "north",
        "data_source_id": "sales",
        "authorization_policy_version": "oidc-claims-v1",
        "verified_execution_context": {
            "actor_id": "alice",
            "role": "sales",
            "tenant_id": "tenant-a",
            "region_id": "north",
            "source": "verified_oidc_jwt",
            "authorization_policy_version": "oidc-claims-v1",
        },
    }

    identity = captured["identity_context"]
    scoped_sql, _audit = prepare_database_query(
        "SELECT order_id FROM orders ORDER BY order_id",
        identity,
        SimpleNamespace(dialect="sqlite"),
    )

    class _SQLiteConnector:
        dialect = "sqlite"

        def __init__(self):
            self.connection = sqlite3.connect(":memory:")
            self.connection.execute(
                "CREATE TABLE orders (tenant_id TEXT, order_id INTEGER, region_id TEXT)"
            )
            self.connection.executemany(
                "INSERT INTO orders VALUES (?, ?, ?)",
                [
                    ("tenant-a", 1, "north"),
                    ("tenant-a", 2, "south"),
                    ("tenant-b", 3, "north"),
                ],
            )

        def query_ex(self, sql, timeout=None):
            assert timeout is not None
            cursor = self.connection.execute(sql)
            return [column[0] for column in cursor.description], cursor.fetchall()

    connector = _SQLiteConnector()
    assert connector.connection.execute(scoped_sql).fetchall() == [(1,)]

    main_result = json.loads(
        make_sql_query(identity, connector)(
            sql="SELECT order_id FROM orders ORDER BY order_id"
        )
    )
    subagent_result = json.loads(
        make_react_tools(identity, database_connector=connector)["sql_query"](
            sql="SELECT order_id FROM orders ORDER BY order_id"
        )
    )
    assert "| 1 |" in main_result["chunks"][0]["content"]
    assert "| 2 |" not in main_result["chunks"][0]["content"]
    assert "| 1 |" in subagent_result["chunks"][0]["content"]
    assert "| 2 |" not in subagent_result["chunks"][0]["content"]
    assert "| 3 |" not in subagent_result["chunks"][0]["content"]
    connector.connection.close()


@pytest.mark.parametrize(
    "claim_overrides",
    [
        {"sub": None},
        {"iss": "https://attacker.test", "sub": "alice"},
    ],
)
def test_react_rejects_invalid_bearer_claims(oidc_react_client, claim_overrides):
    client, _valid_token, _captured, private_key = oidc_react_client
    token = jwt.encode(
        {
            "iss": "https://issuer.test",
            "aud": "dbgpt-test",
            "sub": "alice",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            **claim_overrides,
        },
        private_key,
        algorithm="RS256",
    )

    response = client.post(
        "/v1/chat/react-agent",
        headers={"Authorization": f"Bearer {token}"},
        json={"user_input": "列出订单", "ext_info": {"database_name": "sales"}},
    )

    assert response.status_code == 401


def test_react_requires_bearer_token(oidc_react_client):
    client, _valid_token, _captured, _private_key = oidc_react_client
    response = client.post(
        "/v1/chat/react-agent",
        json={"user_input": "列出订单", "ext_info": {"database_name": "sales"}},
    )

    assert response.status_code == 401
