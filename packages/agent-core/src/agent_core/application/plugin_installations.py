"""Explicit install/rebind/enable operations; component authority remains independent."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from agent_core.domain.extensions import ExtensionIdempotencyKey, ExtensionScope, OpaqueExtensionId
from agent_core.domain.plugin_installations import (
    PluginBinding,
    PluginDigest,
    PluginInstallation,
    PluginMcpBinding,
    PluginPackagePin,
    PluginSkillBinding,
)
from agent_core.domain.plugin_packages import PluginComponentId
from agent_core.ports.extensions import (
    ExtensionNotFoundError,
    ExtensionRevisionConflictError,
    ExtensionStore,
)
from agent_core.ports.mcp_catalog import McpCatalogStore
from agent_core.ports.plugin_installations import (
    PluginComponentInstaller,
    PluginInstallationStore,
    PluginPackagePublisher,
)
from agent_core.ports.skill_publications import SkillPublicationNotFoundError


class PluginSkillSelection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    component_id: PluginComponentId
    kind: Literal["skill-bundle"]
    installation_id: OpaqueExtensionId


class PluginMcpSelection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    component_id: PluginComponentId
    kind: Literal["mcp-http"]
    connection_id: OpaqueExtensionId


PluginSelection = Annotated[PluginSkillSelection | PluginMcpSelection, Field(discriminator="kind")]


class PluginInstallationCreate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    package_digest: PluginDigest
    bindings: tuple[PluginSelection, ...] | None = Field(default=None, min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_bindings(self) -> Self:
        if self.bindings is not None and len({item.component_id for item in self.bindings}) != len(
            self.bindings
        ):
            raise ValueError("duplicate plugin component binding")
        return self


class PluginInstallationPatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    enabled: bool | None = Field(default=None, strict=True)
    package_digest: PluginDigest | None = None
    bindings: tuple[PluginSelection, ...] | None = Field(default=None, min_length=1, max_length=32)

    @model_validator(mode="after")
    def explicit_operation(self) -> Self:
        if self.enabled is not None:
            if self.model_fields_set != {"enabled"}:
                raise ValueError("enablement and rebinding are separate operations")
        elif (
            self.package_digest is None
            or self.bindings is None
            or self.model_fields_set != {"package_digest", "bindings"}
        ):
            raise ValueError("rebind requires package digest and complete bindings")
        return self


def _checked(
    record: PluginInstallation, scope: ExtensionScope, identifier: str
) -> PluginInstallation:
    if (
        not isinstance(record, PluginInstallation)
        or record.scope != scope
        or record.installation_id != identifier
    ):
        raise ExtensionNotFoundError("plugin installation not found in supplied scope")
    return PluginInstallation.model_validate(record.model_dump())


@dataclass(frozen=True)
class PluginInstallationService:
    store: PluginInstallationStore
    extensions: ExtensionStore
    catalogs: McpCatalogStore
    publisher: PluginPackagePublisher
    deployment_namespace: str
    components: PluginComponentInstaller | None = None
    mcp_available: bool = True
    skill_available: bool = True

    async def _package_and_bindings(
        self,
        scope: ExtensionScope,
        request: PluginInstallationCreate,
    ) -> tuple[PluginPackagePin, tuple[PluginBinding, ...]]:
        package = await self.publisher.publish(package_digest=request.package_digest)
        package = PluginPackagePin.model_validate(package.model_dump())
        if (
            package.package_digest != request.package_digest
            or package.expectation.deployment_namespace != self.deployment_namespace
        ):
            raise ValueError("published package disagrees with requested digest/deployment")
        if request.bindings is None:
            if self.components is None:
                raise ValueError("automatic component installation is unavailable")
            prepared = await self.components.prepare(scope=scope, package=package)
            request = PluginInstallationCreate.model_validate(
                {
                    "package_digest": request.package_digest,
                    "bindings": [
                        {
                            "component_id": item.component_id,
                            "kind": item.kind,
                            **(
                                {"installation_id": item.installation.installation_id}
                                if isinstance(item, PluginSkillBinding)
                                else {"connection_id": item.connection.connection_id}
                            ),
                        }
                        for item in prepared
                    ],
                }
            )
        assert request.bindings is not None
        components = {component.id: component for component in package.manifest.components}
        if {item.component_id: item.kind for item in request.bindings} != {
            component.id: component.kind for component in components.values()
        }:
            raise ValueError("bindings must exactly cover package components")
        bindings: list[PluginBinding] = []
        for selection in sorted(request.bindings, key=lambda item: item.component_id):
            if isinstance(selection, PluginSkillSelection):
                installation = await self.extensions.get_skill(
                    scope=scope, installation_id=selection.installation_id
                )
                publication = await self.extensions.get_skill_publication(
                    scope=scope,
                    skill_id=installation.version.skill_id,
                    version_id=installation.version.version_id,
                )
                if (
                    installation.scope != scope
                    or installation.installation_id != selection.installation_id
                    or not installation.enabled
                    or publication.scope != scope
                    or publication.version != installation.version
                    or publication.state != "ready"
                    or publication.manifest != package.skill_files(selection.component_id)
                    or publication.expectation.deployment_namespace != self.deployment_namespace
                ):
                    raise ExtensionRevisionConflictError(
                        "Skill publication disagrees with plugin component"
                    )
                bindings.append(
                    PluginSkillBinding(
                        component_id=selection.component_id, installation=installation
                    )
                )
            else:
                connection = await self.extensions.get_mcp(
                    scope=scope, connection_id=selection.connection_id
                )
                catalog = await self.catalogs.latest(
                    scope=scope,
                    connection_id=selection.connection_id,
                    config_revision=connection.revision,
                )
                if (
                    connection.scope != scope
                    or connection.connection_id != selection.connection_id
                    or not connection.enabled
                    or catalog.connection != connection
                    or connection.auth_mode.value not in {"none", "bearer"}
                    or connection.auth_state.value not in {"not_required", "ready"}
                    or not catalog.tools
                ):
                    raise ExtensionRevisionConflictError("MCP connection/catalog is not ready")
                bindings.append(
                    PluginMcpBinding(
                        component_id=selection.component_id,
                        connection=connection,
                        catalog_digest=catalog.digest,
                    )
                )
        return package, tuple(bindings)

    async def readiness(self, record: PluginInstallation) -> str:
        """Fresh component facts; configured availability is not a Worker heartbeat."""
        if any(isinstance(item, PluginSkillBinding) for item in record.bindings):
            if not self.skill_available:
                return "skill_runtime_unavailable"
        if any(isinstance(item, PluginMcpBinding) for item in record.bindings):
            if not self.mcp_available:
                return "mcp_runtime_unavailable"
        mcp_tools = 0
        seen_connections: set[str] = set()
        for binding in record.bindings:
            try:
                if isinstance(binding, PluginSkillBinding):
                    current = await self.extensions.get_skill(
                        scope=record.scope, installation_id=binding.installation.installation_id
                    )
                    publication = await self.extensions.get_skill_publication(
                        scope=record.scope, skill_id=current.version.skill_id,
                        version_id=current.version.version_id,
                    )
                    if (
                        current != binding.installation or not current.enabled
                        or publication.scope != record.scope
                        or publication.version != current.version
                        or publication.state != "ready"
                        or publication.manifest != record.package.skill_files(binding.component_id)
                        or publication.expectation.deployment_namespace != self.deployment_namespace
                    ):
                        return "component_unavailable"
                else:
                    current_mcp = await self.extensions.get_mcp(
                        scope=record.scope, connection_id=binding.connection.connection_id
                    )
                    catalog = await self.catalogs.latest(
                        scope=record.scope, connection_id=current_mcp.connection_id,
                        config_revision=current_mcp.revision,
                    )
                    if current_mcp.connection_id not in seen_connections:
                        mcp_tools += len(catalog.tools)
                        seen_connections.add(current_mcp.connection_id)
                    if (
                        mcp_tools > 32
                        or current_mcp != binding.connection or not current_mcp.enabled
                        or current_mcp.auth_mode.value not in {"none", "bearer"}
                        or current_mcp.auth_state.value not in {"not_required", "ready"}
                        or catalog.connection != current_mcp
                        or catalog.digest != binding.catalog_digest or not catalog.tools
                    ):
                        return "component_unavailable"
            except (ExtensionNotFoundError, SkillPublicationNotFoundError):
                return "component_unavailable"
        return "ready"

    async def install(
        self,
        *,
        scope: ExtensionScope,
        operated_by: str,
        idempotency_key: str,
        payload: object,
    ) -> tuple[PluginInstallation, bool]:
        key = TypeAdapter(ExtensionIdempotencyKey).validate_python(idempotency_key)
        request = PluginInstallationCreate.model_validate(payload)
        scope = ExtensionScope.model_validate(scope.model_dump())
        key_digest = sha256(
            b"zebra:plugin-installation:create:v1\0" + key.encode("ascii")
        ).hexdigest()
        identifier = "plugin_" + key_digest
        intent = request.model_dump(mode="json")
        if intent["bindings"] is not None:
            intent["bindings"] = sorted(intent["bindings"], key=lambda item: item["component_id"])
        request_digest = sha256(
            json.dumps(intent, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

        async def replay(original: PluginInstallation) -> tuple[PluginInstallation, bool]:
            original = _checked(original, scope, identifier)
            if (
                original.revision != 1
                or original.enabled
                or original.creation_key_digest != key_digest
                or original.creation_request_digest != request_digest
            ):
                raise ExtensionRevisionConflictError("idempotency key request differs")
            return _checked(
                await self.store.get(scope=scope, installation_id=identifier), scope, identifier
            ), False

        try:
            original = await self.store.get_creation(scope=scope, installation_id=identifier)
        except ExtensionNotFoundError:
            pass
        else:
            return await replay(original)
        package, bindings = await self._package_and_bindings(scope, request)
        record = PluginInstallation(
            scope=scope,
            installation_id=identifier,
            revision=1,
            operated_by=operated_by,
            operated_at=datetime.now(UTC),
            creation_key_digest=key_digest,
            creation_request_digest=request_digest,
            package=package,
            bindings=bindings,
        )
        try:
            await self.store.save(scope=scope, installation=record, expected_revision=None)
        except ExtensionRevisionConflictError:
            return await replay(
                await self.store.get_creation(scope=scope, installation_id=identifier)
            )
        return record, True

    async def update(
        self,
        *,
        scope: ExtensionScope,
        operated_by: str,
        installation_id: str,
        expected_revision: int,
        payload: object,
    ) -> PluginInstallation:
        request = PluginInstallationPatch.model_validate(payload)
        current = _checked(
            await self.store.get(scope=scope, installation_id=installation_id),
            scope,
            installation_id,
        )
        if current.revision != expected_revision:
            raise ExtensionRevisionConflictError("plugin revision conflict")
        if request.enabled is True:
            reason = await self.readiness(current)
            if reason != "ready":
                raise ExtensionRevisionConflictError(reason)
        if request.enabled is not None and request.enabled == current.enabled:
            return current
        package, bindings = current.package, current.bindings
        if request.enabled is None:
            package, bindings = await self._package_and_bindings(
                scope,
                PluginInstallationCreate.model_validate(
                    {
                        "package_digest": request.package_digest,
                        "bindings": request.bindings,
                    }
                ),
            )
        record = PluginInstallation.model_validate(
            {
                **current.model_dump(),
                "revision": expected_revision + 1,
                "operated_by": operated_by,
                "operated_at": datetime.now(UTC),
                "package": package,
                "bindings": bindings,
                "enabled": request.enabled if request.enabled is not None else False,
            }
        )
        await self.store.save(scope=scope, installation=record, expected_revision=expected_revision)
        return record
