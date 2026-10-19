"""One bounded fixed-object encoding; no archive extraction or directory access."""

import base64
import json
from hashlib import sha256

from agent_integrations.plugins.package_integrity import (
    PluginPackageFile,
    ValidatedPluginPackage,
    _unique_object,
    validate_plugin_package_files,
)

MAX_PLUGIN_OBJECT_BYTES = 72 * 1024 * 1024


def encode_plugin_package(package: ValidatedPluginPackage) -> bytes:
    return json.dumps(
        {
            "format": "zebra-plugin-package-v1",
            "manifest": package.canonical_manifest,
            "files": [
                {"path": file.path, "content": base64.b64encode(file.content).decode("ascii")}
                for file in package.files
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def decode_plugin_package(payload: bytes) -> ValidatedPluginPackage:
    if len(payload) > MAX_PLUGIN_OBJECT_BYTES:
        raise ValueError("plugin object exceeds limit")
    try:
        value = json.loads(payload, object_pairs_hook=_unique_object)
        if (
            not isinstance(value, dict)
            or set(value) != {"format", "manifest", "files"}
            or value["format"] != "zebra-plugin-package-v1"
            or not isinstance(value["manifest"], str)
            or not isinstance(value["files"], list)
            or len(value["files"]) > 1000
        ):
            raise ValueError
        manifest = value["manifest"].encode()
        files = [
            PluginPackageFile("plugin.json", len(manifest), sha256(manifest).hexdigest(), manifest)
        ]
        for entry in value["files"]:
            if (
                not isinstance(entry, dict)
                or set(entry) != {"path", "content"}
                or not isinstance(entry["path"], str)
                or not isinstance(entry["content"], str)
            ):
                raise ValueError
            content = base64.b64decode(entry["content"], validate=True)
            files.append(
                PluginPackageFile(entry["path"], len(content), sha256(content).hexdigest(), content)
            )
        return validate_plugin_package_files(tuple(sorted(files, key=lambda file: file.path)))
    except (ValueError, TypeError, RecursionError):
        raise ValueError("invalid immutable plugin object") from None
