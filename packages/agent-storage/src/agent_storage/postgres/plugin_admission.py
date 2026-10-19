"""Plugin sources join the accepted command's existing transaction and locks."""

from typing import Any

from agent_core.domain.extension_snapshots import ExtensionSnapshot
from agent_core.domain.plugin_installations import PluginInstallation, PluginSkillBinding
from agent_core.domain.plugin_snapshots import PluginSnapshot

from agent_storage.postgres.extensions import (
    _CURRENT,
    _SCOPE,
    ExtensionSnapshotAdmissionConflictError,
    _decode_record,
    _scope_key,
)
from agent_storage.postgres.plugin_installations import PostgresPluginInstallationStore


def validate_plugin_snapshot_in_transaction(
    connection: Any,
    validator: PostgresPluginInstallationStore,
    snapshot: ExtensionSnapshot,
) -> None:
    namespace = validator.deployment_namespace
    if not snapshot.plugins:
        return
    rows = connection.execute(
        _CURRENT
        + _SCOPE
        + " AND object_id = ANY(%s) ORDER BY object_id FOR SHARE OF extension_configurations",
        (
            *_scope_key(namespace, snapshot.scope, "plugin"),
            [p.installation_id for p in snapshot.plugins],
        ),
    ).fetchall()
    records = {
        _decode_record(PluginInstallation, row, snapshot.scope).installation_id: _decode_record(
            PluginInstallation, row, snapshot.scope
        )
        for row in rows
    }
    skills = {s.installation_id: s for s in snapshot.skills}
    mcp = {m.connection.connection_id: m for m in snapshot.mcp}
    for pin in snapshot.plugins:
        current = records.get(pin.installation_id)
        if (
            current is None
            or not current.enabled
            or PluginSnapshot.from_installation(current) != pin
        ):
            raise ExtensionSnapshotAdmissionConflictError(
                "selected plugin changed during admission"
            )
        for binding in current.bindings:
            if isinstance(binding, PluginSkillBinding):
                matches = skills.get(binding.installation.installation_id) == binding.installation
            else:
                entry = mcp.get(binding.connection.connection_id)
                matches = (
                    entry is not None
                    and entry.connection == binding.connection
                    and entry.catalog_digest == binding.catalog_digest
                )
            if not matches:
                raise ExtensionSnapshotAdmissionConflictError(
                    "plugin source disagrees with snapshot"
                )
        validator._validate_enabled(connection, snapshot.scope, current, current.revision)
