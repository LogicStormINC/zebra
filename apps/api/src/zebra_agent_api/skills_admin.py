from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_core.domain.skills import SkillComponentIdentity
from agent_storage import SQLiteSkillsStateStore
from agent_tools.skills_catalog import LocalSkillCatalog, SkillMetadata
from agent_tools.skills_scope import (
    ScopedSkillRoot,
    SkillScope,
    build_scoped_skill_roots,
    normalize_skill_owner,
)
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_api.responses import ApiResponse, bad_request


def runtime_skills_state(settings: ZebraAgentSettings) -> SQLiteSkillsStateStore | None:
    """The enablement store used to filter the runtime catalog, or None.

    Constructed lazily only when any skill root is configured so the default
    deployment does not create a skills-state database on every run.
    """
    if not scoped_skill_roots(settings):
        return None
    return SQLiteSkillsStateStore(settings.skills_state_path)


def scoped_skill_roots(
    settings: ZebraAgentSettings,
    *,
    owner: str | None = None,
) -> tuple[ScopedSkillRoot, ...]:
    """Build the scope-tagged discovery roots from the four settings roots.

    Delegates to the shared builder so admin and runtime discovery stay aligned.
    """
    return build_scoped_skill_roots(
        system=settings.skill_roots_system,
        admin=settings.skill_roots_admin,
        user=settings.skill_roots,
        repo=settings.skill_roots_repo,
        owner=owner,
    )


def private_skill_owner(identities: tuple[SkillComponentIdentity, ...]) -> str | None:
    return next(
        (
            identity.namespace
            for identity in identities
            if (
                identity.scope == SkillScope.USER.value
                and identity.namespace != SkillScope.USER.value
            )
        ),
        None,
    )


@dataclass(frozen=True)
class ApiSkillsAdminMixin:
    """Bounded Skill inventory and private lifecycle controls.

    Enablement persists operator intent but does not grant authority; Task grants
    remain explicit and frozen. Authentication stays on the existing API surface.
    """

    database_path: Path
    settings: ZebraAgentSettings

    def list_skills(self, owner: str | None = None) -> ApiResponse:
        owner_or_response = _optional_owner(owner)
        if isinstance(owner_or_response, ApiResponse):
            return owner_or_response
        store = SQLiteSkillsStateStore(self.settings.skills_state_path)
        available, ambiguous, truncated = _inventory(self.settings, owner=owner_or_response)
        return ApiResponse(
            status_code=200,
            body={
                "skills": [
                    _serialize_skill(metadata, store)
                    for metadata in available
                ],
                "ambiguous_count": ambiguous,
                "truncated": truncated,
            },
        )

    def show_skill(self, name: str, owner: str | None = None) -> ApiResponse:
        owner_or_response = _optional_owner(owner)
        if isinstance(owner_or_response, ApiResponse):
            return owner_or_response
        store = SQLiteSkillsStateStore(self.settings.skills_state_path)
        matches = _matches(self.settings, name=name, owner=owner_or_response)
        if not matches:
            return ApiResponse(status_code=404, body={"name": name, "status": "not_found"})
        return ApiResponse(
            status_code=200,
            body={
                "skills": [
                    _serialize_skill(metadata, store)
                    for metadata in matches
                ]
            },
        )

    def install_skill(self, name: str, payload: dict[str, object]) -> ApiResponse:
        owner_or_response = _payload_owner(payload, required=True)
        if isinstance(owner_or_response, ApiResponse):
            return owner_or_response
        if owner_or_response is None:
            return bad_request("owner is required for private Skill lifecycle operations")
        operator_or_response = _operator(payload)
        if isinstance(operator_or_response, ApiResponse):
            return operator_or_response
        matches = _matches(self.settings, name=name, owner=owner_or_response, live_only=True)
        if len(matches) != 1 or matches[0].scope is not SkillScope.USER:
            return ApiResponse(status_code=404, body={"name": name, "status": "not_found"})
        metadata = matches[0]
        if metadata.owner != owner_or_response:
            return ApiResponse(status_code=404, body={"name": name, "status": "not_found"})
        catalog = LocalSkillCatalog(
            scoped_skill_roots(self.settings, owner=owner_or_response), inventory_only=True
        )
        try:
            record = SQLiteSkillsStateStore(self.settings.skills_state_path).install_component(
                identity=metadata.component_identity(),
                files=catalog.package_files(name),
                owner=owner_or_response,
                operator=operator_or_response,
            )
        except (ValueError, KeyError) as error:
            return bad_request(str(error))
        state = SQLiteSkillsStateStore(self.settings.skills_state_path)
        return ApiResponse(
            status_code=200,
            body={
                **_serialize_skill(metadata, state),
                "installed_at": record.installed_at.isoformat(),
            },
        )

    def enable_skill(self, name: str, payload: dict[str, object]) -> ApiResponse:
        return self._set_enabled(name, payload, enabled=True)

    def disable_skill(self, name: str, payload: dict[str, object]) -> ApiResponse:
        return self._set_enabled(name, payload, enabled=False)

    def _set_enabled(
        self,
        name: str,
        payload: dict[str, object],
        *,
        enabled: bool,
    ) -> ApiResponse:
        owner_or_response = _payload_owner(payload, required=False)
        if isinstance(owner_or_response, ApiResponse):
            return owner_or_response
        operator_or_response = _operator(payload)
        if isinstance(operator_or_response, ApiResponse):
            return operator_or_response
        selector_or_response = _component_selector(payload)
        if isinstance(selector_or_response, ApiResponse):
            return selector_or_response
        if selector_or_response is not None and owner_or_response is None:
            return bad_request("version and digest require a private Skill owner")
        scope = payload.get("scope")
        if scope is not None and (not isinstance(scope, str) or not scope.strip()):
            return bad_request("scope must be a non-empty string")
        version, digest = selector_or_response or (None, None)
        matches = _matches(
            self.settings,
            name=name,
            owner=owner_or_response,
            scope=scope,
            version=version,
            digest=digest,
            live_only=owner_or_response is not None and selector_or_response is None,
        )
        if owner_or_response is not None and selector_or_response is None and not matches:
            matches = _matches(self.settings, name=name, owner=owner_or_response, scope=scope)
        if not matches:
            return ApiResponse(status_code=404, body={"name": name, "status": "not_found"})
        if len(matches) > 1:
            return bad_request(f"skill '{name}' is ambiguous; specify 'scope'")
        metadata = matches[0]
        store = SQLiteSkillsStateStore(self.settings.skills_state_path)
        try:
            if metadata.owner is not None:
                if metadata.owner != owner_or_response:
                    return ApiResponse(status_code=404, body={"name": name, "status": "not_found"})
                record = store.set_component_enabled(
                    identity=metadata.component_identity(),
                    owner=metadata.owner,
                    enabled=enabled,
                    operator=operator_or_response,
                )
            else:
                record = store.set_enabled(
                    name=name,
                    scope=metadata.scope.value,
                    enabled=enabled,
                    operator=operator_or_response,
                )
        except ValueError as error:
            return bad_request(str(error))
        return ApiResponse(
            status_code=200,
            body={
                "name": record.name,
                "scope": record.scope,
                "namespace": record.namespace,
                "owner": record.owner,
                "digest": record.digest,
                "enabled": record.enabled,
                "updated_at": record.updated_at.isoformat(),
                "operator": record.operator,
            },
        )


def _inventory(
    settings: ZebraAgentSettings,
    *,
    owner: str | None = None,
) -> tuple[tuple[SkillMetadata, ...], int, bool]:
    roots = scoped_skill_roots(settings, owner=owner)
    available, ambiguous, truncated = LocalSkillCatalog(roots, inventory_only=True).list()
    if owner is None:
        return available, ambiguous, truncated
    state = SQLiteSkillsStateStore(settings.skills_state_path)
    snapshots = tuple(
        metadata
        for identity in state.installed_component_identities(owner=owner)
        for metadata in LocalSkillCatalog(
            roots, skills_state=state, granted_component_identities=(identity,)
        ).list()[0]
    )
    merged = {metadata.component_identity(): metadata for metadata in (*available, *snapshots)}
    ordered = tuple(sorted(merged.values(), key=lambda item: (item.name, item.version or "")))
    return ordered, ambiguous, truncated


def _matches(
    settings: ZebraAgentSettings,
    *,
    name: str,
    owner: str | None,
    scope: object | None = None,
    version: str | None = None,
    digest: str | None = None,
    live_only: bool = False,
) -> tuple[SkillMetadata, ...]:
    available = (
        LocalSkillCatalog(scoped_skill_roots(settings, owner=owner), inventory_only=True).list()[0]
        if live_only
        else _inventory(settings, owner=owner)[0]
    )
    return tuple(
        metadata
        for metadata in available
        if metadata.name == name
        and (owner is None or metadata.owner == owner)
        and (scope is None or metadata.scope.value == scope)
        and (version is None or metadata.version == version)
        and (digest is None or metadata.digest == digest)
    )


def _serialize_skill(
    metadata: SkillMetadata,
    store: SQLiteSkillsStateStore,
) -> dict[str, object]:
    if metadata.owner is not None:
        if metadata.version is None:
            installed = None
            state = None
        else:
            installed = store.installed_component(
                identity=metadata.component_identity(), owner=metadata.owner
            )
            state = store.component_state(
                identity=metadata.component_identity(), owner=metadata.owner
            )
        enabled = state.enabled if state is not None else False
    else:
        installed = None
        state = store.get_state(name=metadata.name, scope=metadata.scope.value)
        enabled = state.enabled if state is not None else True
    return {
        "name": metadata.name,
        "description": metadata.description,
        "scope": metadata.scope.value,
        "namespace": metadata.namespace,
        "owner": metadata.owner,
        "source": metadata.source,
        "version": metadata.version,
        "license": metadata.license,
        "digest": metadata.digest,
        "installed": installed is not None if metadata.owner is not None else True,
        "enabled": enabled,
        "updated_at": state.updated_at.isoformat() if state is not None else None,
        "operator": state.operator if state is not None else None,
    }


def _optional_owner(value: object) -> str | None | ApiResponse:
    if value is None:
        return None
    if not isinstance(value, str):
        return bad_request("owner must be an opaque string")
    try:
        return normalize_skill_owner(value)
    except ValueError as error:
        return bad_request(str(error))


def _payload_owner(payload: dict[str, object], *, required: bool) -> str | None | ApiResponse:
    if required and "owner" not in payload:
        return bad_request("owner is required for private Skill lifecycle operations")
    return _optional_owner(payload.get("owner"))


def _operator(payload: dict[str, object]) -> str | None | ApiResponse:
    operator = payload.get("operator")
    if operator is not None and not isinstance(operator, str):
        return bad_request("operator must be a string")
    return operator


def _component_selector(
    payload: dict[str, object],
) -> tuple[str, str] | None | ApiResponse:
    version, digest = payload.get("version"), payload.get("digest")
    if version is None and digest is None:
        return None
    if not isinstance(version, str) or not version.strip():
        return bad_request("version and digest must be non-empty strings together")
    if not isinstance(digest, str) or not digest.strip():
        return bad_request("version and digest must be non-empty strings together")
    return version.strip(), digest.strip()
