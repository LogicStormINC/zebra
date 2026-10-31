"""Operator-only seed, run inside the existing Cloud image with namespace isolation."""

import argparse
import json
import os

from agent_control_plane.frontend_profiles import FrontendProfileService
from agent_core.domain.client_capabilities import (
    FrontendCapabilityProfileVersion,
    canonical_client_capability_digest,
)
from agent_core.domain.host_connectors import HostConnectorBinding, HostConnectorProfileVersion
from agent_storage.postgres.client_capabilities import PostgresClientCapabilityRegistry
from agent_storage.postgres.epoch import (
    PostgresControlPlaneEpochError,
    bootstrap_control_plane_epoch,
    read_control_plane_epoch,
)
from agent_storage.postgres.host_auth import HostRegistryRecord, PostgresHostAuthorityStore
from agent_storage.postgres.host_connectors import PostgresHostConnectorRegistry
from frontend_profile import definition, install_profile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--frontend-revision", type=int, choices=(1, 2), default=1)
parser.add_argument("--rebind-frontend-profile", action="store_true")
options = parser.parse_args()

dsn = os.environ["ZEBRA_DATABASE_URL"]
namespace = "erpnext"
try:
    read_control_plane_epoch(dsn, deployment_namespace=namespace)
except PostgresControlPlaneEpochError:
    bootstrap_control_plane_epoch(dsn, deployment_namespace=namespace)
authority = PostgresHostAuthorityStore(dsn, deployment_namespace=namespace)
authority.upsert_registry(
    HostRegistryRecord(
        host_app_id="erpnext",
        namespace_id=namespace,
        issuer="https://erpnext.zebra.local",
        audience="zebra",
        jwks_uri="https://erpnext.zebra.local/api/method/zebra_erpnext.gateway.jwks",
        allowed_origins=("https://192.168.110.42:18443",),
        algorithms=("RS256",),
        policy_version="erpnext-v1",
        active=True,
    )
)
connectors = PostgresHostConnectorRegistry(dsn, deployment_namespace=namespace)
profile = HostConnectorProfileVersion(
    host_app_id="erpnext",
    connector_id="erpnext-native",
    profile_revision=1,
    base_uri="https://erpnext.zebra.local",
    manifest_path="/api/method/zebra_erpnext.gateway.manifest",
    invoke_path_template="/api/method/zebra_erpnext.gateway.invoke",
    supported_protocol_versions=("v1",),
    workload_identity_ref="erpnext-worker",
    credential_ref="erpnext-native-v1",
)
if not connectors.get_profile("erpnext", "erpnext-native", 1):
    connectors.publish_profile(profile)
connectors.bind(
    HostConnectorBinding(
        host_app_id="erpnext",
        namespace_id=namespace,
        connector_id="erpnext-native",
        profile_revision=1,
        binding_revision=1,
    )
)
frontend = FrontendCapabilityProfileVersion.model_validate(definition(options.frontend_revision))
registry = PostgresClientCapabilityRegistry(dsn, deployment_namespace=namespace)
service = FrontendProfileService(registry)
install_profile(service, registry, frontend, rebind=options.rebind_frontend_profile)
print(
    json.dumps(
        dict(
            revision=frontend.revision,
            digest=frontend.profile_digest,
            actions=[action.model_dump(mode="json") for action in frontend.actions],
            action_digests={
                action.name: canonical_client_capability_digest(action.model_dump(mode="json"))
                for action in frontend.actions
            },
        )
    )
)
