import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from dbgpt.configs import model_config
from dbgpt_app.openapi.api_v1 import agentic_data_api
from dbgpt_serve.utils.auth import UserRequest, get_user_from_headers


@pytest.fixture
def download_client(tmp_path, monkeypatch):
    pilot_path = tmp_path / "pilot"
    monkeypatch.setattr(model_config, "PILOT_PATH", str(pilot_path))
    monkeypatch.setattr(
        agentic_data_api,
        "trusted_agent_execution_context",
        lambda user: {
            "source": "verified_oidc_jwt",
            "actor_id": user.user_id,
        },
    )
    owners = {"conv-alice": "alice", "conv-bob": "bob"}
    monkeypatch.setattr(
        agentic_data_api,
        "_conversation_owner_user_name",
        lambda conv_uid: owners.get(conv_uid),
    )

    app = FastAPI()

    def test_user(authorization: str | None = Header(default=None)):
        if authorization != "Bearer valid":
            raise HTTPException(status_code=401, detail="Bearer token required")
        return UserRequest(user_id="alice")

    app.dependency_overrides[get_user_from_headers] = test_user
    app.include_router(agentic_data_api.router)
    return TestClient(app), pilot_path


def test_agent_file_download_requires_authentication(download_client):
    client, _ = download_client
    response = client.get(
        "/v1/agent/files/download",
        params={"conv_uid": "conv-alice", "file_path": "report.csv"},
    )

    assert response.status_code == 401


def test_agent_file_download_requires_verified_identity(download_client, monkeypatch):
    client, _ = download_client
    monkeypatch.setattr(
        agentic_data_api, "trusted_agent_execution_context", lambda user: None
    )

    response = client.get(
        "/v1/agent/files/download",
        params={"conv_uid": "conv-alice", "file_path": "report.csv"},
        headers={"Authorization": "Bearer valid"},
    )

    assert response.status_code == 401


def test_agent_file_download_rejects_foreign_conversation(download_client):
    client, pilot_path = download_client
    artifact = pilot_path / "tmp" / "conv-alice" / "report.csv"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("private report", encoding="utf-8")

    response = client.get(
        "/v1/agent/files/download",
        params={
            "conv_uid": "conv-bob",
            "file_path": str(artifact),
        },
        headers={"Authorization": "Bearer valid"},
    )

    assert response.status_code == 403


def test_agent_file_download_rejects_path_traversal(download_client):
    client, pilot_path = download_client
    outside = pilot_path / "tmp" / "secret.txt"
    outside.parent.mkdir(parents=True)
    outside.write_text("secret", encoding="utf-8")

    response = client.get(
        "/v1/agent/files/download",
        params={"conv_uid": "conv-alice", "file_path": "../secret.txt"},
        headers={"Authorization": "Bearer valid"},
    )

    assert response.status_code == 403


def test_agent_file_download_rejects_legacy_global_tmp_path(download_client):
    client, _ = download_client

    response = client.get(
        "/v1/agent/files/download",
        params={
            "conv_uid": "conv-alice",
            "file_path": "/tmp/agent-output.csv",
        },
        headers={"Authorization": "Bearer valid"},
    )

    assert response.status_code == 403


def test_agent_file_download_allows_owned_artifact(download_client):
    client, pilot_path = download_client
    artifact = pilot_path / "tmp" / "conv-alice" / "report.csv"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("authorized report", encoding="utf-8")

    response = client.get(
        "/v1/agent/files/download",
        params={"conv_uid": "conv-alice", "file_path": str(artifact)},
        headers={"Authorization": "Bearer valid"},
    )

    assert response.status_code == 200
    assert response.content == b"authorized report"


def test_agent_file_download_rejects_symlink_escape(download_client):
    client, pilot_path = download_client
    artifact_dir = pilot_path / "tmp" / "conv-alice"
    artifact_dir.mkdir(parents=True)
    outside = pilot_path / "tmp" / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    link = artifact_dir / "report.csv"
    try:
        link.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"symlinks unavailable: {error}")

    response = client.get(
        "/v1/agent/files/download",
        params={"conv_uid": "conv-alice", "file_path": str(link)},
        headers={"Authorization": "Bearer valid"},
    )

    assert response.status_code == 403


def test_agent_file_download_rejects_conversation_path_component(download_client):
    client, _ = download_client
    response = client.get(
        "/v1/agent/files/download",
        params={"conv_uid": "../conv-bob", "file_path": "report.csv"},
        headers={"Authorization": "Bearer valid"},
    )

    assert response.status_code == 400
