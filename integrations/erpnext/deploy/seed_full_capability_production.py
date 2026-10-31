"""Seed only the new full namespace using the existing production Host public authority."""

import json
import os
from pathlib import Path

from agent_control_plane.frontend_profiles import FrontendProfileService
from agent_core.domain.client_capabilities import (
    FrontendCapabilityProfileVersion,
    canonical_client_capability_digest,
)
from agent_core.domain.host_connectors import HostConnectorBinding, HostConnectorProfileVersion
from agent_storage import cloud_composition_from_environment
from agent_storage.postgres.client_capabilities import PostgresClientCapabilityRegistry
from agent_storage.postgres.epoch import bootstrap_control_plane_epoch
from agent_storage.postgres.host_auth import HostRegistryRecord, PostgresHostAuthorityStore
from agent_storage.postgres.host_connectors import PostgresHostConnectorRegistry
from frontend_profile import definition, install_profile


def main():
    cloud = cloud_composition_from_environment()
    if (
        cloud.deployment_namespace != "erpnext-full"
        or os.environ["ZEBRA_S3_BUCKET"] != "erpnext-full"
    ):
        raise ValueError("new production namespace required")
    directory = Path("/release")
    site = json.loads((directory / "site.before.json").read_text())["zebra_agent"]
    host = "https://erpnext-full-host.zebra.local"
    bootstrap_control_plane_epoch(cloud.dsn, deployment_namespace=cloud.deployment_namespace)
    PostgresHostAuthorityStore(
        cloud.dsn, deployment_namespace=cloud.deployment_namespace
    ).upsert_registry(
        HostRegistryRecord(
            host_app_id="erpnext",
            namespace_id=cloud.deployment_namespace,
            issuer=site["issuer"],
            audience="zebra",
            jwks_uri=host + "/api/method/zebra_erpnext.gateway.jwks",
            allowed_origins=(site["origin"],),
            algorithms=("RS256",),
            policy_version="erpnext-v1",
        )
    )
    registry = PostgresHostConnectorRegistry(
        cloud.dsn, deployment_namespace=cloud.deployment_namespace
    )
    registry.publish_profile(
        HostConnectorProfileVersion(
            host_app_id="erpnext",
            connector_id="erpnext-full",
            profile_revision=1,
            base_uri=host,
            manifest_path="/manifest",
            invoke_path_template="/tools",
            supported_protocol_versions=("v1",),
            workload_identity_ref="erpnext-worker",
            credential_ref="erpnext-full-v1",
        )
    )
    registry.bind(
        HostConnectorBinding(
            host_app_id="erpnext",
            namespace_id="erpnext-full",
            connector_id="erpnext-full",
            profile_revision=1,
            binding_revision=1,
        )
    )
    version = FrontendCapabilityProfileVersion.model_validate(definition(2))
    clients = PostgresClientCapabilityRegistry(
        cloud.dsn, deployment_namespace=cloud.deployment_namespace
    )
    install_profile(
        FrontendProfileService(clients), clients, version, namespace=cloud.deployment_namespace
    )
    public = dict(
        revision=version.revision,
        digest=version.profile_digest,
        actions=[a.model_dump(mode="json") for a in version.actions],
        action_digests={
            a.name: canonical_client_capability_digest(a.model_dump(mode="json"))
            for a in version.actions
        },
    )
    (directory / "frontend-profile.json").write_text(json.dumps(public))
    from botocore.session import Session

    s3 = Session().create_client(
        "s3",
        endpoint_url=os.environ["ZEBRA_S3_ENDPOINT"],
        region_name="us-east-1",
        aws_access_key_id=os.environ["ZEBRA_S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["ZEBRA_S3_SECRET_KEY"],
    )
    s3.create_bucket(Bucket="erpnext-full")
    s3.put_bucket_versioning(Bucket="erpnext-full", VersioningConfiguration={"Status": "Enabled"})
    print(
        json.dumps(
            dict(
                stage="production_full_authority_seeded",
                namespace=cloud.deployment_namespace,
                model_calls=0,
                search_calls=0,
            )
        )
    )


if __name__ == "__main__":
    main()
