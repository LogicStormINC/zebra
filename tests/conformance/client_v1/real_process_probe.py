"""Cross-process PostgreSQL probe for the Client Integration Plane."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from agent_control_plane.client_admission import ClientAdmissionService, ClientBindingService
from agent_control_plane.client_effects import (
    build_client_effect_continuation,
    build_client_effect_request,
)
from agent_core.domain.client_capabilities import (
    ClientActionContract,
    ClientActionRisk,
    FrontendCapabilityProfileVersion,
    MountedCapabilitySnapshot,
    canonical_client_capability_digest,
)
from agent_core.domain.client_sessions import ClientSessionGrant
from agent_core.domain.identifiers import new_session_id, new_tool_call_id
from agent_storage.postgres.events import PostgresEventStore
from agent_storage.postgres.migration_runner import apply_postgres_migrations
from agent_storage.postgres_platform_composition import postgres_agent_platform_control_plane
from zebra_agent_worker.client_effect_resume import recover_client_effect_wakeup


def _dsn() -> str:
    return os.environ["ZEBRA_TEST_POSTGRES_DSN"]


def _namespace() -> str:
    return os.environ["ZEBRA_TEST_NAMESPACE"]


def seed(output: Path) -> None:
    dsn, namespace = _dsn(), _namespace()
    apply_postgres_migrations(dsn)
    platform = postgres_agent_platform_control_plane(
        dsn, deployment_namespace=namespace, client_integration_enabled=True
    )
    assert platform.frontend_capabilities is not None
    assert platform.client_sessions is not None
    assert platform.client_control_leases is not None
    assert platform.client_effects is not None

    action = ClientActionContract(
        name="fixture.ui.item.open",
        risk=ClientActionRisk.PRESENTATION,
    )
    profile = FrontendCapabilityProfileVersion(
        frontend_app_id="fixture-web",
        revision=1,
        actions=(action,),
        published_at=datetime.now(UTC),
    )
    platform.frontend_capabilities.publish_profile(profile)
    grant = ClientSessionGrant(
        grant_id=uuid4(),
        host_app_id="fixture-host",
        namespace_id="fixture-tenant",
        frontend_app_id=profile.frontend_app_id,
        origin="https://fixture.example",
        user_ref="fixture-user",
        profile_digest=profile.profile_digest,
        scopes=("client.action",),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    admitted = ClientAdmissionService(platform.client_sessions).open_session(grant)
    snapshot = MountedCapabilitySnapshot(
        client_session_id=admitted.session.session_id,
        frontend_app_id=profile.frontend_app_id,
        profile_revision=profile.revision,
        profile_digest=profile.profile_digest,
        mounted_actions=(action.name,),
        ui_revision=1,
        mounted_at=datetime.now(UTC),
    )
    ClientAdmissionService(platform.client_sessions).mount(
        admitted.session.session_id, snapshot, profile=profile
    )
    parent_session_id = new_session_id()
    bound = ClientBindingService(platform.client_sessions, platform.client_control_leases).bind_run(
        task_id=parent_session_id,
        run_id="run-1",
        session_id=admitted.session.session_id,
        task_capability_scope=(action.name,),
    )
    assert bound.controller_fence is not None
    request = build_client_effect_request(
        binding=bound.binding,
        tool_call_id=new_tool_call_id(),
        action_name=action.name,
        arguments={"itemId": "item-7"},
        action_contract_digest=canonical_client_capability_digest(action.model_dump(mode="json")),
        fence_hash=bound.controller_fence.fence_hash,
        expected_ui_revision=1,
        session_id=parent_session_id,
    )
    platform.client_effects.schedule(
        request,
        continuation=build_client_effect_continuation(
            request,
            assistant_message="Opening the requested item.",
            model_calls_used=1,
            tool_calls_executed=0,
        ),
        session_id=parent_session_id,
    )
    output.write_text(
        json.dumps(
            {
                "action_contract_digest": request.action_contract_digest,
                "action_name": action.name,
                "binding_digest": bound.binding.binding_digest,
                "client_session_id": str(admitted.session.session_id),
                "effect_id": str(request.effect_id),
                "fence_token": bound.controller_fence.token,
                "frontend_app_id": profile.frontend_app_id,
                "idempotency_key": request.idempotency_key,
                "parent_session_id": str(parent_session_id),
                "profile_digest": profile.profile_digest,
                "profile_revision": profile.revision,
                "request_digest": request.request_digest,
                "run_id": request.run_id,
                "session_credential": (
                    f"{admitted.session.session_id}:{admitted.credential.token}"
                ),
                "task_id": str(request.task_id),
            },
            indent=2,
            sort_keys=True,
        )
    )


def worker_recover(seed_file: Path, *, expected: str) -> None:
    seed_data = json.loads(seed_file.read_text())
    events = PostgresEventStore(_dsn(), deployment_namespace=_namespace()).list_for_session(
        seed_data["parent_session_id"]
    )
    wakeup = recover_client_effect_wakeup(events)
    if expected == "waiting":
        assert wakeup is None
        assert any(event.event_type.value == "client_effect_scheduled" for event in events)
        return
    assert wakeup is not None
    assert wakeup.effect_id == seed_data["effect_id"]
    assert wakeup.status == "succeeded"
    assert wakeup.result_payload == {"opened": True}


def main() -> None:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)
    seed_parser = subcommands.add_parser("seed")
    seed_parser.add_argument("output", type=Path)
    recover_parser = subcommands.add_parser("worker-recover")
    recover_parser.add_argument("seed_file", type=Path)
    recover_parser.add_argument("--expected", choices=("waiting", "resumed"), required=True)
    args = parser.parse_args()
    if args.command == "seed":
        seed(args.output)
    else:
        worker_recover(args.seed_file, expected=args.expected)


if __name__ == "__main__":
    main()
