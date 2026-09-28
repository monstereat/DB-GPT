import json
import logging
import os
from functools import lru_cache
from ipaddress import ip_address
from typing import Any, Dict, Optional
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from dbgpt._private.pydantic import BaseModel, model_fields

logger = logging.getLogger(__name__)
_bearer_scheme = HTTPBearer(auto_error=False)
_DEFAULT_CLAIM_MAPPINGS = {
    "user_id": "sub",
    "user_no": "employee_number",
    "real_name": "name",
    "user_name": "preferred_username",
    "user_channel": "azp",
    "role": "role",
    "nick_name": "nickname",
    "email": "email",
    "avatar_url": "picture",
    "tenant_id": "tenant_id",
    "region_id": "region_id",
}


def _is_loopback_http_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if parsed.scheme != "http" or not host or parsed.username or parsed.password:
            return False
        try:
            return ip_address(host).is_loopback
        except ValueError:
            return host.rstrip(".").lower() == "localhost"
    except ValueError:
        return False


def _is_https_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return bool(
            parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and not parsed.fragment
        )
    except ValueError:
        return False


def _allow_insecure_local_oidc() -> bool:
    return (
        os.getenv("DBGPT_OIDC_ALLOW_INSECURE_HTTP", "false").strip().lower() == "true"
    )


def _is_allowed_oidc_issuer(issuer: str) -> bool:
    if _is_https_url(issuer):
        return not urlsplit(issuer).query
    return (
        _allow_insecure_local_oidc()
        and _is_loopback_http_url(issuer)
        and not urlsplit(issuer).query
        and not urlsplit(issuer).fragment
    )


class UserRequest(BaseModel):
    user_id: Optional[str] = None
    user_no: Optional[str] = None
    real_name: Optional[str] = None
    # same with user_id
    user_name: Optional[str] = None
    user_channel: Optional[str] = None
    role: Optional[str] = "normal"
    nick_name: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    nick_name_like: Optional[str] = None
    tenant_id: Optional[str] = None
    region_id: Optional[str] = None


def _oidc_settings() -> Optional[Dict[str, Any]]:
    issuer = os.getenv("DBGPT_OIDC_ISSUER")
    if not issuer:
        return None
    audience = os.getenv("DBGPT_OIDC_AUDIENCE")
    if not audience:
        raise RuntimeError("DBGPT_OIDC_AUDIENCE is required when OIDC is enabled")
    if not _is_allowed_oidc_issuer(issuer):
        raise RuntimeError(
            "OIDC issuer must use HTTPS or explicitly enabled loopback HTTP"
        )
    try:
        mappings = json.loads(os.getenv("DBGPT_OIDC_CLAIM_MAPPINGS", "{}"))
        role_mapping = json.loads(os.getenv("DBGPT_OIDC_ROLE_MAPPING", "{}"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("OIDC claim mappings must be valid JSON") from exc
    if not isinstance(mappings, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in mappings.items()
    ):
        raise RuntimeError("OIDC claim mappings must map field names to claim paths")
    if any(
        not field.strip()
        or not path.strip()
        or any(not segment.strip() for segment in path.split("."))
        for field, path in mappings.items()
    ):
        raise RuntimeError("OIDC claim mappings must contain non-empty claim paths")
    supported_fields = set(model_fields(UserRequest))
    if not set(mappings).issubset(supported_fields):
        raise RuntimeError("OIDC claim mappings contain unsupported user fields")
    if not isinstance(role_mapping, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in role_mapping.items()
    ):
        raise RuntimeError("OIDC role mapping must map provider roles to DB-GPT roles")
    if any(
        not role.strip() or not mapped_role.strip()
        for role, mapped_role in role_mapping.items()
    ):
        raise RuntimeError("OIDC role mapping must contain non-empty role names")
    return {
        "issuer": issuer,
        "audience": audience,
        "claim_mappings": {**_DEFAULT_CLAIM_MAPPINGS, **mappings},
        "role_mapping": role_mapping,
    }


@lru_cache(maxsize=8)
def _get_jwks_client(issuer: str) -> PyJWKClient:
    allow_insecure = _allow_insecure_local_oidc()
    if not _is_allowed_oidc_issuer(issuer):
        raise RuntimeError(
            "OIDC issuer must use HTTPS or explicitly enabled loopback HTTP"
        )
    discovery_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    try:
        with urlopen(discovery_url, timeout=5) as response:
            metadata = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, ValueError) as exc:
        raise RuntimeError("Unable to load OIDC discovery metadata") from exc
    if metadata.get("issuer") != issuer:
        raise RuntimeError("OIDC discovery issuer does not match configured issuer")
    jwks_uri = metadata.get("jwks_uri")
    if not isinstance(jwks_uri, str) or not (
        _is_https_url(jwks_uri) or (allow_insecure and _is_loopback_http_url(jwks_uri))
    ):
        raise RuntimeError("OIDC discovery metadata has an invalid jwks_uri")
    return PyJWKClient(jwks_uri, timeout=5)


def _claim_value(claims: Dict[str, Any], path: str) -> Any:
    value: Any = claims
    for segment in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(segment)
    return value


def _user_from_oidc_token(token: str, settings: Dict[str, Any]) -> UserRequest:
    jwks_client = _get_jwks_client(settings["issuer"])
    signing_key = jwks_client.get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
        audience=settings["audience"],
        issuer=settings["issuer"],
        options={"require": ["exp", "iat", "iss", "aud", "sub"]},
    )
    values = {
        field: _claim_value(claims, path)
        for field, path in settings["claim_mappings"].items()
    }
    if not values.get("user_id"):
        raise ValueError("OIDC token has no mapped user identifier")
    provider_role = values.get("role")
    provider_roles = (
        provider_role if isinstance(provider_role, list) else [provider_role]
    )
    mapped_roles = {
        settings["role_mapping"][role]
        for role in provider_roles
        if isinstance(role, str) and role in settings["role_mapping"]
    }
    values["role"] = mapped_roles.pop() if len(mapped_roles) == 1 else "normal"
    values["user_id"] = str(values["user_id"])
    values["user_name"] = values.get("user_name") or values["user_id"]
    values["nick_name"] = values.get("nick_name") or values["user_name"]
    values["real_name"] = values.get("real_name") or values["nick_name"]
    for field in (
        "user_no",
        "user_channel",
        "tenant_id",
        "region_id",
        "email",
        "avatar_url",
    ):
        if values.get(field) is not None:
            values[field] = str(values[field])
    return UserRequest(**values)


def get_user_from_headers(
    user_id: Optional[str] = Header(None),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
):
    try:
        settings = _oidc_settings()
    except RuntimeError as exc:
        logger.error("OIDC authentication is misconfigured: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC authentication is not configured correctly",
        ) from exc
    if settings:
        if not credentials or credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bearer token required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            return _user_from_oidc_token(credentials.credentials, settings)
        except Exception as exc:
            logger.warning("OIDC token authentication failed: %s", type(exc).__name__)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
    try:
        # Legacy development identity. Configure DBGPT_OIDC_ISSUER to require JWT.
        if user_id:
            return UserRequest(
                user_id=user_id, role="admin", nick_name=user_id, real_name=user_id
            )
        else:
            return UserRequest(
                user_id="001", role="admin", nick_name="dbgpt", real_name="dbgpt"
            )
    except Exception as e:
        logging.exception("Authentication failed!")
        raise Exception(f"Authentication failed. {str(e)}")


def trusted_agent_execution_context(user_info: UserRequest) -> Optional[Dict[str, Any]]:
    """Build server-owned identity context only when JWT verification is enabled.

    This helper must only be called with the UserRequest returned by
    ``get_user_from_headers``. The legacy development identity is deliberately
    not accepted for protected datasource resources.
    """
    settings = _oidc_settings()
    if not settings or not user_info.user_id:
        return None
    return {
        "actor_id": user_info.user_id,
        "role": user_info.role,
        "tenant_id": user_info.tenant_id,
        "region_id": user_info.region_id,
        "source": "verified_oidc_jwt",
        "authorization_policy_version": "oidc-claims-v1",
    }


def local_demo_execution_context(
    user_info: UserRequest, database_name: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Build a narrowly scoped identity for an explicitly configured local demo DB."""
    if _oidc_settings() or not user_info or not user_info.user_id or not database_name:
        return None
    if user_info.role != "admin":
        return None
    try:
        mapping = json.loads(os.getenv("DBGPT_LOCAL_DEMO_DATASOURCES", "{}"))
    except json.JSONDecodeError:
        return None
    configured_path = mapping.get(database_name) if isinstance(mapping, dict) else None
    if not isinstance(configured_path, str) or not os.path.isabs(configured_path):
        return None
    try:
        expected_path = os.path.realpath(configured_path)
        if not os.path.isfile(expected_path):
            return None
        from dbgpt._private.config import Config

        rows = Config().local_db_manager.get_db_list(
            db_name=database_name, user_id=None
        )
        datasource = next(
            (row for row in rows if row.get("db_name") == database_name), None
        )
    except Exception:
        logger.warning("Unable to validate local demo datasource", exc_info=True)
        return None
    if (
        not datasource
        or datasource.get("db_type") != "sqlite"
        or datasource.get("user_id") != user_info.user_id
        or os.path.realpath(str(datasource.get("db_path") or "")) != expected_path
    ):
        return None
    tenant_id = os.getenv("DBGPT_LOCAL_DEMO_TENANT_ID", "").strip()
    if not tenant_id:
        return None
    return {
        "actor_id": user_info.user_id,
        "role": user_info.role,
        "tenant_id": tenant_id,
        "region_id": None,
        "data_source_id": database_name,
        "authorization_policy_version": "local-demo-v1",
        "source": "local_demo",
    }
