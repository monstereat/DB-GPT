import json
import os
from dataclasses import dataclass
from functools import cache
from hmac import compare_digest
from typing import List, Optional, Union

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.security.http import HTTPAuthorizationCredentials, HTTPBearer

from dbgpt.component import SystemApp
from dbgpt_serve.core import ResourceTypes, Result, blocking_func_to_async
from dbgpt_serve.datasource.api.schemas import (
    DatasourceCreateRequest,
    DatasourceQueryResponse,
    DatasourceServeRequest,
)
from dbgpt_serve.datasource.config import SERVE_SERVICE_COMPONENT_NAME, ServeConfig
from dbgpt_serve.datasource.service.service import Service
from dbgpt_serve.utils.auth import (
    UserRequest,
    get_user_from_headers,
    local_demo_execution_context,
    trusted_agent_execution_context,
)

router = APIRouter()

# Add your API endpoints here

global_system_app: Optional[SystemApp] = None


def get_service() -> Service:
    """Get the service instance"""
    return global_system_app.get_component(SERVE_SERVICE_COMPONENT_NAME, Service)


get_bearer_token = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class DatasourceActor:
    actor_id: Optional[str]
    is_admin: bool
    authentication: str


def get_datasource_actor(
    authorization: Optional[str] = Header(None),
    user_id: Optional[str] = Header(None),
    service: Service = Depends(get_service),
) -> DatasourceActor:
    """Require verified OIDC identity or an explicitly configured service key."""
    scheme, separator, token = (authorization or "").partition(" ")
    bearer_token = token.strip() if separator and scheme.lower() == "bearer" else ""

    if bearer_token:
        for api_key in _parse_api_keys(service.config.api_keys or ""):
            if compare_digest(bearer_token, api_key):
                return DatasourceActor(
                    actor_id=None, is_admin=True, authentication="service_api_key"
                )

    credentials = (
        HTTPAuthorizationCredentials(scheme=scheme, credentials=bearer_token)
        if bearer_token
        else None
    )
    user_info: UserRequest = get_user_from_headers(
        user_id=user_id, credentials=credentials
    )
    if not trusted_agent_execution_context(user_info):
        raise HTTPException(
            status_code=401,
            detail="Verified OIDC identity or configured service API key required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return DatasourceActor(
        actor_id=user_info.user_id,
        is_admin=user_info.role == "admin",
        authentication="verified_oidc_jwt",
    )


def get_datasource_list_actor(
    authorization: Optional[str] = Header(None),
    user_id: Optional[str] = Header(None),
    service: Service = Depends(get_service),
) -> DatasourceActor:
    """Allow local identity to list only configured synthetic demo sources."""
    try:
        return get_datasource_actor(authorization, user_id, service)
    except HTTPException as error:
        if authorization:
            raise
        user_info = get_user_from_headers(user_id=user_id, credentials=None)
        try:
            configured = json.loads(os.getenv("DBGPT_LOCAL_DEMO_DATASOURCES", "{}"))
        except json.JSONDecodeError:
            configured = {}
        if isinstance(configured, dict) and any(
            isinstance(db_name, str)
            and local_demo_execution_context(user_info, db_name)
            for db_name in configured
        ):
            return DatasourceActor(
                actor_id=user_info.user_id,
                is_admin=False,
                authentication="local_demo",
            )
        raise error


@cache
def _parse_api_keys(api_keys: str) -> List[str]:
    """Parse the string api keys to a list

    Args:
        api_keys (str): The string api keys

    Returns:
        List[str]: The list of api keys
    """
    if not api_keys:
        return []
    return [key.strip() for key in api_keys.split(",")]


async def check_api_key(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(get_bearer_token),
    service: Service = Depends(get_service),
) -> Optional[str]:
    """Check the api key

    If the api key is not set, allow all.

    Your can pass the token in you request header like this:

    .. code-block:: python

        import requests

        client_api_key = "your_api_key"
        headers = {"Authorization": "Bearer " + client_api_key}
        res = requests.get("http://test/hello", headers=headers)
        assert res.status_code == 200

    """
    if service.config.api_keys:
        api_keys = _parse_api_keys(service.config.api_keys)
        if auth is None or (token := auth.credentials) not in api_keys:
            raise HTTPException(
                status_code=401,
                detail={
                    "error": {
                        "message": "",
                        "type": "invalid_request_error",
                        "param": None,
                        "code": "invalid_api_key",
                    }
                },
            )
        return token
    else:
        # api_keys not set; allow all
        return None


@router.get("/health", dependencies=[Depends(check_api_key)])
async def health():
    """Health check endpoint"""
    return {"status": "ok"}


@router.get("/test_auth", dependencies=[Depends(check_api_key)])
async def test_auth():
    """Test auth endpoint"""
    return {"status": "ok"}


@router.post(
    "/datasources",
    response_model=Result[DatasourceQueryResponse],
)
async def create(
    request: Union[DatasourceCreateRequest, DatasourceServeRequest],
    service: Service = Depends(get_service),
    actor: DatasourceActor = Depends(get_datasource_actor),
) -> Result[DatasourceQueryResponse]:
    """Create a new Space entity

    Args:
        request (Union[DatasourceCreateRequest, DatasourceServeRequest]): The request
            to create a datasource. DatasourceServeRequest is deprecated.
        service (Service): The service
    Returns:
        ServerResponse: The response
    """
    res = await blocking_func_to_async(
        global_system_app, service.create, request, actor_id=actor.actor_id
    )
    return Result.succ(res)


@router.put(
    "/datasources",
    response_model=Result[DatasourceQueryResponse],
)
async def update(
    request: Union[DatasourceCreateRequest, DatasourceServeRequest],
    service: Service = Depends(get_service),
    actor: DatasourceActor = Depends(get_datasource_actor),
) -> Result[DatasourceQueryResponse]:
    """Update a Space entity

    Args:
        request (DatasourceServeRequest): The request
        service (Service): The service
    Returns:
        ServerResponse: The response
    """
    res = await blocking_func_to_async(
        global_system_app,
        service.update,
        request,
        actor_id=actor.actor_id,
        is_admin=actor.is_admin,
    )
    return Result.succ(res)


@router.delete(
    "/datasources/{datasource_id}",
    response_model=Result[None],
)
async def delete(
    datasource_id: str,
    service: Service = Depends(get_service),
    actor: DatasourceActor = Depends(get_datasource_actor),
) -> Result[None]:
    """Delete a Space entity

    Args:
        request (DatasourceServeRequest): The request
        service (Service): The service
    Returns:
        ServerResponse: The response
    """
    await blocking_func_to_async(
        global_system_app,
        service.delete,
        datasource_id,
        actor_id=actor.actor_id,
        is_admin=actor.is_admin,
    )
    return Result.succ(None)


@router.get(
    "/datasources/{datasource_id}",
    response_model=Result[DatasourceQueryResponse],
)
async def query(
    datasource_id: str,
    service: Service = Depends(get_service),
    actor: DatasourceActor = Depends(get_datasource_actor),
) -> Result[DatasourceQueryResponse]:
    """Query Space entities

    Args:
        request (DatasourceServeRequest): The request
        service (Service): The service
    Returns:
        List[ServeResponse]: The response
    """
    res = await blocking_func_to_async(
        global_system_app,
        service.get,
        datasource_id,
        actor_id=actor.actor_id,
        is_admin=actor.is_admin,
    )
    return Result.succ(res)


@router.get(
    "/datasources",
    response_model=Result[List[DatasourceQueryResponse]],
)
async def query_page(
    db_type: Optional[str] = Query(
        None, description="Database type, e.g. sqlite, mysql, etc."
    ),
    service: Service = Depends(get_service),
    actor: DatasourceActor = Depends(get_datasource_list_actor),
) -> Result[List[DatasourceQueryResponse]]:
    """Query Space entities

    Args:
        service (Service): The service
    Returns:
        ServerResponse: The response
    """
    res = await blocking_func_to_async(
        global_system_app,
        service.get_list,
        db_type=db_type,
        actor_id=actor.actor_id,
        is_admin=actor.is_admin,
    )
    if actor.authentication == "local_demo":
        local_user = UserRequest(user_id=actor.actor_id, role="admin")
        res = [
            item
            for item in res
            if item.approval_status == "approved"
            and local_demo_execution_context(local_user, item.db_name)
        ]
    return Result.succ(res)


@router.get(
    "/datasource-types",
    response_model=Result[ResourceTypes],
)
async def get_datasource_types(
    service: Service = Depends(get_service),
    _: DatasourceActor = Depends(get_datasource_actor),
) -> Result[ResourceTypes]:
    """Get the datasource types."""
    res = await blocking_func_to_async(global_system_app, service.datasource_types)
    return Result.succ(res)


@router.post(
    "/datasources/test-connection",
    response_model=Result[bool],
)
async def test_connection(
    request: DatasourceCreateRequest,
    service: Service = Depends(get_service),
    _: DatasourceActor = Depends(get_datasource_actor),
) -> Result[bool]:
    """Test the connection using datasource configuration before creating it

    Args:
        request (DatasourceServeRequest): The datasource configuration to test
        service (Service): The service instance

    Returns:
        Result[bool]: The test result, True if connection is successful

    Raises:
        HTTPException: When the connection test fails
    """
    res = await blocking_func_to_async(
        global_system_app, service.test_connection, request
    )
    return Result.succ(res)


@router.post(
    "/datasources/{datasource_id}/refresh",
    response_model=Result[bool],
)
async def refresh_datasource(
    datasource_id: str,
    service: Service = Depends(get_service),
    actor: DatasourceActor = Depends(get_datasource_actor),
) -> Result[bool]:
    """Refresh a datasource by its ID

    Args:
        datasource_id (str): The ID of the datasource to refresh
        service (Service): The service instance

    Returns:
        Result[bool]: The refresh result, True if the refresh was successful

    Raises:
        HTTPException: When the refresh operation fails
    """
    res = await blocking_func_to_async(
        global_system_app,
        service.refresh,
        datasource_id,
        actor_id=actor.actor_id,
        is_admin=actor.is_admin,
    )
    return Result.succ(res)


def init_endpoints(system_app: SystemApp, config: ServeConfig) -> None:
    """Initialize the endpoints"""
    global global_system_app
    system_app.register(Service, config=config)
    global_system_app = system_app
