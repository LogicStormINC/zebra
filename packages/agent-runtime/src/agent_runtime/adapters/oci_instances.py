"""Exact labelled instance operations; no session-wide lookup or deletion."""

import json
from collections.abc import Callable, Mapping, Sequence
from subprocess import CompletedProcess

from agent_core.ports.runtime import RuntimeCapabilityError

from agent_runtime.runtime_instance_lifecycle import RuntimeInstanceLifecycle


def verify_instance_metadata(
    row: object, container_id: str, container_name: str, labels: Mapping[str, str]
) -> None:
    """Require full ID, exact reserved name and every persisted ownership label."""
    try:
        valid = (
            isinstance(row, dict)
            and len(container_id) == 64
            and all(c in "0123456789abcdef" for c in container_id)
            and row["Id"] == container_id
            and row["Name"].lstrip("/") == container_name
            and all(row["Config"]["Labels"].get(k) == v for k, v in labels.items())
        )
    except (KeyError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise RuntimeCapabilityError("exact runtime instance identity could not be verified")


class OciInstances:
    def __init__(
        self,
        lifecycle: RuntimeInstanceLifecycle,
        invoke: Callable[..., CompletedProcess[str]],
        engine: Sequence[str],
    ) -> None:
        self.lifecycle, self._invoke, self._engine = lifecycle, invoke, tuple(engine)
        self._labels: dict[str, Mapping[str, str]] = {}
        self._deleted: set[tuple[str, str]] = set()

    def reserve(self, instance_id: str, session_id: str, digest: str) -> tuple[str, ...]:
        labels = dict(self.lifecycle.reserve(instance_id, session_id, digest))
        labels.update(
            {
                "zebra.agent.instance": instance_id,
                "zebra.agent.engine": self.lifecycle.engine_identity,
                "zebra.agent.session": session_id,
                "zebra.agent.spec": digest,
                "zebra.agent.runtime": "1",
            }
        )
        self._labels[instance_id] = labels
        return tuple(
            part for key, value in labels.items() for part in ("--label", f"{key}={value}")
        )

    def verify(self, instance_id: str, container_id: str) -> None:
        if len(container_id) != 64 or any(c not in "0123456789abcdef" for c in container_id):
            raise RuntimeCapabilityError("runtime requires a full exact container ID")
        result = self._invoke((*self._engine, "inspect", "--format", "{{json .}}", container_id))
        try:
            row = json.loads(result.stdout)
        except ValueError:
            row = None
        if result.returncode:
            raise RuntimeCapabilityError("exact runtime instance identity could not be verified")
        verify_instance_metadata(
            row, container_id, f"zebra-{instance_id}", self._labels[instance_id]
        )

    def authorize(self, instance_id: str, container_id: str) -> None:
        self.verify(instance_id, container_id)
        self.lifecycle.authorize(instance_id, container_id)

    def remove(self, instance_id: str, container_id: str) -> None:
        identity = (instance_id, container_id)
        if identity not in self._deleted:
            self.verify(instance_id, container_id)
            result = self._invoke((*self._engine, "rm", "--force", "--volumes", container_id))
            if result.returncode:
                raise RuntimeCapabilityError("exact runtime instance cleanup failed")
            self._deleted.add(identity)
        # Retain local exact deletion evidence if database settlement fails; retry
        # cannot turn an unrelated empty scan into successful cleanup.
        self.lifecycle.removed(instance_id, container_id)
