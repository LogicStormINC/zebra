"""Bounded independent allocation proof using current generic Native contracts."""

import hashlib
import json
import os
import ssl
import sys
from time import monotonic
from uuid import UUID


def facts(connection, store, sid, wid, namespace, root):
    from agent_core.domain.task_bindings import task_bound_host_thread
    from agent_core.domain.workspace_control import WorkspaceId
    from agent_storage.postgres.task_admission import read_session_task_binding

    row = connection.execute(
        (
            "SELECT task.task_id,projection.workspace_root FROM agent_tasks t"
            "ask JOIN execution_segments segment ON segment.deployment_namesp"
            "ace=task.deployment_namespace AND segment.task_id=task.task_id A"
            "ND segment.session_id=task.active_segment_id JOIN workspace_proj"
            "ections projection ON projection.deployment_namespace=segment.de"
            "ployment_namespace AND projection.session_id=segment.session_id "
            "WHERE task.deployment_namespace=%s AND segment.session_id=%s"
        ),
        (namespace, sid),
    ).fetchone()
    instance = store._require_instance(connection, WorkspaceId(wid))
    binding = read_session_task_binding(connection, namespace, sid)
    if row is None or instance is None or binding is None:
        raise ValueError("missing independent native facts")
    context = binding.host_capability.host_context
    if context is None or binding.task_id != str(row["task_id"]):
        raise ValueError("native Task binding mismatch")
    thread = task_bound_host_thread(binding, task_id=binding.task_id)
    refs = {}
    for ref in context.resource_refs:
        if ref.resource_type in refs:
            raise ValueError("ambiguous authority resource")
        refs[ref.resource_type] = ref.resource_id
    if (
        row["workspace_root"] not in {"workspace://" + str(wid), "workspace:/" + str(wid)}
        or instance.owner_session_id != sid
        or instance.quota_bytes != 256 * 1024 * 1024
        or instance.source.kind.value != "host_reference"
        or not instance.source.locator.startswith(("erpnext://workspace/", "erpnext://schedule/"))
        or instance.source.pinned_revision is not None
        or instance.source.archive_artifact_uri is not None
        or instance.source.content_digest is not None
        or instance.state.value not in {"pending", "ready", "sealed"}
        or instance.state.value != "pending"
        and instance.volume_ref != root + "/" + str(wid)
        or not {"principal", "company", "run"} <= set(refs)
        or "agent.run" not in context.scopes
    ):
        raise ValueError("workspace identity or authority mismatch")
    identity = hashlib.sha256(
        json.dumps(
            dict(
                task=binding.task_id,
                thread=thread.resource_id,
                principal=refs["principal"],
                company=refs["company"],
                workspace_ref=context.workspace_ref,
                workspace_id=str(wid),
                source=instance.source.locator,
            ),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return identity, instance, binding


def main():
    import httpx
    from agent_core.domain.identifiers import SessionId
    from agent_integrations.host_credentials import ConfiguredHmacHostCredentialResolver
    from agent_storage.postgres.database import PostgresDatabase, postgres_deadline
    from agent_storage.postgres.host_connectors import PostgresHostConnectorRegistry
    from agent_storage.postgres.workspace_control import PostgresWorkspaceControlStore
    from zebra_agent_config.host_authority_settings import HostExecutionAuthoritySettings
    from zebra_agent_worker.host_authority_probe import HostAuthorityProbe

    data = sys.stdin.buffer.read(16385)
    if len(data) > 16384:
        raise ValueError("bounded proof request required")
    request = json.loads(data)
    if set(request) != {
        "readonly_dsn",
        "shared_secret",
        "ca_pem",
        "session_id",
        "workspace_id",
        "nonce",
    }:
        raise ValueError("invalid proof request")
    for field in ("session_id", "workspace_id", "nonce"):
        if str(UUID(request[field])) != request[field]:
            raise ValueError("noncanonical identifier")
    qa = os.environ.get("ZEBRA_FULL_QA") == "true"
    namespace = "erpnext-full"
    root = "/var/lib/zebra/erpnext-full-" + ("qa-" if qa else "") + "workspaces"
    sid, wid = SessionId(UUID(request["session_id"])), UUID(request["workspace_id"])
    database = PostgresDatabase(request["readonly_dsn"], deployment_namespace=namespace)
    store = PostgresWorkspaceControlStore(request["readonly_dsn"], deployment_namespace=namespace)
    with postgres_deadline(monotonic() + 5):

        def read():
            with database.connect_task_io() as connection:
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                return facts(connection, store, sid, wid, namespace, root)

        identity, instance, binding = read()
        with httpx.Client(
            verify=ssl.create_default_context(cadata=request["ca_pem"]), follow_redirects=False
        ) as client:
            probe = HostAuthorityProbe(
                binding,
                PostgresHostConnectorRegistry(
                    request["readonly_dsn"], deployment_namespace=namespace
                ),
                ConfiguredHmacHostCredentialResolver(request["shared_secret"]),
                task_id=binding.task_id,
                settings=HostExecutionAuthoritySettings(
                    enabled=True, tool_name="erpnext.authority"
                ),
                client=client,
            )
            expiry = probe.check()
        after = read()
        if (after[0], after[1].model_dump_json(), after[2].binding_digest) != (
            identity,
            instance.model_dump_json(),
            binding.binding_digest,
        ):
            raise ValueError("native allocation facts changed")
    print(
        json.dumps(
            dict(
                identity=identity,
                state=instance.state.value,
                expires_at=expiry.timestamp(),
                **{k: request[k] for k in ("session_id", "workspace_id", "nonce")},
            ),
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("full_workspace_proof_refused", file=sys.stderr)
        sys.exit(1)
