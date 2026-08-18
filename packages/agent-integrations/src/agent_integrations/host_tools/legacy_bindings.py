"""Legacy Host adapter: resource binding inference for pre-v1 manifests.

AL-WORKER-GENERIC-01 moved every Host-specific tool/argument mapping out of
the Worker. Manifests that already declare ``resourceBindings`` (protocol
``zebra.host-capability-manifest/1``) need no inference. Legacy manifests —
like the current Trench Host Tool service — do not declare bindings yet, so
this adapter reconstructs them from the registered per-Host template until
``AL-LEGACY-REMOVAL-01`` deletes the legacy window.

This module is the one permitted home for Host vocabulary in integrations
(plan section 7 rule 5 applies to ``agent-core`` and Worker production code;
Host adapters belong here).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from agent_core.domain.host_capability_manifests import ResourceBindingRule

LEGACY_TRENCH_ARGUMENT_TYPES: Final[Mapping[str, tuple[str, str]]] = {
    "events.get_event": ("event_id", "trench.event"),
    "events.get_evidence": ("event_id", "trench.event"),
    "events.get_related_events": ("event_id", "trench.event"),
    "events.get_entity_timeline": ("entity", "trench.entity"),
    "events.get_topic": ("topic", "trench.topic"),
}


def infer_legacy_resource_bindings(
    tool_names: tuple[str, ...],
) -> tuple[tuple[str, tuple[ResourceBindingRule, ...]], ...]:
    """Infer binding rules for a legacy manifest that declares none itself."""

    inferred: list[tuple[str, tuple[ResourceBindingRule, ...]]] = []
    for name in tool_names:
        entry = LEGACY_TRENCH_ARGUMENT_TYPES.get(name)
        if entry is None:
            continue
        argument_name, resource_type = entry
        inferred.append(
            (
                name,
                (
                    ResourceBindingRule(
                        argument_pointer=f"/{argument_name}",
                        resource_type=resource_type,
                    ),
                ),
            )
        )
    return tuple(inferred)
