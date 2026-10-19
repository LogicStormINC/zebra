"""Concrete PG/S3 fixture; private connection settings never enter evidence output."""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4
from zipfile import ZipFile

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.extensions import McpConnection, SkillInstallation
from agent_core.domain.mcp_catalog import McpCatalogTool, McpToolCatalog
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_integrations.plugins.package_integrity import load_plugin_package
from agent_security.extension_authority import extension_runtime_scope_from_grant
from agent_storage import S3ArtifactObjectStore
from agent_storage.postgres.events import PostgresEventStore
from agent_storage.postgres.extension_snapshots import PostgresExtensionSnapshotStore
from agent_storage.postgres.extensions import PostgresExtensionStore
from agent_storage.postgres.mcp_catalog import PostgresMcpCatalogStore
from agent_storage.postgres.plugin_installations import PostgresPluginInstallationStore
from agent_storage.postgres.projections import PostgresProjectionStore
from agent_storage.postgres.skill_publications import PostgresSkillPublicationStore
from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction
from agent_storage.postgres.task_io import TaskIoConnections
from agent_tools.skill_publications import publish_skill_package
from botocore.config import Config
from botocore.session import Session
from psycopg.conninfo import make_conninfo
from starlette.requests import Request
from zebra_agent_api.command_submission import submit_session_command
from zebra_agent_api.extension_turn_admission import CloudExtensionTurnAdmission
from zebra_agent_api.plugin_composition import compose_plugins
from zebra_agent_api.plugin_installations import plugin_installation_response

from tests.agent_security.test_extension_authority import _task_binding, _verified
from tests.agent_storage.test_postgres_extension_turn_admission import TASK_RESOURCES

SKILL = (
    b"---\nname: native-proof\ndescription: Offline native proof\nversion: v1\n---\n"
    b"Read references/support.txt for NATIVE-SKILL-PROOF.\n"
)
SUPPORT = b"NATIVE-SKILL-PROOF\n"
FILES = {"SKILL.md": SKILL, "references/support.txt": SUPPORT}


def private_config(path: Path) -> dict[str, Any]:
    assert path.is_file() and path.stat().st_mode & 0o777 == 0o600, "private config needs mode 600"
    values = json.loads(path.read_text())
    assert set(values) == {
        "postgres_dsn",
        "s3_endpoint",
        "s3_access_key",
        "s3_secret_key",
        "s3_bucket",
        "owned_containers",
    }
    return values


@dataclass
class NativeFixture:
    config: dict[str, Any]
    schema: str

    def __post_init__(self) -> None:
        assert self.schema.startswith("cloud_plugin_accept_") and self.schema.isidentifier()
        self.namespace = self.schema
        self.dsn = make_conninfo(
            self.config["postgres_dsn"], options=f"-c search_path={self.schema}"
        )
        self.client = Session().create_client(
            "s3",
            endpoint_url=self.config["s3_endpoint"],
            aws_access_key_id=self.config["s3_access_key"],
            aws_secret_access_key=self.config["s3_secret_key"],
            region_name="us-east-1",
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        assert (
            self.client.get_bucket_versioning(Bucket=self.config["s3_bucket"])["Status"]
            == "Enabled"
        )
        self.objects = S3ArtifactObjectStore(self.client, bucket=self.config["s3_bucket"])
        self.io = TaskIoConnections(self.dsn)
        options = dict(deployment_namespace=self.namespace, task_io_connections=self.io)
        self.extensions = PostgresExtensionStore(self.dsn, **options)
        self.snapshots = PostgresExtensionSnapshotStore(self.dsn, **options)
        self.catalogs = PostgresMcpCatalogStore(self.dsn, **options)
        self.plugins = PostgresPluginInstallationStore(self.dsn, **options)
        self.events = PostgresEventStore(self.dsn, deployment_namespace=self.namespace)
        self.projections = PostgresProjectionStore(self.dsn, deployment_namespace=self.namespace)

    def compose(self, root: Path, digest: str):
        settings = SimpleNamespace(
            plugins=SimpleNamespace(enabled=True, bundle_root=str(root), allowed_digests=(digest,)),
            deployment="cloud",
            storage_authority="postgresql",
            cloud_extensions_manage_enabled=True,
            cloud_extension_turn_admission_enabled=True,
            mcp_credentials=SimpleNamespace(worker_enabled=True),
        )
        cloud = SimpleNamespace(
            dsn=self.dsn,
            deployment_namespace=self.namespace,
            artifact_objects=self.objects,
        )
        service, resolver = compose_plugins(
            settings,
            cloud,
            self.extensions,
            task_io_connections=self.io,
        )
        assert service is not None and resolver is not None
        return service, CloudExtensionTurnAdmission(
            self.extensions,
            self.snapshots,
            self.snapshots,
            mcp_catalogs=self.catalogs,
            plugins=resolver,
        )


def verified():
    # Existing verification fixture validates claims; this check does not exercise JWT HTTP crypto.
    return _verified(
        scopes=["agent.run", "extensions.read", "extensions.manage"],
        resource_refs=TASK_RESOURCES,
    )


def bundle(root: Path) -> str:
    candidate = root / "candidate"
    skill_root = candidate / "skills" / "proof"
    skill_root.mkdir(parents=True)
    (candidate / "plugin.json").write_text(
        json.dumps(
            {
                "id": "native-proof",
                "version": "1.0.0",
                "publisher": "Native acceptance",
                "manifest_version": "0.2",
                "components": [
                    {"id": "proof-skill", "kind": "skill-bundle", "skill_root": "skills/proof"},
                    {"id": "proof-mcp", "kind": "mcp-http", "connection_slot": "proof-mcp"},
                ],
            }
        )
    )
    for name, value in FILES.items():
        (skill_root / name).parent.mkdir(parents=True, exist_ok=True)
        (skill_root / name).write_bytes(value)
    digest = load_plugin_package(candidate).package_digest
    candidate.rename(root / digest.removeprefix("sha256:"))
    return digest


async def components(fixture: NativeFixture):
    scope = extension_runtime_scope_from_grant(verified())
    archive = io.BytesIO()
    with ZipFile(archive, "w") as package:
        for name, value in FILES.items():
            package.writestr(name, value)
    publication = await publish_skill_package(
        archive=archive.getvalue(),
        scope=scope,
        deployment_namespace=fixture.namespace,
        store=PostgresSkillPublicationStore(fixture.dsn, deployment_namespace=fixture.namespace),
        objects=fixture.objects,
    )
    skill = SkillInstallation(
        scope=scope,
        installation_id="proof-skill",
        revision=1,
        version=publication.version,
    )
    await fixture.extensions.save_skill(scope=scope, installation=skill, expected_revision=None)
    connection = McpConnection(
        scope=scope,
        connection_id="proof-mcp",
        revision=1,
        endpoint="https://mcp.example.com/native",
    )
    await fixture.extensions.save_mcp(scope=scope, connection=connection, expected_revision=None)
    catalog = McpToolCatalog(
        connection=connection,
        protocol_version="2025-11-25",
        tools=(
            McpCatalogTool(
                name="echo",
                input_schema_json='{"type":"object","properties":{"value":{"type":"string"}},"required":["value"],"additionalProperties":false}',
            ),
        ),
    )
    await fixture.catalogs.publish(scope=scope, catalog=catalog)
    return skill, connection


async def manage(
    service,
    *,
    method: str,
    grant=None,
    identifier="",
    revision=None,
    payload=None,
    key="native-install",
):
    body = json.dumps(payload or {}).encode()
    headers = [(b"idempotency-key", key.encode())]
    if revision is not None:
        headers.append((b"if-match", f'"{revision}"'.encode()))

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": method,
            "path": "/v1/extensions/plugin-installations"
            + ("/" + identifier if identifier else ""),
            "query_string": b"",
            "headers": headers,
            "state": {"verified_host_grant": grant or verified()},
        },
        receive,
    )
    response = await plugin_installation_response(
        request,
        service=service,
        deployment="cloud",
        enabled=True,
        read_enabled=True,
        manage_enabled=True,
    )
    assert response is not None
    return response.status_code, json.loads(response.body)


def seed_task(fixture: NativeFixture, skill_id: str, root: Path, *, network="mcp-proxy-only"):
    grant = verified()
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Native Plugin proof",
            user_input="offline",
            workspace_root=root,
            network_profile=network,
            host_context=grant.context,
            skill_components=(skill_id,),
        )
    )
    binding = _task_binding(grant).model_copy(update={"task_id": str(bootstrap.session.session_id)})
    binding = binding.model_copy(
        update={
            "effective_capabilities": frozenset({"agent.execute", "evidence.read"}),
            "agent_capability_ceiling": binding.agent_capability_ceiling.model_copy(
                update={
                    "capabilities": frozenset({"agent.execute", "evidence.read"}),
                }
            ),
            "host_capability": binding.host_capability.model_copy(
                update={
                    "grant_expires_at": grant.context.expires_at,
                    "capabilities": frozenset({"agent.execute", "evidence.read"}),
                }
            ),
        }
    )
    PostgresTaskAdmissionTransaction(fixture.dsn, deployment_namespace=fixture.namespace).admit(
        TaskAdmissionRequest(
            events=bootstrap.events,
            session=bootstrap.session,
            workspace=rebuild_workspace(list(bootstrap.events)),
            binding=binding,
        ),
    )
    return bootstrap.session.session_id


def admit(fixture: NativeFixture, admission, session_id, selection):
    events = fixture.events.list_for_session(session_id)
    response = submit_session_command(
        SimpleNamespace(events=fixture.events, sessions=fixture.projections),
        str(session_id),
        {
            "kind": "run",
            "expected_revision": events[-1].sequence,
            "payload": {} if selection is None else {"extension_selection": selection},
        },
        idempotency_key="native-run-" + uuid4().hex,
        extension_admission=admission,
        verified_host_grant=verified(),
    )
    assert response.status_code == 202, f"admission status {response.status_code}"
    return fixture.events.list_for_session(session_id)[-1]
