"""Trusted package publication survives directory removal and rejects changed objects."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from agent_core.domain.artifact_objects import ArtifactObjectReceipt
from agent_integrations.plugins.package_integrity import load_plugin_package


class Objects:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.puts = 0

    def put_if_absent(self, request: Any) -> ArtifactObjectReceipt:
        self.puts += 1
        key = str(request.expectation.artifact_id)
        previous = self.values.setdefault(key, request.payload)
        assert previous == request.payload
        return ArtifactObjectReceipt(
            expectation=request.expectation, object_version="v1", verified_at=datetime.now(UTC)
        )

    def read_version_verified(self, expectation: Any, object_version: str) -> bytes:
        assert object_version == "v1"
        return self.values[str(expectation.artifact_id)]


def bundle(root: Path) -> str:
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": "test-plugin",
                "version": "1.0.0",
                "publisher": "Test",
                "manifest_version": "0.2",
                "components": [
                    {"id": "test-mcp", "kind": "mcp-http", "connection_slot": "test-mcp"}
                ],
            }
        )
    )
    return load_plugin_package(root).package_digest


def test_publication_uses_approved_digest_directory_and_fixed_object(tmp_path: Path) -> None:
    from agent_integrations.plugins.publication import PluginPackagePublicationService

    digest = bundle(tmp_path / "input")
    (tmp_path / "input").rename(tmp_path / digest.removeprefix("sha256:"))
    objects = Objects()
    service = PluginPackagePublicationService(
        bundle_root=tmp_path,
        allowed_digests=(digest,),
        objects=objects,
        deployment_namespace="cloud-a",
    )
    pin = asyncio.run(service.publish(package_digest=digest))
    (tmp_path / digest.removeprefix("sha256:") / "plugin.json").unlink()
    recovered = asyncio.run(service.read(pin))
    assert recovered.package_digest == digest
    assert recovered.canonical_manifest == pin.canonical_manifest
    assert objects.puts == 1
    objects.values[str(pin.expectation.artifact_id)] = b"{}"
    with pytest.raises(ValueError):
        asyncio.run(service.read(pin))


def test_unapproved_digest_performs_no_package_or_object_io(tmp_path: Path) -> None:
    from agent_integrations.plugins.publication import PluginPackagePublicationService

    objects = Objects()
    service = PluginPackagePublicationService(
        bundle_root=tmp_path / "absent",
        allowed_digests=(),
        objects=objects,
        deployment_namespace="cloud-a",
    )
    with pytest.raises(ValueError):
        asyncio.run(service.publish(package_digest="sha256:" + "a" * 64))
    assert objects.puts == 0
