"""Publish a reviewed canonical Host manifest without rebinding existing Tasks."""

import json
from argparse import ArgumentParser
from pathlib import Path

from agent_integrations.host_tools import HostToolManifest
from agent_integrations.host_tools.contracts import MAX_MANIFEST_BYTES
from agent_storage.postgres.host_manifest_publication import publish_host_manifest
from zebra_agent_config import load_settings


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--connector", required=True)
    parser.add_argument("--profile-revision", type=int, required=True)
    parser.add_argument("--expected-current-digest", required=True)
    parser.add_argument("--approved-digest", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    with args.manifest.open("rb") as source:
        raw = source.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        parser.error("manifest exceeds its size bound")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        parser.error("manifest must be an object")
    manifest = HostToolManifest.from_payload(payload)
    if manifest.digest != args.approved_digest:
        parser.error("manifest does not match the approved digest")
    settings = load_settings()
    if settings.deployment != "cloud" or settings.storage_authority != "postgresql":
        parser.error("manifest publication requires Cloud PostgreSQL")
    publish_host_manifest(
        settings.database_url, deployment_namespace=args.namespace, host_app_id=args.host,
        connector_id=args.connector, profile_revision=args.profile_revision,
        expected_manifest_digest=args.expected_current_digest, manifest_digest=manifest.digest,
        manifest_payload=manifest.to_payload(),
    )
    print(manifest.digest)


if __name__ == "__main__":
    main()
