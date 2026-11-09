def compose_client_effect_recovery(settings, cloud_bundle, active_namespace):
    client_effect_recovery = None
    if settings.storage_authority == "postgresql":
        from agent_storage.postgres.client_effect_recovery import ClientEffectRecovery

        assert cloud_bundle.dsn is not None and active_namespace is not None
        client_effect_recovery = ClientEffectRecovery(
            cloud_bundle.dsn,
            deployment_namespace=active_namespace,
        ).reconcile
    return client_effect_recovery
