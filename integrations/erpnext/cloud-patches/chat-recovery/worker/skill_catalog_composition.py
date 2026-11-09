from __future__ import annotations


def build_extension_skills(
    settings, cloud_bundle, *, catalog_factory, publication_factory, store_factory
):
    if settings.cloud_skill_worker_enabled:
        assert cloud_bundle.extensions is not None and cloud_bundle.skill_objects is not None
        active_extension_skills = catalog_factory(
            cloud_bundle.extensions,
            cloud_bundle.skill_objects,
            publication_factory(
                store_factory(
                    cloud_bundle.dsn,
                    deployment_namespace=cloud_bundle.deployment_namespace,
                ),
                cloud_bundle.skill_objects,
                cloud_bundle.deployment_namespace,
            )
            if cloud_bundle.dsn
            else None,
        )
    else:
        active_extension_skills = None
    return active_extension_skills
