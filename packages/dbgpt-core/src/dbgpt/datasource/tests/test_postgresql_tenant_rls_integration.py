"""Disposable PostgreSQL RLS isolation test, enabled by an explicit opt-in env var."""

import os
import shutil
import subprocess
import time
import uuid

import pytest
from sqlalchemy import create_engine, text

from dbgpt.datasource.rdbms.base import RDBMSConnector


@pytest.mark.skipif(
    os.getenv("DBGPT_RUN_POSTGRES_RLS_INTEGRATION") != "1",
    reason="set DBGPT_RUN_POSTGRES_RLS_INTEGRATION=1 to start a disposable PostgreSQL",
)
def test_postgresql_rls_context_is_transaction_local_on_reused_connection():
    if not shutil.which("docker"):
        pytest.skip("Docker CLI is not installed")
    pytest.importorskip(
        "psycopg", reason="install the PostgreSQL driver to run RLS smoke"
    )

    container_name = f"dbgpt-rls-test-{uuid.uuid4().hex[:12]}"
    admin_password = uuid.uuid4().hex
    app_password = uuid.uuid4().hex
    subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--name",
            container_name,
            "--publish",
            "127.0.0.1::5432",
            "--env",
            "POSTGRES_USER=rls_admin",
            "--env",
            f"POSTGRES_PASSWORD={admin_password}",
            "--env",
            "POSTGRES_DB=rls_test",
            "postgres:16.6",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    connector = None
    admin_engine = None
    try:
        port = (
            subprocess.run(
                ["docker", "port", container_name, "5432/tcp"],
                check=True,
                capture_output=True,
                text=True,
            )
            .stdout.strip()
            .rsplit(":", 1)[1]
        )
        admin_url = (
            f"postgresql+psycopg://rls_admin:{admin_password}@127.0.0.1:{port}/rls_test"
        )
        admin_engine = create_engine(admin_url)
        deadline = time.monotonic() + 60
        while True:
            try:
                with admin_engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.5)

        with admin_engine.begin() as connection:
            connection.exec_driver_sql(
                f"CREATE ROLE rls_app LOGIN PASSWORD '{app_password}' "
                "NOSUPERUSER NOBYPASSRLS"
            )
            connection.execute(
                text(
                    "CREATE TABLE public.rls_demo "
                    "(tenant_id text NOT NULL, payload text NOT NULL)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO public.rls_demo VALUES "
                    "('tenant-a', 'a1'), ('tenant-b', 'b1')"
                )
            )
            connection.execute(
                text("ALTER TABLE public.rls_demo ENABLE ROW LEVEL SECURITY")
            )
            connection.execute(
                text(
                    "CREATE POLICY tenant_isolation ON public.rls_demo "
                    "USING (tenant_id = current_setting('app.current_tenant', true))"
                )
            )
            connection.execute(text("GRANT USAGE ON SCHEMA public TO rls_app"))
            connection.execute(text("GRANT SELECT ON public.rls_demo TO rls_app"))

        connector = RDBMSConnector.from_uri(
            f"postgresql+psycopg://rls_app:{app_password}@127.0.0.1:{port}/rls_test",
            engine_args={"pool_size": 1, "max_overflow": 0},
        )
        query = "SELECT payload FROM public.rls_demo ORDER BY payload"
        tenant_a = {"source": "verified_oidc_jwt", "tenant_id": "tenant-a"}
        tenant_b = {"source": "verified_oidc_jwt", "tenant_id": "tenant-b"}

        assert connector.query_ex(query, verified_execution_context=tenant_a)[1] == [
            ("a1",)
        ]
        assert connector.query_ex(query, verified_execution_context=tenant_b)[1] == [
            ("b1",)
        ]
        assert connector.query_ex(query, verified_execution_context=None)[1] == []
        assert (
            connector.query_ex(
                query,
                verified_execution_context={
                    "source": "legacy_dev_identity",
                    "tenant_id": "tenant-a",
                },
            )[1]
            == []
        )

        with pytest.raises(Exception):
            connector.query_ex("SELECT * FROM missing_table")
        with pytest.raises(TimeoutError):
            connector.query_ex("SELECT pg_sleep(0.2)", timeout=0.05)
        assert connector.query_ex(query, verified_execution_context=tenant_a)[1] == [
            ("a1",)
        ]
    finally:
        if connector is not None:
            connector._engine.dispose()
        if admin_engine is not None:
            admin_engine.dispose()
        subprocess.run(
            ["docker", "rm", "--force", container_name],
            check=False,
            capture_output=True,
            text=True,
        )
