"""Opt-in raw ZIP publication and exact-scope metadata reads."""

import asyncio

from agent_core.domain.extensions import OpaqueExtensionId
from agent_core.domain.skill_publications import SkillPublication
from agent_core.ports.skill_publications import (
    UPLOAD_IDEMPOTENCY_KEY,
    SkillPublicationConflictError,
    SkillPublicationNotFoundError,
)
from agent_security.extension_authority import extension_scope_from_grant
from agent_security.host_grant import HostGrantSecurityError, VerifiedHostGrant
from agent_tools.skill_packages import MAX_ARCHIVE_BYTES, SkillPackageError
from agent_tools.skill_publications import SkillPublicationService
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter

from zebra_agent_api.extension_reads import extension_error

_PREFIX = "/v1/extensions/skill-packages"
_ID = TypeAdapter(OpaqueExtensionId)
BODY_TIMEOUT_SECONDS = 30


def _public(record: SkillPublication) -> dict[str, str]:
    return {
        "skill_id": record.version.skill_id, "version_id": record.version.version_id,
        "name": record.name, "description": record.description,
        "version_label": record.version_label, "content_digest": record.version.content_digest,
        "state": record.state,
    }


async def skill_publication_response(
    request: Request, *, service: SkillPublicationService | None, deployment: str,
    read_enabled: bool, manage_enabled: bool,
) -> JSONResponse | None:
    path = request.url.path
    if path != _PREFIX and not path.startswith(_PREFIX + "/"):
        return None
    if service is None or deployment == "local" or not read_enabled:
        return extension_error(404)
    parts = path.removeprefix(_PREFIX).split("/")
    collection = path == _PREFIX
    if not collection:
        if len(parts) != 4 or parts[2] != "versions":
            return extension_error(404)
        try:
            _ID.validate_python(parts[1])
            _ID.validate_python(parts[3])
        except ValueError:
            return extension_error(404)
    if collection and not manage_enabled:
        return extension_error(404)
    verified = getattr(request.state, "verified_host_grant", None)
    if not isinstance(verified, VerifiedHostGrant):
        return extension_error(403)
    try:
        scope = extension_scope_from_grant(
            verified, permission="extensions.manage" if collection else "extensions.read",
        )
    except HostGrantSecurityError:
        return extension_error(403)
    if request.method != ("POST" if collection else "GET"):
        return extension_error(405, allow="POST" if collection else "GET")
    if request.query_params:
        return extension_error(422)
    if collection:
        if "content-encoding" in request.headers:
            return extension_error(422)
        if request.headers.getlist("content-type") != ["application/zip"]:
            return JSONResponse(status_code=415, headers={"Cache-Control": "no-store"}, content={
                "code": "unsupported_media_type", "message": "Use application/zip.",
                "retryable": False, "action": None,
            })
        try:
            keys = request.headers.getlist("idempotency-key")
            if len(keys) != 1:
                return extension_error(422)
            key = UPLOAD_IDEMPOTENCY_KEY.validate_python(keys[0])
            lengths = request.headers.getlist("content-length")
            if lengths:
                if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
                    return extension_error(422)
                if int(lengths[0]) > MAX_ARCHIVE_BYTES:
                    return extension_error(413)
            body = bytearray()
            async with asyncio.timeout(BODY_TIMEOUT_SECONDS):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > MAX_ARCHIVE_BYTES:
                        return extension_error(413)
                    body.extend(chunk)
        except (ValueError, TimeoutError):
            return extension_error(422)
        except Exception:
            return extension_error(422)
    try:
        record = (
            await service.publish(archive=bytes(body), scope=scope, idempotency_key=key)
            if collection else
            await service.get(scope=scope, skill_id=parts[1], version_id=parts[3])
        )
    except SkillPackageError as exc:
        return extension_error(413 if exc.reason == "archive_too_large" else 422)
    except SkillPublicationConflictError:
        return extension_error(409)
    except SkillPublicationNotFoundError:
        return extension_error(404)
    except Exception:
        return extension_error(503)
    headers = {"Cache-Control": "no-store"}
    if collection:
        headers["Location"] = (
            f"{_PREFIX}/{record.version.skill_id}/versions/{record.version.version_id}"
        )
    return JSONResponse(content=_public(record), headers=headers)
