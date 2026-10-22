"""No-network regression: filesystem failures cannot strand provisioning state."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from agent_core.domain.workspace_control import WorkspaceAction, WorkspaceLifecycleState
from agent_runtime.workspace_provisioner import PostgresWorkspaceProvisioner


def check() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        for stage in ("reset", "materialize", "restore", "reconcile"):
            store = Mock()
            instance = SimpleNamespace(
                workspace_id=uuid4(),
                state=WorkspaceLifecycleState.PENDING,
                source=object(),
            )
            store.transition.return_value = (instance, None)
            store.get.return_value = instance
            store.list_uncertain.return_value = [instance]
            store.create_pending.return_value = (instance, None)
            failure = PermissionError("workspace denied")
            provisioner = PostgresWorkspaceProvisioner(
                store,
                volume_root=root,
                artifact_reader=Mock(),
                snapshot_reader=Mock(side_effect=failure),
                snapshot_writer=Mock(),
            )
            with (
                patch(
                    "agent_runtime.workspace_provisioner._reset_target",
                    side_effect=failure if stage == "reset" else None,
                ),
                patch.object(provisioner, "_materialize", side_effect=failure),
            ):
                try:
                    if stage == "restore":
                        provisioner.restore(
                            SimpleNamespace(object_uri="snapshot", content_digest="a" * 64),
                            deployment_namespace="check",
                            quota_bytes=1024,
                            idempotency_key="check",
                        )
                    elif stage == "reconcile":
                        provisioner.reconcile_uncertain(deployment_namespace="check", limit=1)
                    else:
                        provisioner.provision_existing(instance.workspace_id)
                except PermissionError as error:
                    assert stage != "reconcile" and error is failure
                else:
                    assert stage == "reconcile"
            actions = [call.args[1] for call in store.transition.call_args_list]
            assert actions[-1] is (
                WorkspaceAction.UNCERTAIN_RESOLVE_FAIL
                if stage == "reconcile"
                else WorkspaceAction.PROVISION_MARK_UNCERTAIN
            ), (stage, actions)
            assert WorkspaceAction.PROVISION_SUCCEED not in actions
    print("workspace filesystem failure checks: 4 passed; network/models=0")


if __name__ == "__main__":
    check()
