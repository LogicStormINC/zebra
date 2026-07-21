from __future__ import annotations

from agent_storage import SQLiteSkillsStateStore
from agent_tools.skills_catalog import LocalSkillCatalog, SkillMetadata
from agent_tools.skills_scope import ScopedSkillRoot, build_scoped_skill_roots
from zebra_agent_config import ZebraAgentSettings


def scoped_skill_roots(settings: ZebraAgentSettings) -> tuple[ScopedSkillRoot, ...]:
    """Build the scope-tagged discovery roots from the four settings roots.

    Delegates to the shared ``build_scoped_skill_roots`` so the CLI inventory and
    the runtime harness discover identical scoped roots.
    """
    return build_scoped_skill_roots(
        system=settings.skill_roots_system,
        admin=settings.skill_roots_admin,
        user=settings.skill_roots,
        repo=settings.skill_roots_repo,
    )


def list_skills(*, settings: ZebraAgentSettings) -> dict[str, object]:
    store = SQLiteSkillsStateStore(settings.skills_state_path)
    available, ambiguous, truncated = _inventory(settings)
    return {
        "skills": [_serialize_skill(metadata, store) for metadata in available],
        "ambiguous_count": ambiguous,
        "truncated": truncated,
    }


def show_skill(*, settings: ZebraAgentSettings, name: str) -> dict[str, object]:
    store = SQLiteSkillsStateStore(settings.skills_state_path)
    available, _, _ = _inventory(settings)
    matches = tuple(metadata for metadata in available if metadata.name == name)
    if not matches:
        return {"name": name, "status": "not_found"}
    return {"skills": [_serialize_skill(metadata, store) for metadata in matches]}


def enable_skill(
    *,
    settings: ZebraAgentSettings,
    name: str,
    scope: str | None = None,
    operator: str | None = None,
) -> dict[str, object]:
    return _set_enabled(settings, name=name, scope=scope, enabled=True, operator=operator)


def disable_skill(
    *,
    settings: ZebraAgentSettings,
    name: str,
    scope: str | None = None,
    operator: str | None = None,
) -> dict[str, object]:
    return _set_enabled(settings, name=name, scope=scope, enabled=False, operator=operator)


def _set_enabled(
    settings: ZebraAgentSettings,
    *,
    name: str,
    scope: str | None,
    enabled: bool,
    operator: str | None,
) -> dict[str, object]:
    available, _, _ = _inventory(settings)
    matches = tuple(metadata for metadata in available if metadata.name == name)
    if not matches:
        return {"name": name, "status": "not_found"}
    resolved_scope = scope
    if resolved_scope is None or not resolved_scope.strip():
        if len(matches) > 1:
            return {
                "status": "invalid_request",
                "reason": f"skill '{name}' is ambiguous across scopes; specify --scope",
            }
        resolved_scope = matches[0].scope.value
    record = SQLiteSkillsStateStore(settings.skills_state_path).set_enabled(
        name=name,
        scope=resolved_scope,
        enabled=enabled,
        operator=operator,
    )
    return {
        "name": record.name,
        "scope": record.scope,
        "enabled": record.enabled,
        "updated_at": record.updated_at.isoformat(),
        "operator": record.operator,
    }


def _inventory(
    settings: ZebraAgentSettings,
) -> tuple[tuple[SkillMetadata, ...], int, bool]:
    # State-less catalog so disabled components stay visible for re-enabling.
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
