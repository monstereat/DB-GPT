"""Datasource credential encryption and approval policy helpers."""

import base64
import hashlib
import json
import os
import secrets
from dataclasses import fields
from typing import Any, Dict, Optional, Set

_ENCRYPTED_PREFIX = "enc:v1:"


def _encryption_key(system_app=None) -> bytes:
    key = os.getenv("DBGPT_DATASOURCE_ENCRYPTION_KEY")
    if not key and system_app is not None:
        config = getattr(system_app, "config", None)
        if config is not None:
            key = config.get("dbgpt.app.global.encrypt_key")
    if not key:
        raise RuntimeError("Datasource encryption key is required")
    return key.encode("utf-8")


def is_encrypted_secret(value: Optional[str]) -> bool:
    return bool(value and value.startswith(_ENCRYPTED_PREFIX))


def encrypt_secret(value: Optional[str], system_app=None) -> Optional[str]:
    if not value or is_encrypted_secret(value):
        return value
    from dbgpt.core.interface.variables import FernetEncryption

    salt = base64.urlsafe_b64encode(secrets.token_bytes(16)).decode("ascii")
    encrypted = FernetEncryption(key=_encryption_key(system_app)).encrypt(value, salt)
    return f"{_ENCRYPTED_PREFIX}{salt}:{encrypted}"


def decrypt_secret(value: Optional[str], system_app=None) -> Optional[str]:
    if not value:
        return value
    if not is_encrypted_secret(value):
        raise RuntimeError("Datasource credentials must be migrated before use")
    _, _, salt, encrypted = value.split(":", 3)
    from dbgpt.core.interface.variables import FernetEncryption

    return FernetEncryption(key=_encryption_key(system_app)).decrypt(encrypted, salt)


def private_parameter_names(parameter_or_class) -> Set[str]:
    return {
        item.name
        for item in fields(parameter_or_class)
        if "privacy" in str(item.metadata.get("tags", "")).split(",")
    }


def validate_stored_secret_envelopes(state: Dict[str, Any], db_type: str, manager):
    """Check approval-time ciphertext and return the active key fingerprint."""
    param_cls = manager._get_param_cls(db_type)
    mapping = param_cls._persisted_state_mapping()
    private_names = private_parameter_names(param_cls)
    secret_values = []
    for name in private_names:
        column = mapping.get(name, name)
        if column != "ext_config" and state.get(column):
            secret_values.append(state[column])
    ext_config = state.get("ext_config")
    if isinstance(ext_config, str) and ext_config:
        ext_config = json.loads(ext_config)
    if isinstance(ext_config, dict):
        secret_values.extend(
            ext_config[name] for name in private_names if ext_config.get(name)
        )
    for value in secret_values:
        if not is_encrypted_secret(value):
            raise RuntimeError("Datasource credentials must be migrated before use")
    if not secret_values:
        return None
    return hashlib.sha256(_encryption_key(manager.system_app)).hexdigest()


def protect_persisted_state(
    state: Dict[str, Any], parameter, system_app=None
) -> Dict[str, Any]:
    """Encrypt privacy-tagged parameters before they enter metadata storage."""
    protected = dict(state)
    mapping = parameter.__class__._persisted_state_mapping()
    for name in private_parameter_names(parameter):
        column = mapping.get(name, name)
        if column == "ext_config":
            continue
        if protected.get(column):
            protected[column] = encrypt_secret(protected[column], system_app)

    ext_config = protected.get("ext_config")
    if isinstance(ext_config, str) and ext_config:
        ext_config = json.loads(ext_config)
    if isinstance(ext_config, dict):
        ext_config = dict(ext_config)
        for name in private_parameter_names(parameter):
            if name in ext_config and ext_config[name]:
                ext_config[name] = encrypt_secret(ext_config[name], system_app)
        protected["ext_config"] = json.dumps(ext_config, ensure_ascii=False)
    return protected


def reveal_persisted_secrets(
    state: Dict[str, Any], db_type: str, manager
) -> Dict[str, Any]:
    """Decrypt private connection fields just before connector construction."""
    revealed = dict(state)
    param_cls = manager._get_param_cls(db_type)
    mapping = param_cls._persisted_state_mapping()
    private_names = private_parameter_names(param_cls)
    for name in private_names:
        column = mapping.get(name, name)
        if column != "ext_config" and revealed.get(column):
            revealed[column] = decrypt_secret(revealed[column], manager.system_app)

    ext_config = revealed.get("ext_config")
    if isinstance(ext_config, str) and ext_config:
        ext_config = json.loads(ext_config)
    if isinstance(ext_config, dict):
        ext_config = dict(ext_config)
        for name in private_names:
            if name in ext_config and ext_config[name]:
                ext_config[name] = decrypt_secret(ext_config[name], manager.system_app)
        revealed["ext_config"] = json.dumps(ext_config, ensure_ascii=False)
    return revealed


def privacy_fields_for_type(db_type: str, manager) -> Set[str]:
    return private_parameter_names(manager._get_param_cls(db_type))
