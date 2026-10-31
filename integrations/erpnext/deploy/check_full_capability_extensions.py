"""Read the actual accepted Turn snapshot and installed Skill bytes; never run a model."""

import json
from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_storage import cloud_composition_from_environment
from agent_storage.postgres.events import PostgresEventStore
from agent_storage.postgres.extension_snapshots import PostgresExtensionSnapshotStore
from agent_storage.postgres.extensions import PostgresExtensionStore
from zebra_agent_worker.extension_recovery import recover_turn_extension
from zebra_agent_worker.worker_skill_catalog import (
    WorkerSkillCatalogSource,
    prepare_worker_skill_catalog,
)


def main():
    cloud = cloud_composition_from_environment()
    if cloud.deployment_namespace != "erpnext-full" or "native-db" not in cloud.dsn:
        raise ValueError("QA only")
    state = json.loads(Path("/prepared.json").read_text())
    sid = SessionId(UUID(state["task_id"]))
    snapshots = PostgresExtensionSnapshotStore(
        cloud.dsn, deployment_namespace=cloud.deployment_namespace
    )
    events = PostgresEventStore(cloud.dsn, deployment_namespace=cloud.deployment_namespace)
    ceiling = snapshots.resolve_task_ceiling(session_id=str(sid))
    extension = recover_turn_extension(
        store=snapshots,
        events=events.list_for_session(sid),
        session_id=sid,
        task_binding=ceiling.binding,
        allow_mcp=True,
    )
    assert extension is not None and len(extension.snapshot.skills) == 1
    catalog = prepare_worker_skill_catalog(
        extension,
        deployment_namespace=cloud.deployment_namespace,
        source=WorkerSkillCatalogSource(
            PostgresExtensionStore(cloud.dsn, deployment_namespace=cloud.deployment_namespace),
            cloud.artifact_objects,
        ),
    )
    assert catalog is not None
    entries, skipped, _ = catalog.list()
    assert len(entries) == 1 and skipped == 0
    result = catalog.read(entries[0].name)
    assert "Read only the isolated QA note." in result.content
    print(
        json.dumps(
            dict(
                stage="actual_accepted_turn_skill",
                snapshot_bound=True,
                skills=len(entries),
                skill_bytes=result.byte_count,
                mcp_selected=len(extension.snapshot.mcp),
                model_calls=0,
                search_calls=0,
            )
        )
    )


if __name__ == "__main__":
    main()
