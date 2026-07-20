from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_storage import SQLiteSkillsStateStore
from agent_tools.skills_catalog import LocalSkillCatalog, SkillMetadata
from agent_tools.skills_scope import ScopedSkillRoot, SkillScope
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_api.responses import ApiResponse, bad_request


def runtime_skills_state(
    settings: ZebraAgentSettings,
) -> SQLiteSkillsStateStore | None:
    """The enablement store used to filter the runtime catalog, or None.

    Constructed lazily only when skill roots are configured so the default
    deployment does not create a skills-state database on every run.
    """
    if not settings.skill_roots:
        return None
    return SQLiteSkillsStateStore(settings.skills_state_path)


def scoped_skill_roots(settings: ZebraAgentSettings) -> tuple[ScopedSkillRoot, ...]:
    """Build the scope-tagged discovery roots from the four settings roots."""
    roots: list[ScopedSkillRoot] = []
    for path in settings.skill_roots_system:
        roots.append(ScopedSkillRoot(scope=SkillScope.SYSTEM, root=path))
    for path in settings.skill_roots_admin:
        roots.append(ScopedSkillRoot(scope=SkillScope.ADMIN, root=path))
    for path in settings.skill_roots:
        roots.append(ScopedSkillRoot(scope=SkillScope.USER, root=path))
    for path in settings.skill_roots_repo:
        roots.append(ScopedSkillRoot(scope=SkillScope.REPO, root=path))
    return tuple(roots)


@dataclass(frozen=True)
class ApiSkillsAdminMixin:
    """Bounded skill admin surface: inventory + enable/disable.

    Enable/disable only persists operator intent; it grants no authority and
    affects only Tasks that start after the change (the harness snapshots the
    effective catalog at construction). Authentication reuses the existing
    optional bearer token; there is no separate admin role.
    """

    database_path: Path
    settings: ZebraAgentSettings

    def list_skills(self) -> ApiResponse:
        store = SQLiteSkillsStateStore(self.settings.skills_state_path)
        available, ambiguous, truncated = _inventory(self.settings)
        return ApiResponse(
            status_code=200,
            body={
                "skills": [_serialize_skill(metadata, store) for metadata in available],
                "ambiguous_count": ambiguous,
                "truncated": truncated,
            },
        )

    def show_skill(self, name: str) -> ApiResponse:
        store = SQLiteSkillsStateStore(self.settings.skills_state_path)
        available, _, _ = _inventory(self.settings)
        matches = tuple(metadata for metadata in available if metadata.name == name)
        if not matches:
            return ApiResponse(status_code=404, body={"name": name, "status": "not_found"})
        return ApiResponse(
            status_code=200,
            body={"skills": [_serialize_skill(metadata, store) for metadata in matches]},
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
        scope_value = payload.get("scope")
        operator = payload.get("operator")
        available, _, _ = _inventory(self.settings)
        matches = tuple(metadata for metadata in available if metadata.name == name)
        if not matches:
            return ApiResponse(status_code=404, body={"name": name, "status": "not_found"})
        if scope_value is None:
            if len(matches) > 1:
                return bad_request(
                    f"skill '{name}' is ambiguous across scopes; specify 'scope'"
                )
            scope_value = matches[0].scope.value
        if not isinstance(scope_value, str) or not scope_value.strip():
            return bad_request("scope must be a non-empty string")
        if operator is not None and not isinstance(operator, str):
            return bad_request("operator must be a string")
        record = SQLiteSkillsStateStore(self.settings.skills_state_path).set_enabled(
            name=name,
            scope=scope_value,
            enabled=enabled,
            operator=operator if isinstance(operator, str) else None,
        )
        return ApiResponse(
            status_code=200,
            body={
                "name": record.name,
                "scope": record.scope,
                "enabled": record.enabled,
                "updated_at": record.updated_at.isoformat(),
                "operator": record.operator,
            },
        )


def _inventory(
    settings: ZebraAgentSettings,
) -> tuple[tuple[SkillMetadata, ...], int, bool]:
    # The admin inventory deliberately builds a state-less catalog so disabled
    # components remain visible for re-enabling; runtime filtering happens in
    # the harness catalog, not here.
    return LocalSkillCatalog(scoped_skill_roots(settings)).list()


def _serialize_skill(metadata: SkillMetadata, store: SQLiteSkillsStateStore) -> dict[str, object]:
    state = store.get_state(name=metadata.name, scope=metadata.scope.value)
    return {
        "name": metadata.name,
        "description": metadata.description,
        "scope": metadata.scope.value,
        "namespace": metadata.namespace,
        "source": metadata.source,
        "version": metadata.version,
        "license": metadata.license,
        "digest": metadata.digest,
        "enabled": state.enabled if state is not None else True,
        "updated_at": state.updated_at.isoformat() if state is not None else None,
        "operator": state.operator if state is not None else None,
    }
