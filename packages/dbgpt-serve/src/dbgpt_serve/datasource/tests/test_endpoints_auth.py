from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.security.http import HTTPAuthorizationCredentials

from dbgpt_serve.datasource.api import endpoints
from dbgpt_serve.datasource.api.schemas import DatasourceQueryResponse
from dbgpt_serve.utils.auth import UserRequest


def test_service_api_key_is_an_explicit_privileged_principal(monkeypatch):
    service = SimpleNamespace(config=SimpleNamespace(api_keys="first,second"))
    monkeypatch.setattr(
        endpoints,
        "get_user_from_headers",
        lambda **_kwargs: pytest.fail("service key must not be parsed as OIDC"),
    )

    actor = endpoints.get_datasource_actor(
        authorization="Bearer second", user_id=None, service=service
    )

    assert actor.actor_id is None
    assert actor.is_admin is True
    assert actor.authentication == "service_api_key"


def test_verified_oidc_identity_becomes_owner_scoped_principal(monkeypatch):
    service = SimpleNamespace(config=SimpleNamespace(api_keys=None))
    user_info = UserRequest(user_id="owner-a", role="normal")
    observed = {}

    def get_user_from_headers(*, user_id, credentials):
        observed.update(user_id=user_id, credentials=credentials)
        return user_info

    monkeypatch.setattr(endpoints, "get_user_from_headers", get_user_from_headers)
    monkeypatch.setattr(
        endpoints,
        "trusted_agent_execution_context",
        lambda user: {"source": "verified_oidc_jwt"} if user is user_info else None,
    )

    actor = endpoints.get_datasource_actor(
        authorization="Bearer signed.jwt", user_id=None, service=service
    )

    assert actor.actor_id == "owner-a"
    assert actor.is_admin is False
    assert isinstance(observed["credentials"], HTTPAuthorizationCredentials)
    assert observed["credentials"].credentials == "signed.jwt"


def test_anonymous_or_legacy_development_identity_is_rejected(monkeypatch):
    service = SimpleNamespace(config=SimpleNamespace(api_keys=None))
    monkeypatch.setattr(
        endpoints,
        "get_user_from_headers",
        lambda **_kwargs: UserRequest(user_id="001", role="admin"),
    )
    monkeypatch.setattr(
        endpoints, "trusted_agent_execution_context", lambda _user: None
    )

    with pytest.raises(HTTPException) as error:
        endpoints.get_datasource_actor(
            authorization=None, user_id=None, service=service
        )

    assert error.value.status_code == 401


def test_invalid_bearer_key_does_not_fall_back_to_development_admin(monkeypatch):
    service = SimpleNamespace(config=SimpleNamespace(api_keys="expected"))
    monkeypatch.setattr(
        endpoints,
        "get_user_from_headers",
        lambda **_kwargs: UserRequest(user_id="001", role="admin"),
    )
    monkeypatch.setattr(
        endpoints, "trusted_agent_execution_context", lambda _user: None
    )

    with pytest.raises(HTTPException) as error:
        endpoints.get_datasource_actor(
            authorization="Bearer wrong", user_id=None, service=service
        )

    assert error.value.status_code == 401


def test_local_development_identity_can_list_only_a_configured_demo_datasource(
    monkeypatch,
):
    service = SimpleNamespace(config=SimpleNamespace(api_keys=None))
    user_info = UserRequest(user_id="001", role="admin")

    def reject_unverified_identity(*_args):
        raise HTTPException(status_code=401, detail="Verified identity required")

    monkeypatch.setattr(endpoints, "get_datasource_actor", reject_unverified_identity)
    monkeypatch.setattr(
        endpoints,
        "get_user_from_headers",
        lambda **_kwargs: user_info,
    )
    monkeypatch.setattr(
        endpoints,
        "local_demo_execution_context",
        lambda user, db_name: (
            {"actor_id": user.user_id} if db_name == "ecommerce-demo" else None
        ),
    )
    monkeypatch.setenv(
        "DBGPT_LOCAL_DEMO_DATASOURCES", '{"ecommerce-demo":"/data/demo.sqlite"}'
    )

    actor = endpoints.get_datasource_list_actor(
        authorization=None, user_id=None, service=service
    )

    assert actor == endpoints.DatasourceActor(
        actor_id="001", is_admin=False, authentication="local_demo"
    )


def test_local_demo_list_does_not_fall_back_when_authorization_header_is_present(
    monkeypatch,
):
    service = SimpleNamespace(config=SimpleNamespace(api_keys=None))

    def reject_unverified_identity(*_args):
        raise HTTPException(status_code=401, detail="Invalid bearer token")

    monkeypatch.setattr(endpoints, "get_datasource_actor", reject_unverified_identity)
    monkeypatch.setattr(
        endpoints,
        "get_user_from_headers",
        lambda **_kwargs: pytest.fail("must not downgrade a supplied credential"),
    )

    with pytest.raises(HTTPException) as error:
        endpoints.get_datasource_list_actor(
            authorization="Bearer invalid", user_id=None, service=service
        )

    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_local_demo_datasource_list_filters_to_approved_configured_sources(
    monkeypatch,
):
    approved = DatasourceQueryResponse(
        type="sqlite",
        params={"database": "ecommerce-demo"},
        description="Synthetic demo",
        id=1,
        db_name="ecommerce-demo",
        approval_status="approved",
    )
    pending = DatasourceQueryResponse(
        type="sqlite",
        params={"database": "pending-demo"},
        description="Pending demo",
        id=2,
        db_name="pending-demo",
        approval_status="pending",
    )
    other = DatasourceQueryResponse(
        type="sqlite",
        params={"database": "other-db"},
        description="Other source",
        id=3,
        db_name="other-db",
        approval_status="approved",
    )
    service = SimpleNamespace(get_list=lambda **kwargs: [approved, pending, other])
    actor = endpoints.DatasourceActor(
        actor_id="001", is_admin=False, authentication="local_demo"
    )

    async def run_blocking(_system_app, function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(endpoints, "blocking_func_to_async", run_blocking)
    monkeypatch.setattr(
        endpoints,
        "local_demo_execution_context",
        lambda user, db_name: (
            {"actor_id": user.user_id} if db_name == "ecommerce-demo" else None
        ),
    )

    result = await endpoints.query_page(db_type=None, service=service, actor=actor)

    assert [item.db_name for item in result.data] == ["ecommerce-demo"]


def test_every_datasource_route_requires_a_datasource_actor():
    protected_paths = {
        "/datasources",
        "/datasources/{datasource_id}",
        "/datasources/{datasource_id}/refresh",
        "/datasources/test-connection",
        "/datasource-types",
    }
    routes = {
        route.path: route
        for route in endpoints.router.routes
        if route.path in protected_paths
    }

    assert set(routes) == protected_paths
    assert any(
        dependency.call is endpoints.get_datasource_list_actor
        for dependency in routes["/datasources"].dependant.dependencies
    )
    for path, route in routes.items():
        if path == "/datasources":
            continue
        assert any(
            dependency.call is endpoints.get_datasource_actor
            for dependency in route.dependant.dependencies
        )
