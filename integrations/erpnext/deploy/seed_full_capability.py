"""Operator-only seed of a dedicated QA namespace; no model, search or dispatch."""

import base64
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
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from frontend_profile import definition, install_profile
from jwt.algorithms import RSAAlgorithm


def main():
    cloud = cloud_composition_from_environment()
    if (
        cloud.deployment_namespace != "erpnext-full"
        or "native-db" not in cloud.dsn
        or os.environ.get("ZEBRA_S3_BUCKET") != "erp-full-qa"
    ):
        raise ValueError("dedicated QA authority/object store required")
    root = Path("/evidence")
    private = load_pem_private_key((root / "tls/signing.key").read_bytes(), password=None)
    public = json.loads(RSAAlgorithm.to_jwk(private.public_key()))
    public.update(kid="erpnext-v1", use="sig", alg="RS256")
    (root / "tls/jwks.json").write_text(json.dumps({"keys": [public]}))
    bootstrap_control_plane_epoch(cloud.dsn, deployment_namespace=cloud.deployment_namespace)
    authority = PostgresHostAuthorityStore(
        cloud.dsn, deployment_namespace=cloud.deployment_namespace
    )
    issuer = "https://erpnext-full-qa.zebra.local"
    authority.upsert_registry(
        HostRegistryRecord(
            host_app_id="erpnext",
            namespace_id="erpnext-full",
            issuer=issuer,
            audience="zebra",
            jwks_uri=issuer + "/api/method/zebra_erpnext.gateway.jwks",
            allowed_origins=("https://127.0.0.1:18544",),
            algorithms=("RS256",),
            policy_version="erpnext-v1",
        )
    )
    registry = PostgresHostConnectorRegistry(
        cloud.dsn, deployment_namespace=cloud.deployment_namespace
    )
    profile = HostConnectorProfileVersion(
        host_app_id="erpnext",
        connector_id="erpnext-full",
        profile_revision=1,
        base_uri=issuer,
        manifest_path="/manifest",
        invoke_path_template="/tools",
        supported_protocol_versions=("v1",),
        workload_identity_ref="erpnext-worker",
        credential_ref="erpnext-full-v1",
    )
    registry.publish_profile(profile)
    registry.bind(
        HostConnectorBinding(
            host_app_id="erpnext",
            namespace_id="erpnext-full",
            connector_id="erpnext-full",
            profile_revision=1,
            binding_revision=1,
        )
    )
    frontend = FrontendCapabilityProfileVersion.model_validate(definition(2))
    clients = PostgresClientCapabilityRegistry(
        cloud.dsn, deployment_namespace=cloud.deployment_namespace
    )
    install_profile(FrontendProfileService(clients), clients, frontend, namespace="erpnext-full")
    record = dict(
        revision=frontend.revision,
        digest=frontend.profile_digest,
        actions=[a.model_dump(mode="json") for a in frontend.actions],
        action_digests={
            a.name: canonical_client_capability_digest(a.model_dump(mode="json"))
            for a in frontend.actions
        },
    )
    (root / "frontend-profile.json").write_text(json.dumps(record))
    from botocore.session import Session

    s3 = Session().create_client(
        "s3",
        endpoint_url=os.environ["ZEBRA_S3_ENDPOINT"],
        region_name="us-east-1",
        aws_access_key_id=os.environ["ZEBRA_S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["ZEBRA_S3_SECRET_KEY"],
    )
    s3.create_bucket(Bucket="erp-full-qa")
    s3.put_bucket_versioning(Bucket="erp-full-qa", VersioningConfiguration={"Status": "Enabled"})
    secret = root / "mcp/master.json"
    secret.parent.mkdir(mode=0o700, exist_ok=True)
    secret.write_text(
        json.dumps(dict(value=base64.b64encode(os.urandom(32)).decode(), version="1"))
    )
    secret.chmod(0o600)
    print(
        json.dumps(
            dict(
                stage="qa_authority_and_versioned_storage_seeded",
                namespace="erpnext-full",
                model_calls=0,
                search_calls=0,
            )
        )
    )


if __name__ == "__main__":
    main()
