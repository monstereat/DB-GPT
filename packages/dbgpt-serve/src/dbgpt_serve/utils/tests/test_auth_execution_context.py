from dbgpt_serve.utils import auth


def test_trusted_agent_context_is_unavailable_without_oidc(monkeypatch):
    monkeypatch.delenv("DBGPT_OIDC_ISSUER", raising=False)

    assert (
        auth.trusted_agent_execution_context(
            auth.UserRequest(user_id="alice", role="admin")
        )
        is None
    )


def test_trusted_agent_context_contains_only_server_identity(monkeypatch):
    monkeypatch.setattr(
        auth, "_oidc_settings", lambda: {"issuer": "https://issuer.example"}
    )
    user = auth.UserRequest(
        user_id="alice", role="sales", tenant_id="tenant-a", region_id="north"
    )

    context = auth.trusted_agent_execution_context(user)

    assert context == {
        "actor_id": "alice",
        "role": "sales",
        "tenant_id": "tenant-a",
        "region_id": "north",
        "source": "verified_oidc_jwt",
        "authorization_policy_version": "oidc-claims-v1",
    }
