"""Default-off Cloud plugin management using approved digests and existing bindings."""

import asyncio
import re

from agent_core.application.plugin_installations import (
    PluginInstallationCreate,
    PluginInstallationPatch,
    PluginInstallationService,
)
from agent_core.domain.extensions import ExtensionIdempotencyKey, OpaqueExtensionId
from agent_core.domain.plugin_installations import PluginInstallation, PluginSkillBinding
from agent_core.ports.extensions import (
    ExtensionNotFoundError,
    ExtensionPageRequest,
    ExtensionRevisionConflictError,
)
from agent_security.extension_authority import extension_scope_from_grant
from agent_security.host_grant import HostGrantSecurityError, VerifiedHostGrant
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter

from zebra_agent_api.extension_reads import extension_error
from zebra_agent_api.extension_request_body import ExtensionBodyTooLarge, extension_request_body

_PREFIX = "/v1/extensions/plugin-installations"


def _public(record: PluginInstallation) -> dict[str, object]:
    return {
        "installation_id": record.installation_id,
        "revision": record.revision,
        "enabled": record.enabled,
        "plugin_id": record.package.manifest.id,
        "version": record.package.manifest.version,
        "publisher": record.package.manifest.publisher,
        "package_digest": record.package.package_digest,
        "manifest_digest": record.package.manifest_digest,
        "operated_at": record.operated_at.isoformat(),
        "bindings": [
            {
                "component_id": binding.component_id,
                "kind": binding.kind,
                **(
                    {
                        "installation_id": binding.installation.installation_id,
                        "revision": binding.installation.revision,
                    }
                    if isinstance(binding, PluginSkillBinding)
                    else {
                        "connection_id": binding.connection.connection_id,
                        "revision": binding.connection.revision,
                        "catalog_digest": binding.catalog_digest,
                    }
                ),
            }
            for binding in record.bindings
        ],
    }


async def plugin_installation_response(
    request: Request,
    *,
    service: PluginInstallationService | None,
    deployment: str,
    enabled: bool,
    read_enabled: bool,
    manage_enabled: bool,
) -> JSONResponse | None:
    path = request.url.path
    if path != _PREFIX and not path.startswith(_PREFIX + "/"):
        return None
    if not enabled or service is None or deployment == "local" or not read_enabled:
        return extension_error(404)
    collection = path == _PREFIX
    identifier = path.removeprefix(_PREFIX + "/")
    if not collection and ("/" in identifier or not identifier):
        return extension_error(404)
    mutation = request.method in {"POST", "PATCH"}
    if mutation and not manage_enabled:
        return extension_error(404)
    verified = getattr(request.state, "verified_host_grant", None)
    if not isinstance(verified, VerifiedHostGrant):
        return extension_error(403)
    try:
        scope = extension_scope_from_grant(
            verified,
            permission="extensions.manage" if mutation else "extensions.read",
        )
    except HostGrantSecurityError:
        return extension_error(403)
    allowed = "GET, POST" if collection else "GET, PATCH"
    if request.method not in ({"GET", "POST"} if collection else {"GET", "PATCH"}):
        return extension_error(405, allow=allowed if manage_enabled else "GET")
    query = request.query_params
    if (
        len(query.multi_items()) != len(query)
        or set(query) - {"limit", "cursor"}
        or (query and (not collection or mutation))
    ):
        return extension_error(422)
    try:
        if not collection:
            TypeAdapter(OpaqueExtensionId).validate_python(identifier)
        page = ExtensionPageRequest(limit=int(query.get("limit", "50")), cursor=query.get("cursor"))
        if mutation:
            async with asyncio.timeout(30):
                body = await extension_request_body(request)
            if collection:
                keys = request.headers.getlist("idempotency-key")
                if len(keys) != 1:
                    return extension_error(422)
                key = TypeAdapter(ExtensionIdempotencyKey).validate_python(keys[0])
                payload = PluginInstallationCreate.model_validate(body).model_dump(mode="json")
            else:
                matches = request.headers.getlist("if-match")
                if not matches:
                    return extension_error(428)
                if len(matches) != 1 or re.fullmatch(r'"[1-9][0-9]*"', matches[0]) is None:
                    return extension_error(422)
                expected_revision = int(matches[0][1:-1])
                patch = PluginInstallationPatch.model_validate(body)
                payload = patch.model_dump(mode="json", exclude_unset=True)
    except ExtensionBodyTooLarge:
        return extension_error(413)
    except (ValueError, TimeoutError, RecursionError):
        return extension_error(422)
    try:
        created = False
        if request.method == "POST":
            record, created = await service.install(
                scope=scope,
                operated_by=verified.subject_ref,
                idempotency_key=key,
                payload=payload,
            )
        elif request.method == "PATCH":
            record = await service.update(
                scope=scope,
                operated_by=verified.subject_ref,
                installation_id=identifier,
                expected_revision=expected_revision,
                payload=payload,
            )
        elif collection:
            records = await service.store.list(scope=scope, page=page)
            if any(record.scope != scope for record in records.items):
                return extension_error(404)
            return JSONResponse(
                content={
                    "items": [_public(record) for record in records.items],
                    "next_cursor": records.next_cursor,
                },
                headers={"Cache-Control": "no-store"},
            )
        else:
            record = await service.store.get(scope=scope, installation_id=identifier)
        if record.scope != scope:
            return extension_error(404)
    except ExtensionNotFoundError:
        return extension_error(404)
    except ExtensionRevisionConflictError:
        return extension_error(409)
    except ValueError:
        return extension_error(422)
    except Exception:
        return extension_error(503)
    headers = {"Cache-Control": "no-store", "ETag": f'"{record.revision}"'}
    if request.method == "POST":
        headers["Location"] = f"{_PREFIX}/{record.installation_id}"
    return JSONResponse(
        content=_public(record), status_code=201 if created else 200, headers=headers
    )
