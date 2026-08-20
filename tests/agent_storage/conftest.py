"""Shared real-infrastructure fixtures for the default-chain E2E suites."""

from __future__ import annotations

import os
import threading
from http.server import ThreadingHTTPServer
from uuid import uuid4

import pytest
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_storage import apply_postgres_migrations, bootstrap_control_plane_epoch
from agent_storage.artifact_objects import S3ArtifactObjectStore
from agent_storage.runtime_composition import CloudCompositionSettings
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.session import Session as BotocoreSession  # type: ignore[import-untyped]

from tests.agent_storage.test_postgres_default_chain_e2e import (
    MODEL_KEY_ENV,
    _StubModelHandler,
)


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture(scope="session")
def cloud_composition(postgres_dsn: str) -> CloudCompositionSettings:
    endpoint = os.environ.get("ZEBRA_TEST_S3_ENDPOINT")
    if not endpoint:
        pytest.skip("set ZEBRA_TEST_S3_ENDPOINT to run real artifact-store tests")
    client = BotocoreSession().create_client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ.get("ZEBRA_TEST_S3_ACCESS_KEY", ""),
        aws_secret_access_key=os.environ.get("ZEBRA_TEST_S3_SECRET_KEY", ""),
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    issuer = OpaqueAuthorityScope(
        authority_issuer="https://zebra-e2e.example.com",
        namespace_id="e2e-history",
    )
    continuation = OpaqueAuthorityScope(
        authority_issuer="https://zebra-e2e.example.com",
        namespace_id="e2e-continuation",
    )
    return CloudCompositionSettings(
        dsn=postgres_dsn,
        deployment_namespace=f"default-chain-{uuid4()}",
        memory_cursor_signing_key=b"e2e-memory-cursor-signing-key-32bytes!!",
        artifact_objects=S3ArtifactObjectStore(
            client,
            bucket=os.environ.get("ZEBRA_TEST_S3_BUCKET", "zebra-artifacts"),
            key_prefix="zebra/artifacts/v1",
        ),
        history_scope=issuer,
        continuation_scope=continuation,
    )


@pytest.fixture
def namespace(cloud_composition: CloudCompositionSettings) -> str:
    namespace = f"default-chain-{uuid4()}"
    bootstrap_control_plane_epoch(
        cloud_composition.dsn, deployment_namespace=namespace
    )
    return namespace


@pytest.fixture
def stub_model_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubModelHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    os.environ[MODEL_KEY_ENV] = "stub-key"
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()
    os.environ.pop(MODEL_KEY_ENV, None)
