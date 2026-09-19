"""Project selected catalog entries into exact Harness Skill read requirements."""

from agent_core.harness.models import SkillReadRequirement
from agent_tools.cloud_skills import CloudSkillCatalog
from agent_tools.skills_catalog import SkillCatalog, SkillMetadata


def build_skill_read_requirements(
    components: tuple[str, ...],
    catalog: SkillCatalog,
    available: tuple[SkillMetadata, ...],
) -> tuple[SkillReadRequirement, ...]:
    if isinstance(catalog, CloudSkillCatalog):
        by_id = {item.version.skill_id: item.version for item in catalog.snapshot.skills}
        return tuple(
            SkillReadRequirement(
                component=component,
                skill_id=version.skill_id,
                version_id=version.version_id,
                digest=version.content_digest,
            )
            for component in components
            if (version := by_id.get(component)) is not None
        )

    by_component = {
        component: next(
            (item for item in available if item.skill_id == component or item.name == component),
            None,
        )
        for component in components
    }
    return tuple(
        SkillReadRequirement(
            component=component,
            name=metadata.name,
            skill_id=metadata.skill_id,
            version=metadata.version,
            version_id=metadata.source if metadata.skill_id is not None else None,
            digest=metadata.digest,
        )
        for component, metadata in by_component.items()
        if metadata is not None
    )
